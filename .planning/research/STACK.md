# Stack Research: Unified GigaEvo CLI

> Researched: 2026-04-11
> Context: Brownfield — replacing 20+ argparse tool scripts + 4 click-based `gigaevo/cli/` modules with a single `gigaevo` CLI.
> Existing stack: Python 3.12+, Redis, Hydra, Pydantic v2, loguru, matplotlib, pytest, click (already a dependency), httpx (already a dependency), requests (used in telegram_notify.py only).

---

## CLI Framework

**Recommendation: Click 8.x (keep current) + rich-click for help rendering**

### Why Click, not Typer

Typer (latest: 0.24.1, Feb 2026) is the popular recommendation for greenfield projects. However, for GigaEvo the calculus is different:

1. **Click is already in use.** `gigaevo/cli/__init__.py` and all 4 subcommand modules (`status.py`, `plot.py`, `collect.py`, `analyze.py`) already use Click. The `pyproject.toml` lists `click` as a dependency. Switching to Typer means rewriting working code for no functional gain.

2. **Typer IS Click underneath.** Typer generates Click commands from type hints. Every Typer app is a Click app. You can always call `app.add_typer()` to embed Typer sub-apps into a Click group, and vice versa via `typer.main.get_command()`. Choosing Click does not lock you out of Typer in the future.

3. **Plugin/lazy-loading story is better in Click.** Click provides `Group.list_commands()` and `Group.get_command()` for lazy loading. The `click-plugins` package (stable, 1.1.1) discovers subcommands via setuptools entry_points. Typer's equivalent (`add_typer`) requires eager imports — lazy loading is a community workaround, not a first-class feature.

4. **The 20+ tool scripts use argparse.** Migration to Click is straightforward (decorator-based, same mental model). Migration to Typer requires more rewriting (type-hint driven, different patterns for callbacks/groups).

5. **Click 8.x is actively maintained** by the Pallets team (same as Flask, Jinja2, Werkzeug). Typer is maintained by a single author (tiangolo) who also maintains FastAPI, SQLModel, and many other projects.

6. **rich-click (latest: 1.9.7, Jan 2026)** adds Rich-formatted help text to Click commands as a drop-in. One import change, zero code rewrite. Typer's built-in Rich support (since 0.6.0) is similar but comes with the Typer migration tax.

### What about argparse?

Do not keep argparse for new code. It requires more boilerplate, has no built-in help theming, no plugin story, and no composability. The 20+ existing argparse scripts should migrate to Click subcommands incrementally.

### Decision

- Keep `click>=8.1` as the CLI framework.
- Add `rich-click>=1.8` for rich help text (zero-code upgrade path: `import rich_click as click`).
- Migrate argparse tool scripts into Click subcommands under the existing `gigaevo` entry point.
- If a future contributor prefers Typer for a new sub-app, they can use `typer.main.get_command()` to register it as a Click command — the two are interoperable.

---

## Plugin System

**Recommendation: Click's lazy Group + `importlib.metadata.entry_points` (stdlib). No pluggy. No stevedore.**

### Why not pluggy?

Pluggy (latest: 1.6.0) is the gold standard for hook-based plugin systems (used by pytest, tox, devpi). It shines when:
- Plugins need to intercept/modify host behavior at well-defined hook points.
- Multiple plugins can contribute to the same hook (firstresult, trylast, tryfirst).
- The plugin API is complex with many extension points.

GigaEvo's CLI does not need any of this. The plugin requirement is simpler: **discover and register subcommand groups at startup**. This is a discovery problem, not a hook system problem. Adding pluggy introduces a new dependency and a new abstraction layer for something that `importlib.metadata.entry_points` + Click's `Group` already solve.

### Why not stevedore?

Stevedore (latest: 5.7.x, OpenStack) wraps `importlib.metadata.entry_points` with manager classes (DriverManager, HookManager, ExtensionManager). It is battle-tested in large OpenStack projects. However:
- It is an OpenStack project with OpenStack-grade complexity and release cadence.
- For CLI subcommand discovery, `importlib.metadata.entry_points` (stdlib since Python 3.9, backport via `importlib_metadata`) is sufficient.
- Stevedore pulls in `pbr` and other OpenStack packaging opinions.
- The project already has zero OpenStack dependencies; adding one for a 20-line plugin loader is not justified.

