---
phase: 03-fix-cli-metrics-reporting-and-manifest-wiring-for-adversaria
plan: 02
subsystem: cli
tags: [cli, metrics, formatting, registry]
dependency_graph:
  requires: []
  provides: [metric-formatting, cli-analyze-collect]
  affects: [gigaevo/cli/status.py, gigaevo/cli/checkpoint.py, gigaevo/cli/__init__.py]
tech_stack:
  added: []
  patterns: [shared-formatting-helper, lazy-subcommand-registry]
key_files:
  created: []
  modified:
    - gigaevo/cli/status.py
    - gigaevo/cli/checkpoint.py
    - gigaevo/cli/__init__.py
    - tests/cli/test_status_cmd.py
    - tests/cli/test_checkpoint_cmd.py
    - tests/cli/test_cli_group.py
decisions:
  - "Format helper lives in status.py; checkpoint.py imports from it (single source of truth)"
  - "Registry entries alphabetized for consistency"
  - "analyze/collect CLI signatures NOT modified -- only registry wiring added"
metrics:
  duration: 217s
  completed: 2026-04-13T12:57:06Z
  tasks: 2/2
  tests_added: 14
  files_modified: 6
---

# Phase 03 Plan 02: Fix CLI Metrics Reporting and Registry Wiring Summary

Metric formatting from metrics.yaml specs (sentinel/percentage/decimals) for status and checkpoint commands, plus analyze/collect wired into the CLI lazy subcommand registry.

## Task Summary

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add metric formatting to status and checkpoint commands | 98d63746 | gigaevo/cli/status.py, gigaevo/cli/checkpoint.py, tests/cli/test_status_cmd.py, tests/cli/test_checkpoint_cmd.py |
| 2 | Wire analyze and collect into CLI lazy subcommand registry | 2dbe6176 | gigaevo/cli/__init__.py, tests/cli/test_cli_group.py |

## Changes Made

### Task 1: Metric Formatting

Added two functions to `gigaevo/cli/status.py`:

- `_load_metric_specs(experiment)` -- loads metrics.yaml specs from all unique problem_names in the experiment manifest. Returns empty dict in --run mode (graceful fallback).
- `_format_metric_value(value, name, specs)` -- formats a metric value per its spec: sentinel values display as "N/A", upper_bound=1.0 metrics display as percentages, decimal places respected, None displays as "?", default is 3 decimal places.

Updated `_snapshot_to_row` in both `status.py` and `checkpoint.py` to accept an optional `metric_specs` parameter and apply formatting. `checkpoint.py` imports both functions from `status.py` (single source of truth).

### Task 2: CLI Registry Wiring

Added `"analyze"` and `"collect"` entries to `_LAZY_SUBCOMMANDS` in `gigaevo/cli/__init__.py`. Alphabetized the entire registry for readability. The analyze and collect commands retain their existing `--prefix`/`--db` interface -- only discoverability via `gigaevo analyze` and `gigaevo collect` was added.

## Test Coverage

- 10 new tests in test_status_cmd.py: `_format_metric_value` (sentinel, percentage, raw, None, default decimals, non-percentage sentinel) and `_snapshot_to_row` (with specs, without specs, sentinel)
- 3 new tests in test_checkpoint_cmd.py: sentinel display, percentage display, format identity with status
- 4 new tests in test_cli_group.py: analyze/collect in command listing, analyze/collect resolve to Click commands
- All 35 tests across the three files pass

## Deviations from Plan

None -- plan executed exactly as written.

## Decisions Made

1. **Format helper in status.py, not a separate module**: The plan suggested placing the helper in status.py since it is the primary consumer. checkpoint.py imports from it. This avoids a new module for two small functions.
2. **Registry alphabetized**: While adding analyze and collect, the entire `_LAZY_SUBCOMMANDS` dict was alphabetized for consistency (previously insertion-ordered).
3. **No analyze/collect signature changes**: Per plan instructions, the existing `--prefix`/`--db` flags on analyze.py and collect.py were left untouched.
