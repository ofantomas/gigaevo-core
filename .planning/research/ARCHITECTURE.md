# Architecture Research: Unified CLI + Plugin-Based Monitoring

## Problem Statement

GigaEvo has 29 watchdog files totaling 14,356 lines of nearly identical code, 20+ standalone tool scripts in `tools/`, and an embryonic Click CLI in `gigaevo/cli/` with 4 subcommands. The goal is to consolidate into a unified `gigaevo` CLI with a generic, plugin-based watchdog that works across experiment types (solo, adversarial pairs, prompt co-evolution) with dual-channel notifications (Telegram + GitHub PR).

## Current State Inventory

| Component | Location | Status |
|---|---|---|
| CLI entry point | `gigaevo/cli/__init__.py` | Exists: Click group with `status`, `collect`, `plot`, `analyze` |
| Console script | `pyproject.toml` `[project.scripts]` | Registered: `gigaevo = "gigaevo.cli:main"` |
| Standalone tools | `tools/*.py` (20+ files) | Standalone argparse scripts, not integrated |
| Watchdog template | `experiments/_template/run_watchdog.py` | 566 lines, copy-pasted 29 times |
| Adversarial watchdog | `experiments/adversarial/optimizer-coevo/run_watchdog.py` | Custom: arms-race plot pairs |
| Heilbron watchdog | `experiments/heilbron/adversarial-dynamic-updates/run_watchdog.py` | Most divergent: 2x2 cell structure, 3-panel plot, Telegram photos |
| Telegram notify | `tools/telegram_notify.py` | Library (not CLI): `notify()`, `send_photo()`, `wait_for_approval()` |
| GitHub PR posting | Inline in every watchdog | Duplicated: `post_or_edit_pr_comment()`, `upload_plot_to_github()` |
| Redis metrics access | `gigaevo/utils/redis.py`, `tools/utils.py`, inline in watchdogs | 3 competing implementations |
| Experiment manifest | `tools/experiment/manifest.py` | Well-structured: `ExperimentManifest` dataclass, state machine |

### Watchdog Variation Analysis

Across 29 watchdog files, the variation points are:

1. **Plot generation** -- the only truly experiment-specific code
   - Template: `comparison.py` + optional `throughput_plot.py` (subprocess call)
   - Adversarial: `plot_arms_race.py` with pair structure
   - Heilbron: Custom 2x2 matplotlib with 3 metric panels + summary table
2. **Plot upload strategy** -- GitHub Contents API vs GitHub Release assets vs git commit+push
3. **Notification channels** -- PR-only (most) vs PR+Telegram (heilbron)
4. **Metric extraction** -- frontier fitness (most) vs per-gen mean series (heilbron)
5. **Experiment-specific state** -- cell structures, pair specs, extra metrics

Everything else (Redis queries, heartbeat, checkpoint, SIGTERM handler, completion detection, rolling comment, main loop, retry logic) is identical.

---

## Component Structure