### Recommended architecture

```
# pyproject.toml
[project.entry-points."gigaevo.cli.plugins"]
# Built-in subcommand groups registered as plugins for symmetry:
status = "gigaevo.cli.status:status"
plot = "gigaevo.cli.plot:plot"
collect = "gigaevo.cli.collect:collect"
analyze = "gigaevo.cli.analyze:analyze"
# Future external plugins just add their own entry_point
```

```python
# gigaevo/cli/__init__.py
import importlib.metadata
import click

class PluginGroup(click.Group):
    """Lazy-loading CLI group that discovers subcommands from entry_points."""

    def list_commands(self, ctx):
        eps = importlib.metadata.entry_points(group="gigaevo.cli.plugins")
        return sorted(ep.name for ep in eps)

    def get_command(self, ctx, cmd_name):
        eps = importlib.metadata.entry_points(group="gigaevo.cli.plugins", name=cmd_name)
        for ep in eps:
            return ep.load()
        return None

@click.group(cls=PluginGroup)
def main():
    """GigaEvo CLI -- evolution experiment tools."""
```

This gives:
- **Lazy loading**: subcommand modules are imported only when invoked (fast startup).
- **Plugin discovery**: any pip-installed package can register a `gigaevo.cli.plugins` entry point.
- **Zero new dependencies**: uses only stdlib `importlib.metadata`.
- **Graceful degradation**: wrap `ep.load()` in try/except to convert broken plugins to error messages (same pattern as `click-plugins.BrokenCommand`).

### If you need hooks later

If future requirements need hook-based extension (e.g., "all plugins run a pre-launch check"), add pluggy at that point. The entry_point discovery mechanism is compatible with pluggy's `load_setuptools_entrypoints()`.

---

## Notification Layer

**Recommendation: httpx (already a dependency) for Telegram. `gh` CLI for GitHub PR comments.**

### Telegram: httpx, not python-telegram-bot or aiogram

The existing `tools/telegram_notify.py` uses `requests` (synchronous) for Telegram Bot API. The project already depends on `httpx>=0.27.0` (used by OpenAI SDK, LiteLLM, etc.). The notification needs are narrow:

| Operation | Telegram API endpoint | Complexity |
|---|---|---|
| Send text message | `POST /bot{token}/sendMessage` | 5 lines |
| Send photo | `POST /bot{token}/sendPhoto` | 8 lines |
| Poll for reply | `GET /bot{token}/getUpdates` | 15 lines |

This does not justify a full Telegram framework:

- **python-telegram-bot** (v22.7): Full async framework with Application, Handlers, ConversationHandler, JobQueue. Massive API surface for what amounts to 3 HTTP calls. Pulls in tornado/APScheduler.
- **aiogram** (v3.27): Modern async framework, FSM support, middleware, routers. Even more abstraction. Requires aiohttp as transport.
- **httpx**: Already installed. Supports both sync and async. Direct API calls are explicit, testable, and debuggable. No framework lock-in.

### Migration path

Replace `requests.post(...)` in `telegram_notify.py` with `httpx.post(...)`. The API is nearly identical. Then remove `requests` from dependencies (it is only used in this one file).

For async contexts (watchdog, long-running monitoring), use `httpx.AsyncClient` — the project already uses asyncio extensively.

### GitHub PR comments

The existing `tools/experiment/pr_comment.py` should use `subprocess.run(["gh", "pr", "comment", ...])` (already available on the server). Do not add PyGithub or ghapi as dependencies — the `gh` CLI handles auth, pagination, and API versioning.

For programmatic use within Python (e.g., posting structured checkpoint data), `httpx` + GitHub REST API with `GITHUB_TOKEN` env var is acceptable as a fallback.

---

## Terminal Output

**Recommendation: Rich 14.x (add as dependency)**

### Why Rich

Rich (latest: 14.2.0, Jan 2026) is the de facto standard for Python terminal output. 50k+ GitHub stars, actively maintained by Textualize (Will McGugan). It provides:

