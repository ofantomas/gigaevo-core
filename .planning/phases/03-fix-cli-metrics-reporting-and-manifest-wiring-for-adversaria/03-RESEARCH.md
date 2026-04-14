# Phase 3: Fix CLI Metrics Reporting and Manifest Wiring — Research

**Researched:** 2026-04-13
**Domain:** CLI metrics reporting, manifest-to-monitoring wiring, multi-experiment-type support
**Confidence:** HIGH

## Summary

Phase 3 fixes the wiring between experiment manifests and the CLI/monitoring layer so that **all experiment types** (standard, feedback, adversarial, prompt co-evolution, heilbron) get correct metrics reporting. The v1.0 MVP (Phases 1-5 of the original roadmap) built the monitoring infrastructure correctly at the library level, but several CLI commands bypass the proper metric discovery paths, leading to missing or incorrect metrics for non-standard experiments.

The core issue is **inconsistent metric_names propagation**: `run_resolver.py` correctly loads metric names from `metrics.yaml` via `_load_metric_names()`, but other entry points (`watchdog_cmd.py`, `checkpoint.py`, `plot_group.py`, `trajectory.py`, `top.py`) either hardcode `["fitness"]` or accept only a single `--metric` flag. For adversarial experiments with 7+ metrics per population (fitness, actual_fitness, quality, resistance, mean_improvement, etc.) and prompt co-evolution with 3 metrics (fitness, prompt_length), this means most metrics are silently invisible.

**Primary recommendation:** Propagate metric discovery from `metrics.yaml` (via `run_resolver._load_metric_names`) to all CLI commands and the watchdog engine. Add a `--metric` multi-value option to commands that need it. Wire watchdog_cmd.py to pass metric_names into RunConfig. Fix the manifest schema to include experiment-type metadata that enables correct plugin resolution.

<phase_requirements>

## Phase Requirements

The roadmap lists Phase 3 as "Fix CLI metrics reporting and manifest wiring for adversarial experiments" with "TBD" requirements. Based on research, the requirements map to existing v1 requirement IDs where applicable:

| ID | Description | Research Support |
|----|-------------|------------------|
| MON-05 (partial) | Gen-by-gen trajectory tracking with multiple metrics | trajectory.py only tracks single metric; needs multi-metric support |
| CLI-03 (gap) | Every subcommand works in both --experiment and --run modes with correct metric discovery | watchdog_cmd, checkpoint, analyze, collect bypass run_resolver metric discovery |
| MAN-02 (gap) | Manifest is optional but when present enables auto-discovery | watchdog_cmd builds RunConfigs without metric_names from manifest |
| MON-03 (gap) | Built-in plugins for all experiment types | Plugins exist but receive snapshots with incomplete metrics |

</phase_requirements>

## Architecture Overview

### Current Data Flow

```
experiment.yaml
    |
    v
tools/experiment/manifest.py (legacy dataclass parser)
    |
    v
gigaevo/cli/run_resolver.py  <-- CORRECT: loads metric_names from metrics.yaml
    |
    v
gigaevo/monitoring/experiment_monitor.py  <-- RunConfig with metric_names
    |
    v
gigaevo/monitoring/redis_queries.py  <-- get_frontier_metrics(prefix, metric_names)
    |
    v
gigaevo/monitoring/snapshot.py  <-- RunSnapshot.metrics dict
```

### Where It Breaks

```
gigaevo/cli/watchdog_cmd.py  -- Builds RunConfig WITHOUT metric_names (defaults to ["fitness"])
gigaevo/cli/trajectory.py    -- Single --metric flag, no auto-discovery from metrics.yaml
gigaevo/cli/top.py           -- Single --metric flag, no auto-discovery
gigaevo/cli/checkpoint.py    -- Uses RunResolver correctly, but snapshot_to_row may miss metrics
gigaevo/cli/plot_group.py    -- Single --metric flag for all plot types
gigaevo/cli/analyze.py       -- Uses --prefix/--db directly, bypasses run_resolver entirely
gigaevo/cli/collect.py       -- Uses --prefix/--db directly, bypasses run_resolver entirely
```

## Specific Bugs Found

### Bug 1: watchdog_cmd.py Missing metric_names [VERIFIED: codebase grep]

**File:** `gigaevo/cli/watchdog_cmd.py` lines 75-80

