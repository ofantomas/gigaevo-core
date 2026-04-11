# Roadmap: GigaEvo Monitoring & Tools Overhaul

## Overview

Bottom-up build: shared library first (everything depends on it), then notification channels, then watchdog engine with plugins, then CLI shell around everything, then composite commands and migration. Each phase is independently testable and deployable. New code goes in `gigaevo/monitoring/` and `gigaevo/cli/` — no changes to `tools/` until Phase 5.

## Phases

- [x] **Phase 1: Foundation** - Shared monitoring library, RunSpec parser, manifest schema validation
- [x] **Phase 2: Notifications** - Telegram + PR channels with strategy pattern, fan-out dispatcher
- [x] **Phase 3: Watchdog** - Generic engine with plugin ABC, 4 experiment-type plugins
- [x] **Phase 4: CLI** - Unified `gigaevo` entry point, subcommands, structured output modes
- [ ] **Phase 5: Integration** - Composite lifecycle commands, anomaly detector, tool absorption, migration

## Phase Details

### Phase 1: Foundation
**Goal**: Shared monitoring library that all other phases import from. Canonical Redis access, RunSnapshot data model, unified RunSpec parser, strict manifest schema.
**Depends on**: Nothing (first phase)
**Requirements**: LIB-01, LIB-02, LIB-03, MAN-01, MAN-02, MAN-03
**Success Criteria** (what must be TRUE):
  1. `RunSpec.parse("prefix@db:label")` handles all edge cases (quotes, `@` in prefix, missing label) — passes property-based tests
  2. `ExperimentMonitor.collect(runs: list[RunConfig])` returns `list[RunSnapshot]` from fakeredis with correct generation, metrics, invalidity
  3. Manifest loads with Pydantic validation — invalid YAML produces actionable error messages, not tracebacks
  4. `AlertDetector.check(snapshots)` detects stall, crash, high-invalidity, completion using multi-signal detection (gen count + running programs + new submissions)
  5. (Phase 5) All 3 existing `parse_run_arg` implementations in `tools/` are replaced by `RunSpec.parse` — deferred from Phase 1 per MIG-01 constraint (no `tools/` changes until Phase 5)
**Plans**: 3 plans

Plans:
- [x] 01-01: RunSpec parser + RunSnapshot dataclass + canonical Redis queries
- [x] 01-02: ExperimentManifest Pydantic schema with validation + JSON Schema export
- [x] 01-03: AlertDetector with multi-signal stall detection

### Phase 2: Notifications
**Goal**: Reliable dual-channel notification delivery. Telegram with retry/escalation, PR comments with tables + plots. Channel-neutral data model rendered by per-channel formatters.
**Depends on**: Phase 1 (imports RunSnapshot, StatusUpdate)
**Requirements**: NOT-01, NOT-02, NOT-03, NOT-04, NOT-05, NOT-06, NOT-07
**Success Criteria** (what must be TRUE):
  1. Telegram startup probe: watchdog refuses to start if Telegram is unreachable (exit 1 with clear error)
  2. After 3 consecutive Telegram failures, PR comments include `⚠ TELEGRAM DOWN` header
  3. Both channels receive identical data: same metrics, same run count, same alert list — verified by integration test against same fixture
  4. Telegram status table matches `gigaevo status` output (all runs, all metrics, PIDs, invalidity %)
  5. Plot PNGs sent as Telegram photos with captions, and embedded in PR comments with cache-busting URLs
  6. Alert cooldown: same alert type not re-sent within configurable window (default: 2 cycles)
**Plans**: 4 plans

Plans:
- [x] 02-01: NotificationChannel ABC + StatusUpdate data model + formatters (GitHub markdown, Telegram markdown)
- [x] 02-02: TelegramChannel with httpx, retry, consecutive failure tracking, startup probe
- [x] 02-03: GitHubPRChannel with plot upload, rolling comment, cache-busting
- [x] 02-04: NotificationDispatcher fan-out + alert severity + cooldown

### Phase 3: Watchdog
**Goal**: Generic watchdog engine with plugin system. One `run_watchdog.py` works for all experiment types. Plugins control only plot generation and status formatting — everything else (loop, heartbeat, Redis, notifications) is the engine.
**Depends on**: Phase 1 (monitoring lib), Phase 2 (notification channels)
**Requirements**: MON-01, MON-02, MON-03, MON-04, MON-05, MON-06
**Success Criteria** (what must be TRUE):
  1. `WatchdogEngine` runs main loop: heartbeat → collect snapshots → check alerts → plugin.generate_plots → plugin.format_status → dispatch notifications
  2. `WatchdogPlugin` ABC enforced: `generate_plots()` and `format_status_body()` are abstract; `extra_telegram_content()` and `extra_redis_queries()` have defaults
  3. Plugin registry resolves: manifest `watchdog_plugin` field > task-prefix heuristic > "solo" fallback
  4. SoloPlugin handles standard MAP-Elites experiments (comparison.py curves)
  5. AdversarialPlugin handles paired arms-race experiments (adversarial pair plots)
  6. HeilbronPlugin handles 2x2 panel plots with 3-metric panels + Telegram photos
  7. `experiments/_template/run_watchdog.py` is a 5-line shim that delegates to the engine
  8. Watchdog self-monitoring: on max restart, posts FINAL alert to both Telegram AND PR before exiting
  9. Resource management: `plt.close(fig)` in finally blocks, bounded plot file retention, memory RSS logged each cycle
