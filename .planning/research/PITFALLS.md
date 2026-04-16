# Pitfalls Research

Research on common pitfalls when building unified CLI tools, plugin-based monitoring systems, and multi-channel notification pipelines in Python. Each pitfall is grounded in patterns observed in production Python projects and calibrated against GigaEvo's specific codebase.

---

## CLI Migration Pitfalls

### P-CLI-01: Flag Explosion from Feature Parity

- **Risk**: Absorbing 20+ scripts means absorbing 20+ distinct flag sets. The unified CLI ends up with dozens of flags per subcommand, many overlapping or contradictory. Users can't remember which flags go with which subcommand. Tab-completion becomes useless.
- **Warning signs**: (1) Subcommand help output exceeds one terminal screen. (2) Multiple flags control the same underlying behavior with different names (e.g., `--output-folder` vs `--output-file` vs `--save-dir`). (3) Users consistently pass wrong flags to wrong subcommands.
- **Prevention**: Define a **flag taxonomy** before implementing any subcommand. Three tiers: global flags (every subcommand), scope flags (`--experiment`, `--run`), and subcommand-specific flags. GigaEvo already has a natural taxonomy: `--experiment task/name` for experiment-scoped ops, `--run prefix@db:label` for run-scoped ops. Enforce this by making scope flags a shared argument group, not per-subcommand definitions. Cap subcommand-specific flags at 5-7; anything beyond that is a sign the subcommand needs splitting.
- **Phase**: Phase 1 (CLI skeleton) -- define taxonomy as a design constraint before writing any `argparse`/`click` code.

### P-CLI-02: Breaking the Run Spec Parser (Again)

- **Risk**: GigaEvo has THREE independent implementations of `parse_run_arg` today: `status.py` returns `(prefix, db, label)`, `comparison.py` returns `RedisRunConfig`, `top_programs.py` returns `RedisRunConfig`. The `status.py` version strips quotes; the others don't. The `status.py` version uses `rfind("@")` to handle `@` in prefixes; the others use `split("@", 1)` which breaks if the prefix contains `@`. Consolidating these is necessary, but getting the consolidated parser wrong breaks every tool at once.
- **Warning signs**: (1) Tests pass but real user input fails (shell quoting, spaces, special chars in prefix paths). (2) Edge cases like `chains/hover/static@6:label` vs `chains/hover/static@6` handled differently. (3) Error messages say "format must be prefix@db[:label]" but don't show what was actually received.
- **Prevention**: Write the canonical parser FIRST with exhaustive property-based tests (hypothesis). Cover: prefixes with `/`, prefixes with no label, labels with special chars, quoted strings, whitespace, empty strings, non-numeric db. Make it return a proper dataclass (like `RedisRunConfig` but with the quote-stripping from `status.py`). Replace all three implementations in one commit with zero behavioral change.
- **Phase**: Phase 1 (CLI skeleton) -- the run spec parser is the foundation everything else builds on.

### P-CLI-03: Entrypoint Performance Penalty

- **Risk**: A unified CLI that imports everything at module level pays the import tax for every invocation. `matplotlib` alone takes 300-500ms to import. If `gigaevo status` imports the plotting stack, or `gigaevo flush` imports pandas, the CLI feels sluggish for simple operations.
- **Warning signs**: (1) `time gigaevo --help` takes > 500ms. (2) Users complain the CLI is slower than the old standalone scripts. (3) CI scripts that call the CLI in loops become bottlenecked by startup time.
- **Prevention**: Lazy imports everywhere. Each subcommand should be a thin function that imports its dependencies inside the function body, not at module level. Use `click`'s lazy group pattern or `typer`'s lazy loading. Measure startup time as a CI gate: `gigaevo --help` must complete in < 200ms.
- **Phase**: Phase 1 (CLI skeleton) -- set the lazy import convention from day one; retrofitting it later means touching every subcommand.

### P-CLI-04: Output Format Proliferation

