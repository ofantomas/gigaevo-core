# Features Research

Research for a unified `gigaevo` CLI replacing 20+ standalone Python scripts.
Informed by: MLflow, Weights & Biases, DVC, Ray Tune, Sacred, Optuna, kubectl,
Poetry, Supervisor, Grafana alerting, and the clig.dev CLI guidelines.

---

## Table Stakes

### CLI

**Subcommand structure** (kubectl/Poetry/MLflow pattern):
- Two-level `noun verb` hierarchy: `gigaevo status`, `gigaevo run flush`, `gigaevo plot comparison`
- Consistent global flags across all subcommands: `--json`, `--quiet`, `--verbose/-v`, `--dry-run`
- `--experiment <task/name>` as the universal context selector (replaces the ad-hoc `--run prefix@db:label` on every tool)
- Auto-generated `--help` at every level (Typer/Click gives this for free)
- Shell completion for Bash/Zsh/Fish (Typer auto-generates; Click requires explicit setup)
- Consistent `--run PREFIX@DB[:LABEL]` shorthand kept for single-run ad-hoc queries (backward compat)
- Exit codes: 0 = success, 1 = error, 2 = partial/warning (match current preflight_check.py pattern)

**Output modes** (clig.dev + kubectl standard):
- Default: human-readable table (Rich tables for aligned columns, color-coded status)
- `--json`: machine-parseable JSON to stdout (enables `| jq` pipelines)
- `--quiet`: suppress all non-essential output (for scripting)
- `--no-color`: disable ANSI codes (auto-detect if stdout is not TTY; respect `NO_COLOR` env var)
- Errors always to stderr, data always to stdout

**Destructive operation safety** (Poetry/clig.dev/kubectl pattern):
- `--confirm` required for flush, kill, archive operations (current pattern; keep it)
- `--dry-run` on all mutating commands (flush, archive, launch, restart)
- Named confirmation for high-risk operations: `gigaevo run flush --confirm=heilbron/my-exp`

**Configuration resolution** (Hydra-adjacent):
- Detect experiment from current git branch when `--experiment` is omitted (branch name `exp/hover/foo` -> `hover/foo`)
- Fallback to `$GIGAEVO_EXPERIMENT` env var
- Config file `~/.gigaevo.yaml` for defaults (redis host/port, default output format, telegram token reference)
- Environment variables override config file; CLI flags override everything

**Entry point**:
- Single `gigaevo` command installed via `console_scripts` entry point in `pyproject.toml`
- Alternatively: `python -m gigaevo_cli` for environments where PATH is unreliable (GPU servers)

### Monitoring / Watchdog

**Live status** (current `status.py` + Supervisor patterns):
- Per-run: generation, all metrics (auto-discovered from `metrics.yaml`), invalid%, validator duration, PID liveness
- Per-experiment: aggregate view of all runs, watchdog heartbeat, overall health
- Color-coded health: GREEN (healthy), YELLOW (stale/slow), RED (dead/crashed)
- Stale detection: watchdog heartbeat older than 2x poll interval = STALE; PID not alive = DEAD

**Process health checks** (Supervisor model):
- PID liveness check via `os.kill(pid, 0)` (already implemented)
- Watchdog heartbeat in Redis with TTL (already implemented: `experiments:{name}:watchdog_heartbeat`)
- Detect zombie states: PID alive but generation not advancing for N hours = STALLED
- Detect crash loops: process restarted but Redis state inconsistent

**Trajectory tracking** (current `trajectory.py`):
- Gen-by-gen table with frontier best, mean fitness, valid program count
- Last improvement detection (gen where frontier last jumped)
- Acceptance rate (improvements per valid program in trailing window)
- Stagnation detection: no frontier improvement for N consecutive gens

**Log access**:
- `gigaevo logs <label>` to tail the nohup log file for a run (like `kubectl logs`)
- `gigaevo logs --follow <label>` for live tailing
- Log path auto-discovered from experiment.yaml `log_path` field

### Notifications

**Telegram integration** (current `telegram_notify.py` covers most of this):
- Text messages with Markdown formatting
- Image/plot attachments (PNG) with captions
- Gate approval flow: send message, poll for reply keywords ("approved", "reject")
- Rate limiting: `wait_duration` to avoid message floods (W&B pattern)
- Proxy support for firewalled servers (already implemented)

