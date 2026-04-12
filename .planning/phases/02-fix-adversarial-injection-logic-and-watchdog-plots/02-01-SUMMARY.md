---
phase: 02-fix-adversarial-injection-logic-and-watchdog-plots
plan: 01
subsystem: plotting/watchdog
tags: [sentinel-filtering, watchdog, arms-race-plot, adversarial]
dependency_graph:
  requires: []
  provides:
    - sentinel_value parameter in prepare_iteration_dataframe
    - sentinel_value pass-through in _fetch_run_data
    - arms-race watchdog plots for heilbron experiments
  affects:
    - tools/utils.py (prepare_iteration_dataframe signature)
    - gigaevo/cli/plot_group.py (_fetch_run_data signature, 3 call sites)
    - experiments/heilbron/asymmetric-iterations/run_watchdog.py (generate_plot)
tech_stack:
  added: []
  patterns:
    - sentinel value filtering before outlier removal in data pipeline
key_files:
  created:
    - tests/test_tools/test_prepare_iteration_sentinel.py
  modified:
    - tools/utils.py
    - gigaevo/cli/plot_group.py
    - experiments/heilbron/asymmetric-iterations/run_watchdog.py
decisions:
  - sentinel_value=-1.0 passed unconditionally to all plot commands (safe no-op when no values match)
  - sentinel filtering uses exact equality (==) not range-based comparison
metrics:
  duration: 7m 20s
  completed: 2026-04-12T19:39:35Z
  tasks_completed: 3
  tasks_total: 3
  tests_added: 8
  files_modified: 4
---

# Phase 02 Plan 01: Fix Watchdog Plots Sentinel Filtering Summary

Sentinel value filtering in prepare_iteration_dataframe removes fitness=-1.0 invalid program markers before rolling mean/std computation, and watchdog switched from comparison to arms-race plot with actual_fitness metric.

## What Was Done

### Task 1: Add sentinel value filtering to prepare_iteration_dataframe
- Added `sentinel_value: float | None = None` parameter to `prepare_iteration_dataframe`
- Implemented "Step 0" sentinel removal before extreme value cutoff and outlier removal
- Logs count/percentage of removed sentinel points via loguru
- Returns empty DataFrame if all data points are sentinels
- **Commit:** `cfdd1e20`

### Task 2: Fix run_watchdog.py to use correct metric and arms-race plot
- Replaced `gigaevo plot comparison` with `gigaevo plot arms-race`
- Added `--metric actual_fitness` matching experiment.yaml `metric_name`
- Added `--paired G_label:D_label` built dynamically from RUNS pop_a/pop_b prefixes
- Removed `--annotate-frontier` and `--no-frontier` flags
- Updated expected output filename to `arms_race.png`
- **Commit:** `fb4ea126`

### Task 3: Wire sentinel_value through _fetch_run_data in plot_group.py
- Added `sentinel_value: float | None = None` to `_fetch_run_data` signature
- Passes `sentinel_value` through to `prepare_iteration_dataframe`
- All three callers (comparison, trajectory, arms_race) pass `sentinel_value=-1.0`
- Added 2 integration tests with mocked Redis verifying pass-through
- **Commit:** `e1938030`

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

| Check | Result |
|-------|--------|
| 8 sentinel filtering tests | PASS |
| ruff lint (all 3 files) | PASS |
| sentinel_value in tools/utils.py (>=3) | 5 occurrences |
| sentinel_value in plot_group.py (>=4) | 6 occurrences |
| actual_fitness in watchdog | Present |
| arms-race in watchdog | Present |

## Commits

| Task | Commit | Message |
|------|--------|---------|
| 1 | `cfdd1e20` | feat(02-01): add sentinel value filtering to prepare_iteration_dataframe |
| 2 | `fb4ea126` | fix(02-01): switch watchdog to arms-race plot with actual_fitness metric |
| 3 | `e1938030` | feat(02-01): wire sentinel_value through _fetch_run_data in plot_group.py |
