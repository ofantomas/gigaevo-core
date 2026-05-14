# Steady-state evolution engine — audit and redesign

**Date:** 2026-05-12
**Branch:** `refactor/steady-state-true-jit-refresh`
**Status:** draft for user review

## 1. Why this audit exists

The user characterises the current `SteadyStateEvolutionEngine` as
"spaghetti-coded" with several overlapping concepts. This document:

1. Names the concrete overlaps and where they live.
2. Proposes a redesign that delivers a *true* steady-state engine: refresh
   only the parents that are selected for mutation, no global epoch barrier,
   one canonical progress counter (`total_mutants`).
3. Sketches the resulting module split. The companion implementation plan
   (see `writing-plans` output) sequences the work.

The doc is intentionally scoped to the engine module
(`gigaevo/evolution/engine/`) and its direct contract with stoppers,
adversarial sync hooks, and downstream `NO_CACHE` stages. Strategies,
storage, and stage internals are out of scope.

## 2. Current state — concept map

### 2.1 Files in scope

| File | LOC | Role |
|---|---|---|
| `core.py` | 715 | Base `EvolutionEngine`: generational loop, ingest, full-archive refresh, snapshot, stop context |
| `steady_state.py` | 935 | `SteadyStateEvolutionEngine`: producer/consumer loops, epoch refresh, multi-pass / bucketed refresh, drains |
| `config.py` | 142 | `EngineConfig` + `SteadyStateEngineConfig` |
| `snapshot.py` | 76 | Frozen Pydantic `EngineSnapshot` (Redis-backed + in-process mirror) |
| `metrics.py` | 70 | `EngineMetrics` Pydantic counters |
| `stopper.py` | 115 | `EvolutionStopper` family |
| `mutation.py` | 159 | `generate_mutations` helper |
| `acceptor.py` | 162 | `ProgramEvolutionAcceptor` interface |
| `hooks.py`, `__init__.py` | small | Plumbing |

### 2.2 Overlapping concepts in the current engine

| Concept | Where it lives today | Why it's confused |
|---|---|---|
| `total_generations` | `EngineMetrics.total_generations`, `EngineSnapshot.total_generations`, `StopContext.total_generations`, log strings, `MaxGenerationsStopper` | In base it means "generation index". In steady-state it is **incremented at every epoch refresh** (`steady_state.py:600`) so it actually counts *epochs*. Two storage locations (metrics + snapshot) kept in sync by hand. |
| "epoch" vs "generation" | Docstrings, log lines (`"---- Epoch {} refresh ----"` at line 525), variable names (`_epoch_mutants`, `_processed_since_epoch`, `epoch_trigger_count`) | The codebase uses both terms for the same counter. `epoch_trigger_count` is just `max_mutations_per_generation` aliased — a config knob whose `max_mutations_per_generation` name is itself a generational-era artefact. |
| Mutation loop gating | `_mutation_gate: asyncio.Event` + `_draining: bool` (lines 67–69) | Two flags for "is the mutation loop allowed to spawn tasks". `_draining` suppresses the *trigger*; `_mutation_gate` blocks the *loop*. Their lifecycles overlap (the gate is briefly closed *inside* `_epoch_refresh` while `_draining=True`). |
| Drain paths | `_drain_in_flight`, `_drain_scoped`, `_poll_and_ingest(exclude_ids=…)` | Three call sites. `_drain_in_flight` is barely used (only the legacy shutdown path). `_drain_scoped` mixes "wait for a specific set" with "opportunistically ingest non-set programs", coupling drain and ingestion. |
| Ingestion paths | `EvolutionEngine._ingest_completed_programs` (base, `core.py:413`) + `SteadyStateEvolutionEngine._ingest_batch` (`steady_state.py:383`) | Two nearly-parallel accept/reject loops with the same notify-hook/batch-discard structure. SS overrides the entire pipeline but keeps the base method for its own initial-population ingestion at `steady_state.py:114`. |
| Archive refresh | `EvolutionEngine._refresh_archive_programs` (base, one-shot flip) → `SteadyStateEvolutionEngine._refresh_archive_programs` (multi-pass dispatcher) → `_refresh_archive_programs_one_pass` (fifo/bucketed) → `super()._refresh_archive_programs()` (fallback) | Four methods across two classes implement what is conceptually "flip these programs DONE→QUEUED and wait". The multi-pass / bucketed code exists because of the cross-program `DGImprovementTracker` race that emerges *because* the archive is globally refreshed (`steady_state.py:797–818`). |
| Cache-key plumbing | `EngineSnapshot.refresh_pass` + `SharedBenchmarkFilteredLineageStage` reading the counter via `get_current_snapshot()` | Engine internals (refresh-pass index) leak into stage cache keys. Stages must know about engine bookkeeping to avoid stale cache hits. |
| Epoch trigger heuristics | `_should_trigger_epoch`, `_EPOCH_WATERMARK_FALLBACK_S`, `_epoch_eligible_since` | An opportunistic "wait for a valley in in-flight count" heuristic plus a 15s fallback timer plus a `<=3` short-circuit. All exists because the global epoch barrier is expensive and the engine tries to amortise it. |
| Elite cache | `_cached_elites`, `_elite_cache_lock`, "thundering herd" docstring | Exists because the gate-reopen at epoch boundary unblocks many mutation tasks simultaneously, all of whom need fresh elites. |