```python
# Current code (BROKEN):
for run in manifest.runs:
    spec = RunSpec(prefix=run.prefix, db=run.db, label=run.label)
    rc = RunConfig(run_spec=spec, pid=run.pid)  # <-- NO metric_names!
    run_configs.append(rc)
```

`RunConfig.metric_names` defaults to `["fitness"]`. For heilbron experiments, this means `actual_fitness`, `quality`, `resistance`, etc. are never queried from Redis. The watchdog sees only the composite `fitness` metric and misses the scientifically meaningful `actual_fitness` that the researcher cares about.

**Fix pattern:** Load metric_names via `run_resolver._load_metric_names(run.problem_name)` for each run.

### Bug 2: trajectory.py Only Reports Single Metric [VERIFIED: codebase]

**File:** `gigaevo/cli/trajectory.py`

Accepts `--metric` (single string, defaults to "fitness"). For adversarial experiments, the researcher needs to see `actual_fitness` trajectory alongside `fitness`. For prompt co-evolution, `prompt_length` trajectory matters alongside `fitness`.

**Fix pattern:** Accept `--metric` as repeatable or auto-discover from metrics.yaml when in `--experiment` mode.

### Bug 3: top.py Only Ranks by Single Metric [VERIFIED: codebase]

**File:** `gigaevo/cli/top.py`

Shows top programs by one `--metric` (defaults to "fitness"). For adversarial experiments, the scientifically relevant metric is `actual_fitness`, not the composite `fitness`. Researchers must manually pass `--metric actual_fitness` every time.

**Fix pattern:** When in `--experiment` mode, read `problem.metric_name` from manifest to determine the primary metric for ranking.

### Bug 4: analyze.py and collect.py Bypass run_resolver [VERIFIED: codebase]

**Files:** `gigaevo/cli/analyze.py`, `gigaevo/cli/collect.py`

These commands use `--prefix`/`--db` flags directly instead of `--experiment`/`--run`. They duplicate metric loading logic (`_load_metrics_yaml`, `_higher_is_better`) that already exists in `run_resolver`. They are not registered in the lazy CLI subcommand registry (analyze/collect are not in `_LAZY_SUBCOMMANDS` in `__init__.py`).

**Fix pattern:** Migrate to use `--experiment`/`--run` via RunResolver, or at minimum wire them into the standard CLI command registry.

### Bug 5: Manifest Schema Missing experiment_type/watchdog_plugin Field [VERIFIED: codebase]

**File:** `gigaevo/monitoring/manifest_schema.py`

The Pydantic `ExperimentManifest` schema has no `watchdog_plugin` field. The `resolve_plugin()` function in `watchdog_plugin.py` tries `getattr(manifest, "watchdog_plugin", None)` which always returns None because the legacy `tools/experiment/manifest.py` dataclass also lacks this field. Plugin resolution falls through to the task-heuristic, which only works for known task prefixes (adversarial, heilbron, hover, hotpotqa, toy).

For mixed experiments (e.g., `adversarial/adversarial-vs-solo` which has task="adversarial" but uses solo runs), the heuristic picks the wrong plugin.

**Fix pattern:** Add `watchdog_plugin: str | None = None` to the Pydantic manifest schema. For the legacy dataclass (tools/experiment/manifest.py), bridge via `_raw` dict in watchdog_cmd.py instead of modifying the tools/ file (running experiment constraint).

### Bug 6: Status Command Metric Formatting Ignores metrics.yaml Display Config [VERIFIED: codebase]

**File:** `gigaevo/cli/status.py` lines 21-23

```python
for name, value in snapshot.metrics.items():
    col_name = name.replace("_", " ").title()
    row[col_name] = value
```

This renders all metrics as raw floats. The `metrics.yaml` specifies `decimals`, `upper_bound` (for percentage display), and `sentinel_value` (for filtering). The tools/README.md says "Fractional metrics (upper_bound=1.0) show as percentages" but the CLI doesn't implement this.

**Fix pattern:** Load `metrics.yaml` specs and format values accordingly (percentage vs raw, decimal places, sentinel filtering).

## Experiment Type Differences

### Metric Structures by Experiment Type [VERIFIED: codebase metrics.yaml files]