- **Tables**: `rich.table.Table` with auto-sizing, word wrapping, column alignment, styles. Replaces the manual `printf`-style formatting in `status.py` and `trajectory.py`.
- **JSON**: `console.print_json()` for pretty-printed, syntax-highlighted JSON output.
- **Progress bars**: `rich.progress.Progress` for long-running operations (Redis export, archiving).
- **Panels and Trees**: For lineage traces and hierarchical experiment views.
- **Markdown**: `rich.markdown.Markdown` for rendering experiment reports inline.
- **Console recording**: `console.export_text()` / `console.export_svg()` for capturing output to files.
- **Logging integration**: `rich.logging.RichHandler` integrates with loguru's standard logging bridge.

### Why not Textual

Textual (also by Textualize) is a TUI framework for full-screen terminal applications. GigaEvo's CLI is a command-execute-exit tool, not an interactive TUI. Textual would be overkill and would complicate testing.

### Why not tabulate

`tabulate` is simpler but limited: no styling, no color, no JSON mode, no progress bars, no composability. Since Rich is needed anyway (for rich-click, for JSON output, for progress), using tabulate alongside it adds a redundant dependency.

### Integration with rich-click

Adding Rich as a dependency also enables `rich-click` (which depends on Rich). One dependency addition enables both rich help text and rich output formatting.

---

## Structured Output

**Recommendation: `--format` flag with enum {table, json, markdown, csv}. Implemented via a thin OutputFormatter abstraction over Rich.**

### The pattern

Modern CLI tools (gh, kubectl, docker, aws-cli) support structured output modes. The standard pattern:

```
gigaevo status --run foo@0:A --format json    # machine-readable
gigaevo status --run foo@0:A --format table   # human-readable (default)
gigaevo status --run foo@0:A --format csv     # spreadsheet/piping
gigaevo status --run foo@0:A --format markdown # for PR comments / docs
```

### Implementation approach

```python
from enum import Enum

class OutputFormat(str, Enum):
    TABLE = "table"
    JSON = "json"
    CSV = "csv"
    MARKDOWN = "markdown"

class OutputFormatter:
    """Renders structured data in the requested format."""

    def __init__(self, fmt: OutputFormat, file=None):
        self.fmt = fmt
        self.console = Console(file=file)

    def render(self, data: list[dict], *, title: str = ""):
        match self.fmt:
            case OutputFormat.TABLE:
                table = Table(title=title)
                for key in data[0]:
                    table.add_column(key)
                for row in data:
                    table.add_row(*[str(v) for v in row.values()])
                self.console.print(table)
            case OutputFormat.JSON:
                self.console.print_json(data=data)
            case OutputFormat.CSV:
                import csv, io
                buf = io.StringIO()
                writer = csv.DictWriter(buf, fieldnames=data[0].keys())
                writer.writeheader()
                writer.writerows(data)
                print(buf.getvalue(), end="")
            case OutputFormat.MARKDOWN:
                # Render as GFM table
                headers = list(data[0].keys())
                lines = ["| " + " | ".join(headers) + " |"]
                lines.append("| " + " | ".join("---" for _ in headers) + " |")
                for row in data:
                    lines.append("| " + " | ".join(str(row[h]) for h in headers) + " |")
                print("\n".join(lines))
```

### Key design decisions

1. **Default is `table`** (human-friendly). Scripts and pipelines explicitly request `json` or `csv`.
2. **JSON mode disables Rich styling** to ensure valid, parseable JSON on stdout. Use `Console(highlight=False)` or direct `json.dumps()`.
3. **Markdown mode** exists specifically for PR comment generation (used by `pr_comment.py` and watchdog).
4. **CSV mode** replaces the separate `redis2pd.py --frontier-csv` pattern with a built-in output mode.
5. **The `--format` flag is added once** as a Click `@click.option` on the group or as a shared decorator — not re-implemented per subcommand.

### Detecting pipe vs terminal

```python
import sys
# Auto-switch to JSON when stdout is piped (unless --format is explicit)
if not sys.stdout.isatty() and format_not_explicitly_set:
    fmt = OutputFormat.JSON
```