### 2.3 Why the current design exists (in one paragraph)

The steady-state engine was grafted onto a generational base. The grafting
preserved the generational `step()` cadence as the *cadence at which the
archive becomes coherent*: every epoch, the entire archive is flipped
DONE→QUEUED so descendant-aware and tracker-aware stages can re-run with
all their cross-program inputs fresh. The cross-program tracker race
inside that global refresh then forced multi-pass (`refresh_passes=2`)
and bucketed (`refresh_order=generation_bucketed`) ordering. The mutation
loop is paused during this global re-coherence to avoid starting children
that read mid-refresh tracker state. All other concept overlap (two flags,
three drain paths, two ingestion paths, watermark heuristics, elite cache)
is downstream of this single design choice: **the engine globally
re-coheres the archive on a fixed cadence**.

## 3. Target design — true steady state

### 3.1 One sentence

**The engine is a continuous async stream of independent mutation
tasks.** Each task picks parents, refreshes those parents on the spot,
produces one mutant, and exits. There is no epoch, no batch, no global
barrier. The only coordination is (a) a `max_in_flight` semaphore for
backpressure and (b) a per-parent-id lock so two tasks that happen to
pick the same parent don't double-flip it.

### 3.2 Conceptual model

The engine has **two long-running coroutines** and a **fan-out of
short-lived per-mutant tasks**:

```
                         ┌── per-mutant task ─────────────────────┐
                         │   parents = parent_selector.pick(...)  │
        dispatcher ──┬──▶│   parents = await refresh(parents)     │
        (long-lived) │   │   mutant  = await mutate(parents)      │
                     │   │   if mutant:                           │
                     │   │       in_flight.add(mutant.id)         │
                     │   │       Program.iteration = total_mutants│
                     │   │       total_mutants += 1               │
                     │   │   else:                                │
                     │   │       semaphore.release()              │
                     │   └────────────────────────────────────────┘
                     │       (one task per mutant, runs to completion
                     │        independently — no shared state with
                     │        other in-flight tasks except the in_flight
                     │        set and the per-parent refresh lock)
                     │
        in_flight set ──── (shared)
                     │
                     ▼
        ingestor (long-lived)
          while running:
            poll in_flight via storage.mget
            for prog in DONE:    ingest (accept→archive | reject→DISCARDED)
            for prog in vanished: sweep
            release semaphore slots for handled IDs

dispatcher loop:
  while running:
    await semaphore.acquire()         # backpressure: blocks when full
    asyncio.create_task(per_mutant())  # spawn and forget
    # NO awaiting the per-mutant task here — the dispatcher
    # immediately loops back for the next slot
```

Critically:

- The dispatcher **does not await** per-mutant tasks. It spawns and
  loops. Backpressure is enforced *only* by the semaphore — when slots
  are exhausted, the dispatcher's `acquire()` blocks; per-mutant tasks
  themselves are not gated.
