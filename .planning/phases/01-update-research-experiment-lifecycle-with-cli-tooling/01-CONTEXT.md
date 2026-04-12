# Phase 1: Update research experiment lifecycle with CLI tooling - Context

**Gathered:** 2026-04-12
**Status:** Ready for planning

<domain>
## Phase Boundary

Migrate all experiment lifecycle skills and agents from legacy `PYTHONPATH=. python tools/...` invocations to the `gigaevo` CLI shipped in v1.0. Zero inline Python should remain in skills after this phase. Also: delete the project-pm skill/agent/script entirely, and remove resource_manager.py references from skills.

</domain>

<decisions>
## Implementation Decisions

### Inline Python Snippet Strategy
- **D-01:** Replace ALL inline `PYTHONPATH="$PROJ" $GIGAEVO_PYTHON -c "..."` snippets with `gigaevo` CLI calls. Zero inline Python in skills.
- **D-02:** Add a new `gigaevo manifest` subcommand for reading experiment.yaml fields (`gigaevo -e hover/foo manifest get runs`, `gigaevo -e hover/foo manifest get stopping_rule`, etc.). This replaces ~30 inline Python snippets that call `load_manifest()`.
- **D-03:** Action-type snippets (PR comments, watchdog start, flush) use existing CLI equivalents (`gigaevo checkpoint`, `gigaevo flush`, `gigaevo watchdog`).

### pm_audit.py and project-pm
- **D-04:** DELETE `pm_audit.py`, the `project-pm` skill, and the `project-pm` agent entirely. Remove all references to pm_audit from other skills (experiment-design, experiment-implement, experiment-launch, experiment-closeout).

### diagnose.py
- **D-05:** Leave experiment-diagnose skill and diagnose.py as-is in this phase. Diagnose.py redesign (well-defined infra service checks) is deferred to a separate future phase.

### resource_manager.py
- **D-06:** Remove all resource_manager.py references from skills. Users manually pick servers and Redis DBs. Resource manager redesign deferred to a separate future phase.

### Migration Approach
- **D-07:** Update ALL 10+ experiment lifecycle skills and agents in one pass. These are Markdown instruction files, not compiled code — risk is low.
- **D-08:** Verification via grep-based checks: zero PYTHONPATH references remaining in skills, all referenced `gigaevo` subcommands exist.

### Claude's Discretion
- Exact `gigaevo manifest` subcommand interface (flags, output format) — follow existing CLI patterns (Click, Rich output, `--format` flag)
- How to handle edge cases in individual skill snippets — some may need slight restructuring beyond simple command substitution
- Whether to update eval output files (`.claude/skills/evals/output/`) — these are historical records, likely leave as-is

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### CLI Architecture
- `gigaevo/cli/` — Existing CLI module structure (commands, run_resolver, output formatting)
- `gigaevo/cli/run_resolver.py` — How `--experiment` and `--run` flags are resolved to RunConfig
- `tools/README.md` — CLI command reference and Redis data model

### Experiment Manifest
- `tools/experiment/manifest.py` — Current manifest loading logic (Pydantic model for experiment.yaml)
- `gigaevo/monitoring/manifest.py` — v1.0 manifest schema (if exists, otherwise tools/experiment/manifest.py is canonical)

### Skills to Update
- `.claude/skills/experiment-checkpoint/SKILL.md`
- `.claude/skills/experiment-closeout/SKILL.md`
- `.claude/skills/experiment-design/SKILL.md`
- `.claude/skills/experiment-implement/SKILL.md`
- `.claude/skills/experiment-launch/SKILL.md`
- `.claude/skills/experiment-restart/SKILL.md`
- `.claude/skills/experiment-diagnose/SKILL.md`
- `.claude/skills/run-experiment/SKILL.md`
- `.claude/skills/research-scheduler/SKILL.md`
- `.claude/skills/auto-optimize-loop/SKILL.md`

### Agents to Update
- `.claude/agents/anomaly-detector.md`

### To Delete
- `.claude/skills/project-pm/` — entire directory
- `.claude/skills/project-pm/scripts/pm_audit.py`

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `gigaevo/cli/` — 12 subcommands already implemented, Click 8.x + Rich
- `RunResolver` — bridges `--experiment`/`--run` flags to monitoring RunConfig
- `OutputFormatter` — consistent table/json/csv/markdown output across commands
- `tools/experiment/manifest.py` — Pydantic model for experiment.yaml (source for new `gigaevo manifest` command)

### Established Patterns
- CLI commands use `@click.command()` with `@click.pass_context`
- Global flags (`--experiment`, `--run`, `--format`, `--quiet`, `--verbose`) via `LazyGroup`
- `_load_manifest()` lazy import pattern in run_resolver.py

### Integration Points
- New `gigaevo manifest` command registers in CLI command group
- Skills reference CLI commands in bash code blocks
- `experiment.yaml` is the manifest file read by all experiment skills

</code_context>

<specifics>
## Specific Ideas

- User described current inline Python as "spaghetti that does something trivial" — emphasis on simplification
- User wants diagnose.py and resource_manager.py properly redesigned in future phases, not just patched here

</specifics>

<deferred>
## Deferred Ideas

- **diagnose.py redesign** — redesign with well-defined infrastructure service checks, proper interfaces. Separate phase.
- **resource_manager.py redesign** — redesign together with resource/infrastructure services. Separate phase.

</deferred>

---

*Phase: 01-update-research-experiment-lifecycle-with-cli-tooling*
*Context gathered: 2026-04-12*