```
gigaevo/
  cli/
    __init__.py          # Click group: `gigaevo` (exists)
    status.py            # `gigaevo status` (exists)
    collect.py           # `gigaevo collect` (exists)
    plot.py              # `gigaevo plot` (exists)
    analyze.py           # `gigaevo analyze` (exists)
    watchdog.py          # NEW: `gigaevo watchdog --experiment task/name`
    flush.py             # NEW: absorb tools/flush.py
    archive.py           # NEW: absorb tools/experiment/archive_run.sh logic
    trajectory.py        # NEW: absorb tools/trajectory.py
    top_programs.py      # NEW: absorb tools/top_programs.py
    comparison.py        # NEW: absorb tools/comparison.py

  monitoring/                    # NEW: shared monitoring library
    __init__.py
    redis_queries.py             # Canonical Redis access (deduplicate 3 implementations)
    snapshot.py                  # RunSnapshot: frozen state of one run at a point in time
    experiment_monitor.py        # ExperimentMonitor: collect snapshots for all runs
    alerts.py                    # Alert detection (stall, high invalidity, model drift, completion)

  monitoring/watchdog/           # NEW: generic watchdog engine
    __init__.py
    engine.py                    # WatchdogEngine: main loop, heartbeat, SIGTERM, retry
    config.py                    # WatchdogConfig dataclass
    plugins/                     # Experiment-type plugins
      __init__.py
      base.py                    # WatchdogPlugin ABC
      registry.py                # Plugin discovery and loading
      solo.py                    # SoloPlugin: standard comparison.py plots
      adversarial.py             # AdversarialPlugin: arms-race pair plots
      heilbron.py                # HeilbronPlugin: 2x2 panel plots + Telegram photos
      prompt_coevo.py            # PromptCoevoPlugin: prompt evolution specific

  monitoring/notifications/      # NEW: multi-channel notification
    __init__.py
    channel.py                   # NotificationChannel ABC
    message.py                   # StatusMessage / AlertMessage dataclasses
    github_pr.py                 # GitHubPRChannel: post/edit PR comments
    telegram.py                  # TelegramChannel: text + photo messages
    dispatcher.py                # Dispatcher: fan-out to all registered channels
    formatters/
      __init__.py
      markdown.py                # GitHub-flavored markdown renderer
      telegram_md.py             # Telegram markdown renderer
```

---

## Plugin Discovery Pattern

### Recommendation: Explicit Registry with ABC (not `entry_points`)

**Why not `entry_points`?** Entry points are the standard Python packaging mechanism for plugin discovery (used by pytest, tox, flake8, etc.), but they require `pip install -e .` to register and are designed for _third-party_ extensibility. GigaEvo's plugins are all first-party, experiment-type-specific, and change frequently during research. The overhead of managing `entry_points` metadata is not justified.

**Why not filename-based auto-discovery?** Scanning a plugins directory with `importlib` (like Django management commands) works but is fragile: files can be imported with side effects, and the mapping from experiment type to plugin becomes implicit.

**Recommended: Explicit registry + Abstract Base Class.**

```python
# gigaevo/monitoring/watchdog/plugins/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from gigaevo.monitoring.snapshot import RunSnapshot


@dataclass(frozen=True)
class WatchdogCycleContext:
    """Everything a plugin needs to render one watchdog cycle."""
    experiment_name: str
    hour: int
    max_gen: int
    run_snapshots: list[RunSnapshot]
    manifest: "ExperimentManifest"
    plot_dir: Path


class WatchdogPlugin(ABC):
    """Extension point for experiment-type-specific watchdog behavior.

    Plugins control:
    1. What plots to generate (and how)
    2. What extra metrics to extract from Redis
    3. How to format the status message body
    4. What Telegram content to send (text-only, photos, etc.)
    """

    @abstractmethod
    def generate_plots(self, ctx: WatchdogCycleContext) -> list[Path]:
        """Generate experiment-specific plots. Return list of PNG paths."""
        ...

    @abstractmethod
    def format_status_body(
        self, ctx: WatchdogCycleContext, plot_urls: list[str]
    ) -> str:
        """Render the PR comment body as markdown."""
        ...

    def extra_telegram_content(
        self, ctx: WatchdogCycleContext, plot_paths: list[Path]
    ) -> list[tuple[Path, str]]:
        """Return (image_path, caption) pairs for Telegram photos.
        Default: no photos (just the PR comment text)."""
        return []

    def extra_redis_queries(
        self, ctx: WatchdogCycleContext
    ) -> dict[str, object]:
        """Return extra experiment-specific data to attach to snapshots.
        Default: empty."""
        return {}
```

