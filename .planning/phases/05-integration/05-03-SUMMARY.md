---
phase: 05-integration
plan: 03
subsystem: cli
tags: [migration, imports, pydantic]
dependency_graph:
  requires: [05-01, 05-02]
  provides: [cli-clean-imports]
  affects: [gigaevo/cli, tests/cli]
tech_stack:
  patterns: [pydantic-manifest-shape, gigaevo-package-imports]
key_files:
  created: []
  modified:
    - gigaevo/cli/__init__.py
    - gigaevo/cli/flush.py
    - gigaevo/cli/export.py
    - gigaevo/cli/plot_group.py
    - gigaevo/cli/run_resolver.py
    - gigaevo/cli/watchdog_cmd.py
    - gigaevo/cli/lifecycle.py
    - gigaevo/cli/manifest_cmd.py
    - tests/cli/test_manifest_cmd.py
    - tests/cli/test_watchdog_cmd.py
    - tests/cli/test_lifecycle_cmd.py
decisions:
  - "Used manifest.experiment.status (Pydantic nested shape) instead of manifest.status (flat dataclass)"
  - "Replaced manifest._raw with manifest.model_dump() for Pydantic compatibility"
  - "Changed _annotate_frontier_points (private) to annotate_frontier_points (public) matching gigaevo.utils.plotting API"
metrics:
  duration: 580s
  completed: 2026-04-13T19:29:00Z
  tasks_completed: 3
  tasks_total: 3
  files_modified: 11
---

# Phase 05 Plan 03: Replace tools/ imports with gigaevo/ package imports Summary

Replace all `from tools.*` imports across `gigaevo/cli/` with `gigaevo.*` package imports, completing the migration from legacy tools/ scripts to the new package structure.

## One-liner

Replaced all tools/ imports in 8 CLI modules with gigaevo/ package imports and migrated manifest_cmd.py to Pydantic nested shape

## Task Results

### Task 1: Register manifest subcommand + replace mechanical tools/ imports in 7 CLI modules
**Commit:** 9ebd3831

- Registered `manifest` subcommand in `_LAZY_SUBCOMMANDS` dict
- `run_resolver.py`: `tools.experiment.manifest` -> `gigaevo.monitoring.manifest`
- `watchdog_cmd.py`: `tools.experiment.manifest` -> `gigaevo.monitoring.manifest`, updated `manifest.max_generations` -> `manifest.experiment.max_generations`
- `lifecycle.py`: `tools.experiment.manifest` -> `gigaevo.monitoring.manifest` (3 sites), updated `manifest.status` -> `manifest.experiment.status` (3 sites)
- `flush.py`: `tools.flush` -> `gigaevo.cli.flush_ops`
- `export.py`: `tools.utils` -> `gigaevo.utils.redis`
- `plot_group.py`: `tools.utils` -> split into `gigaevo.utils.redis` + `gigaevo.utils.dataframes`; `tools.comparison._annotate_frontier_points` -> `gigaevo.utils.plotting.annotate_frontier_points`

### Task 2: Migrate manifest_cmd.py to Pydantic shape
**Commit:** cdddf59e

- Replaced all 6 `from tools.experiment.manifest import ...` with `from gigaevo.monitoring.manifest import ...`
- Updated field accesses to Pydantic nested shape:
  - `manifest_obj.status` -> `manifest_obj.experiment.status`
  - `manifest_obj.name` -> `manifest_obj.experiment.name`
  - `manifest_obj.max_generations` -> `manifest_obj.experiment.max_generations`
  - `manifest_obj.pr_number` -> `manifest_obj.experiment.pr_number`
  - `manifest_obj._raw` -> `manifest_obj.model_dump()`
  - `getattr(manifest_obj, field)` -> `getattr(manifest_obj.experiment, field)` for scalar fields

### Task 3: Update test mock paths
**Commit:** d43ba573

- `test_manifest_cmd.py`: Updated `_MANIFEST_MOD` to `gigaevo.monitoring.manifest`, refactored `_make_manifest` fixture to set fields on `m.experiment.*` and use `m.model_dump.return_value` instead of `m._raw`
- `test_watchdog_cmd.py`: Updated 5 `patch("tools.experiment.manifest.load_manifest")` to `patch("gigaevo.monitoring.manifest.load_manifest")`
- `test_lifecycle_cmd.py`: Updated 2 patch paths + 2 mock fixtures to use `manifest.experiment.status` and `manifest.experiment.name`
- `test_flush_cmd.py`: No changes needed (mocks already used `gigaevo.cli.flush.*` paths)
- `test_plot_cmd.py`: No changes needed (mocks used internal `gigaevo.cli.plot_group._fetch_run_data`)
- `test_export_cmd.py`: No changes needed (mocks used internal `gigaevo.cli.export._fetch_dataframe`)

## Verification

- `grep -rn "from tools\." gigaevo/cli/` returns 0 lines
- `grep -rn "tools\." tests/cli/` returns 0 lines
- `manifest` registered in `_LAZY_SUBCOMMANDS`
- `manifest_cmd.py` uses `manifest.experiment.status` (not `manifest.status`)
- `ruff check` passes on all 11 modified files

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None.

## Self-Check: PASSED

All 11 modified files verified present. All 3 commit hashes verified in git log.
