# Phase 2: Fix Adversarial Injection Logic and Watchdog Plots - Research

**Researched:** 2026-04-12
**Domain:** Adversarial co-evolution pipeline bugs + watchdog monitoring
**Confidence:** HIGH

## Summary

This phase addresses three critical bugs in the heilbron/asymmetric-iterations experiment. All three bugs were confirmed by reading source code -- this is not speculative.

**Bug 1 (CompositionInjectionHook)** has two sub-problems: (a) it injects D's raw `improve(points)` code into G's population, but G's evaluator expects an `entrypoint() -> (11,2) array`, so the injected code will always fail validation; (b) it uses the globally best D program (`get_top_k(1)`) instead of the D program that specifically improved a particular G program. Additionally, the hook is **defined but never wired** into any engine or Hydra config -- it exists only as dead code that is never instantiated.

**Bug 2 (GradientInPromptStage)** uses `get_top_k(1, higher_is_better=True)` to pick the globally best D program for the mutation prompt. The design intends for G to see the D that most improved its specific programs, but the current `OpponentArchiveProvider` interface only supports global ranking (no per-G-program improvement deltas are stored in Redis). A pragmatic fix is to show the most effective D overall, which is what it currently does -- the real question is whether the current behavior is the intended behavior. Per the design doc, "the D that most improved the specific G program being mutated" is desired but requires new Redis data structures.

**Bug 3 (Watchdog plots)** shows negative fitness values because: (a) the `run_watchdog.py` calls `gigaevo plot comparison` with `--no-frontier` but no `--metric` flag, defaulting to `fitness`; (b) both pop_a and pop_b `evaluate.py` use `fitness: -1.0` as sentinel for invalid programs; (c) the mean/rolling-window computation includes these -1.0 sentinels, pulling the mean negative; (d) the experiment's `metric_name` in experiment.yaml is `actual_fitness`, not `fitness`, but the plot command does not use it. The actual `comparison.py` / `plot_group.py` do not filter sentinel values.

**Primary recommendation:** Fix Bug 1 by wrapping D's improve function output in a valid G-style entrypoint and wiring the hook into the engine. Defer per-program D matching (Bug 2) as a separate enhancement. Fix Bug 3 by passing `--metric actual_fitness` and filtering sentinel values in the plot pipeline.

## Project Constraints (from CLAUDE.md)

- **Always use `/run-tests` skill** -- never run pytest directly via Bash [VERIFIED: CLAUDE.md]
- **GitNexus pre-flight mandatory** before any code change -- `gitnexus_impact` + `gitnexus_detect_changes` [VERIFIED: CLAUDE.md]
- **Python**: `/home/jovyan/.mlspace/envs/evo/bin/python3` [VERIFIED: CLAUDE.md]
- **CLI**: Always use `gigaevo` CLI commands, not `PYTHONPATH=. python tools/...` [VERIFIED: CLAUDE.md]
- **Merge**: `gh pr merge --merge --delete-branch` (not --squash) [VERIFIED: CLAUDE.md]
- **TDD non-negotiable**: Every production code change driven by a failing test [VERIFIED: CLAUDE.md]
- **Running experiment constraint**: adversarial-dynamic-updates running on separate branch; this branch (exp/heilbron/asymmetric-iterations) has the running asymmetric-iterations experiment [VERIFIED: STATE.md]

## Architecture Patterns

### Adversarial Evaluation Flow (verified from source)

```
G (Constructor, pop_a):
  entrypoint() -> (11,2) np.ndarray    # G produces point configurations
  evaluate.py receives:
    program_output: (11,2) array        # G's output
    opponent_results: list of callables  # D's improve() functions
  fitness = 0.5 * quality + 0.5 * resistance

D (Improver, pop_b):
  entrypoint() -> callable improve(pts) -> improved_pts
  evaluate.py receives:
    program_output: callable            # D's improve() function
    opponent_results: list of (11,2) arrays  # G's point configs
  fitness = mean(normalized improvements)
```

[VERIFIED: `problems/heilbron_adversarial/pop_a/evaluate.py` and `pop_b/evaluate.py`]