```python
# gigaevo/monitoring/watchdog/plugins/registry.py
from gigaevo.monitoring.watchdog.plugins.base import WatchdogPlugin

_REGISTRY: dict[str, type[WatchdogPlugin]] = {}


def register(name: str):
    """Decorator to register a plugin class."""
    def decorator(cls: type[WatchdogPlugin]):
        _REGISTRY[name] = cls
        return cls
    return decorator


def get_plugin(experiment_name: str, manifest) -> WatchdogPlugin:
    """Resolve plugin for an experiment.

    Resolution order:
    1. manifest.watchdog_plugin field (explicit override)
    2. Task prefix heuristic (heilbron/* -> heilbron, adversarial/* -> adversarial)
    3. Fallback: "solo" (standard single-population experiments)
    """
    # 1. Explicit override in experiment.yaml
    plugin_name = getattr(manifest, "watchdog_plugin", None)

    # 2. Task-based heuristic
    if not plugin_name:
        task = experiment_name.split("/")[0]
        if task in _REGISTRY:
            plugin_name = task
        else:
            plugin_name = "solo"

    cls = _REGISTRY.get(plugin_name)
    if cls is None:
        raise ValueError(
            f"Unknown watchdog plugin '{plugin_name}'. "
            f"Available: {sorted(_REGISTRY.keys())}"
        )
    return cls(manifest)
```

**Why this approach:**

1. **Explicit is better than implicit.** Each plugin is a decorated class -- you can grep for `@register("solo")` to find it.
2. **No packaging overhead.** No `pip install` dance, no `pyproject.toml` edits.
3. **ABC enforces the contract.** Missing methods are caught at import time, not at 3 AM when the watchdog crashes.
4. **Resolution chain** allows both convention (task prefix) and explicit override (manifest field), covering new experiment types without code changes to the registry.
5. **Frozen context object** prevents plugins from accidentally mutating shared state.

### Pattern precedent

This is the same pattern used by:
- **Flask blueprints** (explicit `app.register_blueprint()`)
- **SQLAlchemy dialects** (registry + ABC)
- **Airflow operators** (registry decorators)
- **Terraform providers** (schema interface + registry)

---

## Notification Channel Pattern

### Recommendation: Strategy Pattern with Dispatcher (fan-out)

The notification system has two orthogonal concerns:

1. **Message creation** -- what to say (experiment-specific, driven by plugins)
2. **Message delivery** -- where to say it (GitHub PR, Telegram, future: Slack, email)

**Pattern: Channel abstraction (strategy) + Dispatcher (composite).**

```python
# gigaevo/monitoring/notifications/channel.py
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class StatusUpdate:
    """Channel-agnostic status update."""
    experiment_name: str
    hour: int
    markdown_body: str           # Full markdown (for GitHub)
    summary_text: str            # One-line summary (for Telegram text)
    plot_paths: list[Path]       # Local PNG paths
    plot_urls: list[str]         # Remote URLs (after upload)
    is_completion: bool
    alerts: list[str]


class NotificationChannel(ABC):
    """Delivers status updates to a specific destination."""

    @abstractmethod
    def send_status(self, update: StatusUpdate) -> bool:
        """Send a status update. Returns True on success."""
        ...

    @abstractmethod
    def send_alert(self, experiment_name: str, alert_text: str) -> bool:
        """Send an alert. Returns True on success."""
        ...

    def is_available(self) -> bool:
        """Check if this channel is configured and reachable."""
        return True
```

```python
# gigaevo/monitoring/notifications/dispatcher.py
class NotificationDispatcher:
    """Fan-out to all registered channels. Never fails -- logs errors."""

    def __init__(self, channels: list[NotificationChannel]):
        self._channels = channels

    def send_status(self, update: StatusUpdate) -> dict[str, bool]:
        results = {}
        for ch in self._channels:
            name = type(ch).__name__
            try:
                if ch.is_available():
                    results[name] = ch.send_status(update)
                else:
                    results[name] = False
            except Exception as e:
                log(f"Channel {name} failed: {e}")
                results[name] = False
        return results
```

**Why not an event bus / pub-sub?** An event bus (like `blinker` or `pyee`) adds indirection without benefit here. The watchdog has exactly one producer (the main loop) and a fixed set of consumers (channels). A simple list of channels with fan-out is easier to debug and test.

