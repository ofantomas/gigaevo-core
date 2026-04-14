---
phase: 06-polish-watchdog-cli-to-replicate-old-watchdog-behavior
plan: 01
subsystem: monitoring
tags: [manifest, watchdog, alerts, cli, redis]
dependency_graph:
  requires: []
  provides:
    - WatchdogSection manifest schema with PlotCommand, AlertThresholds
    - format_telegram_body ABC method on WatchdogPlugin
    - ModelDriftRule anomaly detector
    - Redis checkpoint and completion markers in WatchdogEngine
    - NO_PROXY auto-configuration in watchdog CLI
  affects:
    - gigaevo/monitoring/manifest_schema.py
    - gigaevo/monitoring/watchdog_plugin.py
    - gigaevo/monitoring/watchdog_config.py
    - gigaevo/monitoring/alerts.py
    - gigaevo/monitoring/watchdog_engine.py
    - gigaevo/cli/watchdog_cmd.py
tech_stack:
  added: []
  patterns:
    - Pydantic model_validator for backward-compat field migration
    - Standalone anomaly rule class (not coupled to AlertDetector)
    - Redis checkpoint markers at configurable milestone percentages
key_files:
  created: []
  modified:
    - gigaevo/monitoring/manifest_schema.py
    - gigaevo/monitoring/watchdog_plugin.py
    - gigaevo/monitoring/watchdog_config.py
    - gigaevo/monitoring/alerts.py
    - gigaevo/monitoring/watchdog_engine.py
    - gigaevo/cli/watchdog_cmd.py
    - tests/monitoring/test_manifest_schema.py
    - tests/monitoring/test_watchdog_plugin.py
    - tests/monitoring/test_watchdog_config.py
    - tests/monitoring/test_alerts.py
    - tests/monitoring/test_watchdog_engine.py
    - tests/cli/test_watchdog_cmd.py
decisions:
  - "WatchdogSection as a new Pydantic model with backward-compat migration from legacy watchdog_plugin/watchdog_plugin_options fields"
  - "ModelDriftRule as standalone class, not integrated into AlertDetector (different invocation pattern -- needs URL/model params)"
  - "Redis checkpoints use exists() guard to avoid overwriting earlier milestone data"
  - "Completion detection in _cycle() triggers both Redis marker write and _shutdown flag"
metrics:
  duration_s: 532
  completed: "2026-04-14T03:51:42Z"
  tasks_completed: 2
  tasks_total: 2
  tests_added: 42
  files_modified: 12
---

# Phase 06 Plan 01: Foundational Interfaces and Lifecycle Features Summary

Watchdog manifest schema, plugin ABC extension, model drift rule, Redis lifecycle markers, and NO_PROXY auto-setup

## What Was Done

### Task 1: Extend manifest schema with WatchdogSection and update plugin ABC + config

Added three new Pydantic models to `manifest_schema.py`:
- `PlotCommand`: CLI plot command specification with command name, args, output_name, caption
- `AlertThresholds`: Configurable thresholds for invalidity_rate, stagnation_window, generation_gap_threshold
- `WatchdogSection`: Full watchdog configuration including plugin override, plot_commands, plot_metrics, alert_thresholds, poll_interval_s, plot_retries, checkpoint_milestones, no_proxy_hosts

Added `watchdog: WatchdogSection` field to `ExperimentManifest` with a `model_validator` that migrates legacy `watchdog_plugin` and `watchdog_plugin_options` fields for backward compatibility.

Added `format_telegram_body()` default method to `WatchdogPlugin` ABC -- returns None by default, plugins can override for custom Telegram formatting.

Added `plot_retries`, `plot_retry_delay_s`, `rolling_comment_threshold_hours`, and `checkpoint_milestones` fields to `WatchdogConfig` frozen dataclass.

**Commit:** 56a7445a

### Task 2: Implement model drift anomaly rule + Redis checkpoint/completion + NO_PROXY auto-setup

Added `MODEL_DRIFT = "model_drift"` to `AlertType` enum.

Added `ModelDriftRule` as a standalone class in `alerts.py` that probes LiteLLM `/models` endpoint via `urllib.request` to verify the expected model is still being served. Returns `None` if model found, or an `Alert` with `AlertType.MODEL_DRIFT` if not found or on connection error.

Added `_write_redis_checkpoint()` and `_write_completion()` methods to `WatchdogEngine`:
- Checkpoints are written at configurable milestone percentages (default: 10%, 20%, 50%, 100%) with `exists()` guard to prevent overwriting
- Completion marker written when any `COMPLETION` alert is detected, which also sets `_shutdown = True`

Updated `watchdog_cmd.py` to:
- Auto-configure `NO_PROXY` and `no_proxy` env vars from `manifest.servers` + `api.github.com` + `watchdog.no_proxy_hosts`
- Build `WatchdogConfig` from manifest watchdog section (CLI flags take precedence over manifest values)

**Commit:** b1a17868

## Deviations from Plan

None -- plan executed exactly as written.

## Test Results

153 tests across 6 test files, all passing:
- `test_manifest_schema.py`: 53 tests (27 new)
- `test_watchdog_plugin.py`: 18 tests (2 new)
- `test_watchdog_config.py`: 9 tests (4 new)
- `test_alerts.py`: 40 tests (5 new)
- `test_watchdog_engine.py`: 27 tests (8 new)
- `test_watchdog_cmd.py`: 6 tests (1 new)

## Commits

| Task | Hash | Message |
|------|------|---------|
| 1 | 56a7445a | feat(06-01): add WatchdogSection manifest schema, format_telegram_body ABC method, and config fields |
| 2 | b1a17868 | feat(06-01): add model drift rule, Redis checkpoint/completion markers, and NO_PROXY auto-setup |

## Self-Check: PASSED

All 6 source files found. Both commits verified. All 15 acceptance criteria met.
