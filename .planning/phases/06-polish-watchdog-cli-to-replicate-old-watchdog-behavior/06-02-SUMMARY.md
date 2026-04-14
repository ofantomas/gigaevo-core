---
phase: 06-polish-watchdog-cli-to-replicate-old-watchdog-behavior
plan: 02
subsystem: monitoring
tags: [watchdog, plugins, telegram, plots, subprocess, retry]
dependency_graph:
  requires: [06-01]
  provides: [plugin-plot-delegation, plugin-telegram-formatting, engine-retry, engine-telegram-wiring]
  affects: [gigaevo/monitoring/watchdog_engine.py, tests/monitoring/test_watchdog_engine.py]
tech_stack:
  added: []
  patterns: [retry-loop, plugin-format-dispatch]
key_files:
  created: []
  modified:
    - gigaevo/monitoring/watchdog_engine.py
    - tests/monitoring/test_watchdog_engine.py
decisions:
  - "Option B chosen for Telegram wiring: engine populates telegram_body on StatusUpdate before dispatch, TelegramChannel reads it"
  - "Baseline passed via WatchdogEngine constructor parameter, not manifest lookup"
metrics:
  duration_minutes: 11
  completed: "2026-04-14T04:18:00Z"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 2
  tests_added: 8
  tests_total: 186
---

# Phase 06 Plan 02: Plugin Plot Delegation + Telegram Formatting Summary

Configurable plot retry loop in WatchdogEngine and format_telegram_body wiring from plugins through engine to TelegramChannel

## One-liner

Engine retry loop for CLI-delegated plot generation plus plugin-specific Telegram body wiring through StatusUpdate

## What Was Done

### Task 1: Plot retry logic in WatchdogEngine

The engine's single try/except around `plugin.generate_plots()` was replaced with a configurable retry loop using `config.plot_retries` (default 3) and `config.plot_retry_delay_s` (default 30s). Each failed attempt is logged with attempt number. The `finally` clause ensures matplotlib figures are cleaned up on each attempt. If all retries are exhausted, the cycle continues with an empty plots list.

All three plugins (adversarial, solo, prompt_coevo) already had subprocess-based `generate_plots()` implementations delegating to `gigaevo plot` CLI commands -- no changes needed to the plugins themselves. Similarly, all plugin tests were already comprehensive.

The existing `test_cycle_survives_plot_generation_error` test was updated to use `plot_retry_delay_s=0` to avoid 30-second timeouts in the test suite.

### Task 2: format_telegram_body wiring in WatchdogEngine

Added step 6b in the engine's `_cycle()` method: after format_status_body, the engine calls `plugin.format_telegram_body()` and passes the result as `telegram_body` on the `StatusUpdate` dataclass. TelegramChannel already checks this field and uses it instead of the generic HTML table when present.

Added `baseline` parameter to `WatchdogEngine.__init__()` and `_get_baseline()` helper method so SOTA comparison values can flow from experiment config through to Telegram formatting.

All three plugins already had `format_telegram_body()` implementations, `StatusUpdate` already had the `telegram_body` field, and `TelegramChannel.send_status()` already had the conditional check -- no changes needed to those files.

## Pre-existing State

The vast majority of the plan's deliverables were already implemented by prior phases:

| Component | Expected State | Actual State |
|-----------|---------------|--------------|
| AdversarialPlugin.generate_plots() subprocess delegation | Needs rewrite | Already implemented |
| SoloPlugin.generate_plots() subprocess delegation | Needs rewrite | Already implemented |
| PromptCoevoPlugin.generate_plots() subprocess delegation | Needs rewrite | Already implemented |
| All plugins: format_telegram_body() | Needs implementation | Already implemented |
| StatusUpdate.telegram_body field | Needs addition | Already present |
| TelegramChannel telegram_body check | Needs addition | Already present |
| All plugin tests | Needs creation | Already existed (72 tests) |
| Telegram channel tests for telegram_body | Needs creation | Already existed (3 tests) |
| Engine plot retry loop | Missing | **Added** |
| Engine format_telegram_body wiring | Missing | **Added** |

## Commits

| Task | Commit | Message |
|------|--------|---------|
| 1 | ac8088e2 | feat(06-02): add plot retry logic to WatchdogEngine |
| 2 | d0c1e5e4 | feat(06-02): wire format_telegram_body into WatchdogEngine cycle |

## Deviations from Plan

None - plan executed exactly as written (only the engine changes were needed since plugins were already complete).

## Verification

```
186 passed in 29.82s
```

All 186 tests across plugins (72), telegram channel (28), notifications (46), and engine (40) pass.

## Acceptance Criteria

- [x] adversarial.py contains `subprocess.run` (CLI delegation)
- [x] adversarial.py contains `"plot"` and `"arms-race"` in subprocess command
- [x] adversarial.py contains `"plot"` and `"comparison"` in subprocess command
- [x] solo.py contains `subprocess.run` (CLI delegation)
- [x] prompt_coevo.py contains `subprocess.run` (CLI delegation)
- [x] watchdog_engine.py contains `for attempt in range(self.config.plot_retries):`
- [x] watchdog_engine.py contains `time.sleep(self.config.plot_retry_delay_s)`
- [x] None of the three plugin files contain `ax.bar(` (bar charts removed)
- [x] adversarial.py contains `def format_telegram_body(` with G/D grouping and SOTA
- [x] solo.py contains `def format_telegram_body(`
- [x] prompt_coevo.py contains `def format_telegram_body(`
- [x] notifications.py StatusUpdate has `telegram_body: str | None = None`
- [x] telegram_channel.py send_status checks `update.telegram_body`
- [x] Engine calls plugin.format_telegram_body() and populates StatusUpdate
- [x] All tests pass

## Self-Check: PASSED

- FOUND: gigaevo/monitoring/watchdog_engine.py
- FOUND: tests/monitoring/test_watchdog_engine.py
- FOUND: 06-02-SUMMARY.md
- FOUND: commit ac8088e2
- FOUND: commit d0c1e5e4
