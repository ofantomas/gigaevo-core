# Phase 5: Polish CLI/watchdog/manifest wiring — Research

**Researched:** 2026-04-13
**Domain:** CLI wiring, plugin resolution, manifest consolidation, legacy import elimination
**Confidence:** HIGH

## Summary

Phase 5 is a reliability and consolidation phase. The CLI, watchdog, and manifest systems were built in Phases 1-5 (v1.0 MVP) but integrated with each other through `tools/` imports that break when the `gigaevo` package is installed via pip (no PYTHONPATH). The issues log from the running heilbron/asymmetric-iterations experiment documents the exact failures: `ModuleNotFoundError: No module named 'tools'` when invoking `gigaevo watchdog`, dual manifest shape crashes in `resolve_plugin()`, and a `manifest` subcommand that skills invoke but is not registered in the CLI.

The phase has three distinct work streams: (1) eliminate all `from tools.*` imports in `gigaevo/cli/` by migrating the needed functions into the `gigaevo` package, (2) consolidate the dual manifest system (Pydantic in `gigaevo/monitoring/manifest_schema.py` vs legacy dataclass in `tools/experiment/manifest.py`) into a single Pydantic schema, and (3) merge the `heilbron` plugin into `adversarial` and delete the task-name heuristic. All decisions are locked in CONTEXT.md.

**Primary recommendation:** Execute in 3-4 plans: (1) manifest consolidation + CLI registration, (2) tools/ import elimination in CLI modules, (3) plugin merge + resolve_plugin rewrite, (4) skill/agent audit. Each plan is independently testable.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Plugin is declared EXPLICITLY in `experiment.yaml` via the `watchdog_plugin` field. If absent, fall back to `solo`. No heuristic guessing. Delete `_TASK_HEURISTIC` dict entirely.
- **D-02:** Merge `heilbron` plugin into `adversarial` plugin. The adversarial plugin becomes the single plugin for all adversarial/co-evolution experiments. Delete `gigaevo/monitoring/plugins/heilbron.py`.
- **D-03:** Plot metrics are specified per-experiment in `experiment.yaml` as `watchdog_plugin_options: {plot_metrics: [fitness, actual_fitness]}`. These are validated against `metrics.yaml` — every metric in `plot_metrics` must exist in the problem's `metrics.yaml`. If a metric is listed but not found, warn loudly.
- **D-04:** Pydantic manifest (`gigaevo/monitoring/manifest_schema.py`) is the single source of truth. Remove the legacy dataclass from `tools/experiment/manifest.py`. All callers (CLI, watchdog, skills, agents) migrate to the Pydantic schema.
- **D-05:** Fix `resolve_plugin()` to use `manifest.experiment.task` correctly (Pydantic shape), since the legacy dataclass that used `manifest.task` is being removed.
- **D-06:** Move ALL useful `tools/` functionality into the `gigaevo/` package. Not just fixing broken imports — full migration. Functions used by CLI commands, plotting, data export, lineage, preflight checks, archiving — all move into `gigaevo/`.
- **D-07:** After migration, `gigaevo/cli/` and `gigaevo/monitoring/` must have ZERO imports from `tools/`. The `tools/` directory remains for standalone scripts that haven't been migrated yet, but the installed `gigaevo` package is self-contained.
- **D-08:** Audit ALL experiment lifecycle skills (`.claude/skills/experiment-*/SKILL.md`) for incorrect CLI flags, wrong argument formats, and references to non-existent commands. Fix every incorrect invocation.
- **D-09:** Audit ALL agents (`.claude/agents/*.md`) for the same issues. Agents must use the correct `gigaevo` CLI API — no stale command references, no wrong flags.

### Claude's Discretion
- Internal package structure for migrated tools/ code (e.g., `gigaevo/tools/` vs `gigaevo/cli/utils/` vs spreading across existing modules)
- Whether to keep `tools/` scripts as thin wrappers calling `gigaevo` internals, or delete them entirely
- How to handle `tools/comparison.py` subprocess calls in plugins (inline the logic vs keep as CLI command)

