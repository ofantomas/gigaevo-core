# Phase 02: Validation Architecture

## Wave 0 Test Gap Coverage

| Test Gap (from RESEARCH.md) | Covered By | Status |
|---|---|---|
| CompositionInjectionHook wrapper code generation | Plan 02-02 Task 1 (TDD, 8 behavior tests) | Covered |
| Engine-level hook wiring | Plan 02-02 Task 2 (TDD, 5 behavior tests) | Covered |
| Sentinel value filtering in plot data | Plan 02-01 Task 1 (TDD, 6 behavior tests) | Covered |
| Sentinel value wiring through _fetch_run_data | Plan 02-01 Task 3 (TDD, 2 behavior tests) | Covered |
| Watchdog metric parameter passing | -- | Deferred |

## Deferred: Watchdog Metric Parameter Test

`tests/monitoring/test_watchdog_metric.py` (verifying the CLI passes `--metric actual_fitness`) is deferred. Rationale:

1. `run_watchdog.py` is a per-experiment script, not a reusable module. Testing it requires subprocess mocking of `gigaevo plot arms-race` which adds complexity for low ROI.
2. The verification for correct metric usage is handled by acceptance criteria in Plan 02-01 Task 2: `grep "actual_fitness" run_watchdog.py` confirms the metric is passed.
3. The arms-race plot command itself is already tested via the existing `tests/monitoring/plugins/test_heilbron.py` test suite.

If watchdog metric parameter testing becomes important (e.g., if run_watchdog.py becomes a reusable template), create `tests/monitoring/test_watchdog_metric.py` in a future phase.
