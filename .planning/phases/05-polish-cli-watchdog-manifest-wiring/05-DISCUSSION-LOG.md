# Phase 5: Polish CLI/watchdog/manifest wiring - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-13
**Phase:** 05-polish-cli-watchdog-manifest-wiring
**Areas discussed:** Plugin Resolution, Plot Metric Configuration, Manifest Consolidation, Legacy tools/ Migration, Agent/Skill CLI Reliability

---

## 1. Plugin Resolution

| Option | Description | Selected |
|--------|-------------|----------|
| experiment.yaml `watchdog_plugin` field | Plugin declared explicitly per-experiment | ✓ |
| metrics.yaml `plugin` field | Plugin declared per-problem in metrics.yaml | |
| Heuristic from task name | Current `_TASK_HEURISTIC` approach | |

**User's choice:** Plugin declared in `experiment.yaml` via `watchdog_plugin` field. Fallback to `solo` if absent. Delete `_TASK_HEURISTIC` entirely.

**Follow-up:** Should heilbron plugin remain separate or merge into adversarial?
- **User's choice:** Merge heilbron into adversarial. One adversarial plugin for all adversarial/co-evolution experiments.

**Notes:** User strongly prefers zero heuristic guessing. "I want either explicit or solo, no guessing."

---

## 2. Plot Metric Configuration

| Option | Description | Selected |
|--------|-------------|----------|
| Hardcoded per-plugin | Each plugin knows its metrics (current approach) | |
| experiment.yaml `watchdog_plugin_options` | Metrics specified per-experiment, validated against metrics.yaml | ✓ |
| Auto-discover from metrics.yaml | Read all metrics from problem's metrics.yaml | |

**User's choice:** Plot metrics specified in `experiment.yaml` as `watchdog_plugin_options: {plot_metrics: [fitness, actual_fitness]}`. Validated against `metrics.yaml` — every metric in `plot_metrics` must exist in the problem's `metrics.yaml`.

**Follow-up:** How to validate? (A) Warn loudly if metric missing, (B) Hard fail if metric missing
- **User's choice:** D — warn loudly + validate against metrics.yaml. Not a hard fail.

**Notes:** User also mentioned that `gigaevo plot` CLI must match the "nice and curvy" styling from `tools/comparison.py` watchdog plots. The current CLI plots lack the smoothing/styling that was debugged into the watchdog plots.

---

## 3. Manifest Consolidation

| Option | Description | Selected |
|--------|-------------|----------|
| Pydantic manifest wins | Remove legacy dataclass, migrate all callers to Pydantic | ✓ |
| Legacy dataclass wins | Keep flat structure, remove Pydantic | |
| Shape-agnostic adapter | Make resolve_plugin() work with both | |

**User's choice:** Pydantic manifest (`gigaevo/monitoring/manifest_schema.py`) is the single source of truth. Remove the legacy dataclass from `tools/experiment/manifest.py`. All callers migrate to Pydantic schema.

**Notes:** User explicitly rejected the shape-agnostic adapter approach — "we need to do polish of entire tools/skills/agent/cli/observability wiring", not workarounds.

---

## 4. Legacy tools/ Migration

| Option | Description | Selected |
|--------|-------------|----------|
| (a) Fix imports only | Add tools/ to sys.path in CLI entry point | |
| (b) Full migration into gigaevo/ | Move ALL useful tools/ functionality into gigaevo package | ✓ |
| (c) Thin wrappers | tools/ scripts call gigaevo internals | |

**User's choice:** Option (b) — full migration. Move everything into `gigaevo/` package. After migration, `gigaevo/cli/` and `gigaevo/monitoring/` must have ZERO imports from `tools/`. The `tools/` directory remains for standalone scripts only; the installed `gigaevo` package is self-contained.

**Notes:** User wants clean break, not import hacks.

---

## 5. Agent/Skill CLI Reliability

| Option | Description | Selected |
|--------|-------------|----------|
| Fix CLI to be more forgiving | Make CLI accept various flag formats | |
| Fix skills/agents to use correct API | Audit and fix all skill/agent CLI invocations | ✓ |
| Both | Fix CLI ergonomics AND fix skills | |

**User's choice:** Fix skills and agents. The CLI API is fine — skills pass wrong flags or arguments. Audit ALL experiment lifecycle skills (`.claude/skills/experiment-*/SKILL.md`) and ALL agents (`.claude/agents/*.md`) for incorrect CLI flags, wrong argument formats, and references to non-existent commands.

**Notes:** User observation: "agents do not understand api of gigaevo tools" — this is a documentation/skill problem, not a CLI problem.

---

## Claude's Discretion

- Internal package structure for migrated tools/ code (e.g., `gigaevo/tools/` vs `gigaevo/cli/utils/` vs spreading across existing modules)
- Whether to keep `tools/` scripts as thin wrappers calling `gigaevo` internals, or delete them entirely
- How to handle `tools/comparison.py` subprocess calls in plugins (inline the logic vs keep as CLI command)

## Deferred Ideas

- Generation-aware sync hook for SteadyState — needs its own phase
- Watch mode / Rich Live dashboard — deferred from v1.0
- Configurable alert routing — deferred from v1.0