| Experiment Type | Example Problem | Primary Metric | Additional Metrics | Sentinel |
|----------------|----------------|---------------|-------------------|----------|
| Standard (hover) | chains/hover/static_soft | fitness | (none beyond is_valid) | -1000.0 |
| Standard (hotpotqa) | chains/hotpotqa/static | fitness | (none beyond is_valid) | -1.0 |
| Adversarial Constructor | heilbron_adversarial/pop_a | fitness | actual_fitness, quality, resistance, mean_improvement, best_post_improvement, n_opponents | -1.0 |
| Adversarial Improver | heilbron_adversarial/pop_b | fitness | actual_fitness, mean_improvement_raw, mean_pre_quality, mean_post_quality, max_post_quality, n_opponents | -1.0 |
| Solo (heilbron) | heilbron | fitness | (none beyond is_valid) | -1000 |
| Solo (heilbron_solo) | heilbron_solo | fitness | (none beyond is_valid) | -1000 |
| Prompt Evolution | prompt_evolution_hover | fitness | prompt_length | -1.0 |

### Pipeline Configurations by Type [VERIFIED: codebase config/pipeline/]

| Pipeline Config | Experiment Type | Special Features |
|----------------|----------------|-----------------|
| standard.yaml | Standard MAP-Elites | Basic stages |
| adversarial.yaml | Adversarial | Opponent fetch + injection stages |
| adversarial_asymmetric.yaml | Asymmetric adversarial | G/D roles, sync hooks |
| adversarial_coevo.yaml | Co-evolution | Main run sync |
| adversarial_coevo_ss.yaml | Steady-state coevo | Progress-based sync |
| adversarial_coevo_feedback.yaml | Feedback coevo | Gradient feedback |
| prompt_evolution.yaml | Prompt co-evolution | Prompt population stages |
| hover_feedback.yaml | Feedback experiments | Additional feedback stages |
| hotpotqa_asi.yaml | HotpotQA ASI | ASI-specific stages |

### Watchdog Plugin Mapping [VERIFIED: codebase watchdog_plugin.py]

| Plugin Name | Registered Class | Task Heuristic |
|-------------|-----------------|----------------|
| solo | SoloPlugin | hover, hotpotqa, toy |
| adversarial | AdversarialPlugin | adversarial |
| heilbron | HeilbronPlugin | heilbron |
| prompt_coevo | PromptCoevoPlugin | (no heuristic -- must be explicit) |

