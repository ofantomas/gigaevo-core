---
phase: 03-fix-cli-metrics-reporting-and-manifest-wiring-for-adversaria
plan: 01
subsystem: cli, monitoring
tags: [bugfix, metrics, manifest, watchdog]
dependency_graph:
  requires: []
  provides:
    - metric-aware watchdog RunConfig construction
    - multi-metric trajectory display
    - manifest-aware top default metric
    - watchdog_plugin field on both manifest schemas
  affects:
    - gigaevo/cli/watchdog_cmd.py
    - gigaevo/cli/trajectory.py
    - gigaevo/cli/top.py
    - gigaevo/monitoring/manifest_schema.py
    - tools/experiment/manifest.py
tech_stack:
  added: []
  patterns:
    - RunConfig metric_names propagation from metrics.yaml
    - Click multiple=True for repeatable options
    - Lazy manifest import for manifest-aware defaults
key_files:
  created: []
  modified:
    - gigaevo/cli/watchdog_cmd.py
    - gigaevo/cli/trajectory.py
    - gigaevo/cli/top.py
    - gigaevo/monitoring/manifest_schema.py
    - tools/experiment/manifest.py
    - tests/cli/test_watchdog_cmd.py
    - tests/cli/test_trajectory_cmd.py
    - tests/cli/test_top_cmd.py
    - tests/monitoring/test_manifest_schema.py
decisions:
  - Patch _load_metric_names at source (run_resolver) rather than watchdog_cmd module for test mock targeting
  - Patch load_manifest at tools.experiment.manifest source for lazy imports in top.py
metrics:
  duration: 4m 39s
  completed: 2026-04-13T12:57:00Z
  tasks_completed: 2
  tasks_total: 2
  tests_added: 7
  tests_total: 66
requirements:
  - MON-05
  - CLI-03
  - MAN-02
  - MON-03
---

# Phase 03 Plan 01: Fix Metric Discovery Propagation and Manifest Watchdog Plugin Summary

Fix metric discovery propagation in watchdog_cmd, trajectory, and top commands; add watchdog_plugin field to both manifest schemas. watchdog_cmd now loads per-run metric_names from metrics.yaml via _load_metric_names, trajectory accepts repeatable --metric flags with auto-discovery from RunConfig, top uses manifest problem.metric_name as default ranking metric.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | c9c84bb6 | Fix watchdog_cmd metric_names propagation, add watchdog_plugin to manifest schemas |
| 2 | 14529a13 | Add multi-metric trajectory support, manifest-aware top default metric |

## Task Details

### Task 1: Fix watchdog_cmd metric_names propagation and add manifest watchdog_plugin field

**Changes:**
- `gigaevo/cli/watchdog_cmd.py`: Added import of `_load_metric_names` from `run_resolver`; updated RunConfig construction loop to call `_load_metric_names(run.problem_name)` and pass `metric_names` to each RunConfig
- `gigaevo/monitoring/manifest_schema.py`: Added `watchdog_plugin: str | None = None` field to Pydantic ExperimentManifest
- `tools/experiment/manifest.py`: Added `watchdog_plugin: str | None = None` field to legacy dataclass ExperimentManifest; updated `_validate()` to read `watchdog_plugin` from raw YAML dict

**Tests added:**
- `TestWatchdogMetricNamesPropagation.test_run_configs_contain_metric_names_from_metrics_yaml` -- verifies RunConfigs get metric_names from metrics.yaml
- `TestWatchdogPluginField.test_watchdog_plugin_accepted_in_yaml` -- Pydantic accepts watchdog_plugin value
- `TestWatchdogPluginField.test_watchdog_plugin_defaults_to_none` -- defaults to None when absent
- `TestWatchdogPluginField.test_watchdog_plugin_in_json_schema` -- JSON Schema export includes field
- `TestWatchdogPluginField.test_watchdog_plugin_roundtrip` -- survives to_dict/from_dict roundtrip

### Task 2: Fix trajectory multi-metric support and top default metric from manifest

**Changes:**
- `gigaevo/cli/trajectory.py`: Changed `--metric` option to `multiple=True`; added auto-discovery logic that collects unique metric names from RunConfig.metric_names; updated data-fetching loop to iterate over metrics_to_show; added "Metric" column when showing multiple metrics
- `gigaevo/cli/top.py`: Added manifest-aware default metric resolution -- when `metric == "fitness"` and `--experiment` is used, loads manifest and checks `problem.metric_name`; lazy import of `load_manifest` keeps CLI startup fast

**Tests added:**
- `TestTrajectoryMultiMetric.test_multiple_metric_flags_show_both` -- two --metric flags show both metrics with Metric column
- `TestTrajectoryMultiMetric.test_auto_discovery_uses_run_config_metric_names` -- auto-discovers metrics from RunConfig when no --metric specified
- `TestTopManifestDefaultMetric.test_experiment_mode_uses_manifest_metric_name` -- manifest metric_name used as default
- `TestTopManifestDefaultMetric.test_explicit_metric_overrides_manifest` -- explicit --metric overrides manifest

## Deviations from Plan

None -- plan executed exactly as written.

## Known Stubs

None -- all data paths are fully wired.

## Self-Check: PASSED

- All 9 modified/created files verified on disk
- Commits c9c84bb6 and 14529a13 verified in git log
- All acceptance criteria patterns confirmed in source files
- 66 tests pass across all 4 test files
