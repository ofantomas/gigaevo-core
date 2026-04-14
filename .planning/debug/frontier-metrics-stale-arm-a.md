---
status: diagnosed
trigger: "Arm A G runs have stale frontier metrics (valid_frontier_actual_fitness stuck at step=0), programs_total_count=9 vs programs_processed=332, D>>G generation desync"
created: 2026-04-13T12:00:00Z
updated: 2026-04-13T12:30:00Z
---

## Current Focus

hypothesis: CONFIRMED — CompositionInjectionHook creates programs without "iteration" key in metadata, causing KeyError in MetricsTracker._process_program() line 235, which kills the entire MetricsTracker async task
test: Verified via Redis data inspection and code trace
expecting: n/a — root cause found
next_action: Return diagnosis

## Symptoms

expected: |
  1. Frontier metrics (valid_frontier_actual_fitness) should update as archive programs' actual_fitness changes during epoch refresh re-evaluations
  2. programs_total_count should reflect all unique programs processed
  3. G and D generation counts should be roughly in sync
  4. All arms should show progressive fitness improvement over 17+ generations

actual: |
  1. A1_G reports fitness=0.01097 (31.8% of SOTA) but archive has programs with actual_fitness up to 0.03554 (103% SOTA) — frontier metric NEVER updated past step=0
  2. programs_total_count=9 for A1_G and A2_G, but programs_processed=332 and 228. C1_G healthy: total=496
  3. D runs at gen ~43 while G runs at gen ~17 — 2.5x generation desync
  4. valid_frontier_actual_fitness for A1_G has only 1 Redis entry at step=0

errors: |
  No error messages — silent incorrect behavior. MetricsTracker logs KeyError but only at exception level in run() outer handler.

reproduction: |
  Redis DB 1, prefix heilbron_adversarial/pop_a (A1_G) vs DB 5 prefix heilbron_adversarial/pop_a (C1_G)

started: Since experiment launch 2026-04-12T21:02:21Z

## Eliminated

- hypothesis: _refresh_changed_fitness hash comparison failing
  evidence: MetricsTracker crashes before _refresh_changed_fitness ever runs on enough programs — the crash is in _process_program, not in the refresh logic
  timestamp: 2026-04-13T12:15:00Z

- hypothesis: D>>G desync is bug-caused
  evidence: D>>G desync exists across ALL arms (A and C), ranging from 1.2x to 2.3x. This is expected behavior — D evaluations are faster than G evaluations, and sync hook min_delta=1 allows asynchronous advancement. Not a bug.
  timestamp: 2026-04-13T12:25:00Z

## Evidence

- timestamp: 2026-04-13T12:05:00Z
  checked: CompositionInjectionHook.inject() program creation (line 162-171)
  found: Creates Program with metadata={"mutation_type":"d_improvement","d_source_id":...,"g_source_id":...,"d_fitness":...} — NO "iteration" key
  implication: MetricsTracker._process_program line 235 does program.metadata["iteration"] which will KeyError

- timestamp: 2026-04-13T12:08:00Z
  checked: MetricsTracker.run() exception handling (line 144-152)
  found: run() catches Exception at outermost level and logs it, but then EXITS the while loop — the MetricsTracker async task dies permanently
  implication: A single KeyError kills ALL metrics tracking for the entire run, not just that one program

- timestamp: 2026-04-13T12:10:00Z
  checked: Redis A1_G programs_total_count vs actual program count
  found: programs_total_count=9 (only seeds), but 362 actual program keys in Redis
  implication: MetricsTracker died after processing exactly the 9 seed programs

- timestamp: 2026-04-13T12:12:00Z
  checked: Redis A1_G d_improvement program metadata
  found: d_improvement program 5f3a2602 has metadata keys [mutation_type, d_source_id, g_source_id, d_fitness, mutation_context] — no "iteration" key. Normal mutants all have "iteration" key.
  implication: Confirms d_improvement programs are the ones missing "iteration"

- timestamp: 2026-04-13T12:14:00Z
  checked: Temporal correlation between last MetricsTracker activity and first d_improvement program
  found: Last MetricsTracker entry at 2026-04-12T21:13:25Z. First d_improvement created at 2026-04-12T21:13:24Z. Within 1 second.
  implication: MetricsTracker died on the very next _drain_once() cycle after the first CompositionInjection

- timestamp: 2026-04-13T12:16:00Z
  checked: A2_G (DB 3) same pattern
  found: frontier=1, total_count=9, actual_programs=256, d_improvement missing iteration key
  implication: Bug is systematic — affects ALL Arm A G runs identically

- timestamp: 2026-04-13T12:18:00Z
  checked: C1_G and C2_G (no CompositionInjection)
  found: C1_G: frontier=31, total=502, programs=509. C2_G: frontier=35, total=647, programs=648. Both healthy.
  implication: Arm C runs (no CompositionInjection) are unaffected — confirms CompositionInjection is the trigger

- timestamp: 2026-04-13T12:20:00Z
  checked: experiment.yaml extra_overrides
  found: Only A1_G and A2_G have post_step_hook=${composition_injection_hook}. C1_G and C2_G do not.
  implication: The presence/absence of CompositionInjection perfectly predicts which runs have broken metrics