**Why not observer pattern?** Observer is structurally equivalent but implies event-driven / push semantics. The watchdog is poll-based: it collects state, renders, then pushes to channels in a synchronous loop. Strategy + Dispatcher maps more naturally.

### Channel implementations

```python
# gigaevo/monitoring/notifications/github_pr.py
@dataclass
class GitHubPRConfig:
    repo: str
    pr_number: int
    branch: str
    upload_strategy: Literal["contents_api", "release_asset", "git_push"]

class GitHubPRChannel(NotificationChannel):
    """Posts/edits PR comments with embedded plot images."""
    # Absorbs: _get_token, _get_rolling_comment_id, _set_rolling_comment_id,
    #          post_or_edit_pr_comment, upload_plot_to_github
    # Currently duplicated across all 29 watchdogs
```

```python
# gigaevo/monitoring/notifications/telegram.py
class TelegramChannel(NotificationChannel):
    """Wraps tools/telegram_notify.py into the channel interface."""
    # Absorbs: telegram_notify.notify, telegram_notify.send_photo
    # Adds: format_status_for_telegram (shorter, phone-friendly)
```

---

## Shared Library Structure

### Recommendation: Single `gigaevo.monitoring` Package

**Why not a separate package?** The monitoring code is tightly coupled to GigaEvo's Redis schema, manifest format, and metrics conventions. A separate package would need to import from `gigaevo` anyway, creating a circular dependency or forcing interface duplication.

**Why not `tools/` as a package?** The `tools/` directory is a loose collection of scripts with `PYTHONPATH=.` invocation. Converting it to a proper package would break every existing launch script and watchdog. Better to build new in `gigaevo/monitoring/` and migrate tools gradually.

**Structure:**

```
gigaevo/monitoring/
    __init__.py
    redis_queries.py         # Deduplicated Redis access
    snapshot.py              # RunSnapshot: frozen state of one run
    experiment_monitor.py    # ExperimentMonitor: collect snapshots for all runs
    alerts.py                # Alert detection logic

    watchdog/
        __init__.py
        engine.py            # WatchdogEngine: main loop
        config.py            # WatchdogConfig
        plugins/             # (see Plugin Discovery section)

    notifications/
        __init__.py
        channel.py           # NotificationChannel ABC
        message.py           # StatusUpdate, AlertMessage
        github_pr.py         # GitHub PR channel
        telegram.py          # Telegram channel
        dispatcher.py        # Fan-out dispatcher
        formatters/
            markdown.py      # GitHub markdown renderer
            telegram_md.py   # Telegram-friendly renderer
```

### Deduplication Targets

The following functions exist in 2-3 copies each. The `gigaevo.monitoring.redis_queries` module absorbs them all:

| Function | Currently in | Copies |
|---|---|---|
| `get_generation(db, prefix)` | 29 watchdogs + `tools/status.py` | 30 |
| `get_val_fitness(db, prefix)` | 29 watchdogs | 29 |
| `check_invalidity(db, prefix)` | 29 watchdogs | 29 |
| `check_model_identity(url, model)` | 29 watchdogs | 29 |
| `_get_token()` | 29 watchdogs | 29 |
| `post_or_edit_pr_comment()` | 29 watchdogs | 29 |
| `write_redis_heartbeat()` | 29 watchdogs | 29 |
| `write_redis_checkpoint()` | 29 watchdogs | 29 |
| `_load_metrics_yaml()` | `tools/status.py` + `gigaevo/cli/status.py` + `gigaevo/cli/plot.py` + `gigaevo/cli/collect.py` + `gigaevo/cli/analyze.py` | 5 |

---

## Data Flow

