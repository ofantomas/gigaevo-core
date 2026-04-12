---
phase: 02-fix-adversarial-injection-logic-and-watchdog-plots
plan: 03
subsystem: adversarial-dg-tracker
tags: [adversarial, dg-tracker, gradient-prompt, per-program-selection, redis-sorted-sets]
dependency_graph:
  requires: [post_step_hook, composition_injection_hook]
  provides: [dg_tracker, per_program_d_selection]
  affects: [gigaevo/adversarial/gradient_prompt.py, gigaevo/adversarial/composition_injection.py, config/pipeline/adversarial_asymmetric.yaml]
tech_stack:
  added: []
  patterns: [Redis sorted sets for D-G improvement tracking, per-program opponent selection with global fallback]
key_files:
  created:
    - gigaevo/adversarial/dg_tracker.py
    - tests/adversarial_pipeline/test_dg_tracker.py
  modified:
    - gigaevo/adversarial/gradient_prompt.py
    - gigaevo/adversarial/composition_injection.py
    - config/pipeline/adversarial_asymmetric.yaml
    - tests/adversarial_pipeline/test_gradient_prompt.py
    - tests/adversarial_pipeline/test_composition_injection.py
decisions:
  - "L2 norm of point difference as improvement delta proxy (not actual fitness delta, which requires full G evaluation)"
  - "ZADD GT semantics for sorted sets -- only highest delta per (D, G) pair is retained"
  - "24-hour TTL on improvement records to prevent unbounded Redis growth"
metrics:
  duration: 402s
  completed: 2026-04-12T19:53:31Z
  tasks_completed: 3
  tasks_total: 3
  tests_added: 20
  files_modified: 7
---

# Phase 02 Plan 03: D-G Improvement Tracking and Per-Program D Selection Summary

DGImprovementTracker stores per-(D,G) improvement deltas in Redis sorted sets, CompositionInjectionHook records pairs after successful injection, and GradientInPromptStage selects the D that most improved the specific G being mutated (with global fallback).

## What Changed

### Task 1: Create DGImprovementTracker with Redis storage (49015932)

Created `gigaevo/adversarial/dg_tracker.py` with:
- `DGImprovementTracker` class using Redis sorted sets (`{prefix}:dg_improvements:{g_id}`)
- `record_improvement(d_id, g_id, delta)` -- stores only positive deltas with ZADD GT
- `get_best_d_for_g(g_id)` -- returns `(d_id, delta)` tuple for the highest-scoring D
- `record_batch(pairs)` -- efficient multi-pair recording via Redis pipeline
- `get_top_d_for_g(g_id, k)` -- top-k D programs for a G
- TTL-based expiry (default 24h) to prevent unbounded growth
- 8 tests with fakeredis covering storage, retrieval, filtering, batch, and ZADD GT semantics

### Task 2: Per-G-program D selection in GradientInPromptStage (d927b852)

Updated `gigaevo/adversarial/gradient_prompt.py`:
- Added optional `dg_tracker: DGImprovementTracker | None = None` parameter
- New `_select_best_d(program)` method with priority: per-program D from tracker > global best D
- Fetches full D code via `get_programs_by_ids([d_id])` after tracker returns d_id
- Falls back to global `get_top_k(1)` when: tracker is None, no data for G, or D evicted from archive
- Backward compatible: `dg_tracker=None` uses identical global best behavior
- 8 new tests (14 total) covering per-program selection, fallback paths, and edge cases

### Task 3: Wire recording into CompositionInjectionHook and Hydra config (efac778c)

Updated `gigaevo/adversarial/composition_injection.py`:
- Computes `improvement_delta = float(np.linalg.norm(composed_points - g_points))` as continuous proxy
- Calls `dg_tracker.record_improvement(d_id, g_id, delta)` after successful injection
- Recording exception caught and logged (injection still succeeds) per threat T-02-09
- Type annotation updated from `Any | None` to `DGImprovementTracker | None` via TYPE_CHECKING

Updated `config/pipeline/adversarial_asymmetric.yaml`:
- Added `dg_tracker` config block targeting `gigaevo.adversarial.dg_tracker.DGImprovementTracker`
- Wired `dg_tracker: ${dg_tracker}` into `composition_injection_hook`
- Uses G's Redis DB and prefix (G-centric data)

4 new tests (15 total) covering: recording on success, None tracker, no recording on failure, exception resilience.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed record_improvement signature mismatch**
- **Found during:** Task 3
- **Issue:** Plan 02-02 had `inject()` calling `dg_tracker.record_improvement(d_id=..., g_id=..., injected_id=...)` which doesn't match the DGImprovementTracker API that expects `delta` not `injected_id`.
- **Fix:** Replaced `injected_id` with `delta=improvement_delta` where delta is computed as L2 norm of point difference.
- **Files modified:** `gigaevo/adversarial/composition_injection.py`
- **Commit:** efac778c

## Decisions Made

1. **L2 norm as improvement delta**: Used `np.linalg.norm(composed_points - g_points)` as a continuous proxy for improvement magnitude. The actual fitness delta would require running G's full evaluator (expensive). L2 distance reflects how much D changed G's configuration, which is sufficient for ranking which D most affects which G.

2. **ZADD GT semantics**: Redis sorted sets use GT flag so that if the same D improves the same G multiple times, only the highest delta is retained. This prevents score regression from noisy evaluations.

3. **24-hour TTL**: Improvement records expire after 24 hours to prevent unbounded growth as programs cycle out of the archive. This is sufficient for the typical experiment duration where recent improvements are most relevant.

## Self-Check: PASSED

- [x] gigaevo/adversarial/dg_tracker.py exists with DGImprovementTracker, record_improvement, get_best_d_for_g, record_batch, zadd, zrevrange
- [x] tests/adversarial_pipeline/test_dg_tracker.py exists with 8 test functions
- [x] gigaevo/adversarial/gradient_prompt.py contains dg_tracker parameter, _select_best_d, get_best_d_for_g, get_programs_by_ids, fallback to get_top_k
- [x] tests/adversarial_pipeline/test_gradient_prompt.py has 14 test functions (6 existing + 8 new)
- [x] gigaevo/adversarial/composition_injection.py contains record_improvement, DGImprovementTracker in TYPE_CHECKING
- [x] config/pipeline/adversarial_asymmetric.yaml contains dg_tracker block with DGImprovementTracker target and dg_tracker: ${dg_tracker} in composition_injection_hook
- [x] tests/adversarial_pipeline/test_composition_injection.py has 15 test functions (11 existing + 4 new)
- [x] All 37 tests pass across all three test files
- [x] All lint checks pass
- [x] Commit 49015932 exists
- [x] Commit d927b852 exists
- [x] Commit efac778c exists