**PR comments** (current `pr_comment.py`):
- Post checkpoint summaries to experiment PR
- Embed status tables and plot images
- Update existing comment vs. new comment (for hourly watchdog updates, collapse into single comment)

**Alert types** (W&B + Grafana pattern):
- Stagnation alert: no fitness improvement for N gens (configurable threshold)
- Crash alert: PID not alive, watchdog stale
- Anomaly alert: sudden fitness drop, invalid rate spike above 75%
- Completion alert: all runs hit `max_generations`
- Each alert has a severity level: INFO, WARN, ERROR

### Plotting

**Comparison plots** (current `comparison.py` already rich):
- Rolling fitness vs iteration across multiple runs
- Multiple smoothing methods (rolling mean, LOWESS, Savitzky-Golay, Gaussian)
- Confidence bands (std dev, percentile)
- Multiple output formats: PNG, PDF, SVG (all three emitted by default)
- Headless by default (`Agg` backend); `--show` for interactive display

**Trajectory plots**:
- Per-gen frontier and mean fitness
- Baseline reference lines (from `experiment.yaml`)

**Export**:
- CSV export of evolution data (`redis2pd.py` already does this)
- Frontier-only CSV for results tables

---

## Differentiators

### Branch-Aware Context Resolution

Detect experiment from current git branch automatically. If you are on
`exp/hover/prompt_coevolution`, `gigaevo status` should show that experiment
without any flags. No other ML CLI does this because most do not tie experiments
to git branches. GigaEvo does (every experiment is a PR branch), so this is a
natural and powerful UX win.

Implementation: parse branch name, strip `exp/` prefix, look up `experiment.yaml`.
Fallback chain: `--experiment` flag > `$GIGAEVO_EXPERIMENT` env > git branch > error.

### Unified Run Spec Language

Current state: each tool independently parses `prefix@db[:label]`. The unified CLI
should parse this once in a shared layer and pass structured `RunSpec` objects downstream.
This eliminates the class of bugs where tools parse the same string differently (the
`parse_pid_arg` quoting bug from the issues log is an example).

### Watch Mode (Live Dashboard)

`gigaevo watch [--experiment <name>]` — a single-screen terminal dashboard that
auto-refreshes every 60s (configurable). Shows:
- Status table (all runs, gen, metrics, PID health)
- Mini sparklines for frontier fitness of each run (Rich Sparkline widget)
- Last checkpoint time, time since last gen advance
- Alert banner if any run is stalled/dead

This is not the same as a full Textual TUI (which would be a differentiator of
diminishing returns). It is a Rich Live display that clears and redraws. Low
complexity, high value. Think `watch -n60 gigaevo status` but prettier and
with inline sparklines.

### Anomaly Detector Integration

The watchdog already has ad-hoc anomaly detection (sync deadlock detection in
the adversarial experiment). Generalize this into a pluggable pattern:
- Define anomaly rules as small Python functions that take a `RunSnapshot` and return `AnomalyReport | None`
- Built-in rules: stagnation, crash, high-invalid-rate, sync-deadlock
- Experiment-specific rules loaded from `experiments/<task>/<name>/anomaly_rules.py` if present
- Each rule has a severity, cooldown period, and notification channel

### Checkpoint Command

`gigaevo checkpoint [--experiment <name>]` — runs the full checkpoint cycle:
1. Read status for all runs
2. Generate comparison plot
3. Post PR comment with status table + plot
4. Send Telegram notification (if configured)
5. Log to `04_issues_log.md` if any anomalies detected

This replaces the current multi-step manual checkpoint that the experiment-checkpoint
skill orchestrates. Making it a single CLI command means it can also be called from
cron or systemd timer, not just from Claude Code.

### Composite Commands (Lifecycle Shortcuts)

- `gigaevo launch <experiment>` — preflight + generate launch script + execute + record PIDs + start watchdog
- `gigaevo closeout <experiment>` — test eval + archive all runs + upload + write results + update INDEX.md
- `gigaevo restart <experiment>` — kill all + flush DBs + re-launch (current skill does this but as a complex multi-step)