```
                    ┌─────────────────────────────────────────────────┐
                    │               Experiment Manifest               │
                    │         (experiments/task/name/experiment.yaml)  │
                    └────────────────────┬────────────────────────────┘
                                         │
                                         ▼
              ┌──────────────────────────────────────────────┐
              │            WatchdogEngine.main_loop()        │
              │  1. write_heartbeat()                        │
              │  2. refresh_db_claims()                      │
              │  3. sleep(POLL_INTERVAL)                     │
              └────────────┬─────────────────────────────────┘
                           │
                           ▼
              ┌──────────────────────────────────────────────┐
              │         ExperimentMonitor.collect()          │
              │  For each run in manifest.runs:              │
              │    redis_queries.get_generation()            │
              │    redis_queries.get_frontier_metrics()      │
              │    redis_queries.get_invalidity()            │
              │    plugin.extra_redis_queries()              │
              │  → list[RunSnapshot]                         │
              └────────────┬─────────────────────────────────┘
                           │
                           ▼
              ┌──────────────────────────────────────────────┐
              │           AlertDetector.check()              │
              │  stall_detection(snapshots, last_gen)        │
              │  high_invalidity(snapshots)                  │
              │  model_drift(manifest.runs)                  │
              │  completion(snapshots, max_gen)               │
              │  → list[Alert]                               │
              └────────────┬─────────────────────────────────┘
                           │
                           ▼
              ┌──────────────────────────────────────────────┐
              │        WatchdogPlugin (experiment-specific)  │
              │  generate_plots(ctx) → list[Path]            │
              │  format_status_body(ctx, urls) → str         │
              │  extra_telegram_content(ctx) → [(Path, str)] │
              └────────────┬─────────────────────────────────┘
                           │
                           ▼
              ┌──────────────────────────────────────────────┐
              │        NotificationDispatcher.send()         │
              │                                              │
              │  ┌─────────────┐    ┌──────────────────┐     │
              │  │ GitHubPR    │    │ Telegram          │    │
              │  │ Channel     │    │ Channel           │    │
              │  │             │    │                   │    │
              │  │ upload_plot │    │ send_photo()      │    │
              │  │ post_comment│    │ notify()          │    │
              │  └─────────────┘    └──────────────────┘    │
              └──────────────────────────────────────────────┘
```

### Detailed Data Flow (one cycle)

1. **WatchdogEngine** wakes up from `time.sleep(POLL_INTERVAL)`.
2. **WatchdogEngine** calls `ExperimentMonitor.collect(manifest)` which:
   a. Opens Redis connections to each run's DB.
   b. Reads generation count, frontier metrics, invalidity rate, validator duration.
   c. Calls `plugin.extra_redis_queries()` for experiment-specific metrics.
   d. Returns `list[RunSnapshot]` -- immutable frozen dataclasses.
3. **WatchdogEngine** passes snapshots to `AlertDetector.check()` which returns `list[Alert]`.
4. **WatchdogEngine** builds `WatchdogCycleContext` and calls `plugin.generate_plots(ctx)` which returns `list[Path]` of local PNGs.
5. **WatchdogEngine** calls `plugin.format_status_body(ctx, plot_urls=[])` to get the markdown body.
6. **WatchdogEngine** constructs a `StatusUpdate` message object with body, plot paths, alerts.
7. **NotificationDispatcher** iterates channels:
   a. **GitHubPRChannel** uploads plots (via configured strategy), embeds URLs in markdown, posts/edits PR comment.
   b. **TelegramChannel** sends summary text and calls `plugin.extra_telegram_content()` for photos.
8. **WatchdogEngine** writes Redis checkpoint if at a milestone generation.
9. If `AlertDetector` flagged completion, engine signals completion and exits.

---

## Build Order

### Phase 1: Shared Monitoring Library (`gigaevo.monitoring`)

**Why first:** Every other component depends on this. The 30 copies of `get_generation()` and friends must be consolidated before the watchdog or CLI can import them.