### Pipeline Architecture

```
AdversarialAsymmetricPipelineBuilder (extends AdversarialPipelineBuilder):
  Standard pipeline + FetchOpponentIds + FetchOpponentResults
  + For D (improver): SourceCodeInjectionStage
  + For G (constructor) + gradient_in_prompt: GradientInPromptStage
  + For G (constructor) + composition: NO pipeline change (hook is external)
```

[VERIFIED: `gigaevo/adversarial/asymmetric_pipeline.py`]

### Hydra Config Wiring

```yaml
# adversarial_asymmetric.yaml
opponent_provider:  # points to opponent's Redis archive
  _target_: RedisOpponentArchiveProvider
  sources: [{db: ${opponent_redis_db}, prefix: ${opponent_redis_prefix}}]

pipeline_builder:
  _target_: AdversarialAsymmetricPipelineBuilder
  opponent_provider: ${opponent_provider}
  d_provider: ${opponent_provider}      # SAME as opponent_provider!
  population_role: ${population_role}
  feedback_mode: ${feedback_mode}
```

**Critical observation:** For G runs, `opponent_provider` points to D's archive (via `opponent_redis_db`/`opponent_redis_prefix`). Since `d_provider: ${opponent_provider}`, the `d_provider` also points to D's archive. This is correct for GradientInPromptStage (it needs D's programs). [VERIFIED: `config/pipeline/adversarial_asymmetric.yaml`]

### Engine Hook Architecture

The `EvolutionEngine` supports a single `pre_step_hook` callable (called before each generation step). Currently used by `MainRunSyncHook` or `ProgressBasedSyncHook` for synchronization. There is **no** `post_step_hook` or `post_generation_hook` in the engine API. [VERIFIED: `gigaevo/evolution/engine/core.py:56,209`]

### Watchdog Architecture

Two watchdog paths exist for this experiment:

1. **run_watchdog.py** (legacy script) -- currently running, uses `subprocess.run(["gigaevo", ..., "plot", "comparison", ...])` [VERIFIED: `experiments/heilbron/asymmetric-iterations/run_watchdog.py:271-301`]
2. **WatchdogEngine + HeilbronPlugin** (new CLI) -- uses matplotlib panel plots, NOT comparison curves [VERIFIED: `gigaevo/monitoring/plugins/heilbron.py`]

The run_watchdog.py is the ACTIVE watchdog (PID 4052592 per experiment.yaml). It generates the problematic plots. [VERIFIED: experiment.yaml `launch.watchdog_pid: 4052592`]

## Bug Analysis

### Bug 1: CompositionInjectionHook Injects Wrong Code

**Root cause (confirmed):** Three distinct sub-bugs:

1. **Type mismatch**: `CompositionInjectionHook.inject()` takes `d_best.code` (which is D's `entrypoint()` returning a callable `improve(pts)`) and creates a `Program(code=d_best.code)` in G's storage. But G's evaluator calls `entrypoint()` expecting an `(11,2) ndarray`. D's code returns a callable, not an array. The injected program will always fail G's `_validate_config()`. [VERIFIED: `composition_injection.py:44`, `pop_a/evaluate.py:36-48`]

2. **Global best, not per-program best**: Uses `get_top_k(1)` -- global best D by fitness, not the D that beat a specific G program. The design calls for D(G()) output, not D's global best. [VERIFIED: `composition_injection.py:38`]

3. **Never wired**: `CompositionInjectionHook` is defined but **never instantiated** anywhere in the codebase. No Hydra config, no `run.py`, no entrypoint references it. The `asymmetric_pipeline.py` docstring says "CompositionInjectionHook is wired at the engine level (not here)" but no engine-level wiring exists. [VERIFIED: grep for `CompositionInjectionHook` across the entire codebase -- only found in definition, test, docstrings, and design docs]

**What the fix needs:**

- Wrap D's `improve()` output as a valid G-style entrypoint that returns an `(11,2)` array
- The injected code should be something like: `def entrypoint(): return improve(g_points)` where `improve` is D's function and `g_points` is the G program being improved
- Wire the hook into the engine lifecycle (needs a post-generation callback or integration into the pipeline)
- The engine only has `pre_step_hook` -- no post-step hook exists, so the hook needs to be called somewhere
- Options: (a) add a `post_step_hook` to the engine, (b) integrate injection as a pipeline stage, (c) call it in the sync hook

**Existing test coverage:** 4 tests in `tests/adversarial_pipeline/test_composition_injection.py` -- but they only test the current (buggy) behavior (raw code injection). Tests need updating. [VERIFIED: test file read]

### Bug 2: GradientInPromptStage Picks Wrong D

**Root cause (confirmed):** `GradientInPromptStage.compute()` calls `self._provider.get_top_k(1, higher_is_better=True)` -- this returns the globally best D program by fitness. [VERIFIED: `gradient_prompt.py:57`]

**What the design wants:** "the D that most improved the specific G program being mutated, or at minimum the D with highest improvement delta" (from phase description).

**Why this is hard to fix properly:**

- `OpponentArchiveProvider` caches a flat list of `OpponentProgram(program_id, code, fitness)` -- no per-G-program improvement data is stored [VERIFIED: `opponent_provider.py:45-47`]
- Redis does not store per-opponent evaluation results (improvement deltas) -- `evaluate.py` returns aggregate metrics only [VERIFIED: `pop_a/evaluate.py:109-120`]
- To know "which D most improved G_i" would require either:
  - Running D's `improve()` on each G program and comparing results (expensive, requires subprocess execution)
  - Storing per-pair evaluation results in Redis (new data structure)

**Pragmatic approach:** The "globally best D" is already a reasonable heuristic. The design doc says "or at minimum the D with highest improvement delta" -- the highest fitness D likely has the highest improvement delta too (since D's fitness IS its mean improvement). The current behavior may be acceptable with documentation of the limitation.

**Existing test coverage:** 6 tests in `tests/adversarial_pipeline/test_gradient_prompt.py`. [VERIFIED: test file read]

### Bug 3: Watchdog Plots Show Negative Values

**Root cause (confirmed by viewing actual plots):**

The `comparison_hour_002.png` plot clearly shows:
- Y-axis ranges from -1.0 to +1.0
- Several runs (especially D runs) show mean fitness going negative
- Huge confidence bands spanning from -1.0 to +1.0

This happens because:

1. **Wrong metric**: `run_watchdog.py` calls `gigaevo plot comparison` without `--metric`, defaulting to `fitness`. But `experiment.yaml` specifies `metric_name: actual_fitness`. The `fitness` metric includes sentinel value -1.0 for invalid programs. [VERIFIED: `run_watchdog.py:276-294`, experiment.yaml]

2. **Sentinel values not filtered**: Both `pop_a/evaluate.py` and `pop_b/evaluate.py` return `{"fitness": -1.0, ...}` for invalid programs. The plotting code includes ALL program evaluations (including invalids) in the rolling mean/std computation. Neither `comparison.py` nor `plot_group.py` filter out sentinel values. [VERIFIED: `pop_a/evaluate.py:24-33`, `pop_b/evaluate.py:20-29`, `tools/comparison.py` grep for sentinel]

3. **Bar chart vs time series**: The HeilbronPlugin (new CLI watchdog) uses simple bar charts of latest metric snapshots -- it does NOT use the time series comparison plot. The run_watchdog.py (legacy, actually running) uses `gigaevo plot comparison` which plots the full iteration history with sentinel-polluted data. [VERIFIED: `heilbron.py:64-93` vs `run_watchdog.py:271-301`]

**What the fix needs:**

- Pass `--metric actual_fitness` in `run_watchdog.py` (matches experiment.yaml `metric_name`)
- OR filter sentinel values (-1.0) from the plotting data in `plot_group.py` / `comparison.py`
- Ideally BOTH: use the right metric AND filter sentinels

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| D output wrapping for G injection | Custom code generation from scratch | Template-based wrapper that calls D's `improve()` on the specific G points | Must produce syntactically valid Python that passes G's full DAG |
| Per-program D matching | Custom Redis query layer | Simple heuristic (global best D) with TODO for future improvement | Full per-program matching requires new Redis data structures and is expensive |
| Sentinel filtering in plots | Custom per-metric filtering | Use `metrics.yaml` `sentinel_value` field to auto-filter | Already defined in each problem's metrics.yaml |

## Common Pitfalls

### Pitfall 1: Injected Code Must Pass G's Full DAG Pipeline

**What goes wrong:** The injected program goes through G's complete DAG: ValidateCodeStage (syntax check), CallProgramFunction (execute `entrypoint()`), FetchOpponentIds, FetchOpponentResults, CallValidatorFunction (evaluate.py). If the injected code has the wrong function signature or returns the wrong type, it fails silently.
**Why it happens:** D's `entrypoint()` returns a callable, not an array. G's pipeline expects `entrypoint()` to return an `(11,2) ndarray`.
**How to avoid:** The injected program must define `entrypoint()` that returns an `(11,2) ndarray`. It should wrap D's improvement of a specific G program's output.
**Warning signs:** High invalidity rate on injected programs (metadata `mutation_type=d_improvement` programs failing validation).

### Pitfall 2: CompositionInjectionHook Has No Engine Wiring Point

**What goes wrong:** The hook is designed as a "post-sync hook" but the engine only has `pre_step_hook`. There is no `post_generation_hook` or `post_step_hook` in the `EvolutionEngine` API.
**Why it happens:** The hook was designed after the engine API was frozen.
**How to avoid:** Options: (a) call injection from within the sync hook itself (before yielding control to the next gen), (b) add a `post_step_hook` to the engine, (c) make it a pipeline stage instead.
**Warning signs:** Hook defined but never called.

### Pitfall 3: Sentinel Values Pollute Aggregate Statistics

**What goes wrong:** Invalid programs have `fitness=-1.0` and `actual_fitness=-1.0`. The comparison plot computes rolling mean/std over ALL evaluations, including invalids. With high invalidity rates (50%+), the mean is pulled far below zero.
**Why it happens:** Sentinel values are a valid design pattern for marking invalids, but downstream consumers (plots) don't filter them.
**How to avoid:** Use the `sentinel_value` field from `metrics.yaml` (already defined!) to filter before aggregation.
**Warning signs:** Negative fitness in plots when the metric has a non-negative valid range.

### Pitfall 4: Running Experiment Safety

**What goes wrong:** The heilbron/asymmetric-iterations experiment is currently running (8 runs, PID-tracked). Changing the wrong code could crash running processes.
**Why it happens:** Hot-patching code that's imported by running processes.
**How to avoid:** The fixes in this phase target `composition_injection.py` (never imported by running processes -- confirmed never wired), `gradient_prompt.py` (imported by running G processes -- be careful), `run_watchdog.py` (running process), and plot utilities.
**Warning signs:** Any of the 8 run PIDs dying after a code change.

## Code Examples

### Current CompositionInjectionHook (Buggy)

```python
# Source: gigaevo/adversarial/composition_injection.py:36-61
async def inject(self) -> str | None:
    top = await self._d_provider.get_top_k(1, higher_is_better=True)
    if not top:
        return None
    d_best = top[0]
    # BUG: injects D's raw code (entrypoint() -> callable)
    # into G's population (expects entrypoint() -> (11,2) array)
    program = Program(
        code=d_best.code,  # <-- wrong: this is D's code
        metadata={"mutation_type": "d_improvement", ...},
    )
    await self._g_storage.add(program)
```

### What the Fix Should Produce

The injected program needs to:
1. Call D's `improve()` on a specific G program's point configuration
2. Return an `(11,2) ndarray` from `entrypoint()`
3. Be a complete, standalone Python program

Conceptual fix pattern:
```python
# Template for injected G-style program
WRAPPER_TEMPLATE = '''
import numpy as np

# G's original point configuration
_G_POINTS = {g_points_repr}

# D's improvement function (from D program {d_id})
{d_code}

def entrypoint():
    """Wraps D's improvement of G's specific points as a valid G program."""
    improve = entrypoint.__wrapped_entrypoint__()
    improved = improve(np.array(_G_POINTS))
    return improved

# Store D's original entrypoint
entrypoint.__wrapped_entrypoint__ = {d_entrypoint_ref}
'''
```

### Watchdog Plot Fix

```python
# Current (buggy): no --metric flag
subprocess.run(
    ["gigaevo"] + run_args + [
        "plot", "comparison",
        "--annotate-frontier", "--no-frontier",
        "-o", str(plot_dir),
    ], ...
)

# Fixed: use actual_fitness metric from experiment.yaml
subprocess.run(
    ["gigaevo"] + run_args + [
        "plot", "comparison",
        "--metric", METRIC_NAME,  # "actual_fitness"
        "--annotate-frontier", "--no-frontier",
        "-o", str(plot_dir),
    ], ...
)
```

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 + pytest-asyncio |
| Config file | pyproject.toml |
| Quick run command | `/run-tests tests/adversarial_pipeline/` |
| Full suite command | `/run-tests` |

### Bug -> Test Map
| Bug | Behavior | Test Type | Test File | File Exists? |
|-----|----------|-----------|-----------|-------------|
| Bug 1 | Injected code is a valid G-style entrypoint returning (11,2) array | unit | `tests/adversarial_pipeline/test_composition_injection.py` | YES (needs update) |
| Bug 1 | Hook is wired and called during engine lifecycle | integration | `tests/adversarial_pipeline/test_composition_injection.py` | NO (Wave 0) |
| Bug 2 | GradientInPromptStage selects appropriate D program | unit | `tests/adversarial_pipeline/test_gradient_prompt.py` | YES (needs update) |
| Bug 3 | Watchdog plot uses correct metric from experiment.yaml | unit | `tests/monitoring/test_watchdog_plot.py` | NO (Wave 0) |
| Bug 3 | Sentinel values filtered from plot data | unit | `tests/monitoring/test_sentinel_filter.py` | NO (Wave 0) |

### Wave 0 Gaps
- [ ] Tests for CompositionInjectionHook wrapper code generation
- [ ] Tests for engine-level hook wiring
- [ ] Tests for sentinel value filtering in plot data
- [ ] Tests for watchdog metric parameter passing

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | D's `improve()` function signature is always `improve(points: np.ndarray) -> np.ndarray` based on seed.py and task_description.txt | Bug 1 Analysis | Wrapper template would fail if D programs use a different function interface |
| A2 | The globally best D (by fitness) is an acceptable proxy for "best D for this specific G program" in Bug 2 | Bug 2 Analysis | Mutation prompt may show irrelevant D strategy if D fitness does not correlate with improvement of the specific G being mutated |
| A3 | Changing `gradient_prompt.py` while the experiment is running could affect G runs | Pitfall 4 | If G processes import this module at startup and cache it, runtime changes would not take effect (safe); if they re-import per generation (unsafe) |

## Open Questions (RESOLVED)

1. RESOLVED: Use template-based code composition with subprocess execution at injection time. **Should CompositionInjectionHook run D's improve() at injection time?**
   - What we know: D's code needs to be executed against a specific G program's output to produce a valid (11,2) array for injection
   - What's unclear: Should the hook execute D's improve() in a subprocess (like FetchOpponentResultsStage does) or embed the code as a static wrapper?
   - Recommendation: Execute D's improve() at injection time, capture the resulting array, and inject a static `entrypoint()` that returns that array. This avoids the complexity of a runtime wrapper and ensures the injected code is deterministic.

2. RESOLVED: Add `post_step_hook` to `EvolutionEngine.step()` -- called after Phase 7 (archive reindex) and before generation counter increment. **Where should CompositionInjectionHook be called in the engine lifecycle?**
   - What we know: Engine has `pre_step_hook` only, no `post_step_hook`. The hook is designed to run after D's archive updates.
   - What's unclear: Best integration point
   - Recommendation: Add a `post_step_hook` to `EvolutionEngine.step()` (simple 3-line change) or call injection from within the sync hook after it unblocks.

3. RESOLVED: Bug 2 is deferred -- global best D is accepted as a sufficient heuristic for this phase. Per-program D matching requires new Redis infrastructure and is out of scope. **Should Bug 2 (GradientInPromptStage) be fixed at all in this phase?**
   - What we know: The current behavior (global best D) is a reasonable heuristic. Full per-program matching requires new Redis infrastructure.
   - What's unclear: Whether the user considers this a "bug" or a "future enhancement"
   - Recommendation: Document the limitation and defer per-program matching. The global best D is the most effective D overall, which is useful signal for G.

4. RESOLVED: `run_watchdog.py` is the active watchdog (confirmed via experiment.yaml `watchdog_pid: 4052592` and watchdog.log). Fix targets run_watchdog.py; watchdog must be restarted manually after the fix. **Is the `run_watchdog.py` the active watchdog or the CLI watchdog?**
   - What we know: experiment.yaml shows `watchdog_pid: 4052592`, watchdog.log shows `run_watchdog.py` output, the watchdog was stopped via SIGTERM at 18:32 UTC
   - What's unclear: Whether the watchdog needs to be restarted after the fix
   - Recommendation: Fix run_watchdog.py, restart watchdog manually after fix

## Sources

### Primary (HIGH confidence)
- `gigaevo/adversarial/composition_injection.py` -- CompositionInjectionHook implementation
- `gigaevo/adversarial/gradient_prompt.py` -- GradientInPromptStage implementation
- `gigaevo/adversarial/opponent_provider.py` -- OpponentArchiveProvider interface and RedisOpponentArchiveProvider
- `gigaevo/adversarial/asymmetric_pipeline.py` -- Pipeline wiring for asymmetric arms
- `gigaevo/adversarial/source_injection.py` -- SourceCodeInjectionStage (working, for reference)
- `gigaevo/monitoring/plugins/heilbron.py` -- HeilbronPlugin plot generation
- `gigaevo/monitoring/watchdog_engine.py` -- WatchdogEngine loop
- `gigaevo/evolution/engine/core.py` -- EvolutionEngine hook interface
- `problems/heilbron_adversarial/pop_a/evaluate.py` -- G's evaluation function
- `problems/heilbron_adversarial/pop_b/evaluate.py` -- D's evaluation function
- `problems/heilbron_adversarial/pop_a/task_description.txt` -- G output format spec
- `problems/heilbron_adversarial/pop_b/task_description.txt` -- D output format spec
- `experiments/heilbron/asymmetric-iterations/experiment.yaml` -- Experiment config
- `experiments/heilbron/asymmetric-iterations/run_watchdog.py` -- Active watchdog script
- `experiments/heilbron/asymmetric-iterations/01_design.md` -- Experiment design
- `experiments/heilbron/asymmetric-iterations/plots/comparison_hour_002.png` -- Visual confirmation of negative values
- `config/pipeline/adversarial_asymmetric.yaml` -- Hydra pipeline config
- `tests/adversarial_pipeline/test_composition_injection.py` -- Existing tests
- `tests/adversarial_pipeline/test_gradient_prompt.py` -- Existing tests
- `tests/monitoring/plugins/test_adversarial.py` -- Watchdog plugin tests
- `tests/monitoring/plugins/test_heilbron.py` -- Heilbron plugin tests

## Metadata

**Confidence breakdown:**
- Bug 1 analysis: HIGH -- source code read directly, type mismatch confirmed, wiring absence confirmed via full codebase grep
- Bug 2 analysis: HIGH -- source code read directly, OpponentArchiveProvider interface documented, Redis schema confirmed
- Bug 3 analysis: HIGH -- actual plot images viewed, sentinel values confirmed in evaluate.py, metric defaults confirmed in CLI code
- Fix approach: MEDIUM -- multiple valid approaches for Bug 1 (execute-at-injection vs wrapper template); need user input for Bug 2 scope

**Research date:** 2026-04-12
**Valid until:** 2026-04-26 (30 days -- stable codebase, no API churn expected)
