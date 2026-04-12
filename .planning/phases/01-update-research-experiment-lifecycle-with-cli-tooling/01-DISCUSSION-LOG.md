# Phase 1: Update research experiment lifecycle with CLI tooling - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-12
**Phase:** 01-update-research-experiment-lifecycle-with-cli-tooling
**Areas discussed:** Inline Python snippet strategy, pm_audit.py and diagnose.py handling, Migration scope and safety, resource_manager.py integration

---

## Inline Python snippet strategy

| Option | Description | Selected |
|--------|-------------|----------|
| New `gigaevo manifest` subcommand | Add `gigaevo manifest get <field>` and `gigaevo manifest list-runs` to the CLI. Skills call CLI instead of inline Python. Clean, testable, consistent with v1.0 direction. | |
| Keep inline Python, fix imports | Replace PYTHONPATH hack with proper `pip install -e .` imports. Keeps skill logic self-contained but doesn't reduce complexity. | |
| Shell helper script | Create a shared `tools/experiment/skill_env.sh` with helper functions. Skills source it. Less clean but fastest to implement. | |

**User's choice:** User described current code as "spaghetti that does something trivial" — asked what manifest is. After explanation, chose `gigaevo manifest` subcommand approach.

**Follow-up:** Confirmed ALL inline Python (both reads and actions) should become CLI calls. Zero inline Python in skills.

**Follow-up:** Asked "Does CLI work for runs without experiment.yaml?" — confirmed yes, CLI has both `--experiment` and `--run` modes. `gigaevo manifest` only for experiment contexts.

---

## pm_audit.py and diagnose.py handling

| Option | Description | Selected |
|--------|-------------|----------|
| Absorb into CLI | `gigaevo pm audit`, `gigaevo diagnose`. Consistent with "everything through CLI" direction. | |
| Keep as standalone, fix imports | They're skill-internal scripts. Just make them importable without PYTHONPATH hack. | |
| You decide | Claude picks the cleanest approach for each script. | |

**User's choice:** Custom answer — "I want to remove pm_audit and pm agent. diagnose.py needs standalone tool because currently its too spaghetti, we need to redesign so there is well defined infra services to check against."

**Follow-up:** Confirmed diagnose.py redesign should be a separate future phase, not this phase.

---

## Migration scope and safety

| Option | Description | Selected |
|--------|-------------|----------|
| All at once | These are doc/skill files, not runtime code. Update all SKILL.md files in one pass, commit. | ✓ |
| Batch by lifecycle stage | Group 1: design+implement. Group 2: launch+checkpoint. Group 3: closeout+restart. | |
| One skill at a time | Most cautious. Update one SKILL.md, test with a real experiment step, then next. | |

**User's choice:** All at once

| Option | Description | Selected |
|--------|-------------|----------|
| Grep-based verification only | Verify zero PYTHONPATH references remain in skills, all `gigaevo` commands referenced actually exist. | ✓ |
| Dry-run one experiment lifecycle | After migration, run through one experiment design→implement→launch cycle to confirm skills work. | |
| No special testing needed | Skills are docs, not code. The next real experiment will validate them. | |

**User's choice:** Grep-based verification only

---

## resource_manager.py integration

| Option | Description | Selected |
|--------|-------------|----------|
| Absorb into CLI: `gigaevo resource` | `gigaevo resource check`, `gigaevo resource assign -e hover/foo`. | |
| Keep standalone, fix PYTHONPATH | It works fine as a standalone tool. Just make it callable without PYTHONPATH hack. | |
| Remove it entirely | Resource allocation is done manually anyway. | |

**User's choice:** Custom answer — "I think needs redesign together with resource services. Now its probably too spaghetti."

**Follow-up:** Confirmed resource_manager redesign deferred to separate phase. For this phase: remove resource_manager references from skills. Users manually pick servers/DBs.

---

## Claude's Discretion

- Exact `gigaevo manifest` subcommand interface details
- Handling of edge cases in individual skill snippet replacement
- Whether to update historical eval output files

## Deferred Ideas

- diagnose.py redesign (well-defined infra service model) — future phase
- resource_manager.py redesign (infra services) — future phase
