# Research Summary

## Stack

**CLI**: Click 8.x (already a dependency) + rich-click for rich help text. Not Typer (would require rewriting 4 existing Click modules for no gain). Not argparse for new code.

**Plugin system**: `importlib.metadata.entry_points` (stdlib) + Click lazy Group. Not pluggy (hook system overkill), not stevedore (OpenStack-grade complexity).

**Telegram**: httpx (already a dependency via OpenAI SDK). Not python-telegram-bot or aiogram (only 3 API calls needed). Remove `requests` (only used in telegram_notify.py).

**Output**: Rich 14.x for tables, JSON, progress, panels. Not Textual (TUI overkill), not tabulate (redundant with Rich).

**Structured output**: `--format {table,json,csv,markdown}` via thin `OutputFormatter` over Rich. Auto-switch to JSON when piped.

**Net dependency change**: Add `rich>=14.0`, `rich-click>=1.8`. Remove `requests`.

## Table Stakes

- Two-level subcommand CLI (`gigaevo status`, `gigaevo plot comparison`) with consistent global flags
- Output modes: table (default), JSON, CSV, markdown. Errors to stderr.
- Destructive ops require `--confirm` + `--dry-run`
- PID liveness, watchdog heartbeat, stale/stall detection
- Telegram text + photos, PR comments with tables + plots
- Comparison curves, trajectory plots, CSV export
- Branch-aware experiment detection (`exp/hover/foo` -> `hover/foo`)

## Watch Out For

**CRITICAL** (fix-or-fail):
- **Silent notification failure** (P-NOT-01): Current code swallows Telegram errors. Need startup probe + consecutive failure tracking + fallback escalation.
- **Breaking running experiments** (P-MIG-04): adversarial-dynamic-updates is live. New code goes in NEW packages; don't touch `tools/`.

**HIGH** (grounded in actual codebase bugs):
- **Divergent run spec parsers** (P-CLI-02): 3 independent `parse_run_arg` implementations with different behaviors. Consolidate first with exhaustive tests.
- **Proxy fragility** (P-NOT-02): `HTTPS_PROXY` not set in nohup'd processes. Dedicated config file instead of env vars.
- **False stall alarms** (P-WD-01): Single-signal detection (gen count) produces false positives. Need multi-signal: gen count + running programs + new submissions.

**Design decisions**:
- Plugin system: simple dict registry, NOT entry_points (only 3-4 experiment types). Design interface around adversarial case first (most complex).
- Output: data objects rendered by format-specific serializers, not per-subcommand string formatting.
- Migration: old scripts become thin wrappers first, removed after 2-4 weeks.

## Architecture

**Core insight**: Across 29 watchdog files (14,356 lines), the ONLY variation is plot generation and status formatting. Everything else (Redis queries, heartbeat, notification delivery, completion detection) is identical.

**Build order**:
1. Shared monitoring library (`gigaevo/monitoring/`) -- everything depends on this
2. Notification channels (`gigaevo/monitoring/notifications/`) -- strategy pattern + fan-out dispatcher
3. Watchdog engine + plugin ABC (`gigaevo/monitoring/watchdog/`)
4. Experiment-specific plugins (solo, adversarial, heilbron, prompt-coevo)
5. CLI integration (`gigaevo watchdog` subcommand)
6. Absorb remaining tools into CLI subcommands

**Plugin resolution**: manifest `watchdog_plugin` field > task-prefix heuristic > "solo" fallback.

**Notification pattern**: `NotificationChannel` ABC + `NotificationDispatcher` fan-out. Channel-neutral `StatusUpdate` data object rendered by per-channel formatters.

## Files

| Document | Lines | Focus |
|----------|-------|-------|
| `STACK.md` | 321 | CLI framework, plugin system, notification layer, terminal output |
| `FEATURES.md` | 323 | Table stakes vs differentiators vs anti-features, complexity assessment |
| `ARCHITECTURE.md` | 610 | Component structure, data flow, build order, integration points |
| `PITFALLS.md` | 242 | 22 pitfalls ranked by probability x impact, with prevention strategies |
