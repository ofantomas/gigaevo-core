# Phase 6: Polish watchdog CLI to replicate old-watchdog behavior - Context

**Gathered:** 2026-04-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Close the feature gap between the per-experiment `run_watchdog.py` scripts (battle-tested over months of real experiments) and the new `gigaevo watchdog` CLI command. After this phase, `gigaevo watchdog` produces the same quality of monitoring output as the old scripts: publication-quality time-series plots, GitHub-embedded images, rolling PR comments, model drift detection, Redis bookkeeping, rich Telegram summaries, and configurable plot/metric setup via experiment.yaml. Additionally, all watchdog and CLI commands have extensive integration tests with mock experiment data for all experiment types.

</domain>

<decisions>
## Implementation Decisions

### Plot Generation (D-01 through D-04)
- **D-01:** Watchdog plugins delegate plot generation to `gigaevo plot` CLI commands (arms-race, comparison) as subprocesses — same approach as old `run_watchdog.py`. This guarantees visual parity with existing publication-quality plots (EMA smoothing, frontier annotations, SOTA baselines).
- **D-02:** Plot configuration is specified in `experiment.yaml` using Hydra/OOP-style instantiation (consistent with the rest of the codebase). Plugins read this config to determine which `gigaevo plot` commands to invoke and with which arguments.
- **D-03:** Configurable plot metrics (which metrics get time-series curves) and alert thresholds (invalidity rate threshold, stagnation window, generation gap threshold) — all specified in experiment.yaml via Hydra/OOP instantiation.
- **D-04:** Plot generation retries 3 times with 30s delay between attempts (matching old watchdog behavior). Failures are logged but don't crash the cycle.

### GitHub Integration (D-05 through D-07)
- **D-05:** Plot images are uploaded to the GitHub repo (experiment branch) via the GitHub API. Raw URLs are embedded in PR comments so plots render inline. This is the same approach as old `run_watchdog.py`.
- **D-06:** Rolling PR comment pattern: new comments for first N hours, then edit-in-place using Redis-tracked comment ID to avoid flooding the PR. Old watchdog uses 24h threshold.
- **D-07:** All GitHub plot upload and rolling comment logic lives in `GitHubPRChannel`, not `WatchdogEngine`. Engine passes `PlotAttachment` objects; channel handles upload and comment management.

### Watchdog Lifecycle Features (D-08 through D-11)
- **D-08:** Model drift detection (probe LiteLLM `/models` endpoint to verify expected model) is implemented as a pluggable anomaly detector rule, not a core engine feature. Only runs if configured.
- **D-09:** Redis checkpoint/completion markers: write `experiments:{name}:checkpoint:{gen}` at milestone percentages and `experiments:{name}:completion` on all-done. Used by anomaly detector and closeout skills.
- **D-10:** NO_PROXY setup: watchdog reads manifest server addresses and configures `NO_PROXY` environment variable automatically before entering the main loop.
- **D-11:** DB claims refresh is NOT included in this phase (not selected as a priority).

### Telegram Formatting (D-12, D-13)
- **D-12:** Each `WatchdogPlugin` provides a `format_telegram_body()` method (new ABC method alongside existing `format_status_body()` for PR). AdversarialPlugin produces G/D-separated summaries with emoji flags. SoloPlugin produces a simpler run-by-run format.
- **D-13:** SOTA comparison in Telegram messages is plugin-dependent — only shown if the plugin supports it and a baseline is configured in experiment.yaml. Not forced on all experiment types.