- **Risk**: Different tools currently emit: plain text tables (`status.py`), matplotlib plots (`comparison.py`), CSV (`redis2pd.py`), JSON (`top_programs.py --json`), and Markdown (`watchdog PR comments`). A unified CLI needs structured output modes, but if each subcommand implements its own `--json`/`--telegram`/`--markdown` formatting, the formats drift apart and consumers (notification pipeline, scripts) break.
- **Warning signs**: (1) Telegram messages and PR comments show different data for the same run. (2) `--json` output schemas differ between subcommands for the same entities. (3) Test assertions are brittle string matches against formatted output.
- **Prevention**: Define output as **data objects** (dataclasses/Pydantic models) that get rendered by format-specific serializers at the boundary. A `RunStatus` model gets rendered as text table, JSON, Telegram Markdown, or PR Markdown by four renderers. The subcommand never formats output directly -- it returns data, and the CLI framework calls the appropriate renderer based on `--format`.
- **Phase**: Phase 2 (shared library) -- define the data models and renderers as part of the shared library, before subcommands use them.

### P-CLI-05: Losing the PYTHONPATH=. Convention

- **Risk**: Every current tool requires `PYTHONPATH=. python tools/status.py`. A CLI entrypoint (`gigaevo status`) installed via `pip install -e .` or a console_scripts entry point eliminates the PYTHONPATH requirement. But if the CLI internally does relative imports that assume PYTHONPATH is set, it breaks in some invocation modes and not others.
- **Warning signs**: (1) `gigaevo status` works but `python -m gigaevo status` doesn't. (2) Tests pass in CI but fail locally. (3) Import errors that only appear when the CLI is installed globally vs. in development mode.
- **Prevention**: Use absolute imports throughout. Define a proper `pyproject.toml` entry point. Test both `python -m gigaevo` and the console script in CI. Delete the `PYTHONPATH=.` requirement from docs once the CLI is the primary interface.
- **Phase**: Phase 1 (CLI skeleton) -- the entry point mechanism is foundational.

---

## Plugin System Pitfalls

### P-PLG-01: Over-Engineered Plugin Discovery

- **Risk**: Building a generic plugin system with entry points, namespace packages, or plugin registries when there are only 3-4 known experiment types (solo MAP-Elites, adversarial pairs, prompt co-evolution, adversarial-dynamic-updates). The plugin system becomes more complex than the plugins themselves. Discovery mechanisms add import-time overhead and fail in confusing ways.
- **Warning signs**: (1) More code in the plugin framework than in all plugins combined. (2) Plugin load failures produce opaque tracebacks instead of "plugin X not found" messages. (3) Adding a new experiment type requires understanding the plugin framework, not just writing a renderer.
- **Prevention**: Start with a **simple registry pattern**: a dict mapping experiment type string to a renderer class. Import them explicitly. No entry points, no namespace packages, no `importlib.import_module` scanning. The bar for promotion to a real plugin system is: more than 6 renderer types AND external contributors. Until then, a module-level dict is the entire "plugin system."
- **Phase**: Phase 3 (watchdog core) -- implement the registry when building the watchdog, not before.

### P-PLG-02: Plugin Interface Too Narrow (or Too Wide)

- **Risk**: If the plugin interface is "render status as a string," every non-trivial experiment type (adversarial with paired plots, co-evolution with prompt metrics) has to cram its data into a flat format. If the interface is "here's the full Redis connection, do whatever you want," plugins become as complex as the current standalone watchdogs.
- **Warning signs**: (1) Plugins doing raw Redis queries because the interface didn't expose enough data. (2) Multiple plugins duplicating the same "fetch frontier series" logic. (3) The interface has `**kwargs` parameters that every plugin interprets differently.
- **Prevention**: Design the interface around the **data flow**, not the rendering. The core loop fetches raw metrics into a standard structure (per-run generation count, frontier values, gen-mean series, stall detection). The plugin receives this structured data and returns: (a) a status table (list of rows with labeled columns), (b) optional plot figure(s), and (c) optional alert messages. The plugin never touches Redis directly. Three methods: `table_columns()`, `render_plot(data) -> Figure | None`, `check_alerts(data) -> list[str]`.
- **Prevention (validation)**: Write the adversarial-dynamic-updates renderer FIRST (most complex case). If the interface supports that without escape hatches, it supports everything simpler.
- **Phase**: Phase 3 (watchdog core) -- the interface is the design center of the whole plugin system.