- N per-mutant tasks run concurrently, each doing
  `refresh → mutate → register`. A slow parent refresh on task A does
  not block task B, C, D unless they share a parent (in which case
  task B waits on A's per-parent lock for that one parent only).
- The ingestor is a single coroutine (not per-mutant) because batch
  `storage.mget` is cheaper than N independent polls. It is purely
  an **implementation detail** of "wait for DAG eval to finish":
  conceptually each per-mutant task is finished when its mutant
  reaches DONE; mechanically that observation is multiplexed by the
  ingestor.

No epoch barrier. No mutation gate. No drain. No global refresh. No
multi-pass. No bucketed refresh. No refresh-pass cache-key counter.
**No batched cohort of mutants** — mutants are born, evaluated, and
ingested in a continuous stream whose only rate-limiter is the
semaphore.

### 3.3 What disappears

The following all go away in one bundle (each is justified by "there is no
epoch"):

- `_mutation_gate: asyncio.Event` and every `_mutation_gate.wait()` / `_mutation_gate.clear()` / `_mutation_gate.set()` call
- `_draining: bool` and every reference
- `_processed_since_epoch`, `_epoch_mutants`, `_epoch_eligible_since`
- `_EPOCH_WATERMARK_FALLBACK_S`
- `_should_trigger_epoch`
- `_epoch_refresh` (entirely)
- `_drain_in_flight` (no one will call it)
- `_drain_scoped` (no one will call it)
- `_cached_elites`, `_elite_cache_lock`, `_get_cached_elites` — the JIT-refresh flow has no "many tasks unblock at once" moment, so no thundering herd to dampen. **Caveat:** if `select_elites` turns out to be expensive enough that per-mutant-task call cost matters, reintroduce a short-TTL cache as a localised optimisation in `mutant_task.py`. Do not pre-emptively add it.
- `SteadyStateEngineConfig.refresh_passes`, `refresh_order`, `epoch_trigger_count` property
- `EngineSnapshot.refresh_pass`
- `_refresh_archive_programs` overrides and the entire bucketed-refresh branch
- The "wait for refresh DAGs after ingest" tail in base `step()` (since base `step()` itself goes away — see §3.6)

### 3.4 What's new

A single helper:

```python
async def _refresh_parents(self, parents: list[Program]) -> list[Program]:
    """Flip selected parents DONE→QUEUED, wait until they are DONE again,
    return the freshly-evaluated Program objects.

    Multi-parent aware: `parents` may have len > 1 when
    `ParentSelector.num_parents > 1` (both `RandomParentSelector` and
    `AllCombinationsParentSelector` already take this knob). All parents
    in the list are refreshed together — flipped in one batch transition
    and awaited as a set — so the producer never reads a half-fresh
    parent bundle.

    Idempotent: parents already QUEUED/RUNNING are awaited; DISCARDED parents
    are surfaced as errors to the caller (they should not have been selected).
    """
```

This is the only place archive programs are flipped after the seed
phase. Its scope is exactly `len(parents)` — `num_parents` from the
configured `ParentSelector` (see
`gigaevo/evolution/mutation/parent_selector.py`:
`RandomParentSelector(num_parents=1)` is the default;
`RandomParentSelector(num_parents=2+)` and
`AllCombinationsParentSelector(num_parents=2+)` are the multi-parent
paths the helper must batch-refresh together).

Open subquestions for this helper (deferred to the implementation plan,
not the audit):

- **Per-mutant slot accounting.** If parent refresh runs inside the
  producer's `acquired` semaphore window, parent-DAG time eats into
  in-flight budget. Likely we keep the slot held (parent re-eval is part
  of producing one mutant) but the plan should benchmark this.
- **Concurrent same-parent refresh.** Two producer tasks may select
  overlapping parents within ms of each other (especially when
  `num_parents > 1` — two producers can share one parent of a
  multi-parent bundle). The helper needs to no-op for a parent already
  in flight rather than double-flip it. A per-parent-id `asyncio.Lock`
  or a `dict[str, asyncio.Future]` "in-progress refresh" registry
  handles this; the plan picks one.
- **Failure semantics.** If any parent's refresh DAG fails or times
  out, the producer task aborts that mutant (releases the slot) — does
  *not* fall back to using stale parent state for the remaining
  parents, because that would silently reintroduce the very
  inconsistency we are removing. Multi-parent batches are
  all-or-nothing.

### 3.5 Counter consolidation

```
BEFORE                             AFTER
──────                             ─────
EngineMetrics.total_generations    EngineMetrics.total_mutants
EngineSnapshot.total_generations   (removed)
EngineSnapshot.programs_processed  EngineSnapshot.programs_processed   (unchanged)
EngineSnapshot.refresh_pass        (removed)
StopContext.total_generations      StopContext.total_mutants
MaxGenerationsStopper              MaxMutantsStopper (alias kept for one release)
Program.iteration  (== old epoch)  Program.iteration  (== total_mutants
                                                       at production time)
```

**`Program.iteration` is the plot/metrics axis** (see
`gigaevo/programs/stages/collector.py:549` populating
`EvolutionaryStatistics.iteration`, `*_in_iteration` aggregates at
`collector.py:171–182`, and the plot x-axis at
`gigaevo/utils/plotting.py:26,56,60,64` and
`gigaevo/cli/plot_group.py:353,520,744`). Today this field is fed
`self.metrics.total_generations` (i.e. the epoch counter) by both base
and steady-state engines (`core.py:407`, `steady_state.py:281`).

Under the new design, `Program.iteration = total_mutants_at_production`.
That is the same monotone axis, just denser (one tick per mutant
instead of one tick per epoch). Plot semantics are preserved:

- `iteration` remains monotone non-decreasing and dense in production
  order.
- `*_in_iteration` aggregates (best/worst/avg/valid-rate over programs
  sharing the same `iteration` value) become aggregates *per mutant*.
  Under epochs they were aggregates *per epoch* (i.e. over the cohort
  produced in one mutation phase). Under JIT, each mutant has its own
  iteration value, so the per-iteration aggregates collapse to "this
  one program" — i.e. they become uninformative as cohort statistics.

  **Decision:** stop computing `*_in_iteration` fields under the new
  engine (set to `None`, the field is already `| None`). Migrate any
  consumer that needs cohort aggregates (plot smoothers, exporters) to
  a *windowed* aggregate over `iteration` — e.g. rolling-mean over a
  fixed mutant window. Concrete consumer audit (which call sites in
  `cli/plot_group.py` and `cli/export.py` actually read
  `*_in_iteration`) is a plan-level task. If any consumer hard-depends
  on cohort-by-iteration semantics, we add an `iteration_bucket`
  field (= `iteration // bucket_size`) computed at plot time, not at
  collection time — keeping the engine free of plot-bucket choices.

`utils/trackers/` (`step: int`) is unaffected: that counter is
per-tag and auto-incremented; the engine never read or wrote it
through `iteration`.

- `total_mutants` is incremented **once, in the producer, immediately
  after `generate_mutations` returns a non-empty list** (i.e. when a
  mutant id is added to `in_flight`). Not on accept, not on DONE —
  "produced" is the cleanest invariant because it's pre-evaluation and
  monotone.
- `programs_processed` keeps its current meaning ("number of mutants
  that reached DONE, accepted or rejected"). It remains the
  Redis-published counter the `ProgressBasedSyncHook` reads, so no
  external contract breaks.
- `MaxGenerationsStopper` (which today already keys on
  `total_generations` == epoch count) becomes `MaxMutantsStopper`
  keying on `total_mutants`. **Config-migration heuristic only** (not a
  strict equality, because today's `programs_processed` counts
  *evaluated* mutants while `epoch_trigger_count =
  max_mutations_per_generation` counts *processed-since-epoch*):
  `new max_mutants ≈ old max_generations × max_mutations_per_generation`.
  The implementation plan keeps `MaxGenerationsStopper` as a deprecated
  alias for one release so existing Hydra configs do not break on
  upgrade.
- `GenerationBoundary` event in `monitoring/events.py` is emitted by
  base `step()` only. Since base `step()` goes away (§3.6), this
  event source goes with it. Monitoring plugins that listened for
  generation boundaries (e.g. `monitoring/plugins/solo.py`) move to a
  programs-processed threshold or a wall-clock cadence.

### 3.6 Generational engine — keep or delete?

There is **no remaining production caller** of the generational
`EvolutionEngine.step()` once steady-state covers every use case. The
audit recommends:

- **Delete `EvolutionEngine.step()` and its generational `run()` loop.**
- Keep the *class* `EvolutionEngine` as a thin abstract base holding
  shared concerns (snapshot, metrics, hooks, `_await_idle`,
  `_select_elites_for_mutation`, `_notify_hook`,
  `_build_stop_context`, `_write_snapshot`, `restore_state`).
- Move the dispatcher loop, per-mutant task function, ingestor loop,
  the `_refresh_parents` helper, and in-flight bookkeeping into
  `SteadyStateEvolutionEngine` — which then becomes *the* engine.
  Optionally rename `SteadyStateEvolutionEngine → EvolutionEngine`
  later as a separate cleanup; this audit does not require the rename.

Risk: any test or experiment config that explicitly uses the
generational engine breaks. The plan will inventory and migrate them
before the deletion lands.

## 4. Module split

Once epochs vanish, the remaining engine is small enough to split along
clean responsibilities. Target: no file >~250 LOC; each file has a
single concern.

```
gigaevo/evolution/engine/
├── __init__.py            # public exports
├── config.py              # EngineConfig (SS-only knobs: max_in_flight)
├── snapshot.py            # EngineSnapshot (no refresh_pass)
├── metrics.py             # EngineMetrics (total_mutants, not total_generations)
├── stopper.py             # MaxMutantsStopper + others (StopContext.total_mutants)
├── acceptor.py            # (unchanged)
├── mutation.py            # generate_mutations helper (unchanged interface)
├── hooks.py               # (unchanged)
├── engine.py              # NEW: lifecycle (start/stop/pause/resume), snapshot,
│                          #      metrics, _await_idle, _notify_hook,
│                          #      _build_stop_context, _write_snapshot.
│                          #      Owns the in_flight set, semaphore, and
│                          #      per-parent refresh-lock registry.
├── dispatcher.py          # NEW: the long-lived "spawn per-mutant tasks"
│                          #      loop. Acquires semaphore, creates task,
│                          #      loops. ~50 LOC.
├── mutant_task.py         # NEW: the per-mutant async function:
│                          #      pick_parents → refresh → mutate →
│                          #      register-or-release. One asyncio task
│                          #      per mutant, runs to completion
│                          #      independently. ~80 LOC.
├── ingestor.py            # NEW: long-lived ingestion coroutine.
│                          #      _poll_and_ingest, _ingest_batch,
│                          #      accept/reject/notify. ~150 LOC.
└── refresh.py             # NEW: _refresh_parents (the only post-seed
                           #      DONE→QUEUED path), per-parent lock
                           #      registry, failure semantics. ~80 LOC.
```

`engine.py` composes `dispatcher`, `mutant_task`, `ingestor`, `refresh`
— it owns the shared state (the in-flight set, the semaphore, the
per-parent lock registry, the snapshot) and hands references to the
workers. The dispatcher and ingestor are the only long-lived
coroutines; `mutant_task` is a function that the dispatcher spawns
per mutant.

Single-responsibility test: each file should be summarisable in one
sentence and unit-testable with a single fake (storage, strategy, or
mutation operator), not all three at once.

## 5. Migration boundary — what must keep working

| Consumer | Key it reads | Action |
|---|---|---|
| `gigaevo/adversarial/sync.py` (`ProgressBasedSyncHook`) | `EngineSnapshot.programs_processed` | Unchanged. Already keys on the right counter. |
| `gigaevo/prompts/coevolution/sync.py` | same | Unchanged. |
| `gigaevo/monitoring/redis_queries.py` | `EngineSnapshot.total_generations` | Update to read `total_mutants` (one site to fix). |
| `MaxGenerationsStopper` callers (Hydra configs `config/stopper/*.yaml`) | `max_generations` key | Plan adds a transition shim: accept `max_generations` as deprecated alias for `max_mutants`. After one cleanup pass, remove the alias. |
| `SharedBenchmarkFilteredLineageStage` cache key (uses `EngineSnapshot.refresh_pass`) | `refresh_pass` | Cache-key contract changes. Since global refresh is gone, the pass counter no longer makes sense. The stage moves to keying on the (refreshed-once) parent set or a per-program version field. Worked out in the implementation plan. |
| `GenerationBoundary` event consumers (`monitoring/plugins/*`) | event stream | Replace boundary subscribers with a counter-threshold subscriber. Listed in §6 follow-ups. |
| Plot/CLI tooling (`cli/plot_group.py`, `cli/export.py`, `utils/plotting.py`, `utils/dataframes.py`) | `Program.iteration` column / x-axis | **No breaking change.** Field stays; the value now ticks per-mutant instead of per-epoch (denser axis). Migration only required for the `*_in_iteration` cohort aggregates in `collector.py` (see §3.5). |

## 6. Risks and follow-ups (deferred to plan, not the audit)

1. **Descendant-aware stages without global refresh.** Today a
   grandparent's `LineagesToDescendantsStage` view picks up its
   newly-added grandchild only after the next global flip. Under JIT,
   the grandparent's view stays stale until the grandparent is itself
   picked as a parent. The user has explicitly accepted this trade.
   The audit only flags it for the plan to *measure* (e.g. distribution
   of "selections since last refresh" per archive program — confirms
   popular elites stay fresh in practice).
2. **`DGTrackerStage` cross-program writes.** The two-pass /
   bucketed refresh exists to close a tracker race that only
   *exists because* the archive is globally refreshed. With JIT,
   parents are re-evaluated sequentially per producer-task, and
   children are produced *after* their parents' tracker writes
   land. The race is structurally eliminated. The plan must verify
   no other consumer depended on the global ordering.
3. **`FitnessPlateauStopper` is currently dead.** `core.py` does not
   populate `StopContext.best_fitness` (a TODO at `stopper.py:59-63`
   admits this). The audit recommends wiring it in `_build_stop_context`
   as a quick win during the refactor since `_metrics_tracker` already
   knows the best fitness.
4. **Test coverage.** The current `tests/` directory must be inventoried
   for engine tests before deletion-by-rename starts. Expectation: tests
   referencing "epoch" or "generation" semantics will need rewriting
   against the new producer/consumer/refresh boundaries.
5. **`*_in_iteration` cohort aggregates.** Under epochs, "iteration"
   was a cohort (the mutants of one epoch); under JIT it's a single
   mutant, so cohort-aggregate fields collapse to scalars. The plan
   must (a) grep for consumers of
   `{best,worst,average}_fitness_in_iteration` and `valid_rate_in_iteration`
   in `cli/`, `utils/`, and any monitoring plugin, (b) decide per
   consumer: drop, replace with rolling-window aggregate, or replace
   with an explicit `iteration_bucket` view computed at plot time.
   No engine change depends on this; it is downstream collector/plot
   cleanup.
6. **Multi-parent backpressure.** With `num_parents=2+`, one producer
   task holds one in-flight slot while refreshing N parents. If many
   producers concurrently want overlapping parents, the per-parent
   refresh lock serialises them — this is desired (no double-flip)
   but the plan should verify it doesn't starve producers when
   `max_in_flight` is small and the elite set is small. Likely fine
   in practice (parent refresh is fast vs. mutation LLM call) but
   worth a smoke test.

## 7. What this audit does *not* commit to

- A specific class hierarchy beyond §4's file split (e.g. ABCs vs
  duck-typed composition is a plan-level decision).
- The exact ordering of refactor steps. The implementation plan
  sequences them under TDD with checkpoints.
- Renaming `SteadyStateEvolutionEngine → EvolutionEngine` (optional
  follow-up).
- Migration of CMA / non-LLM optimisers that also use
  `MaxGenerationsStopper` (`gigaevo/programs/stages/optimization/cma.py`)
  — those run outside the evolution engine and keep generational
  semantics; their stopper alias is preserved.

## 8. Success criteria

The refactor is done when:

1. `gigaevo/evolution/engine/` has no file >300 LOC and each file's
   single responsibility is stated in its module docstring.
2. The string `epoch` does not appear in `gigaevo/evolution/engine/`
   except in legacy-config back-compat shims.
3. `total_mutants` is the single producer-incremented counter; no
   other field tries to count "iterations".
4. The full test suite passes; one new integration test covers
   "select-parent → JIT-refresh → produce-mutant → ingest" end-to-end
   without an epoch barrier.
5. A smoke run of one current production-style experiment config
   (e.g. `heilbron/d-tanh-no-lineage`) reaches a known-good fitness
   trajectory on the new engine.

## 9. Smoke-test results

### 9.1 Hydra config dry-run (2026-05-12)

A fresh `python run.py problem.name=heilbron_smooth_v1/pop_a
evolution=steady_state stopper=max_mutants max_mutants=3 --cfg job`
resolves cleanly. Key observations from the dumped config:

| Target | Resolved value |
|---|---|
| Engine | `gigaevo.evolution.engine.SteadyStateEvolutionEngine` |
| Engine config | `gigaevo.evolution.engine.SteadyStateEngineConfig` |
| Stopper | `gigaevo.evolution.engine.stopper.MaxMutantsStopper` |
| `max_mutants` | `3` (override propagated) |
| `max_in_flight` | `8` (steady_state.yaml default) |

No reference to `max_mutations_per_generation`, `MaxGenerationsStopper`,
`total_generations`, `refresh_pass`, or `refresh_passes` appears anywhere
in the resolved config. The new schema is the canonical one.

The pre-existing `experiments/heilbron/d-tanh-no-lineage/experiment.yaml`
retains its closed-experiment freeze (`stopper: max_generations`,
`max_mutations_per_generation: 8`, `refresh_passes: 1`) — per the
project's "no migration scripts for closed experiments" rule, that file
is not modified. Any *new* experiment generated after this refactor must
use `stopper: max_mutants` and omit the dead fields.

### 9.2 Live cluster run

A full live-cluster smoke run on `heilbron/d-tanh-no-lineage` is deferred
to a follow-up after merge — it requires GPU servers and the user's
launch authorization, and the refactor is dry-run-clean.
