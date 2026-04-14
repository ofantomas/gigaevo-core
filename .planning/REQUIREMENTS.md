# Requirements: GigaEvo Monitoring & Tools Overhaul

**Defined:** 2026-04-11
**Core Value:** When an experiment launches, the researcher checks their phone — not the terminal.

## v1 Requirements

### CLI

- [ ] **CLI-01**: Unified `gigaevo` entry point with two-level subcommand hierarchy (`gigaevo status`, `gigaevo plot comparison`, `gigaevo run flush`) replacing all standalone `tools/*.py` scripts
- [ ] **CLI-02**: Consistent global flags: `--experiment task/name` (reads experiment.yaml), `--run prefix@db:label` (ad-hoc, no manifest needed), `--quiet`, `--verbose`
- [ ] **CLI-03**: Every subcommand works in BOTH modes: `--experiment` (auto-discovers runs from manifest) and `--run` (operates on a single run with no experiment.yaml)
- [ ] **CLI-04**: Structured output via `--format {table,json,csv,markdown}`. Default: table. Auto-switch to JSON when stdout is piped (unless `--format` explicit)
- [ ] **CLI-05**: Destructive commands (`flush`, `archive`, `kill`) require `--confirm` flag. All mutating commands support `--dry-run`
- [ ] **CLI-06**: Click 8.x + rich-click for help rendering. No Typer migration. Existing Click modules preserved

### Manifest

- [ ] **MAN-01**: Strict Pydantic-validated schema for experiment.yaml with version field, required vs optional sections, and clear validation error messages
- [ ] **MAN-02**: Manifest is OPTIONAL — all tools work without it via `--run` mode. Manifest mode adds auto-discovery, not gating
- [ ] **MAN-03**: Schema exported as JSON Schema for editor autocompletion and CI validation

### Monitoring

- [ ] **MON-01**: Generic watchdog core loop that reads experiment.yaml and adapts to any experiment type via `WatchdogPlugin` ABC
- [ ] **MON-02**: Plugin system: `WatchdogPlugin` ABC with `generate_plots()`, `format_status_body()`, optional `extra_telegram_content()` and `extra_redis_queries()`. Simple dict registry with `@register` decorator
- [ ] **MON-03**: Built-in plugins for: solo MAP-Elites, adversarial pairs, prompt co-evolution. Designed around adversarial case first (most complex)
- [ ] **MON-04**: PID liveness (`os.kill(pid, 0)`), watchdog heartbeat TTL in Redis, stale detection (heartbeat > 2× poll interval), stall detection (gen not advancing for N hours)
- [ ] **MON-05**: Gen-by-gen trajectory tracking: frontier best, mean fitness, valid program count, last improvement gen, acceptance rate in trailing window
- [ ] **MON-06**: Stagnation detection: no frontier improvement for N consecutive gens → alert
- [ ] **MON-07**: `gigaevo logs <label>` to tail nohup log file. `gigaevo logs --follow <label>` for live tailing. Log path auto-discovered from experiment.yaml or passed explicitly

### Notifications

- [ ] **NOT-01**: Telegram delivery via httpx (replace `requests`). Retry with exponential backoff. Consecutive failure counter. Startup connectivity probe before entering main loop
- [ ] **NOT-02**: Full status table in Telegram messages — same data as `gigaevo status --experiment`: all runs, all metrics, PIDs, invalidity rate, validator timing
- [ ] **NOT-03**: Fitness curve plots sent as Telegram photos alongside status tables (PNG attachments with captions)
- [ ] **NOT-04**: `NotificationChannel` ABC + `NotificationDispatcher` fan-out. Channel-neutral `StatusUpdate` data object rendered by per-channel formatters
- [ ] **NOT-05**: PR comments contain structured data: status tables (markdown), fitness plot image links, metrics summary. Update-in-place for recurring watchdog updates
- [ ] **NOT-06**: Both Telegram and PR get the same complete data. PR is the permanent audit record; Telegram is real-time push
- [ ] **NOT-07**: Alert types with severity: stagnation (WARN), crash (ERROR), anomaly (WARN), completion (INFO). Cooldown per alert type to prevent floods

### Plotting

- [ ] **PLT-01**: Comparison curves: rolling fitness vs iteration across multiple runs. Multiple smoothing methods. Confidence bands. Output: PNG/PDF/SVG
- [ ] **PLT-02**: Trajectory plots: per-gen frontier and mean fitness with baseline reference lines
- [ ] **PLT-03**: CSV export of evolution data and frontier-only data (absorbs `redis2pd.py` functionality)

### Shared Library

- [ ] **LIB-01**: `gigaevo/monitoring/` package with shared Redis query layer (`RunSnapshot` frozen dataclass), plot rendering, and notification formatting — used by CLI, watchdog, and notification channels
- [ ] **LIB-02**: Unified `RunSpec` parser: parse `prefix@db[:label]` ONCE in a shared module. Structured `RunSpec` dataclass passed downstream. Eliminates 3 divergent parser implementations
- [ ] **LIB-03**: Consistent error handling via loguru with contextual prefixes. Errors to stderr, data to stdout