### Testing (D-14 through D-18)
- **D-14:** Full integration tests with mock Redis (fakeredis): test complete watchdog cycles (collect snapshots → generate plots → format status → dispatch notifications) for all experiment types.
- **D-15:** YAML fixture files in `tests/fixtures/watchdog/` for each experiment type: solo MAP-Elites (hover), adversarial pairs (heilbron-style), and prompt co-evolution. Each fixture includes `experiment.yaml`, `metrics.yaml`, and Redis data snapshots.
- **D-16:** Click CliRunner end-to-end tests for `gigaevo watchdog`, `gigaevo status`, `gigaevo plot`, and other CLI commands. These catch import errors, flag mismatches, and wiring issues that caused the initial crash.
- **D-17:** All three experiment types (solo, adversarial, prompt co-evolution) have test fixtures covering their specific monitoring behavior: solo single-population metrics, adversarial G/D pairing with arms-race dynamics, prompt co-evolution dual-population layout.
- **D-18:** Mock GitHub API and Telegram API for notification channel tests. Verify plot upload, rolling comment creation/editing, and Telegram message formatting without hitting real services.

### Visual Plot Verification (D-19, D-20)
- **D-19:** After implementing the new watchdog plot generation, visually inspect the produced plots against reference plots from previous adversarial experiments. Reference plots are at: `experiments/adversarial/heilbron-prover/plots/arms_race_latest.png` (old arms-race style), `experiments/heilbron/adversarial-v2/plots/arms_race_latest.png` (dual-panel with confidence bands + SOTA baselines), `experiments/heilbron/adversarial-v2/plots/evolution_runs_comparison.png` (multi-run comparison with frontier dashes + shaded bands), `experiments/heilbron/asymmetric-iterations/plots/arms_race_hour_013.png` (current 8-run arms-race), `experiments/heilbron/asymmetric-iterations/plots/g_fitness_hour_013.png` (current 8-run comparison).
- **D-20:** The new watchdog must produce plots with these specific quality features: time-series curves (not bar charts), EMA smoothing with confidence bands, frontier (best) dashed lines alongside mean, SOTA baseline reference lines when configured, proper legends with condition labels, multi-panel layout for arms-race (G panel + D panel). Any visual regression from the reference plots is a blocking issue.

### Experiment Lifecycle Agent Integration (D-21, D-22)
- **D-21:** `/experiment-design` agent proposes a monitoring section in the design doc with suggested plots, metrics, and alert thresholds based on experiment type.
- **D-22:** `/experiment-implement` agent confirms or adjusts the monitoring config when writing experiment.yaml. Asks the researcher which metrics to plot and which alert thresholds to set.

### Claude's Discretion
- Exact Hydra config schema for watchdog plot configuration (specific field names, nesting structure)
- Whether to add a `WatchdogPlugin.format_telegram_body()` as abstract or with a default implementation that plugins can override
- Plot retry backoff strategy details (fixed 30s vs exponential)
- Which milestone percentages for Redis checkpoints (10/20/50/100 or configurable)
- How to structure the anomaly detector model-drift rule configuration

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Old Watchdog (reference implementation)
- `experiments/heilbron/asymmetric-iterations/run_watchdog.py` — Battle-tested old watchdog with all features to replicate (model drift, plot upload, rolling comment, Redis bookkeeping, Telegram formatting)
- `experiments/heilbron/asymmetric-iterations/04_issues_log.md` — Documents crashes and missing features that motivated this phase

### New Watchdog Architecture
- `gigaevo/cli/watchdog_cmd.py` — CLI entry point for `gigaevo watchdog`
- `gigaevo/monitoring/watchdog_engine.py` — WatchdogEngine core loop (heartbeat, collect, alert, plot, dispatch)
- `gigaevo/monitoring/watchdog_plugin.py` — Plugin ABC, registry, `resolve_plugin()`
- `gigaevo/monitoring/plugins/adversarial.py` — Current adversarial plugin (bar charts to be replaced)
- `gigaevo/monitoring/plugins/solo.py` — Solo plugin
- `gigaevo/monitoring/plugins/prompt_coevo.py` — Prompt co-evolution plugin