### P-PLG-03: Stale Plugin After Metrics Schema Change

- **Risk**: A new experiment adds a custom metric (e.g., `resistance` in adversarial experiments). The generic watchdog doesn't know about it. The plugin that renders it assumes specific Redis key patterns. When the metrics schema evolves (it has -- see `valid_frontier_{metric}` keys), plugins break silently by showing stale or missing data.
- **Warning signs**: (1) A watchdog plot shows "N/A" for a metric that has data in Redis. (2) Different plugins hardcode different Redis key patterns for the same concept. (3) Adding a new metric requires editing both the framework AND the plugin.
- **Prevention**: The core loop discovers metrics dynamically from `metrics.yaml` (which `status.py` already does). Plugins declare which metric names they need; the core loop provides them as named values. Plugins never construct Redis keys. If a declared metric is missing from `metrics.yaml`, the core logs a WARNING at startup, not a silent None.
- **Phase**: Phase 2 (shared library) -- the metrics discovery layer goes in the shared library.

### P-PLG-04: Plugin State Accumulation (Memory Leaks)

- **Risk**: The watchdog runs for days or weeks. If plugins accumulate state (plot data lists, metric histories, cached Redis connections) without bounds, memory grows linearly with experiment duration. The adversarial-dynamic-updates watchdog already keeps `_last_gen` dict and creates matplotlib figures in a loop -- if `plt.close()` is ever missed, each figure leaks ~20MB.
- **Warning signs**: (1) Watchdog memory usage grows monotonically over hours. (2) `plt.close()` calls are inconsistent across plugins. (3) Redis connection pool exhaustion after many cycles.
- **Prevention**: (1) Mandate `plt.close(fig)` in a `finally` block in every plot method -- or better, provide a `@managed_figure` decorator in the framework that handles this. (2) Plugins receive fresh data each cycle; they don't accumulate history. If a plugin needs history (e.g., stall detection), the framework manages the bounded buffer and passes it in. (3) Single Redis connection pool shared across all plugins, managed by the core loop.
- **Phase**: Phase 3 (watchdog core) -- resource management is the core loop's responsibility.

---

## Notification Pitfalls

### P-NOT-01: Silent Failure is the Default

- **Risk**: The current `telegram_notify.py` returns `False` on failure and prints to stdout. No one reads watchdog stdout. The watchdog continues posting to the PR but the researcher's phone stays silent. This is the #1 current pain point. The same pattern repeats in any notification system: HTTP POST fails, the code catches the exception, logs it, and moves on.
- **Warning signs**: (1) Telegram notifications stop arriving but no one notices for hours. (2) The watchdog log shows "WARNING: failed to send message" but the process keeps running. (3) The researcher discovers missed notifications only when manually checking the PR.
- **Prevention**: Distinguish between **transient** failures (network blip, rate limit) and **persistent** failures (bad token, blocked proxy, wrong chat ID). Transient: retry with exponential backoff (3 attempts, 5s/15s/45s). Persistent: escalate to a fallback channel. Specifically: if Telegram fails 3x in a row, post a visible warning to the PR: "Telegram delivery failed -- check proxy config." Track consecutive failure count; after 5 cycles of failure, the watchdog should include `TELEGRAM DOWN` in every PR comment header.
- **Prevention (startup probe)**: At watchdog startup, send a test message to Telegram. If it fails, REFUSE TO START (exit 1) with a clear error. Don't silently run without notifications.
- **Phase**: Phase 4 (notification pipeline) -- this is the core requirement of the notification rework.

### P-NOT-02: Proxy Configuration Fragility

