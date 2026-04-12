---
phase: 02-fix-adversarial-injection-logic-and-watchdog-plots
plan: 02
subsystem: adversarial-injection
tags: [adversarial, composition-injection, engine-hooks, hydra-config]
dependency_graph:
  requires: []
  provides: [post_step_hook, composition_injection_hook, d_improvement_programs]
  affects: [gigaevo/evolution/engine/core.py, gigaevo/evolution/engine/steady_state.py, config/pipeline/adversarial_asymmetric.yaml]
tech_stack:
  added: []
  patterns: [post_step_hook lifecycle, code composition via template, delta gating]
key_files:
  created: []
  modified:
    - gigaevo/adversarial/composition_injection.py
    - gigaevo/evolution/engine/core.py
    - gigaevo/evolution/engine/steady_state.py
    - config/pipeline/adversarial_asymmetric.yaml
    - config/constants/evolution.yaml
    - config/evolution/default.yaml
    - config/evolution/steady_state.yaml
    - experiments/heilbron/asymmetric-iterations/launch.sh
    - tests/adversarial_pipeline/test_composition_injection.py
    - tests/evolution/test_evolution_engine_complex.py
decisions:
  - "Used g_storage.get_all() to read G programs instead of separate g_provider (simpler, avoids config complexity)"
  - "post_step_hook exceptions caught and logged (not propagated) unlike pre_step_hook — injection failure should not stop evolution"
  - "Composed code uses regex rename of D's entrypoint to _d_entrypoint to avoid name collision"
metrics:
  duration: 501s
  completed: 2026-04-12T19:42:05Z
  tasks_completed: 2
  tasks_total: 2
  tests_added: 17
  files_modified: 10
---

# Phase 02 Plan 02: Rewrite CompositionInjectionHook and Add post_step_hook Summary

Rewrote CompositionInjectionHook with D(G) code composition producing valid G programs, added post_step_hook to EvolutionEngine lifecycle, wired via Hydra config, and activated for Arm A G runs in launch.sh.

## What Changed

### Task 1: Rewrite CompositionInjectionHook (bde2eef3)

Completely rewrote `gigaevo/adversarial/composition_injection.py` to fix three bugs:
1. **Bug: D's raw code injected into G** -- Now `_compose_g_program` produces a standalone wrapper that renames D's `entrypoint` to `_d_entrypoint`, embeds G's point configuration as `_G_POINTS`, and defines a new `entrypoint()` that applies D's improve function to G's points.
2. **Bug: No validation of composed output** -- Now executes both G's original program and the composed program via `run_exec_runner` subprocess, only injects if composed output differs from original (delta gating).
3. **Bug: Never wired into engine** -- Added `__call__` method delegating to `inject()` for hook compatibility. Added optional `dg_tracker` parameter for Plan 02-03.

12 tests covering: composition code generation, delta gating, empty archive handling, metadata correctness, callable interface, tracker integration.

### Task 2: Add post_step_hook to EvolutionEngine (bf490e14)

- Added `post_step_hook: Callable[[], Awaitable[None]] | None` parameter to `EvolutionEngine.__init__`
- Hook called after Phase 7 (archive reindex), before generation counter increment
- Exceptions caught and logged (engine continues) -- more resilient than pre_step_hook since injection failure is non-fatal
- SteadyStateEvolutionEngine calls post_step_hook at epoch boundary (step 8a, after reindex)
- Hydra configs: `post_step_hook: null` default in constants, wired in both default and steady_state engine blocks
- `adversarial_asymmetric.yaml`: added `composition_injection_hook` config block pointing to `CompositionInjectionHook`
- `launch.sh`: Arm A G runs (A1_G, A2_G) pass `'post_step_hook=${composition_injection_hook}'` -- D runs and C runs unchanged

5 tests covering: hook called, None backward compat, exception resilience, ordering (pre before post), called even without refresh.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing functionality] Removed g_provider parameter**
- **Found during:** Task 1
- **Issue:** Plan specified separate `g_provider: OpponentArchiveProvider` parameter, but `opponent_provider` for G runs points to D's archive (the opponent). G's own programs are in `g_storage`.
- **Fix:** Used `g_storage.get_all()` to read G programs directly instead of a separate provider. Simpler config, no need for a self-provider.
- **Files modified:** `gigaevo/adversarial/composition_injection.py`, `config/pipeline/adversarial_asymmetric.yaml`

## Decisions Made

1. **g_storage.get_all() for G programs**: The plan initially suggested a separate `g_provider` parameter, but `opponent_provider` for G runs points to D's archive. Using `g_storage.get_all()` is simpler and avoids config complexity.

2. **post_step_hook exception isolation**: Unlike `pre_step_hook` (which propagates exceptions), `post_step_hook` catches and logs exceptions. Injection failure should not crash evolution.

3. **Regex rename for D's entrypoint**: Used `re.sub` to rename D's `entrypoint` to `_d_entrypoint` in composed code, avoiding name collision with the wrapper's `entrypoint`.

## Self-Check: PASSED

- [x] gigaevo/adversarial/composition_injection.py exists and contains `_compose_g_program`, `_d_entrypoint`, `dg_tracker`, `run_exec_runner`, `async def __call__`, `mutation_type.*d_improvement`
- [x] gigaevo/evolution/engine/core.py contains `post_step_hook: Callable` in __init__, `self._post_step_hook`, `await self._post_step_hook()`, `post_step_hook failed`
- [x] config/constants/evolution.yaml contains `post_step_hook: null`
- [x] config/evolution/default.yaml contains `post_step_hook: ${post_step_hook}`
- [x] config/evolution/steady_state.yaml contains `post_step_hook: ${post_step_hook}`
- [x] config/pipeline/adversarial_asymmetric.yaml contains `composition_injection_hook` and `CompositionInjectionHook`
- [x] experiments/heilbron/asymmetric-iterations/launch.sh contains `post_step_hook` in A1_G and A2_G blocks (4 occurrences)
- [x] launch.sh does NOT contain `post_step_hook` in D or C run blocks
- [x] tests/adversarial_pipeline/test_composition_injection.py: 12 tests pass
- [x] tests/evolution/test_evolution_engine_complex.py: 25 tests pass (5 new)
- [x] All lint checks pass
- [x] Commit bde2eef3 exists
- [x] Commit bf490e14 exists