**Gap:** prompt_coevo plugin has NO task heuristic. Task "hover" maps to "solo", so `hover/prompt_coevolution` gets SoloPlugin by default. The user must manually pass `--plugin prompt_coevo` to watchdog or set `watchdog_plugin: prompt_coevo` in experiment.yaml (but that field doesn't exist in the schema).

## Architecture Patterns

### Recommended Fix Approach

The fixes should follow the existing codebase pattern: **run_resolver.py is the canonical bridge** between CLI flags and the monitoring library. All commands should go through it.

### Pattern 1: Metric Discovery Through RunResolver

**What:** All CLI commands that need metric information should call `RunResolver.resolve()` which already handles both `--experiment` (auto-discover from metrics.yaml) and `--run` (defaults to ["fitness"]) modes.

**When to use:** Any command that queries Redis for metric data.

**Example:**
```python
# In watchdog_cmd.py, replace manual RunConfig building:
from gigaevo.cli.run_resolver import RunResolver

run_configs = RunResolver.resolve(
    experiment=experiment,
    runs=(),
    redis_host=config.redis_host,
    redis_port=config.redis_port,
)
# Now run_configs have correct metric_names from metrics.yaml
```

### Pattern 2: Manifest-Aware Plugin Resolution

**What:** Add `watchdog_plugin` field to the Pydantic ExperimentManifest and bridge via `_raw` dict for the legacy dataclass. Propagate to plugin resolution.

**When to use:** When the task-name heuristic is insufficient (e.g., prompt_coevo experiments under hover task).

### Pattern 3: Metric Formatting from metrics.yaml

**What:** Use `metrics.yaml` specs to format display values (percentages, decimal places, sentinel filtering).

**When to use:** Any command that displays metric values to the user.

**Example:**
```python
def format_metric_value(value: float, spec: dict) -> str:
    if value == spec.get("sentinel_value"):
        return "N/A"
    upper = spec.get("upper_bound", None)
    decimals = spec.get("decimals", 3)
    if upper and upper == 1.0:
        return f"{value:.{decimals}%}"
    return f"{value:.{decimals}f}"
```

### Anti-Patterns to Avoid

- **Hardcoding ["fitness"]:** Never hardcode metric names. Always load from metrics.yaml or accept from user.
- **Bypassing RunResolver:** New commands should use `RunResolver.resolve()`, not create RunConfig manually.
- **Duplicating metrics.yaml loading:** Use the existing `_load_metric_names()` function, don't copy-paste the YAML loading logic.
- **Modifying tools/experiment/manifest.py while experiment is running:** STATE.md constraint. Use `_raw` dict bridge instead.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Metric names for a problem | Parse metrics.yaml inline | `run_resolver._load_metric_names()` | Already handles primary sorting, is_valid exclusion, fallback |
| Run resolution from CLI flags | Manual RunConfig construction | `RunResolver.resolve()` | Already handles experiment vs run mode, metric discovery, PID loading |
| Metric value formatting | Ad-hoc f-string formatting | Centralized formatter reading metrics.yaml specs | Consistency across all CLI commands |
| Plugin resolution | Manual if/else on task name | `watchdog_plugin.resolve_plugin()` | Already has registry, heuristic, fallback chain |

## Common Pitfalls

### Pitfall 1: Shared-Prefix Adversarial Runs

**What goes wrong:** Multiple adversarial runs share the same prefix (e.g., `heilbron_adversarial/pop_a@1` and `heilbron_adversarial/pop_a@3`). CLI commands that group by prefix (AdversarialPlugin, PromptCoevoPlugin) need to handle multiple DBs with the same prefix.

**Why it happens:** Adversarial experiments use replicate pairs (A1_G, A2_G) on the same problem (same prefix) but different Redis DBs.

**How to avoid:** Use (prefix, db) tuple or the label as the grouping key, never prefix alone when deduplication matters.

**Warning signs:** Plots showing only one run when multiple replicates exist.

### Pitfall 2: Sentinel Values in Metrics

**What goes wrong:** Metrics like `actual_fitness=-1.0` (sentinel for invalid programs) contaminate means, plots, and status displays.

**Why it happens:** Sentinel values are stored in Redis like normal metric values. The `comparison` plot command already handles this with `sentinel_value=-1.0`, but `trajectory.py` and `status.py` don't filter sentinels.

**How to avoid:** Read `sentinel_value` from `metrics.yaml` and filter before aggregation/display. Already implemented in `plot_group._fetch_run_data()` -- replicate the pattern.

**Warning signs:** Metric values showing -1.0 or -1000.0 in status tables.

### Pitfall 3: Metric Name Mismatch Between Problem Types

**What goes wrong:** The primary metric varies by experiment type. `heilbron` uses `fitness` as MAP-Elites selection metric but `actual_fitness` as the scientifically meaningful metric. Researchers want to see `actual_fitness` in status/trajectory/top but the framework defaults to `fitness`.

**Why it happens:** `metrics.yaml` has `is_primary: true` on `fitness` (the selection metric) but the researcher cares about `actual_fitness` (the raw objective). The `manifest.problem.metric_name` field is supposed to indicate the "headline" metric but it's not used by the CLI.

**How to avoid:** Add concept of "display metric" vs "selection metric". Use `manifest.problem.metric_name` as the default for display when available, fall back to primary metric from metrics.yaml.

### Pitfall 4: Two Manifest Implementations

**What goes wrong:** Changes to manifest parsing need to be made in both `tools/experiment/manifest.py` (legacy dataclass) and `gigaevo/monitoring/manifest_schema.py` (Pydantic v2). They can drift out of sync.

**Why it happens:** The Pydantic schema was added in the v1.0 MVP but the legacy dataclass is still the one used by all CLI commands (via `tools.experiment.manifest.load_manifest`).

**How to avoid:** In this phase, add `watchdog_plugin` only to the Pydantic schema. For the legacy dataclass, bridge via the `_raw` dict in watchdog_cmd.py (reads `manifest._raw.get("watchdog_plugin")` and sets it as a dynamic attribute). This avoids modifying tools/ while the experiment is running. Long-term (out of scope per MIG-02), the legacy schema should be replaced by the Pydantic one.

### Pitfall 5: Running Experiment Constraint

**What goes wrong:** The heilbron/asymmetric-iterations experiment is currently running. Changes to `tools/` or running watchdog imports can break the live experiment.

**Why it happens:** STATE.md constraint: "do NOT touch tools/ or any running watchdog imports".

**How to avoid:** All new code goes in `gigaevo/monitoring/` and `gigaevo/cli/`. Do not modify `tools/` files. Do not change any import used by the running watchdog.

## Code Examples

### Correct metric_names Propagation in watchdog_cmd.py

```python
# Source: gigaevo/cli/run_resolver.py pattern (verified in codebase)
from gigaevo.cli.run_resolver import _load_metric_names

run_configs = []
for run in manifest.runs:
    spec = RunSpec(prefix=run.prefix, db=run.db, label=run.label)
    metric_names = _load_metric_names(run.problem_name)
    rc = RunConfig(run_spec=spec, metric_names=metric_names, pid=run.pid)
    run_configs.append(rc)
```

### Multi-Metric Trajectory Display

```python
# Pattern for trajectory with multiple metrics
for rc in run_configs:
    for metric in rc.metric_names:
        rows = _fetch_trajectory(r, spec.prefix, metric)
        for row in rows:
            row["Metric"] = metric
        all_rows.extend(rows)
```

### Metric Formatting with specs.yaml

```python
# Source: tools/README.md + metrics.yaml pattern (verified in codebase)
def _format_metric(value: float | None, name: str, specs: dict) -> str:
    if value is None:
        return "?"
    spec = specs.get(name, {})
    sentinel = spec.get("sentinel_value")
    if sentinel is not None and value == sentinel:
        return "N/A"
    decimals = spec.get("decimals", 3)
    upper_bound = spec.get("upper_bound", None)
    if upper_bound == 1.0:
        return f"{value * 100:.{max(0, decimals - 2)}f}%"
    return f"{value:.{decimals}f}"
```

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x |
| Config file | `pyproject.toml` (pytest section) |
| Quick run command | `/run-tests tests/cli/` |
| Full suite command | `/run-tests` |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BUG-01 | watchdog_cmd passes metric_names from metrics.yaml | unit | `/run-tests tests/cli/test_watchdog_cmd.py` | Yes (extend) |
| BUG-02 | trajectory supports multi-metric display | unit | `/run-tests tests/cli/test_trajectory_cmd.py` | Yes (extend) |
| BUG-03 | top uses problem.metric_name as default ranking metric | unit | `/run-tests tests/cli/test_top_cmd.py` | Yes (extend) |
| BUG-04 | analyze/collect wired into CLI registry | unit | `/run-tests tests/cli/test_cli_group.py` | Yes (extend) |
| BUG-05 | manifest schema has watchdog_plugin field | unit | `/run-tests tests/monitoring/test_manifest_schema.py` | Yes (extend) |
| BUG-06 | status formats metrics per metrics.yaml specs | unit | `/run-tests tests/cli/test_status_cmd.py` | Yes (extend) |

### Sampling Rate

- **Per task commit:** `/run-tests tests/cli/ tests/monitoring/`
- **Per wave merge:** `/run-tests`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] Test helpers for multi-metric fakeredis population (extend `_populate_run` in test_status_cmd.py to accept arbitrary metric names/values)
- [ ] Test fixture for adversarial-type metrics.yaml (7+ metrics with sentinels)
- [ ] Test fixture for prompt-coevo-type metrics.yaml (fitness + prompt_length)

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Individual `tools/*.py` scripts | `gigaevo` CLI with lazy subcommands | v1.0 MVP (2026-04-12) | Unified entry point |
| tools/experiment/manifest.py only | Pydantic manifest_schema.py added | v1.0 MVP (2026-04-12) | Strict validation, JSON Schema export |
| No watchdog plugin system | WatchdogPlugin ABC + 4 plugins | v1.0 MVP (2026-04-12) | Type-aware monitoring |
| Manual metric querying | ExperimentMonitor + RunSnapshot | v1.0 MVP (2026-04-12) | Composable monitoring |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The user wants ALL experiment types covered (not just adversarial) | Summary | Scope would shrink to adversarial only -- less work but less value |
| A2 | `analyze` and `collect` commands should be wired into the standard CLI registry | Bug 4 | They could remain standalone -- but this contradicts CLI-01 requirement |
| A3 | Sentinel value filtering should use the value from metrics.yaml, not hardcoded -1.0 | Pitfall 2 | Different problems use different sentinels (-1.0, -1000.0, 0) -- hardcoding would miss some |