- **Risk**: Telegram is blocked on the servers. The current code reads `HTTPS_PROXY` from the environment and passes it to `requests`. But: (a) the proxy env var may not be set in the watchdog's process environment (it's set in `.claude/settings.json` which isn't sourced by nohup), (b) the `NO_PROXY` bypass list must include the Redis server and GitHub API but NOT Telegram, and (c) the watchdog manually constructs `NO_PROXY` from the manifest server list, which can conflict with system-level proxy settings.
- **Warning signs**: (1) Telegram works from the developer's shell but not from nohup'd watchdog. (2) Adding a new server to infrastructure.yaml breaks Telegram because it gets added to NO_PROXY. (3) `requests` ignores the proxy silently when `NO_PROXY` matches the Telegram URL.
- **Prevention**: (1) The notification module should read proxy config from a dedicated config file (e.g., `~/.gigaevo/notify.yaml`), not from environment variables. (2) The proxy is set per-destination: Telegram gets the HTTPS proxy, GitHub API and Redis get direct. (3) At startup, the notification module tests connectivity to each endpoint and reports which work and which don't. (4) NO_PROXY construction should NEVER include wildcard entries that could accidentally match `api.telegram.org`.
- **Phase**: Phase 4 (notification pipeline) -- proxy handling is the first thing to fix in the notification module.

### P-NOT-03: Message Formatting Divergence Between Channels

- **Risk**: PR comments use GitHub Markdown (tables with `|`, image links with `![]()`). Telegram uses its own Markdown dialect (no tables, limited HTML, 4096-char limit, images as separate `sendPhoto` calls). If the formatting logic is per-channel, changes to the status table structure require updating both formatters independently. They drift, and the researcher gets different information on their phone vs. in the PR.
- **Warning signs**: (1) PR comment shows a metric that Telegram message doesn't. (2) Telegram messages get truncated at 4096 chars with no indication of what was lost. (3) Bug fixes to formatting are applied to one channel but not the other.
- **Prevention**: The data model produces a **channel-neutral status object** (structured data, not strings). Two renderers transform it: `render_github_markdown(status) -> str` and `render_telegram(status) -> TelegramPayload` (which may be text + optional photo). Both renderers are tested against the same fixture data. The Telegram renderer handles truncation explicitly: if the full table exceeds 4096 chars, it sends a summary + "full status on PR #N" link.
- **Phase**: Phase 4 (notification pipeline) -- define the neutral data model in Phase 2 (shared library), implement renderers in Phase 4.

### P-NOT-04: Rate Limiting and Throttling

- **Risk**: Telegram Bot API has rate limits (~30 messages/second per bot, 20 messages/minute per chat). GitHub API has rate limits (5000 requests/hour authenticated). During experiment launch (8 runs starting simultaneously) or completion (burst of status updates), the notification system can exceed these limits and get silently dropped or return 429 errors.
- **Warning signs**: (1) Some Telegram messages from a batch don't arrive. (2) GitHub API returns 403 "rate limit exceeded" in watchdog logs. (3) The PR gets fewer comments than expected during rapid status changes.
- **Prevention**: (1) Coalesce notifications: don't send per-run updates; aggregate into one message per cycle. (2) Respect `Retry-After` headers from both APIs. (3) Track remaining rate limit budget via response headers (`X-RateLimit-Remaining` for GitHub). (4) For Telegram, enforce a minimum 2-second gap between API calls. The current 1-hour poll interval makes this unlikely to trigger, but burst scenarios (startup, completion, error storms) can.
- **Phase**: Phase 4 (notification pipeline) -- implement as part of the delivery layer.

### P-NOT-05: Stale Plot Images in PR Comments

- **Risk**: The current watchdog uploads plot PNGs to the experiment branch and links them in PR comments. But GitHub caches raw.githubusercontent.com images aggressively. After hour 24, the watchdog edits a rolling comment and updates the image URL, but GitHub may serve the cached old image. The researcher sees a stale plot in the PR.
- **Warning signs**: (1) PR comment says "Hour 30" but the plot clearly shows data only up to hour 24. (2) Force-refreshing the browser shows the correct image but normal viewing doesn't. (3) Different team members see different plot versions.
- **Prevention**: (1) Add a cache-busting query parameter to image URLs: `?t={unix_timestamp}`. (2) Use unique filenames per hour (already done: `hour_NNN.png`) instead of overwriting a single file. (3) For the rolling comment, embed the image as a base64 data URI instead of a URL (GitHub supports this in comments up to ~10MB). (4) Alternatively, upload to GitHub Release assets which have different caching behavior.
- **Phase**: Phase 5 (PR integration) -- fix as part of the PR comment rendering.