### Extras

- [ ] **EXT-01**: `gigaevo checkpoint` command: runs status → plot → PR comment → Telegram notification in one shot. Callable from cron or manually
- [ ] **EXT-02**: Pluggable anomaly detector: rules as Python functions taking `RunSnapshot`, returning `AnomalyReport | None`. Built-in: stagnation, crash, high-invalid-rate, sync-deadlock
- [ ] **EXT-03**: `gigaevo launch` composite: preflight → config dump → launch → PID verify → watchdog start
- [ ] **EXT-04**: `gigaevo closeout` composite: test eval → archive → upload → results → INDEX.md update
- [ ] **EXT-05**: `gigaevo restart` composite: kill → flush → re-launch with current code

### Migration

- [ ] **MIG-01**: New code goes in `gigaevo/monitoring/` and `gigaevo/cli/`. Do NOT touch `tools/` — running experiments depend on it
- [ ] **MIG-02**: Old `tools/*.py` scripts removed AFTER CLI absorbs their functionality and tests pass. No wrapper/facade period
- [ ] **MIG-03**: `requests` dependency removed after Telegram migrated to httpx

## v2 Requirements

### CLI Enhancements

- **CLI-V2-01**: Config resolution chain: auto-detect experiment from git branch (`exp/hover/foo` → `hover/foo`). Fallback: `--experiment` > `$GIGAEVO_EXPERIMENT` > git branch
- **CLI-V2-02**: `~/.gigaevo.yaml` config file for defaults (Redis host/port, output format, Telegram token reference)
- **CLI-V2-03**: Shell completion for Bash/Zsh/Fish (Click requires explicit `_GIGAEVO_COMPLETE` setup)

### Monitoring Enhancements

- **MON-V2-01**: Watch mode: Rich Live auto-refreshing dashboard with status table + sparklines. `gigaevo watch --experiment <name>`. Redraws every 60s

### Notifications Enhancements

- **NOT-V2-01**: Configurable alert routing: different alert types to different channels (crash → telegram+PR, stagnation → PR only). YAML config in experiment.yaml

## Out of Scope

| Feature | Reason |
|---------|--------|
| Full TUI dashboard (Textual/curses) | SSH sessions break TUIs; researchers glance at status, not watch for hours |
| Web dashboard / Grafana | Adds infrastructure; Telegram-first is the goal |
| Slack integration | Team uses Telegram; support one channel well |
| Plugin marketplace / registry | <5 users; overkill |
| Hot-reload for plugins/rules | Restart watchdog instead (5s operation) |
| WebSocket / real-time streaming | 1 event/min doesn't justify WebSocket infrastructure |
| Automatic experiment restart | Crashes indicate bugs; auto-restart wastes GPU hours |
| Multi-server SSH orchestration | Use existing tools (tmux, nohup, systemd) |
| Rewriting experiment lifecycle skills | Skills work; only monitoring layer is broken |
| Changing Redis data model | Tools consume it, don't define it |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| LIB-01 | Phase 1 | Pending |
| LIB-02 | Phase 1 | Pending |
| LIB-03 | Phase 1 | Pending |
| MAN-01 | Phase 1 | Pending |
| MAN-02 | Phase 1 | Pending |
| MAN-03 | Phase 1 | Pending |
| NOT-01 | Phase 2 | Pending |
| NOT-02 | Phase 2 | Pending |
| NOT-03 | Phase 2 | Pending |
| NOT-04 | Phase 2 | Pending |
| NOT-05 | Phase 2 | Pending |
| NOT-06 | Phase 2 | Pending |
| NOT-07 | Phase 2 | Pending |
| MON-01 | Phase 3 | Pending |
| MON-02 | Phase 3 | Pending |
| MON-03 | Phase 3 | Pending |
| MON-04 | Phase 3 | Pending |
| MON-05 | Phase 3 | Pending |
| MON-06 | Phase 3 | Pending |
| CLI-01 | Phase 4 | Pending |
| CLI-02 | Phase 4 | Pending |
| CLI-03 | Phase 4 | Pending |
| CLI-04 | Phase 4 | Pending |
| CLI-05 | Phase 4 | Pending |
| CLI-06 | Phase 4 | Pending |
| MON-07 | Phase 4 | Pending |
| PLT-01 | Phase 4 | Pending |
| PLT-02 | Phase 4 | Pending |
| PLT-03 | Phase 4 | Pending |
| EXT-01 | Phase 5 | Pending |
| EXT-02 | Phase 5 | Pending |
| EXT-03 | Phase 5 | Pending |
| EXT-04 | Phase 5 | Pending |
| EXT-05 | Phase 5 | Pending |
| MIG-01 | Phase 5 | Pending |
| MIG-02 | Phase 5 | Pending |
| MIG-03 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 37 total
- Mapped to phases: 37
- Unmapped: 0 ✓

---
*Requirements defined: 2026-04-11*
*Last updated: 2026-04-11 after feature scoping*