### Deferred Ideas (OUT OF SCOPE)
- Generation-aware sync hook for SteadyState (ProgressBasedSyncHook only syncs programs_processed, not generations) — logged in 04_issues_log.md, needs its own phase
- Watch mode / Rich Live dashboard (deferred from v1.0)
- Configurable alert routing (deferred from v1.0)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| D-01 | Explicit plugin declaration in experiment.yaml, delete _TASK_HEURISTIC | Plugin resolution architecture mapped; _TASK_HEURISTIC at watchdog_plugin.py:101-107; resolve_plugin() at line 139 |
| D-02 | Merge heilbron plugin into adversarial | Both plugins analyzed: heilbron.py is 159 lines with multi-metric bar chart panel, adversarial.py is 132 lines with subprocess comparison.py calls; heilbron is more advanced and should be the merge target pattern |
| D-03 | watchdog_plugin_options with plot_metrics validated against metrics.yaml | _load_metric_names() already exists in run_resolver.py:21; metrics.yaml format documented |
| D-04 | Pydantic manifest as single source of truth | Both manifests fully analyzed: Pydantic at manifest_schema.py (271 lines, ExperimentManifest with nested Pydantic models), legacy at tools/experiment/manifest.py (622 lines, flat dataclass with Redis locking + mutation API) |
| D-05 | Fix resolve_plugin() for Pydantic shape | Crash at line 169: `manifest.experiment.task` works for Pydantic but not legacy dataclass which uses `manifest.task` |
| D-06 | Migrate tools/ functionality into gigaevo package | 4 tools/ modules consumed by CLI: manifest.py (load/set/update/generate_pr), flush.py (kill workers + flush), utils.py (prepare_iteration_dataframe), comparison.py (_annotate_frontier_points) |
| D-07 | Zero tools/ imports in gigaevo/cli/ and gigaevo/monitoring/ | 17 import sites mapped across 8 CLI files |
| D-08 | Audit skills for CLI correctness | 10 skills with 80+ gigaevo invocations found; manifest subcommand NOT registered (critical bug) |
| D-09 | Audit agents for CLI correctness | anomaly-detector.md uses `gigaevo -r "prefix@db:label" trajectory --tail 5` (verified: --tail flag exists) |
</phase_requirements>

## Architecture Patterns

### Current Import Dependency Map

Every `tools/` import site in `gigaevo/cli/` and `gigaevo/monitoring/`:

```
gigaevo/cli/manifest_cmd.py
  L113  from tools.experiment.manifest import load_manifest
  L194  from tools.experiment.manifest import set_status
  L219  from tools.experiment.manifest import update_manifest
  L243  from tools.experiment.manifest import load_manifest
  L276  from tools.experiment.manifest import generate_pr_description
  L282  from tools.experiment.manifest import load_manifest

gigaevo/cli/run_resolver.py
  L16   from tools.experiment.manifest import load_manifest

gigaevo/cli/watchdog_cmd.py
  L56   from tools.experiment.manifest import load_manifest

gigaevo/cli/lifecycle.py
  L28   from tools.experiment.manifest import load_manifest
  L63   from tools.experiment.manifest import load_manifest
  L97   from tools.experiment.manifest import load_manifest

gigaevo/cli/top.py
  L80   from tools.experiment.manifest import load_manifest

gigaevo/cli/flush.py
  L9    from tools.flush import (find_exec_runner_pids, flush_db,
                                  kill_run_writers, kill_workers)

gigaevo/cli/export.py
  L31   from tools.utils import fetch_evolution_dataframe

gigaevo/cli/plot_group.py
  L53   from tools.utils import (fetch_evolution_dataframe,
                                  prepare_iteration_dataframe)
  L223  from tools.comparison import _annotate_frontier_points
```

[VERIFIED: codebase grep] Zero `tools/` imports in `gigaevo/monitoring/` — only CLI modules are affected.

### Manifest Shape Differences