---

## Watchdog Pitfalls

### P-WD-01: False Stall Alarms

- **Risk**: The current watchdog detects stalls by comparing generation count between cycles (1-hour intervals). But a long-running evaluation (e.g., HoVer 3-hop chain with 10-minute timeout) can legitimately produce zero generation advancement in one hour. The watchdog flags this as stalled, the researcher gets an alert, checks the system, finds nothing wrong. After enough false alarms, the researcher ignores ALL alerts -- including real ones.
- **Warning signs**: (1) Stall alerts that resolve themselves next cycle. (2) Researcher stops responding to Telegram alerts. (3) Stall detection threshold is tuned to match one experiment type but false-alarms on another.
- **Prevention**: Multi-signal stall detection. Generation count is necessary but not sufficient. Also check: (a) are there RUNNING programs? (checked via `{prefix}:status:RUNNING` set), (b) are new programs being submitted? (checked via `programs_total_count` metric trend), (c) is the process alive? (PID check). Only alarm if ALL signals agree: no gen advancement AND no running programs AND no new submissions over 2+ consecutive cycles. Also: differentiate "stalled" (stuck, needs intervention) from "slow" (progressing, just slowly).
- **Phase**: Phase 3 (watchdog core) -- stall detection is core watchdog logic, not a plugin concern.

### P-WD-02: Watchdog Itself Becomes the Single Point of Failure

- **Risk**: The watchdog monitors the experiment, but nothing monitors the watchdog. If the watchdog crashes (it has a 5-restart limit, after which it gives up), the experiment runs silently with no monitoring. The current `check_all_watchdogs.sh` cron script checks Redis heartbeats, but if the cron job itself fails, there's no monitoring at all.
- **Warning signs**: (1) The watchdog log ends abruptly with no "shutting down" message. (2) The PR goes quiet (no hourly updates) but no one notices. (3) The Redis heartbeat key expires and nothing acts on it.
- **Prevention**: Defense in depth: (a) The watchdog writes a heartbeat to Redis with a TTL of 3x the poll interval. (b) A cron job checks for expired heartbeats and sends a Telegram alert if any are missing. (c) The cron job ALSO writes its own heartbeat. (d) The watchdog includes "watchdog alive since X" in every PR comment so a human can notice the absence. (e) When the watchdog exceeds its restart limit, it posts a FINAL alert to both Telegram AND PR before exiting.
- **Prevention (already partial)**: The current code does post a crash alert to the PR on max restarts. Extend this to also alert Telegram.
- **Phase**: Phase 3 (watchdog core) -- the self-monitoring is part of the core loop.

### P-WD-03: Resource Exhaustion Under Long Runs

- **Risk**: Experiments can run for days or weeks. The watchdog opens Redis connections every cycle, generates matplotlib figures, uploads images via HTTP, and posts to GitHub API. If any of these resources leak (unclosed connections, uncollected figures, file handles from plot saves), the watchdog degrades over time.
- **Warning signs**: (1) Watchdog memory usage grows linearly over days. (2) Redis "too many connections" errors after several days. (3) Matplotlib warnings about exceeding figure limit. (4) Disk fills up with timestamped plot PNGs.
- **Prevention**: (1) Use context managers for all Redis connections (`with redis.Redis(...) as r:`). (2) Wrap all matplotlib usage in try/finally with `plt.close(fig)`. (3) Limit stored plot files to the last N (e.g., 50) and delete older ones. (4) Log memory usage (RSS) every cycle so growth is visible. (5) Run the watchdog under `ulimit` to cap memory and file descriptors.
- **Phase**: Phase 3 (watchdog core) -- resource management is the framework's job, not the plugin's.

### P-WD-04: Cascading Failures from Shared Redis