Note: A1 is based on explicit user clarification in the phase prompt. A2 and A3 are grounded in the existing codebase patterns and REQUIREMENTS.md (CLI-01 specifies unified entry point).

## Open Questions (RESOLVED)

1. **Should `analyze` and `collect` be refactored to use RunResolver or deprecated?** (RESOLVED)
   - What we know: They duplicate metric-loading logic and bypass the standard CLI flag system. They use `--prefix`/`--db` instead of `--run`/`--experiment`.
   - What's unclear: Whether they are used by any automated tools or skills that depend on their current interface.
   - **Resolution:** Wire them into the CLI registry only (no interface refactor). Preserve `--prefix`/`--db` for backward compatibility. Full RunResolver migration deferred to a future phase.

2. **Should the legacy manifest (`tools/experiment/manifest.py`) be updated to include `watchdog_plugin`?** (RESOLVED)
   - What we know: The Pydantic schema (`manifest_schema.py`) should get this field. The legacy dataclass is what all running code actually uses.
   - What's unclear: Whether adding a field to the legacy dataclass risks breaking the running experiment.
   - **Resolution:** Do NOT modify tools/experiment/manifest.py (STATE.md constraint: running experiment). Add `watchdog_plugin` only to Pydantic schema. Bridge in watchdog_cmd.py by reading `manifest._raw.get("watchdog_plugin")` and setting as dynamic attribute for `resolve_plugin()`.