The legacy dataclass (tools/experiment/manifest.py) and Pydantic manifest (gigaevo/monitoring/manifest_schema.py) have DIFFERENT shapes:

| Attribute | Legacy Dataclass | Pydantic |
|-----------|-----------------|----------|
| Name | `manifest.name` | `manifest.experiment.name` |
| Task | `manifest.task` | `manifest.experiment.task` |
| Status | `manifest.status` | `manifest.experiment.status` |
| Max generations | `manifest.max_generations` | `manifest.experiment.max_generations` |
| Branch | `manifest.branch` | `manifest.experiment.branch` |
| PR number | `manifest.pr_number` | `manifest.experiment.pr_number` |
| Tracking issue | `manifest.tracking_issue` | `manifest.experiment.tracking_issue` |
| Problem | `manifest.problem` (ProblemSpec dataclass) | `manifest.problem` (ProblemSpec Pydantic) |
| Runs | `manifest.runs` (list[RunSpec]) | `manifest.runs` (list[ManifestRunSpec]) |
| Raw dict | `manifest._raw` | `manifest.to_dict()` / `manifest.model_dump()` |

[VERIFIED: code inspection of both files]

**Critical implication:** Migrating to Pydantic changes every `manifest.name` to `manifest.experiment.name`, etc. This affects ALL CLI commands, skills, and agents that read manifest fields. The migration MUST update every access site.

### Functions to Migrate from tools/

| Source File | Functions | Target | Why |
|-------------|-----------|--------|-----|
| `tools/experiment/manifest.py` | `load_manifest`, `set_status`, `update_manifest`, `generate_pr_description`, `experiment_dir`, `manifest_path`, `claim_dbs`, `refresh_db_claims`, `release_db_claims`, `find_active_experiments`, `has_test_set` | `gigaevo/monitoring/manifest.py` (new) | 12 callers in CLI; Redis locking logic must be preserved |
| `tools/flush.py` | `find_exec_runner_pids`, `flush_db`, `kill_run_writers`, `kill_workers` | `gigaevo/cli/flush_ops.py` (new) or inline in `flush.py` | 1 caller (flush.py); self-contained process management |
| `tools/utils.py` | `prepare_iteration_dataframe`, `detect_outliers`, `OutlierMethod`, `fetch_frontier_from_redis`, `add_frontier_from_redis_to_dataframe` | `gigaevo/utils/dataframes.py` (new) | 2 callers (plot_group.py, export.py); `fetch_evolution_dataframe` already in `gigaevo/utils/redis.py` |
| `tools/comparison.py` | `_annotate_frontier_points` | `gigaevo/utils/plotting.py` (new) | 1 caller (plot_group.py); 70-line function, trivially extractable |

[VERIFIED: code inspection]

### Plugin Architecture After Merge

Current state:
- `solo.py` — subprocess to `tools/comparison.py` for plots
- `adversarial.py` — subprocess to `tools/comparison.py`, group by prefix
- `heilbron.py` — matplotlib inline, multi-metric panel, group by prefix
- `prompt_coevo.py` — subprocess to `tools/comparison.py`, group by prefix

After merge (D-02):
- `solo.py` — keep as-is (but migrate comparison.py subplot away from tools/)
- `adversarial.py` — absorb heilbron's multi-metric panel pattern, make labels/metrics configurable via `watchdog_plugin_options`
- `prompt_coevo.py` — keep as-is (but migrate comparison.py subplot away from tools/)
- `heilbron.py` — DELETE

The heilbron plugin's pattern (matplotlib inline, multi-metric) is MORE advanced than the adversarial plugin (subprocess to comparison.py). The merged adversarial plugin should adopt the heilbron pattern with configurable metrics from `watchdog_plugin_options.plot_metrics`.

### Plugin subprocess dependency on tools/comparison.py

Three plugins (`solo`, `adversarial`, `prompt_coevo`) call `tools/comparison.py` via subprocess:
```python
cmd = [sys.executable, str(_PROJ / "tools" / "comparison.py"), ...]
subprocess.run(cmd, cwd=str(_PROJ), env={"PYTHONPATH": str(_PROJ)}, ...)
```