**Plans**: 5 plans

Plans:
- [x] 03-01-PLAN.md — WatchdogPlugin ABC + registry + WatchdogConfig
- [x] 03-02-PLAN.md — WatchdogEngine core loop (heartbeat, collect, alert, dispatch, SIGTERM, retry)
- [x] 03-03-PLAN.md — SoloPlugin + AdversarialPlugin
- [x] 03-04-PLAN.md — HeilbronPlugin + PromptCoevoPlugin
- [x] 03-05-PLAN.md — Template shim + integration test (engine + mock plugin + mock channels + fakeredis)

### Phase 4: CLI
**Goal**: Unified `gigaevo` entry point that absorbs all standalone tools. Two-level subcommands with structured output. Every command works in both `--experiment` and `--run` mode.
**Depends on**: Phase 1 (shared lib), Phase 3 (watchdog — for `gigaevo watchdog` subcommand)
**Requirements**: CLI-01, CLI-02, CLI-03, CLI-04, CLI-05, CLI-06, MON-07, PLT-01, PLT-02, PLT-03
**Success Criteria** (what must be TRUE):
  1. `gigaevo status --experiment task/name` shows same data as current `tools/status.py --experiment`
  2. `gigaevo status --run prefix@db:label` works without experiment.yaml
  3. `gigaevo status --format json | jq .` produces valid, parseable JSON
  4. `gigaevo plot comparison --run A --run B --output-dir ./plots/` produces PNG/PDF/SVG
  5. `gigaevo logs --follow label` tails the nohup log file
  6. `gigaevo flush --db 5 6 --confirm` kills workers and flushes (same behavior as tools/flush.py)
  7. `gigaevo trajectory --run prefix@db:label --tail 10` shows last 10 gens
  8. `gigaevo --help` completes in < 200ms (lazy imports, no matplotlib at startup)
  9. Destructive commands (`flush`, `archive`) require `--confirm` and support `--dry-run`
**Plans:** 4 plans

Plans:
- [x] 04-01-PLAN.md -- CLI skeleton: Click group + rich-click + global flags + OutputFormatter + RunResolver + lazy imports
- [x] 04-02-PLAN.md -- Read-only subcommands: status, trajectory, top, logs (using monitoring lib)
- [x] 04-03-PLAN.md -- Plotting + export subcommands: plot comparison, plot trajectory, export csv, export frontier
- [x] 04-04-PLAN.md -- Mutating + long-running subcommands: flush (--confirm gate) + watchdog

### Phase 5: Integration
**Goal**: Composite lifecycle commands, pluggable anomaly detector, tool absorption. Old `tools/*.py` scripts become thin shims then get removed.
**Depends on**: Phase 4 (CLI must exist for composite commands to wrap)
**Requirements**: EXT-01, EXT-02, EXT-03, EXT-04, EXT-05, MIG-01, MIG-02, MIG-03
**Success Criteria** (what must be TRUE):
  1. `gigaevo checkpoint --experiment task/name` runs status + plot + PR comment + Telegram in one shot
  2. `gigaevo launch --experiment task/name` runs preflight → config dump → launch → PID verify → watchdog start
  3. `gigaevo closeout --experiment task/name` runs test eval → archive → upload → results
  4. Anomaly detector rules pluggable: built-in stagnation/crash/high-invalid/sync-deadlock + per-experiment rules from `anomaly_rules.py`
  5. Old `tools/*.py` scripts print deprecation warning then delegate to `gigaevo` CLI
  6. `requests` dependency removed from `pyproject.toml` (replaced by httpx)
  7. `tools/README.md` and `CLAUDE.md` updated to reference `gigaevo` CLI commands
**Plans**: TBD

Plans:
- [ ] 05-01: Checkpoint + anomaly detector (gigaevo checkpoint, pluggable rules)
- [ ] 05-02: Composite lifecycle commands (launch, closeout, restart)
- [ ] 05-03: Tool absorption (shims → removal) + dependency cleanup + docs update

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 3/3 | Complete | 2026-04-11 |
| 2. Notifications | 4/4 | Complete | 2026-04-11 |
| 3. Watchdog | 5/5 | Complete | 2026-04-11 |
| 4. CLI | 4/4 | Complete | 2026-04-12 |
| 5. Integration | 0/3 | Not started | - |

---
*Roadmap created: 2026-04-11*
*Last updated: 2026-04-12 after Phase 4 complete (87 CLI tests)*
