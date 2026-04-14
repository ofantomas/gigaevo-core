# Phase 5: Polish CLI/watchdog/manifest wiring - Context

**Gathered:** 2026-04-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Make the entire monitoring/CLI/observability stack work reliably for ANY experiment type. No crashes when agents invoke CLI commands, no guesswork in plugin resolution, no legacy imports from `tools/`. After this phase, you point the watchdog at any experiment.yaml and it just works.

</domain>

<decisions>
## Implementation Decisions

### Plugin Resolution (D-01 through D-03)
- **D-01:** Plugin is declared EXPLICITLY in `experiment.yaml` via the `watchdog_plugin` field. If absent, fall back to `solo`. No heuristic guessing. Delete `_TASK_HEURISTIC` dict entirely.
- **D-02:** Merge `heilbron` plugin into `adversarial` plugin. The adversarial plugin becomes the single plugin for all adversarial/co-evolution experiments. Delete `gigaevo/monitoring/plugins/heilbron.py`.
- **D-03:** Plot metrics are specified per-experiment in `experiment.yaml` as `watchdog_plugin_options: {plot_metrics: [fitness, actual_fitness]}`. These are validated against `metrics.yaml` — every metric in `plot_metrics` must exist in the problem's `metrics.yaml`. If a metric is listed but not found, warn loudly.

### Manifest Consolidation (D-04, D-05)
- **D-04:** Pydantic manifest (`gigaevo/monitoring/manifest_schema.py`) is the single source of truth. Remove the legacy dataclass from `tools/experiment/manifest.py`. All callers (CLI, watchdog, skills, agents) migrate to the Pydantic schema.
- **D-05:** Fix `resolve_plugin()` to use `manifest.experiment.task` correctly (Pydantic shape), since the legacy dataclass that used `manifest.task` is being removed.

### Legacy tools/ Elimination (D-06, D-07)
- **D-06:** Move ALL useful `tools/` functionality into the `gigaevo/` package. Not just fixing broken imports — full migration. Functions used by CLI commands, plotting, data export, lineage, preflight checks, archiving — all move into `gigaevo/`.
- **D-07:** After migration, `gigaevo/cli/` and `gigaevo/monitoring/` must have ZERO imports from `tools/`. The `tools/` directory remains for standalone scripts that haven't been migrated yet, but the installed `gigaevo` package is self-contained.

### Agent/Skill CLI Reliability (D-08, D-09)
- **D-08:** Audit ALL experiment lifecycle skills (`.claude/skills/experiment-*/SKILL.md`) for incorrect CLI flags, wrong argument formats, and references to non-existent commands. Fix every incorrect invocation.
- **D-09:** Audit ALL agents (`.claude/agents/*.md`) for the same issues. Agents must use the correct `gigaevo` CLI API — no stale command references, no wrong flags.

### Claude's Discretion
- Internal package structure for migrated tools/ code (e.g., `gigaevo/tools/` vs `gigaevo/cli/utils/` vs spreading across existing modules)
- Whether to keep `tools/` scripts as thin wrappers calling `gigaevo` internals, or delete them entirely
- How to handle `tools/comparison.py` subprocess calls in plugins (inline the logic vs keep as CLI command)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### CLI and Monitoring Architecture
- `gigaevo/cli/` — All CLI command modules (status_cmd, watchdog_cmd, plot_group, run_resolver, flush, etc.)
- `gigaevo/monitoring/` — Watchdog engine, plugins, manifest schema, notifications, snapshots, redis queries
- `gigaevo/monitoring/watchdog_plugin.py` — Plugin ABC, registry, `resolve_plugin()`, `_TASK_HEURISTIC` (to be deleted)
- `gigaevo/monitoring/plugins/` — solo.py, adversarial.py, heilbron.py (to be merged), prompt_coevo.py
- `gigaevo/monitoring/manifest_schema.py` — Pydantic ExperimentManifest (the winner)

### Legacy Code to Migrate
- `tools/experiment/manifest.py` — Legacy dataclass ExperimentManifest (to be removed)
- `tools/comparison.py` — Called via subprocess by solo/adversarial/prompt_coevo plugins
- `tools/utils.py` — `fetch_evolution_dataframe`, `prepare_iteration_dataframe` (imported by plot_group.py)
- `tools/README.md` — Full tools index and Redis data model reference

### Experiment Skills and Agents
- `.claude/skills/experiment-*/SKILL.md` — All lifecycle skills to audit for CLI correctness
- `.claude/agents/*.md` — All agents to audit for CLI correctness
- `CLAUDE.md` — CLI command reference table (must be updated if commands change)

### Problem Metrics
- `problems/*/metrics.yaml` — Per-problem metric specs (source of truth for `plot_metrics` validation)

### Known Issues (from running experiment)
- `experiments/heilbron/asymmetric-iterations/04_issues_log.md` — Documents the watchdog/CLI crashes that motivated this phase
- `experiments/PATTERNS.md` — Known Failures section (KF-01 through KF-05)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `RunConfig.metric_names` — Already carries discovered metrics from `metrics.yaml` into the monitoring stack
- `RunSnapshot.metrics` — Generic `dict[str, float | None]` — already supports any metric set
- `_load_metric_names()` — Already reads `metrics.yaml` and returns metric name list
- `format_status_table_markdown()` — Generic status formatter, works with any metrics

### Established Patterns
- Plugin registry with `@register("name")` decorator — keep this pattern
- `RunSpec.parse("prefix@db:label")` — standard run identifier format
- Hydra config for pipeline selection (`config/pipeline/*.yaml`)
- `experiment.yaml` as the manifest for all experiment metadata

### Integration Points
- `watchdog_cmd.py:56` — currently imports `from tools.experiment.manifest import load_manifest` (BROKEN)
- `run_resolver.py:16` — same broken import
- `plot_group.py:53,223` — lazy imports from `tools.utils` and `tools.comparison` (BROKEN at runtime)
- `resolve_plugin():169` — accesses `manifest.experiment.task` but receives legacy flat object (CRASHES)

### Pipeline → Plugin Mapping (for reference, NOT for heuristic)
- `standard`, `hotpotqa_*`, `hover_*`, `auto`, `custom` → solo
- `adversarial*` → adversarial
- `prompt_evolution` → prompt_coevo

</code_context>

<specifics>
## Specific Ideas

- User wants: "I want either explicit or solo, no guessing" — zero heuristic, zero magic
- User wants: plugin options in experiment.yaml for plot metrics, validated against metrics.yaml
- User wants: agents to stop passing wrong flags/arguments to CLI — this is a skill/agent documentation problem, not a CLI problem
- User wants: full tools/ migration into gigaevo package, not partial fixes
- User wants: `gigaevo plot` CLI to produce the same "nice and curvy" plot style as `tools/comparison.py` watchdog plots — current CLI plots lack smoothing/interpolation and required debugging to get right. When migrating comparison.py into gigaevo, preserve the plot styling (line smoothing, colors, layout) that already works in the watchdog context.

</specifics>

<deferred>
## Deferred Ideas

- Generation-aware sync hook for SteadyState (ProgressBasedSyncHook only syncs programs_processed, not generations) — logged in 04_issues_log.md, needs its own phase
- Watch mode / Rich Live dashboard (deferred from v1.0)
- Configurable alert routing (deferred from v1.0)

</deferred>

---

*Phase: 05-polish-cli-watchdog-manifest-wiring*
*Context gathered: 2026-04-13*