This is fragile: requires PYTHONPATH manipulation and hard path to `tools/`. Per CONTEXT.md (Claude's Discretion), the choice is "inline the logic vs keep as CLI command."

**Recommendation:** Inline the plotting logic. The `gigaevo/cli/plot_group.py` already has a full matplotlib implementation of comparison plots (lines 153-437). The plugins should call a shared plotting function from `gigaevo/utils/plotting.py` instead of shelling out to `tools/comparison.py`. This eliminates the subprocess + PYTHONPATH hack entirely.

[VERIFIED: code inspection of all 3 plugins and plot_group.py]

### Critical Bug: `manifest` Subcommand Not Registered

The `manifest` subcommand group (`gigaevo/cli/manifest_cmd.py`) exists but is NOT in `_LAZY_SUBCOMMANDS` in `gigaevo/cli/__init__.py`. Every skill invocation of `gigaevo -e "$EXP" manifest get|set|update|gate|pr-description` fails with "No such command 'manifest'."

[VERIFIED: `_LAZY_SUBCOMMANDS` dict inspection + runtime test confirming `gigaevo manifest` returns exit code 2]

Skills that invoke `gigaevo manifest` (10 skills, 80+ invocations):
- experiment-implement, experiment-launch, experiment-closeout, experiment-checkpoint
- experiment-restart, experiment-design, experiment-diagnose, run-experiment
- experiment-closeout/references/merge-rules.md
- experiment-implement/references/smoke-test-checklist.md

The existing tests in `tests/cli/test_manifest_cmd.py` PASS because they patch `tools.experiment.manifest` and invoke the Click runner with `main` directly. The tests mock the import, so the missing registration is masked.

**Fix:** Add `"manifest": ("gigaevo.cli.manifest_cmd", "manifest")` to `_LAZY_SUBCOMMANDS`.

### Manifest Migration: What Must Be Preserved

The legacy `tools/experiment/manifest.py` (622 lines) has features beyond simple load/validate:

1. **Redis-based locking** (`_acquire_lock`, `_release_lock`) — FUSE filesystem doesn't support fcntl.flock; uses Redis SET NX with TTL
2. **Atomic writes** (`_write_manifest_atomic`) — tmp + rename for NFS safety
3. **Status state machine** (`VALID_TRANSITIONS`, `RECOVERY_TRANSITIONS`) — enforces valid status transitions
4. **DB claims** (`claim_dbs`, `refresh_db_claims`, `release_db_claims`) — Redis SET NX for exclusive DB ownership
5. **PR description generation** (`generate_pr_description`) — markdown generation from manifest state
6. **Mutation API** (`set_status`, `update_manifest`) — read-modify-write under lock

The Pydantic `ExperimentManifest` currently handles only parsing and validation. The migration must add the mutation/locking/state-machine layer ON TOP of the Pydantic schema, not replace the legacy module with just the Pydantic class.

[VERIFIED: code inspection of tools/experiment/manifest.py lines 356-622]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| YAML round-trip | Custom YAML writer | `yaml.safe_dump` with `_write_manifest_atomic` pattern | Existing atomic write pattern is proven on NFS/FUSE |
| Manifest locking | File locks | Redis SET NX with TTL | FUSE filesystem; fcntl.flock does not work on NFS |
| Plot comparison curves | New plotting from scratch | Port existing `plot_group.py` matplotlib code into shared util | 680+ lines of working plot code already exists |
| Process kill logic | New kill implementation | Port `tools/flush.py` functions directly | Handles orphan detection, PID scanning, race conditions |

## Common Pitfalls

### Pitfall 1: Manifest Shape Migration Breaks Callers Silently
**What goes wrong:** After switching from legacy dataclass to Pydantic manifest, callers using `manifest.name` get AttributeError because the field moved to `manifest.experiment.name`.
**Why it happens:** The two manifest classes have fundamentally different shapes (flat vs nested).
**How to avoid:** Add compatibility properties on the Pydantic ExperimentManifest class: `@property def name(self) -> str: return self.experiment.name` etc. This lets callers work with both old and new access patterns during migration. OR do a clean break and update all access sites in one pass.
**Warning signs:** AttributeError on manifest.name, manifest.task, manifest.status in any CLI command or skill.

### Pitfall 2: Legacy Manifest Has Mutation API, Pydantic Doesn't
**What goes wrong:** Switching to Pydantic manifest for loading is easy, but `set_status()` and `update_manifest()` operate on raw dicts with Redis locking. If you naively replace the import, you lose the locking and atomic write.
**Why it happens:** Pydantic ExperimentManifest is read-only (parse + validate). The mutation API is in the legacy module.
**How to avoid:** Create a new `gigaevo/monitoring/manifest.py` that wraps the Pydantic schema with the mutation operations. Migrate the Redis locking, atomic write, and state machine from the legacy module.
**Warning signs:** Concurrent manifest writes corrupting experiment.yaml; status transitions that should be blocked succeed.

### Pitfall 3: Plugin subprocess calls break when tools/ is removed
**What goes wrong:** solo, adversarial, and prompt_coevo plugins shell out to `tools/comparison.py` with `PYTHONPATH=<project_root>`. If tools/ code is deleted or moved, these break.
**Why it happens:** Plugins use subprocess rather than importing comparison logic.
**How to avoid:** Before deleting any tools/ code, first replace all subprocess calls in plugins with direct function calls to the migrated code.
**Warning signs:** Watchdog plot generation fails with FileNotFoundError or ModuleNotFoundError.

### Pitfall 4: Test mocks hide real integration bugs
**What goes wrong:** Tests for manifest_cmd.py pass because they mock `tools.experiment.manifest`. After migration, the mock path changes but tests still pass because they mock the wrong module.
**Why it happens:** Tests patch `tools.experiment.manifest.load_manifest` by string path. When the real code moves to `gigaevo.monitoring.manifest`, the mock target must also change.
**How to avoid:** Update ALL mock paths in test files when changing import paths. Search for the old path string across all test files.
**Warning signs:** Tests pass but real CLI invocations fail.

### Pitfall 5: Running experiment affected by manifest migration
**What goes wrong:** The heilbron/asymmetric-iterations experiment is currently running. Changing `tools/experiment/manifest.py` could break the running watchdog or anomaly detector.
**Why it happens:** Running processes import from `tools/` at startup; new processes import from `gigaevo/`.
**How to avoid:** Do NOT delete or modify `tools/experiment/manifest.py`. Create the new module alongside it. The old module stays until the running experiment completes.
**Warning signs:** Running watchdog crashes after a git pull.

## Code Examples

### Pattern 1: Manifest Module Migration (new gigaevo/monitoring/manifest.py)

```python
# Source: derived from tools/experiment/manifest.py + manifest_schema.py
"""Manifest operations: load, mutate, lock, validate.

Wraps the Pydantic ExperimentManifest with Redis-based locking,
atomic YAML writes, and status state machine.
"""
from __future__ import annotations
from pathlib import Path
from gigaevo.monitoring.manifest_schema import ExperimentManifest

PROJ = Path(__file__).parent.parent.parent  # gigaevo/monitoring/manifest.py -> repo root

def experiment_dir(experiment: str) -> Path:
    return PROJ / "experiments" / experiment

def manifest_path(experiment: str) -> Path:
    return experiment_dir(experiment) / "experiment.yaml"

def load_manifest(experiment: str) -> ExperimentManifest:
    """Load and validate experiment.yaml using Pydantic schema."""
    path = manifest_path(experiment)
    return ExperimentManifest.from_yaml_file(path)

# set_status, update_manifest, claim_dbs, etc. — same Redis locking
# pattern from tools/experiment/manifest.py but returning Pydantic objects
```

[ASSUMED — exact implementation depends on Claude's discretion for package structure]

### Pattern 2: Plugin Resolution After Rewrite

```python
# Source: derived from CONTEXT.md D-01 decision
def resolve_plugin(manifest=None) -> type[WatchdogPlugin]:
    """Resolve plugin: explicit field > solo fallback. No heuristics."""
    if manifest is not None:
        explicit = manifest.watchdog_plugin  # Pydantic field, not getattr
        if explicit:
            if explicit not in _REGISTRY:
                raise KeyError(f"Plugin '{explicit}' not found. Available: {sorted(_REGISTRY)}")
            return _REGISTRY[explicit]
    # Fallback to solo — no _TASK_HEURISTIC
    return _REGISTRY["solo"]
```

[VERIFIED: based on CONTEXT.md D-01 locked decision]

### Pattern 3: Register manifest in CLI

```python
# In gigaevo/cli/__init__.py, add to _LAZY_SUBCOMMANDS:
_LAZY_SUBCOMMANDS: dict[str, tuple[str, str]] = {
    # ... existing entries ...
    "manifest": ("gigaevo.cli.manifest_cmd", "manifest"),
    # ... existing entries ...
}
```

[VERIFIED: _LAZY_SUBCOMMANDS structure from __init__.py inspection]

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (via `/run-tests` skill) |
| Config file | pyproject.toml `[tool.pytest]` section |
| Quick run command | `/run-tests tests/cli/` |
| Full suite command | `/run-tests` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| D-01 | resolve_plugin uses explicit field only, no heuristic | unit | `/run-tests tests/monitoring/test_watchdog_plugin.py` | Yes (update needed) |
| D-02 | Adversarial plugin handles multi-metric; heilbron deleted | unit | `/run-tests tests/monitoring/plugins/` | Yes (update needed) |
| D-03 | watchdog_plugin_options.plot_metrics validated against metrics.yaml | unit | `/run-tests tests/monitoring/test_watchdog_plugin.py` | Wave 0 |
| D-04 | Pydantic manifest loads/validates/mutates correctly | unit | `/run-tests tests/monitoring/test_manifest_schema.py` | Yes (extend) |
| D-05 | resolve_plugin works with Pydantic manifest shape | unit | `/run-tests tests/monitoring/test_watchdog_plugin.py` | Yes (update) |
| D-06 | Migrated functions work from gigaevo package | unit | `/run-tests tests/cli/` | Wave 0 (new tests for migrated modules) |
| D-07 | Zero tools/ imports in gigaevo/cli/ and gigaevo/monitoring/ | smoke | `grep -r "from tools\." gigaevo/cli/ gigaevo/monitoring/` returns empty | Manual verification |
| D-08 | Skills use correct CLI commands | smoke | `gigaevo manifest --help` returns help, not error | Manual + integration |
| D-09 | Agents use correct CLI commands | smoke | Agent invocations in anomaly-detector.md verified against CLI | Manual |

### Sampling Rate
- **Per task commit:** `/run-tests tests/cli/ tests/monitoring/`
- **Per wave merge:** `/run-tests` (full suite, ~4800 tests)
- **Phase gate:** Full suite green + `grep -r "from tools\." gigaevo/cli/ gigaevo/monitoring/` returns empty

### Wave 0 Gaps
- [ ] Tests for new `gigaevo/monitoring/manifest.py` module (load, set_status, update_manifest with Pydantic)
- [ ] Tests for watchdog_plugin_options.plot_metrics validation
- [ ] Tests for manifest CLI registration (`gigaevo manifest get status` works end-to-end)
- [ ] Update test mock paths from `tools.experiment.manifest` to new module path
- [ ] Tests for migrated flush_ops (if extracted to separate module)

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `gigaevo/monitoring/manifest.py` is the right location for the migrated manifest operations | Architecture Patterns | Low — just a file path, easily changed |
| A2 | Compatibility properties on Pydantic manifest can bridge the shape difference | Pitfalls | Medium — if callers use `._raw` extensively, properties may not suffice |
| A3 | Running experiment processes won't be affected because they import at startup and don't reimport on git pull | Pitfalls | Low — Python imports are cached per process |
| A4 | The `tools/` scripts should be kept as-is (not deleted) for backward compatibility with running experiments | Pitfalls | Medium — user may want them deleted; CONTEXT.md says "remain for standalone scripts" |

## Open Questions

1. **Manifest compatibility during migration**
   - What we know: Legacy callers use `manifest.name`, Pydantic uses `manifest.experiment.name`
   - What's unclear: Should we add @property shims on ExperimentManifest or do a clean break?
   - Recommendation: Add @property shims (`name`, `task`, `status`, `max_generations`, `branch`) for backward compatibility, with deprecation warnings. Clean break would require updating 80+ skill invocations simultaneously.

2. **Plugin plot generation: inline vs subprocess**
   - What we know: 3 plugins call `tools/comparison.py` via subprocess; plot_group.py has equivalent matplotlib code
   - What's unclear: Should plugins share the plot_group.py implementation, or should each plugin keep its own?
   - Recommendation: Extract a `generate_comparison_plot()` function from plot_group.py into `gigaevo/utils/plotting.py`. Plugins call this function directly. This eliminates the subprocess hack and preserves plot styling consistency (user requested "nice and curvy" plots).

3. **Whether tools/ scripts get thin wrappers or stay as-is**
   - What we know: CONTEXT.md says this is Claude's discretion
   - What's unclear: Whether any external automation calls `PYTHONPATH=. python tools/comparison.py` directly
   - Recommendation: Keep `tools/` scripts unchanged. They work fine when invoked from project root with PYTHONPATH. The goal is to make `gigaevo` CLI self-contained, not to delete tools/.

## Sources

### Primary (HIGH confidence)
- `gigaevo/cli/__init__.py` — CLI registration, lazy subcommand dict [VERIFIED: code inspection]
- `gigaevo/monitoring/watchdog_plugin.py` — Plugin ABC, registry, _TASK_HEURISTIC, resolve_plugin [VERIFIED: code inspection]
- `gigaevo/monitoring/manifest_schema.py` — Pydantic ExperimentManifest (271 lines) [VERIFIED: code inspection]
- `tools/experiment/manifest.py` — Legacy dataclass + mutation API (622 lines) [VERIFIED: code inspection]
- `gigaevo/cli/manifest_cmd.py` — Manifest CLI group (not registered) [VERIFIED: code inspection + runtime test]
- `gigaevo/monitoring/plugins/heilbron.py` — 159 lines, multi-metric panel [VERIFIED: code inspection]
- `gigaevo/monitoring/plugins/adversarial.py` — 132 lines, subprocess comparison.py [VERIFIED: code inspection]
- `tools/flush.py` — Process kill + DB flush (307 lines) [VERIFIED: code inspection]
- `tools/utils.py` — prepare_iteration_dataframe, outlier detection (490 lines) [VERIFIED: code inspection]
- `tools/comparison.py` — _annotate_frontier_points at line 612 (1121 lines total) [VERIFIED: code inspection]
- `.claude/skills/experiment-*/SKILL.md` — 10 skills with 80+ `gigaevo manifest` invocations [VERIFIED: grep]
- `.claude/agents/anomaly-detector.md` — 8 `gigaevo` invocations [VERIFIED: grep]

### Secondary (MEDIUM confidence)
- Runtime test confirming `gigaevo manifest` fails with exit code 2 [VERIFIED: CliRunner test]
- All `tools/` import sites in `gigaevo/cli/` — 17 import statements across 8 files [VERIFIED: grep]

## Metadata

**Confidence breakdown:**
- Import elimination: HIGH — all 17 import sites mapped with line numbers
- Manifest consolidation: HIGH — both schemas fully analyzed, shape differences documented
- Plugin merge: HIGH — both plugins read, architectural differences understood
- Skill/agent audit: HIGH — all invocations grep'd, manifest registration bug confirmed
- Package structure: MEDIUM — exact file locations are Claude's discretion

**Research date:** 2026-04-13
**Valid until:** 2026-04-27 (stable codebase, internal project)
