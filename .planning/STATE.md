---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: In progress
last_updated: "2026-04-13T23:30:00.000Z"
progress:
  total_phases: 8
  completed_phases: 7
  total_plans: 28
  completed_plans: 27
  percent: 96
---

# Project State: GigaEvo Monitoring & Tools Overhaul

## Current Phase

Phase 6: Polish watchdog CLI — **IN PROGRESS** (4/5 plans complete, 06-05 Task 3 human-verify pending). Prior phases: 1 (3/3), 2 (4/4), 3 (5/5), 4 (4/4), 5 (3/3) all complete.

## Key Decisions Log

| Decision | Date | Context |
|----------|------|---------|
| Click 8.x, not Typer | 2026-04-11 | Click already in codebase (4 modules); Typer adds migration tax for no gain |
| Rich 14.x for output | 2026-04-11 | Tables, JSON, progress, panels — one library covers all output needs |
| httpx for Telegram | 2026-04-11 | Already a dependency; replaces requests (only used in telegram_notify.py) |
| Dict registry, not entry_points | 2026-04-11 | Only 3-4 experiment types; entry_points is packaging overhead for no benefit |
| Manifest is OPTIONAL | 2026-04-11 | User: "not all runs use experiment.yaml" — --run mode is first-class |
| Strict Pydantic manifest schema | 2026-04-11 | User: "if we depend on experiment.yaml, it has to be very strict" |
| No configurable alert routing (v1) | 2026-04-11 | All alerts go to all channels; routing deferred to v2 |
| No watch mode (v1) | 2026-04-11 | Rich Live dashboard deferred to v2; status + logs covers the use case |
| Both channels get everything | 2026-04-11 | PR is permanent audit record; Telegram is real-time push; same data in both |
| Replace tools, not wrap | 2026-04-11 | Clean break; old tools have inconsistent APIs that a facade would inherit |

## Constraints

- adversarial-dynamic-updates experiment is running — do NOT touch `tools/` or any running watchdog imports
- New code goes in `gigaevo/monitoring/` and `gigaevo/cli/` only
- ~4800 existing tests must keep passing
- NFS filesystem — keep tests fast

## Open Questions

- None yet

## Accumulated Context

### Roadmap Evolution

- Phase 1 added: Update research experiment lifecycle with CLI tooling
- Phase 4 added: Wire GSD into experiment lifecycle skills for robust implementation and debugging

### Phase 01 (CLI Tooling Update) Progress

- Plan 01-01 COMPLETE: `gigaevo manifest` CLI subcommand group (get/set/update/gate/pr-description), 19 tests
- Plan 01-02 COMPLETE: 6 skill/agent files migrated to gigaevo CLI; project-pm deleted; 10 files changed (4 deleted, 6 updated)
- Plan 01-03 COMPLETE: 5 heavy skills migrated (launch/closeout/checkpoint/restart/run-experiment); pm_audit removed from launch+closeout; 6 files changed; 99 gigaevo CLI refs across all skills

### Phase 01 Summary

All 3 plans complete. Phase-wide verification: 0 PYTHONPATH (excl. diagnose/evals), 0 manifest imports, 0 pm_audit, 99 gigaevo CLI references.

### Phase 04 (GSD Wiring) Progress

- Plan 04-01 COMPLETE: Foundation — EVENT/ISSUE format in issues log template + 5 Known Failures (KF-01 through KF-05) in PATTERNS.md
- Plan 04-02 COMPLETE: GSD plan generation wired into experiment-implement (Steps 4a/4b/4c) and experiment-launch (Steps 0a/0b/0c) + 3 event auto-capture points in launch
- Plan 04-03 COMPLETE: Event auto-capture added to experiment-restart (2 events), experiment-checkpoint (2 events), experiment-diagnose (1 event)
- Plan 04-04 COMPLETE: Known Failures promotion in experiment-closeout (Step 13a) + fix report generation in post-experiment-fixes (Steps 4/5/6)

### Phase 04 Summary

All 4 plans complete (2 waves). All 8 validation checks green. Requirements D-01 through D-10 satisfied. 12 commits total. No Python code changes — all modifications to Markdown skill files and knowledge stores.

### Phase 06 (Polish Watchdog CLI) Progress

- Plan 06-01 COMPLETE: WatchdogSection schema, plugin ABC, model drift rule, Redis checkpoints, NO_PROXY
- Plan 06-02 COMPLETE: Plugin plot delegation to CLI subprocess, format_telegram_body, Telegram wiring
- Plan 06-03 COMPLETE: GitHub PR channel with experiment-path upload, Redis rolling comment, baseline wiring
- Plan 06-04 COMPLETE: YAML test fixtures (solo/adversarial/prompt-coevo) + 14 integration tests + 6 CliRunner tests
- Plan 06-05 PARTIAL: Skill integration done (Tasks 1-2); Task 3 human visual verification pending

**Blocking**: 06-05 Task 3 requires researcher visual inspection of watchdog plots against reference plots.

---
*Last updated: 2026-04-13 after Phase 06 plans 01-04 complete, 05 Tasks 1-2 done*
