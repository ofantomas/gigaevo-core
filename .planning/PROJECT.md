# GigaEvo Monitoring & Tools Overhaul

## What This Is

A ground-up redesign of GigaEvo's experiment monitoring, notification, and CLI tooling. Unified `gigaevo` CLI with 12 subcommands, plugin-based watchdog architecture, and dual-channel notifications (Telegram + GitHub PR comments) delivering full status tables and fitness plots.

## Core Value

When an experiment launches, the researcher checks their phone — not the terminal. Every experiment type works out of the box, every notification arrives reliably, and every tool has one consistent interface.

## Current State

Shipped v1.0 with 13,125 LOC Python across `gigaevo/monitoring/` (shared library, notifications, watchdog) and `gigaevo/cli/` (12 subcommands). 435 tests. All 37 v1 requirements implemented.

## Requirements

### Validated

- ✓ Redis-based metrics storage and retrieval — existing
- ✓ Multi-run fitness curve plotting — existing
- ✓ Run archiving and GitHub Release upload — existing
- ✓ Redis flush with worker cleanup — existing
- ✓ Top programs inspection — existing
- ✓ Evolutionary lineage tracing — existing
- ✓ CSV data export — existing
- ✓ Experiment manifest system — existing
- ✓ Preflight validation (20-check gate) — existing
- ✓ PR comment posting via `gh` CLI — existing
- ✓ Telegram text and photo notifications — existing
- ✓ CLI-01 through CLI-06 — v1.0 (unified gigaevo CLI)
- ✓ MAN-01 through MAN-03 — v1.0 (Pydantic manifest)
- ✓ MON-01 through MON-07 — v1.0 (watchdog engine + plugins)
- ✓ NOT-01 through NOT-07 — v1.0 (dual-channel notifications)
- ✓ PLT-01 through PLT-03 — v1.0 (plots + CSV export)
- ✓ LIB-01 through LIB-03 — v1.0 (shared monitoring library)
- ✓ EXT-01 through EXT-05 — v1.0 (composite lifecycle commands)
- ✓ MIG-01 — v1.0 (new code in monitoring/ and cli/ only)

### Active

(None — all v1 requirements shipped. Next milestone TBD.)

### Out of Scope

- Web dashboard / Grafana — adds infrastructure complexity; Telegram-first is the goal
- Rewriting the experiment lifecycle skills (design, implement, launch, checkpoint, closeout) — those work; only the monitoring layer is broken
- Changing the Redis data model or metrics schema — tools consume it, they don't define it
- Multi-user access control — single researcher workflow
- Real-time streaming (WebSocket/SSE) — polling-based is sufficient for experiment timescales

## Context

The current monitoring stack evolved organically. Each experiment copies `run_watchdog.py` from a template and patches it for the specific experiment type (solo vs adversarial pairs vs prompt co-evolution). Plots break when label patterns don't match assumptions. Telegram fails silently due to proxy issues. The 20+ tools in `tools/` have different flag conventions (`--run prefix@db:label` vs `--experiment task/name` vs positional args), different output formats, and no shared library.

**What exists today:**
- `tools/status.py` — best tool, reads experiment.yaml, auto-discovers metrics
- `tools/comparison.py` — generates fitness curve plots (png/pdf/svg)
- `tools/trajectory.py` — gen-by-gen text tables
- `tools/top_programs.py` — inspect best programs
- `tools/lineage.py` — ancestry tracing
- `tools/redis2pd.py` — CSV export
- `tools/flush.py` — Redis cleanup
- `tools/telegram_notify.py` — text + photo notifications (requires HTTPS_PROXY)
- Per-experiment `run_watchdog.py` — posts PR comments, generates plots

**What breaks regularly:**
- Watchdog assumes adversarial pair labels (`P{N}_A`/`P{N}_B`) — fails for solo experiments
- Plot generation fails when matplotlib can't find labels or data is empty
- Telegram proxy configuration is fragile (HTTPS_PROXY env var, `.claude/settings.json`)
- Each tool parses `--run prefix@db:label` independently with slightly different parsing

**Codebase map:** `.planning/codebase/` (7 documents) provides detailed architecture, stack, conventions, testing, and concerns analysis.

## Constraints

- **Tech stack**: Python 3.12+, must integrate with existing Hydra config system and Redis storage
- **Backward compat**: Old `tools/*.py` scripts can be removed once CLI absorbs them — no wrapper/facade period needed
- **Dependencies**: Minimize new dependencies; matplotlib already available for plotting
- **Testing**: All new code must have tests (pytest, ~4800 existing tests)
- **NFS filesystem**: Test suite runs on NFS — keep tests fast (`-x` flag essential)
- **No breaking experiments**: Changes must not disrupt currently running experiments (adversarial-dynamic-updates is active)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Telegram-first monitoring | Researcher wants to check phone, not terminal | ✓ Good — TelegramChannel with httpx, retry, photos |
| Plugin-based watchdog | Different experiment types need different renderers | ✓ Good — 4 plugins (solo, adversarial, heilbron, prompt-coevo) |
| Replace tools, not wrap | Clean break from inconsistent APIs | ✓ Good — 12 CLI subcommands, shared OutputFormatter |
| Both channels get everything | PR = audit trail, Telegram = real-time push | ✓ Good — NotificationDispatcher fan-out |
| Design first, then build | Structural pain needs architecture | ✓ Good — 5 phases, bottom-up build |
| Click 8.x, not Typer | Already in codebase, no migration tax | ✓ Good — LazyGroup pattern works well |
| Manifest is OPTIONAL | Not all runs use experiment.yaml | ✓ Good — --run mode first-class everywhere |
| Dict registry, not entry_points | Only 3-4 experiment types | ✓ Good — simple, no packaging overhead |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? -> Move to Out of Scope with reason
2. Requirements validated? -> Move to Validated with phase reference
3. New requirements emerged? -> Add to Active
4. Decisions to log? -> Add to Key Decisions
5. "What This Is" still accurate? -> Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-12 after v1.0 milestone*