This follows the `gh` CLI convention: rich output for humans, structured output for machines.

---

## Recommendations Summary

| Component | Choice | Version | Rationale |
|---|---|---|---|
| CLI Framework | **Click** | `>=8.1` | Already in use, mature plugin story, lazy loading, Pallets-maintained |
| Help Rendering | **rich-click** | `>=1.8` | Drop-in Rich help for Click, zero code change |
| Plugin Discovery | **importlib.metadata** | stdlib | Zero deps, entry_points + lazy Group, extensible |
| Telegram Notifications | **httpx** | `>=0.27` (already dep) | Already installed, sync+async, 3 API calls don't need a framework |
| GitHub PR Comments | **gh CLI** | system | Already available, handles auth/pagination |
| Terminal Output | **Rich** | `>=14.0` | Tables, JSON, progress, markdown, logging — one library covers all |
| Structured Output | **OutputFormatter** | custom (thin) | `--format {table,json,csv,markdown}` over Rich primitives |
| Test Framework | **pytest** | `>=8.0` (already dep) | No change needed |

### New dependencies to add

| Package | Why |
|---|---|
| `rich>=14.0` | Terminal output (tables, JSON, progress, panels, markdown) |
| `rich-click>=1.8` | Rich-formatted help text for Click commands |

### Dependencies to remove

| Package | Why |
|---|---|
| `requests` | Only used in `telegram_notify.py`; replace with `httpx` (already a dep) |

---

## What NOT to Use

### Typer (for this project)
Typer is excellent for greenfield projects but wrong for GigaEvo. The project already has Click-based CLI code and 20+ argparse scripts. Migrating to Typer provides no functional benefit over Click (since Typer IS Click) while requiring rewrites. The plugin/lazy-loading story is weaker. If a future contributor wants Typer for a new sub-app, it can be registered into the Click group via `typer.main.get_command()`.

### pluggy (for now)
Pluggy is the right tool when you need hook-based extension points (pytest model). GigaEvo needs subcommand discovery, not hook interception. `importlib.metadata.entry_points` solves this in ~20 lines. If hook-based extension is needed later, pluggy can be added incrementally.

### stevedore
OpenStack-grade plugin management. Wraps `importlib.metadata.entry_points` with manager classes, but pulls in `pbr` and OpenStack packaging conventions. Overkill for CLI subcommand discovery.

### python-telegram-bot / aiogram
Full Telegram bot frameworks with handler systems, FSMs, middleware, and job queues. GigaEvo makes 3 types of HTTP calls to Telegram (send text, send photo, poll updates). A framework adds complexity, dependencies, and abstraction for no gain.

### requests
Already used in `telegram_notify.py`, but `httpx` is already a project dependency with a nearly identical API. Having both is redundant. Migrate and remove.

### tabulate
Simple table formatter, but Rich provides tables plus JSON, progress, markdown, panels, trees, and logging. Using tabulate alongside Rich is redundant.

### Textual
Full-screen TUI framework from Textualize. GigaEvo's CLI is command-execute-exit, not interactive. Textual would complicate testing and add unnecessary complexity.

### argparse (for new code)
No composability, no plugin story, no help theming, more boilerplate. Existing scripts should migrate to Click incrementally; no new argparse code should be written.

---

## Migration Strategy (Brief)

1. **Phase 0**: Add `rich` and `rich-click` to `pyproject.toml`. Change `gigaevo/cli/__init__.py` to use `import rich_click as click`. Instant rich help text, zero breakage.
2. **Phase 1**: Implement `PluginGroup` with entry_points. Register existing 4 subcommands as entry_points. Verify lazy loading.
3. **Phase 2**: Add `OutputFormatter` with `--format` flag. Apply to `status` subcommand first as proof of concept.
4. **Phase 3**: Migrate high-value argparse tools (`status.py`, `trajectory.py`, `top_programs.py`, `comparison.py`) into Click subcommands.
5. **Phase 4**: Replace `requests` with `httpx` in `telegram_notify.py`. Add notification subcommand (`gigaevo notify`).
6. **Phase 5**: Migrate remaining argparse tools. Deprecate direct `python tools/X.py` invocation.