**Deliverables:**
- `gigaevo/monitoring/redis_queries.py` -- canonical Redis access functions
- `gigaevo/monitoring/snapshot.py` -- `RunSnapshot` frozen dataclass
- `gigaevo/monitoring/experiment_monitor.py` -- `ExperimentMonitor.collect()` method
- `gigaevo/monitoring/alerts.py` -- `AlertDetector.check()` method
- Tests for all of the above (using fakeredis)

**Migration:** `gigaevo/cli/status.py` and `gigaevo/cli/collect.py` can immediately import from `gigaevo.monitoring.redis_queries` instead of duplicating Redis access code.

### Phase 2: Notification Channel Abstraction (`gigaevo.monitoring.notifications`)

**Why second:** The watchdog engine needs channels to deliver messages. Building channels before the watchdog engine lets us test them independently.

**Deliverables:**
- `NotificationChannel` ABC
- `StatusUpdate` and `AlertMessage` dataclasses
- `GitHubPRChannel` -- absorbs `_get_token`, `post_or_edit_pr_comment`, `upload_plot_to_github` (all 3 upload strategies)
- `TelegramChannel` -- wraps `tools/telegram_notify.py`
- `NotificationDispatcher` -- fan-out with error isolation
- Markdown formatters (GitHub + Telegram)
- Tests (mock HTTP for GitHub API, mock for Telegram API)

### Phase 3: Watchdog Plugin System (`gigaevo.monitoring.watchdog`)

**Why third:** Requires Phase 1 (monitoring lib) and Phase 2 (channels).

**Deliverables:**
- `WatchdogPlugin` ABC
- Plugin registry with `@register` decorator
- `WatchdogEngine` -- main loop, heartbeat, SIGTERM, retry, completion detection
- `WatchdogConfig` dataclass
- `SoloPlugin` -- standard comparison.py plots (covers ~80% of experiments)
- Tests for engine (mock plugins, mock channels, fakeredis)

### Phase 4: Experiment-Specific Plugins

**Why fourth:** Now that the plugin system exists, migrate the divergent watchdog logic.

**Deliverables:**
- `AdversarialPlugin` -- arms-race pair plots
- `HeilbronPlugin` -- 2x2 panel plots + Telegram photo captions
- `PromptCoevoPlugin` -- prompt evolution metrics
- Add `watchdog_plugin` field to `ExperimentManifest` schema
- Tests for each plugin

### Phase 5: CLI Integration (`gigaevo watchdog`)

**Why fifth:** Everything is now tested as a library. The CLI subcommand is a thin Click wrapper.

**Deliverables:**
- `gigaevo/cli/watchdog.py` -- `gigaevo watchdog --experiment task/name [--poll-interval 3600]`
- Register in `gigaevo/cli/__init__.py`
- Update `experiments/_template/run_watchdog.py` to be a 5-line shim:
  ```python
  #!/usr/bin/env python3
  """Watchdog shim -- delegates to gigaevo watchdog engine."""
  from gigaevo.cli.watchdog import run_watchdog
  run_watchdog("task/name")  # ONLY MANUAL EDIT
  ```

### Phase 6: Absorb Remaining Tools

**Why last:** Lower priority, can be done incrementally.

**Deliverables:**
- `gigaevo flush --db N [N ...]` (absorb `tools/flush.py`)
- `gigaevo trajectory --run prefix@db:label` (absorb `tools/trajectory.py`)
- `gigaevo top --run prefix@db:label` (absorb `tools/top_programs.py`)
- `gigaevo compare --run ... --run ...` (absorb `tools/comparison.py`)
- `gigaevo archive --experiment task/name` (absorb `tools/experiment/archive_run.sh`)
- Keep `tools/` scripts as thin shims that import from `gigaevo.cli` for backward compat

---

## Integration Points with Existing Code

### 1. `tools/experiment/manifest.py` (no changes needed)

The `ExperimentManifest` dataclass is already the single source of truth for experiment configuration. The watchdog engine will import `load_manifest()` directly. The only addition is a new optional field `watchdog_plugin: str | None` for explicit plugin override.