- **Risk**: The watchdog reads from the same Redis instance that the experiment writes to. If the watchdog issues expensive queries (e.g., `LRANGE` on a million-entry list, `HGETALL` on a huge archive), it can slow down the experiment's Redis operations. If the watchdog has a bug that writes to Redis (it shouldn't, but the manifest `refresh_db_claims` does write), it can corrupt experiment data.
- **Warning signs**: (1) Experiment throughput drops during watchdog cycles. (2) Redis `SLOWLOG` shows watchdog queries. (3) Unexpected keys appear in experiment DBs.
- **Prevention**: (1) Watchdog MUST use read-only Redis operations only. Enforce this by using a Redis client wrapper that blocks write commands (or at minimum, audit all Redis calls in the watchdog). (2) For expensive queries, use `LRANGE` with bounded ranges (e.g., last 100 entries) instead of `LRANGE 0 -1`. (3) The watchdog should connect to Redis with a separate client that has a short timeout (5s) so it doesn't block the experiment's connection pool. (4) Consider running `READONLY` mode if Redis supports it in your topology.
- **Phase**: Phase 2 (shared library) -- the Redis access layer enforces read-only semantics.

### P-WD-05: Clock Skew in Multi-Server Experiments

- **Risk**: Experiments can run across multiple servers. The watchdog runs on one server but reads Redis data written by processes on other servers. Timestamps in metrics history (`"t"` field) come from different server clocks. If clocks are skewed, the watchdog's "wall-clock time" plots show impossible patterns (negative durations, reversed ordering).
- **Warning signs**: (1) Fitness-vs-time plots show data points in the future. (2) Duration calculations produce negative values. (3) Metrics from different runs show inconsistent temporal ordering.
- **Prevention**: (1) Use Redis server time (`TIME` command) as the canonical clock for all timestamp comparisons. (2) When plotting wall-clock data, normalize to relative offsets from experiment start, not absolute timestamps. (3) Log the clock offset between the watchdog server and Redis server at startup. If offset > 5s, warn.
- **Phase**: Phase 2 (shared library) -- timestamp normalization goes in the metrics access layer.

---

## Migration-Specific Pitfalls

### P-MIG-01: Muscle Memory Breakage

- **Risk**: Researchers and scripts have months of muscle memory for `PYTHONPATH=. python tools/status.py --run ...`. If the new CLI changes the invocation to `gigaevo status --run ...`, every shell history entry, every script, every CLAUDE.md example, every skill file, and every `.sh` launch script breaks. The researcher's reflex is to type the old command, get an error, and become frustrated.
- **Warning signs**: (1) The old scripts are deleted but referenced in 50+ files. (2) The researcher keeps typing the old command weeks after migration. (3) CI scripts fail because they use the old invocation.
- **Prevention**: Two-phase migration. Phase A: the old scripts become thin wrappers that print a deprecation warning ("Use `gigaevo status` instead") then delegate to the new CLI. Phase B (2-4 weeks later): remove the wrappers. Track wrapper usage via a counter or log to know when it's safe to remove. Also: provide a `gigaevo migrate` command that rewrites known script patterns (sed-style) in launch scripts and docs.
- **Phase**: Phase 6 (migration) -- after the CLI is complete and tested, NOT as part of the initial build.

### P-MIG-02: Flag Renaming Without Mapping

- **Risk**: The old `comparison.py` uses `--output-folder`. The old `top_programs.py` uses `--save-dir`. The old `redis2pd.py` uses `--output-file`. If the unified CLI normalizes these to `--output`, users of each tool must learn a different mapping. Worse, if the old and new flags have subtly different semantics (directory vs. file path), the migration silently produces wrong output.
- **Warning signs**: (1) Users pass `--output-folder` to the new CLI and get "unknown flag" error. (2) Users pass a directory path to `--output` and the CLI interprets it as a file path (or vice versa). (3) The migration guide is a long table that no one reads.
- **Prevention**: (1) Accept old flag names as hidden aliases with deprecation warnings. click/argparse support this natively. (2) For semantically different flags (dir vs. file), keep them distinct: `--output-dir` and `--output-file`. Don't over-unify. (3) The CLI should detect common mistakes: if `--output-file` path doesn't have an extension, suggest `--output-dir` instead.
- **Phase**: Phase 1 (CLI skeleton) -- flag naming conventions must be set before subcommands are built.