These are the "porcelain" commands (git analogy). Individual tools remain available as "plumbing".

### Configurable Alert Routing

Different alert types go to different channels:
- Crash alerts: Telegram (immediate) + PR comment
- Stagnation: PR comment only (less urgent)
- Completion: Telegram + PR comment
- Gate approval requests: Telegram only (needs interactive reply)

Configuration in `experiment.yaml` or `~/.gigaevo.yaml`:
```yaml
alerts:
  channels:
    telegram: true
    pr_comment: true
  routes:
    crash: [telegram, pr_comment]
    stagnation: [pr_comment]
    completion: [telegram, pr_comment]
    gate: [telegram]
```

---

## Anti-Features

### Full TUI Dashboard (Textual/curses)

Do NOT build a Textual-based full terminal UI application. Reasons:
- GigaEvo experiments run on GPU servers accessed via SSH. Textual requires a
  terminal with full mouse/keyboard event support; SSH sessions over unstable
  connections will break the TUI regularly.
- The maintenance burden of a reactive TUI is 10x a simple Rich Live display.
- Researchers do not sit and watch dashboards for hours. They check status,
  glance at a table, and move on. A `gigaevo status` that prints a table and
  exits is the right UX.
- The watch mode (Rich Live auto-refresh) covers the "I want to keep an eye on
  things" use case at 5% of the complexity.

### Web Dashboard

Do NOT build a web UI for experiment monitoring. Reasons:
- MLflow/W&B/Neptune already exist for this. GigaEvo should not compete with
  them on web UI. The CLI is the interface; the web is where you look at plots
  after they are generated.
- A web server introduces deployment, auth, ports, firewalls, CORS, and a
  JavaScript build step. None of this exists in the current stack.
- PR comments (GitHub) already serve as the "web view" of experiment status.

### Plugin Marketplace / Registry

Do NOT build a plugin registry or marketplace. Reasons:
- There are fewer than 5 users of GigaEvo. A marketplace is absurd at this scale.
- Discoverability is not a problem when the entire team fits in one room.
- entry_points-based plugin discovery is fine for future extensibility, but do not
  build infrastructure around it (no versioning, no compatibility checks, no download).

### Hot-Reload Plugin System

Do NOT implement hot-reload for plugins or anomaly rules. Reasons:
- Experiments run for days. Reloading code mid-experiment is a consistency hazard.
- The watchdog runs as a long-lived process; if you want new anomaly rules, restart
  the watchdog. This is a 5-second operation, not a deployment pipeline.
- Python's `importlib.reload()` is notoriously fragile with stateful modules.

### Slack Integration

Do NOT build Slack integration alongside Telegram. Reasons:
- The team uses Telegram. Supporting two notification backends doubles maintenance
  with zero user benefit.
- If the team ever migrates to Slack, refactor at that time. Do not pre-build for
  hypothetical futures.
- Generic webhook support (POST JSON to a URL) would cover Slack/Discord/etc. if
  needed later, without building specific integrations.

### Real-Time Streaming / WebSockets

Do NOT stream Redis metrics to clients via WebSocket. Reasons:
- Experiments produce one data point per evaluation (~1/min). Polling every 60s
  is perfectly adequate. WebSocket infrastructure for 1 event/min is overengineering.
- The watchdog already polls Redis on a 1-hour interval. Status checks are on-demand.

### Automatic Experiment Restart

Do NOT auto-restart crashed experiments without human approval. Reasons:
- A crash usually indicates a bug. Auto-restarting will reproduce the crash, waste
  GPU hours, and potentially corrupt Redis state.
- Supervisor-style autorestart makes sense for stateless web services, not for
  stateful evolutionary runs where Redis state is the ground truth.
- Alert on crash, let the researcher decide. The `gigaevo restart` command makes
  manual restart trivial.

### Multi-Server Orchestration

Do NOT build SSH-based remote execution into the CLI. Reasons:
- Experiments currently launch via `nohup` on the local machine or via SSH manually.
  Building a distributed executor (Ansible/Fabric-style) is a large investment.