3. **What should be the "display metric" for adversarial experiments?** (RESOLVED)
   - What we know: `manifest.problem.metric_name` is set to "actual_fitness" for heilbron experiments and "fitness" for most others. The composite `fitness` drives MAP-Elites selection but `actual_fitness` is what researchers report.
   - What's unclear: Whether to always display `metric_name` prominently or show all metrics equally.
   - **Resolution:** Use `manifest.problem.metric_name` as the default ranking metric in `top` command. Show all discovered metrics in `trajectory` and `status`. The headline metric is the one researchers care about for ranking; all metrics are visible for monitoring.

## Environment Availability

Step 2.6: SKIPPED (no external dependencies identified). This phase is purely code/config changes within `gigaevo/cli/` and `gigaevo/monitoring/`.

## Security Domain

Not applicable -- this phase involves CLI output formatting and manifest schema updates. No authentication, input validation at trust boundaries, cryptography, or access control changes.

## Sources

### Primary (HIGH confidence)

- `gigaevo/cli/watchdog_cmd.py` -- Verified missing metric_names in RunConfig construction (lines 75-80)
- `gigaevo/cli/run_resolver.py` -- Verified correct metric loading via `_load_metric_names()` (lines 21-47)
- `gigaevo/monitoring/experiment_monitor.py` -- Verified RunConfig.metric_names defaults to ["fitness"] (line 24)
- `gigaevo/monitoring/redis_queries.py` -- Verified collect_snapshot uses metric_names parameter (line 147)
- `gigaevo/monitoring/watchdog_plugin.py` -- Verified plugin registry and task heuristic (lines 101-107)
- `problems/heilbron_adversarial/pop_a/metrics.yaml` -- 7 metrics for adversarial constructor
- `problems/heilbron_adversarial/pop_b/metrics.yaml` -- 8 metrics for adversarial improver
- `problems/prompt_evolution_hover/metrics.yaml` -- 3 metrics for prompt evolution
- `experiments/heilbron/asymmetric-iterations/experiment.yaml` -- Live adversarial manifest
- `experiments/hover/prompt_coevolution/experiment.yaml` -- Prompt coevo manifest

### Secondary (MEDIUM confidence)

- `experiments/heilbron/asymmetric-iterations/04_issues_log.md` -- MetricsTracker crash confirms frontier metric staleness is a real production issue
- `.planning/REQUIREMENTS.md` -- CLI-01 through CLI-06, MAN-01 through MAN-03 define the target architecture

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- pure Python changes in existing modules, no new dependencies
- Architecture: HIGH -- follows established patterns in the codebase (RunResolver, ExperimentMonitor, plugins)
- Pitfalls: HIGH -- all identified from actual experiment issues logs and code analysis

**Research date:** 2026-04-13
**Valid until:** 2026-05-13 (30 days -- stable codebase patterns)