### P-MIG-03: Legacy --redis-db / --redis-prefix Breakage

- **Risk**: `redis2pd.py` already supports both `--run prefix@db:label` (new) and `--redis-db` + `--redis-prefix` (legacy, used by `archive_run.sh`). Other tools may have similar legacy flag paths. During migration, these legacy paths must keep working because `archive_run.sh` calls them programmatically.
- **Warning signs**: (1) `archive_run.sh` calls `redis2pd.py` with `--redis-db` and `--redis-prefix` but the new CLI doesn't support those flags. (2) The migration removes legacy flags but doesn't update all callers. (3) Tests pass because they use the new flags, but production scripts use the old ones.
- **Prevention**: (1) Before removing any legacy flag, grep the ENTIRE codebase (including `.sh` scripts, skills, agents) for all usages. (2) Keep legacy flags as hidden aliases for at least one experiment cycle (~2 weeks). (3) `archive_run.sh` should be migrated to use the new CLI as part of the same phase.
- **Phase**: Phase 1 (CLI skeleton) -- support legacy flags from day one; removal is Phase 6.

### P-MIG-04: Breaking Running Experiments During Migration

- **Risk**: The adversarial-dynamic-updates experiment is currently running. Its watchdog is a standalone Python script that imports from `tools/`. If the migration moves or renames modules in `tools/`, the running watchdog's next import will fail. If the migration changes Redis key patterns or metric names, the running experiment's data becomes unreadable.
- **Warning signs**: (1) The running watchdog crashes after a git pull. (2) The running experiment's status shows "0 programs" because the query format changed. (3) The PR stops getting hourly updates.
- **Prevention**: (1) The migration MUST NOT change any module that running watchdogs import. (2) New code goes in a NEW package (`gigaevo.cli`, `gigaevo.monitoring`) -- it doesn't modify `tools/`. (3) Running watchdogs are only migrated to the new system at experiment boundaries (after closeout, before next launch). (4) The new CLI reads the same Redis keys with the same format -- it's a consumer, not a schema change.
- **Phase**: ALL phases -- this is a cross-cutting constraint, not a phase-specific task. Every PR should be reviewed against "does this break running experiments?"

### P-MIG-05: Test Coverage Gap During Transition

- **Risk**: The old tools have minimal or no tests (they were scripts, not library code). The new CLI has tests. But the migration period creates a gap: the old scripts are still the primary interface, the new CLI is being built, and neither is fully tested against real experiment data. Bugs that would have been caught by the old scripts' implicit "it works in production" validation are now missed because the new code hasn't been battle-tested yet.
- **Warning signs**: (1) The new CLI passes unit tests but produces wrong output for real Redis data. (2) Edge cases that the old scripts handled (empty data, missing metrics, single-run experiments) aren't covered by new tests. (3) The new CLI works for hotpotqa but fails for adversarial experiments because test fixtures only cover one experiment type.
- **Prevention**: (1) Before writing the new CLI, extract the old scripts' implicit test cases: take screenshots of their actual output for 2-3 experiment types and use these as golden-file tests for the new CLI. (2) Run the new CLI in "shadow mode" alongside the old scripts for at least one experiment cycle: both produce output, a diff script compares them. (3) Test fixtures must include at least: solo MAP-Elites (hotpotqa), adversarial pairs (adversarial-vs-solo), prompt co-evolution (hover/prompt_coevolution), and the current adversarial-dynamic-updates.
- **Phase**: Phase 1 (CLI skeleton) -- set up shadow testing infrastructure before building subcommands.

### P-MIG-06: Documentation Drift

