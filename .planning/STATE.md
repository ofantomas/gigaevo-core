# Project State: GigaEvo Monitoring & Tools Overhaul

## Current Phase
Phase 1: Foundation — **COMPLETE** (3/3 plans, 135 tests, all success criteria verified). Ready for `/gsd-plan-phase 2`

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

---
*Last updated: 2026-04-11 after roadmap creation*