- timestamp: 2026-04-13T12:25:00Z
  checked: D>>G gen desync across all arms
  found: A1:43vs19, A2:28vs24, C1:44vs32, C2:51vs34. Desync ranges 1.2-2.3x across ALL arms.
  implication: D>>G desync is expected — D evaluations are inherently faster. Not specific to Arm A.

## Resolution

root_cause: |
  CompositionInjectionHook.inject() (composition_injection.py:162-171) creates Program objects
  without an "iteration" key in metadata. When MetricsTracker._process_program() (metrics_tracker.py:235)
  encounters such a program, it calls program.metadata["iteration"] which raises KeyError.
  This unhandled exception propagates up through _drain_once() to run(), where it is caught
  by the outer except Exception handler (line 151), which logs the error and EXITS the while loop.
  The MetricsTracker async task dies permanently — all subsequent metrics (frontier, counts,
  per-program, per-gen aggregates) are never written. The run continues to evolve programs
  normally via the engine, but all metrics reporting is silently dead.

  Two bugs compound:
  1. PRIMARY: CompositionInjectionHook.inject() does not set "iteration" in program metadata
  2. SECONDARY: MetricsTracker._process_program() uses dict key access (program.metadata["iteration"])
     instead of .get() with a default, and MetricsTracker.run() does not gracefully handle
     per-program processing errors (one bad program kills the entire tracker)

fix: See Fix Plan below
verification: Run full test suite + restart experiment
files_changed: []

## Fix Plan

### Task 1: Promote `iteration` to top-level Program field (make omission impossible)

**Rationale**: Instead of relying on every Program-creation site to remember `metadata["iteration"]`, make `iteration` a typed Pydantic field with default=0. Impossible to omit by construction.

**Files to modify**:
1. `gigaevo/programs/program.py`
   - Add `iteration: int = Field(default=0, ge=0, description="Monotonic evaluation counter.")`
   - Add `@model_validator(mode='before')` to extract `metadata.iteration` → top-level field (Redis backwards compat)
   - Keep dual-write: `set_metadata("iteration", ...)` also updates `self.iteration` (or deprecate)
2. `gigaevo/evolution/engine/mutation.py:80`
   - `program.set_metadata("iteration", iteration)` → `program.iteration = iteration`
3. `gigaevo/problems/initial_loaders.py:38,109`
   - Remove `"iteration": 0` from metadata dicts (now redundant — default on field)
4. `gigaevo/adversarial/composition_injection.py:162`
   - No change needed — default=0 on field handles it. But optionally set explicitly for clarity.
5. `gigaevo/utils/metrics_tracker.py:235`
   - `program.metadata["iteration"]` → `program.iteration`
6. `gigaevo/utils/metrics_tracker.py:209`
   - `prog.metadata.get("iteration", 0)` → `prog.iteration`
7. `gigaevo/programs/stages/collector.py:508,522`
   - `program.get_metadata("iteration")` → `program.iteration`
8. `gigaevo/evolution/bus/engine.py:89`
   - `prog.metadata.get("iteration", 0)` → `prog.iteration`
9. `gigaevo/memory/ideas_tracker/csv_loader.py` — Check if CSV has iteration column; if so, extract to field

**Tests to update**:
- `tests/test_metrics_tracker.py:82` — `p.metadata["iteration"] = N` → `p.iteration = N`
- `tests/benchmarks/test_metrics_tracker.py:97,139` — `metadata={"iteration": N}` → `iteration=N`
- `tests/stages/test_collector.py:509,511,513` — `set_metadata("iteration", N)` → `.iteration = N`
- `tests/evolution/bus/test_engine.py:85` — same
- `tests/problems/test_initial_loaders.py:49,456` — assert `prog.iteration == 0` instead of metadata

**New tests**:
- Program() has iteration=0 by default
- Program deserialized from Redis blob with metadata.iteration populates top-level field
- Program serialized to dict includes iteration in metadata for backwards compat

### Task 2: MetricsTracker error isolation

**Files to modify**:
- `gigaevo/utils/metrics_tracker.py`
  - In `_drain_once()`, wrap per-program loop body in try/except that logs and continues
  - In `run()`, wrap `_drain_once()` in try/except that logs and continues the while loop (never exit)

**New tests**:
- MetricsTracker survives a program with broken data and continues to next program
- MetricsTracker continues running after _drain_once raises

### Task 3: Fix D>>G sync to achieve tighter parity

**Files to modify**:
- `config/pipeline/adversarial_asymmetric.yaml:67`
  - `min_delta: 1` → `min_delta: 8` (= max_mutations_per_generation)
  - Each population waits until opponent processes a full epoch before advancing

**Rationale**: With min_delta=8, after each epoch the sync hook blocks until the opponent has processed >=8 programs (roughly one epoch). This gives approximate 1:1 epoch parity. Current min_delta=1 allows D to run ~2.5x faster than G because D only waits for 1 program, not a full epoch.

### Task 4: Experiment restart

1. Log all issues in `experiments/heilbron/asymmetric-iterations/04_issues_log.md`
2. `/experiment-restart heilbron/asymmetric-iterations`

### Execution Order

1. Task 1 (Program.iteration field) — highest blast radius, do first
2. Task 2 (MetricsTracker error isolation) — defensive, small scope
3. Task 3 (sync config) — one-line config change
4. Run tests to verify no regressions
5. Commit all fixes
6. Task 4 (restart experiment)