- **Risk**: GigaEvo has extensive documentation: `tools/README.md` (full tool index with usage examples), `CLAUDE.md` (project-level instructions), experiment-specific `CONTEXT.md` files, and skill files that reference tool commands. Migrating the tools without updating ALL documentation means the docs actively mislead. Worse: Claude Code reads these docs as context, so stale tool references in `CLAUDE.md` cause Claude to suggest commands that don't work.
- **Warning signs**: (1) Claude suggests `PYTHONPATH=. python tools/status.py --run ...` after the tool is absorbed into the CLI. (2) `tools/README.md` references scripts that no longer exist. (3) New researchers follow the docs and get confused.
- **Prevention**: (1) Create a documentation migration checklist: every file that references `tools/*.py` must be updated. (2) Add a CI check (`tools/check_docs_freshness.py` already exists) that verifies tool references in docs point to existing files. (3) Update `CLAUDE.md` and `tools/README.md` as part of each CLI subcommand PR, not as a separate "docs cleanup" PR. (4) Skill files that reference tool commands should use the new CLI commands from the start.
- **Phase**: Every phase -- documentation updates are part of each PR's definition of done.

---

## Cross-Cutting Concerns

### P-XC-01: Testing the Notification Pipeline End-to-End

- **Risk**: Unit tests for individual components (parser, renderer, Telegram client, GitHub client) all pass, but the full pipeline (fetch data -> render -> deliver to both channels) is never tested end-to-end. Integration points fail: the renderer produces Markdown that Telegram's parser rejects, the PR comment body exceeds GitHub's 65535-char limit, the plot file path has spaces that break the upload.
- **Prevention**: Create an integration test suite that runs against: (a) a real Redis with test data, (b) a mock Telegram API (httpretty or responses library), (c) a mock GitHub API. The test exercises the full path: read experiment data, render status, deliver to both channels, verify the received content matches expectations. Run this as part of CI, not just manually.
- **Phase**: Phase 5 (PR integration) -- after both channels are implemented, before migration.

### P-XC-02: Configuration Sprawl

- **Risk**: The current system has configuration in: Hydra YAML (`config/`), experiment.yaml, `.env` (Telegram tokens), environment variables (HTTPS_PROXY, NO_PROXY, GIGAEVO_PYTHON), `.claude/settings.json`, and infrastructure.yaml. Adding CLI configuration (default output format, default Redis host, notification preferences) creates yet another config source. The researcher can't answer "where is X configured?" without checking 6 places.
- **Prevention**: Adopt a clear precedence: CLI flags > environment variables > config file (`~/.gigaevo/config.yaml`) > defaults. Document the precedence explicitly. Don't introduce new config sources; consolidate into the config file where possible. Move Telegram tokens from `.env` to the config file (or keep in `.env` but document it's the ONLY place for secrets).
- **Phase**: Phase 1 (CLI skeleton) -- define the config precedence before implementing anything that reads config.

---

## Priority Matrix

Pitfalls ranked by (probability x impact) for GigaEvo specifically:

| Priority | Pitfall | Why |
|----------|---------|-----|
| CRITICAL | P-NOT-01 | Silent Telegram failures are the #1 current pain point |
| CRITICAL | P-MIG-04 | Breaking running experiments would lose weeks of compute |
| HIGH | P-CLI-02 | Three divergent parsers will produce subtle bugs during consolidation |
| HIGH | P-NOT-02 | Proxy fragility has already caused real failures |
| HIGH | P-WD-01 | False stall alarms erode trust in the monitoring system |
| HIGH | P-MIG-01 | 30+ watchdog files and 50+ doc references to old commands |
| MEDIUM | P-PLG-01 | Over-engineering risk is high given only 3-4 experiment types |
| MEDIUM | P-PLG-02 | Interface design determines whether the plugin system actually works |
| MEDIUM | P-CLI-03 | Matplotlib import tax is real but manageable with lazy imports |
| MEDIUM | P-CLI-04 | Output format drift is guaranteed without shared data models |
| MEDIUM | P-MIG-05 | No tests for old scripts means no safety net during migration |
| MEDIUM | P-MIG-06 | Claude reads stale docs and suggests broken commands |
| LOW | P-WD-05 | Clock skew is rare on managed infrastructure |
| LOW | P-NOT-04 | Rate limiting unlikely at 1-hour polling intervals |
| LOW | P-CLI-05 | PYTHONPATH is annoying but functional |