- Tools like `tmux`, `screen`, `nohup`, and systemd already handle remote process
  management well enough.
- If multi-server orchestration becomes a real need, adopt an existing tool (Ray,
  Kubernetes, Slurm) rather than building a bespoke one.

---

## Complexity Assessment

| Feature | Complexity | Dependencies | Notes |
|---------|-----------|-------------|-------|
| Subcommand structure (Typer/Click) | Low | typer or click, rich | Wraps existing scripts; mostly argparse migration |
| `--json` output mode | Low | (none, use json stdlib) | Add `OutputFormat` enum, pass to each command |
| `--dry-run` on mutating commands | Low | (already exists on flush) | Extend pattern to archive, launch |
| Branch-aware experiment detection | Low | gitpython or subprocess git | Parse branch name, lookup experiment.yaml |
| `gigaevo status` (unified) | Low | redis, rich, pyyaml | Port existing status.py into CLI subcommand |
| `gigaevo trajectory` | Low | redis | Port existing trajectory.py |
| `gigaevo top` (top programs) | Low | redis | Port existing top_programs.py |
| `gigaevo logs` (log tailing) | Low | (none) | Read log_path from manifest, tail -f |
| `gigaevo plot comparison` | Low | matplotlib, scipy, pandas | Port existing comparison.py |
| `gigaevo plot trajectory` | Low | matplotlib | New but simple (gen-by-gen line chart) |
| `gigaevo run flush` | Low | redis | Port existing flush.py |
| `gigaevo run archive` | Medium | gh CLI, subprocess | Port archive_run.sh; shell-to-Python conversion |
| `gigaevo run preflight` | Low | redis, requests | Port existing preflight_check.py |
| `gigaevo run launch` | Medium | subprocess, manifest | Port generate_launch.py + execution |
| `gigaevo notify` (send message) | Low | requests | Port existing telegram_notify.py |
| `gigaevo checkpoint` (composite) | Medium | status + plot + notify + pr_comment | Orchestrates 4 existing tools in sequence |
| `gigaevo watch` (live dashboard) | Medium | rich (Live, Table, Sparkline) | New; Rich Live display with auto-refresh |
| Alert routing configuration | Medium | pyyaml | New config schema + dispatcher |
| Anomaly detector (pluggable rules) | Medium | (none) | Protocol + 4 built-in rules + file-based discovery |
| `gigaevo launch` (composite) | Medium | preflight + launch + record_pids | Orchestrates existing tools |
| `gigaevo closeout` (composite) | High | test_eval + archive + upload + results | Many steps, error handling, rollback |
| `gigaevo restart` (composite) | Medium | kill + flush + launch | Orchestrates existing tools |
| Config file (`~/.gigaevo.yaml`) | Low | pyyaml | Global defaults for redis, output format, alerts |
| Shell completion | Free | typer (auto) or click (manual) | Comes with framework choice |
| `gigaevo resources` (resource mgr) | Low | redis, ssh | Port existing resource_manager.py |

### Recommended Implementation Order

1. **Foundation** (week 1): Typer app skeleton, global flags (`--json`, `--quiet`, `--experiment`), branch detection, config resolution
2. **Core read-only commands** (week 1-2): `status`, `trajectory`, `top`, `logs`, `resources` — zero risk, immediate value
3. **Plotting** (week 2): `plot comparison`, `plot trajectory` — port existing matplotlib code
4. **Mutating commands** (week 2-3): `run flush`, `run archive`, `run preflight` — existing logic, new CLI skin
5. **Notifications** (week 3): `notify`, alert routing config
6. **Watch mode** (week 3): Rich Live dashboard
7. **Composite commands** (week 4): `checkpoint`, `launch`, `closeout`, `restart`
8. **Anomaly rules** (week 4): pluggable detector framework

### Framework Recommendation: Typer + Rich

- **Typer** over Click: type-annotation-driven, less boilerplate, auto-completion, built on Click (escape hatch to Click internals when needed)
- **Rich** for output: tables, sparklines, color, Live display, progress bars — already a transitive dependency via Typer
- Avoid adding Textual as a dependency (TUI anti-feature above)
- Keep matplotlib for plots (already in stack; no need for a terminal charting library)