### 2. `gigaevo/cli/__init__.py` (additive only)

The existing Click group just gets more `add_command()` calls. No changes to existing subcommands.

### 3. `tools/telegram_notify.py` (wrapped, not replaced)

The `TelegramChannel` wraps `notify()` and `send_photo()` from this module. The module continues to work standalone for gate approvals (`wait_for_approval`), which are not part of the watchdog flow.

### 4. `tools/status.py` / `tools/comparison.py` / etc. (kept as shims)

Existing tool scripts are invoked by Claude Code skills, launch scripts, and user muscle memory. They stay as thin wrappers that import from the new library. Example:

```python
# tools/status.py (after migration)
"""Legacy shim -- delegates to gigaevo.monitoring."""
from gigaevo.monitoring.redis_queries import get_run_status
# ... argparse wrapper calling get_run_status()
```

### 5. `gigaevo/utils/redis.py` and `gigaevo/utils/metrics_tracker.py`

These are _framework-level_ Redis access (used by the evolution engine at runtime). The _monitoring-level_ Redis access in `gigaevo/monitoring/redis_queries.py` is read-only, connects to arbitrary DBs, and is used only by tooling. These two layers should remain separate -- they serve different trust boundaries and lifecycle stages.

### 6. `tools/experiment/generate_launch.py`

Currently generates a standalone `run_watchdog.py` per experiment. After Phase 5, it would generate the 5-line shim instead. This is a one-line template change.

### 7. `pyproject.toml`

No changes needed -- `gigaevo = "gigaevo.cli:main"` already points to the Click group. New subcommands are auto-registered via `add_command()`.

---

## Testing Strategy

| Component | Test approach |
|---|---|
| `redis_queries.py` | fakeredis: populate keys, assert correct values returned |
| `snapshot.py` | Unit: frozen dataclass construction |
| `experiment_monitor.py` | Integration: fakeredis + mock manifest |
| `alerts.py` | Unit: feed snapshots, assert correct alerts |
| `NotificationChannel` implementations | Unit: mock HTTP (responses lib or unittest.mock) |
| `NotificationDispatcher` | Unit: mock channels, verify fan-out and error isolation |
| `WatchdogPlugin` implementations | Integration: fakeredis → snapshots → plots (check PNG files exist) |
| `WatchdogEngine` | Integration: mock plugin + mock dispatcher + fakeredis, run 2-3 cycles |
| CLI commands | Smoke: `gigaevo watchdog --help`, `gigaevo status --help` |

---

## Risk Mitigation

| Risk | Mitigation |
|---|---|
| Breaking existing watchdogs mid-experiment | Keep all 29 watchdog files unchanged until their experiments complete. New experiments use the engine. |
| Plot rendering differences | Each plugin generates plots with its own matplotlib code (moved from watchdog, not rewritten). Visual diff testing optional. |
| Telegram API rate limiting | `TelegramChannel.is_available()` checks token presence. Dispatcher catches and logs failures. No retry loop -- next cycle will try again. |
| Redis connection overhead | `ExperimentMonitor` reuses one `redis.Redis` per DB per cycle (same as current watchdogs). |
| Plugin resolution ambiguity | Manifest field takes priority over heuristic. Explicit > implicit. |

---

## Summary

The core insight from analyzing the codebase is that **the watchdog variation is purely in plot generation and status formatting** -- the monitoring loop, Redis queries, GitHub/Telegram delivery, heartbeat, and completion detection are identical across all 29 files. The architecture exploits this by:

1. **Extracting the invariant** (monitoring loop, Redis access, notification delivery) into `gigaevo.monitoring`.
2. **Parameterizing the variant** (plots, formatting) via `WatchdogPlugin` ABC.
3. **Unifying delivery** via `NotificationChannel` strategy pattern with fan-out dispatcher.
4. **Building bottom-up** (shared lib -> channels -> engine -> plugins -> CLI) so each phase is independently testable and deployable.
