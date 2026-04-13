# Phase 05 Plan 02: Plugin Resolution Rewrite and Subprocess Elimination Summary

Plugin resolution simplified to explicit manifest field + solo fallback. All subprocess calls to tools/comparison.py replaced with inline matplotlib. HeilbronPlugin deleted and absorbed into AdversarialPlugin with configurable multi-metric panels.

## Tasks Completed

| Task | Description | Commit | Key Files |
|------|-------------|--------|-----------|
| 1 | Tests for resolve_plugin and WatchdogPluginOptions | fded0ed4 | tests/monitoring/test_watchdog_plugin.py |
| 2 | Delete heilbron, rewrite solo/prompt_coevo with inline matplotlib | 765dec20 | gigaevo/monitoring/plugins/ (6 files), tests/monitoring/plugins/ (4 files) |

## Changes Made

### Task 1: Tests for resolve_plugin and WatchdogPluginOptions
- Rewrote TestResolvePlugin: removed obsolete _TASK_HEURISTIC tests (heilbron heuristic, hover heuristic)
- Added tests for: explicit plugin, fallback to solo (no heuristic), unknown plugin KeyError, no-solo-registered KeyError
- Added TestWatchdogPluginOptions: round-trip, validate_plot_metrics with known/unknown metrics, empty metrics passthrough

### Task 2: Delete heilbron, rewrite solo/prompt_coevo
- Deleted gigaevo/monitoring/plugins/heilbron.py entirely
- Removed heilbron import from gigaevo/monitoring/plugins/__init__.py
- Rewrote gigaevo/monitoring/plugins/solo.py: inline matplotlib bar charts replacing subprocess calls to tools/comparison.py
- Rewrote gigaevo/monitoring/plugins/prompt_coevo.py: inline matplotlib per-group bar charts replacing subprocess calls
- Rewrote tests/monitoring/plugins/test_adversarial.py: verify no subprocess, test multi-metric panels, telegram content
- Rewrote tests/monitoring/plugins/test_heilbron.py: verify heilbron removed from registry and module not importable
- Rewrote tests/monitoring/plugins/test_solo.py: verify inline matplotlib output, no subprocess mocks
- Rewrote tests/monitoring/plugins/test_prompt_coevo.py: verify inline matplotlib per-group, no subprocess mocks

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fix test_watchdog_integration.py heilbron assertion**
- **Found during:** Task 2
- **Issue:** tests/monitoring/test_watchdog_integration.py::TestPluginRegistryCompleteness::test_all_plugins_registered asserted "heilbron" in registry, which fails after deletion
- **Fix:** Removed the `assert "heilbron" in registry` line
- **Files modified:** tests/monitoring/test_watchdog_integration.py
- **Commit:** 765dec20

## Verification

- All 376 tests in tests/monitoring/ pass
- No subprocess imports in any plugin file
- No tools/ references in any plugin file
- No _PROJ in any plugin file
- "heilbron" not in plugin registry
- "adversarial" in plugin registry
- heilbron.py deleted from disk

## Metrics

- **Duration:** ~12 minutes
- **Tests:** 376 passed, 0 failed
- **Files created:** 0
- **Files modified:** 8
- **Files deleted:** 1 (heilbron.py)