### Notification Channels
- `gigaevo/monitoring/dispatcher.py` — NotificationDispatcher fan-out
- `gigaevo/monitoring/github_pr_channel.py` — GitHub PR channel (needs plot upload + rolling comment)
- `gigaevo/monitoring/telegram_channel.py` — Telegram channel (needs plugin-specific formatting)
- `gigaevo/monitoring/notifications.py` — StatusUpdate, PlotAttachment, format_status_table_markdown

### Monitoring Infrastructure
- `gigaevo/monitoring/alerts.py` — AlertDetector, Alert types (needs model drift rule)
- `gigaevo/monitoring/experiment_monitor.py` — ExperimentMonitor, RunConfig
- `gigaevo/monitoring/snapshot.py` — RunSnapshot
- `gigaevo/monitoring/manifest_schema.py` — Pydantic ExperimentManifest (watchdog config section lives here)
- `gigaevo/monitoring/manifest.py` — load_manifest()

### Plotting
- `gigaevo/cli/plot_group.py` — CLI `gigaevo plot` subcommands (comparison, arms-race, trajectory)

### Existing Tests
- `tests/cli/` — Existing CLI tests
- `tests/monitoring/` — Existing monitoring tests

### Experiment Lifecycle Skills
- `.claude/skills/experiment-design/SKILL.md` — Needs monitoring config section (D-19)
- `.claude/skills/experiment-implement/SKILL.md` — Needs watchdog config step (D-20)

### Known Issues
- `experiments/PATTERNS.md` — Known Failures section (KF-01 through KF-05)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `WatchdogEngine` — core loop with SIGTERM handling, heartbeat, restart logic already works
- `NotificationDispatcher` + `TelegramChannel` + `GitHubPRChannel` — channel abstraction exists, needs enhancement
- `AlertDetector` with `AlertType`/`AlertSeverity` — anomaly detection framework for model drift rule
- `gigaevo plot arms-race/comparison` CLI commands — plot generation already works, just needs to be called from plugins
- `RunSnapshot.metrics` — generic dict supports any metric set
- Old `run_watchdog.py` — complete reference implementation of all features to replicate

### Established Patterns
- Plugin registry with `@register("name")` decorator
- WatchdogPlugin ABC with `generate_plots()`, `format_status_body()`, `extra_telegram_content()`
- Hydra/OOP config instantiation throughout the codebase
- YAML fixture files in `tests/` for test data

### Integration Points
- `WatchdogPlugin` ABC — needs new `format_telegram_body()` method
- `GitHubPRChannel` — needs plot upload + rolling comment logic
- `AlertDetector` — needs model drift rule
- `WatchdogEngine._cycle()` — needs Redis checkpoint/completion writing
- `experiment.yaml` manifest schema — needs watchdog plot config section
- Experiment lifecycle skills — need monitoring config sections

</code_context>

<specifics>
## Specific Ideas

- User wants: hourly updates with "nice plots which actually represent progress" — the current bar charts are a regression, time-series curves with EMA smoothing are mandatory
- User wants: configurable plot setup from scratch in experiment.yaml — Hydra/OOP instantiation like rest of codebase
- User wants: experiment-design agent to propose monitoring config and experiment-implement agent to confirm it by interviewing the researcher
- User wants: extensive tests — CLI crashed on first use, this must never happen again. Mock data for solo, adversarial, and prompt co-evolution setups. Click CliRunner end-to-end tests.
- User wants: which metrics receive top-k tracking should also be configurable (noted for future, not in D-03 scope since user selected plot metrics and alert thresholds only)

</specifics>

<deferred>
## Deferred Ideas

- Top-k program tracking configurability — user mentioned it but selected plot metrics and alert thresholds as priority. Can be added later.
- DB claims refresh (`refresh_db_claims()`) — not selected as a lifecycle feature for this phase
- Watch mode / Rich Live dashboard (deferred from v1.0)
- Generation-aware sync hook for SteadyState (logged in 04_issues_log.md)

</deferred>

---

*Phase: 06-polish-watchdog-cli-to-replicate-old-watchdog-behavior*
*Context gathered: 2026-04-13*
