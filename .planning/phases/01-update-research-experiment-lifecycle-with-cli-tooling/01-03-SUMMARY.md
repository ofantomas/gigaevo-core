---
phase: 01-update-research-experiment-lifecycle-with-cli-tooling
plan: 03
subsystem: skills
tags: [cli, gigaevo, experiment-lifecycle, markdown, skills, pm-audit-removal]

requires:
  - phase: 01-01
    provides: "gigaevo manifest CLI subcommand (get/set/update/gate/pr-description)"
  - phase: 01-02
    provides: "lighter skills already migrated; project-pm deleted"
provides:
  - "5 heavy experiment lifecycle skills migrated from inline Python to gigaevo CLI"
  - "pm_audit references removed from experiment-launch and experiment-closeout"
  - "merge-rules.md reference file updated to remove PYTHONPATH and project-pm"
  - "Phase-wide: zero PYTHONPATH, zero manifest imports, zero pm_audit (excluding diagnose/evals)"
affects: [experiment-launch, experiment-closeout, experiment-checkpoint, experiment-restart, run-experiment]

tech-stack:
  added: []
  patterns: ["gigaevo -e $EXP manifest gate/get/set/update/pr-description replaces inline PYTHONPATH Python", "Piped JSON pattern: gigaevo manifest get runs --format json | $GIGAEVO_PYTHON -c for Redis/PID ops"]

key-files:
  created: []
  modified:
    - ".claude/skills/experiment-launch/SKILL.md"
    - ".claude/skills/experiment-closeout/SKILL.md"
    - ".claude/skills/experiment-checkpoint/SKILL.md"
    - ".claude/skills/experiment-restart/SKILL.md"
    - ".claude/skills/run-experiment/SKILL.md"
    - ".claude/skills/experiment-closeout/references/merge-rules.md"

decisions:
  - "Piped JSON pattern for Redis queries: CLI outputs JSON, piped to inline Python for Redis/PID ops (allowed per clarified D-01)"
  - "Step 8 checkpoint recording uses raw YAML write instead of manifest update (complex nested append not supported by CLI update)"
  - "merge-rules.md /project-pm reference replaced with manual INDEX.md update instruction (per D-04 deletion)"

metrics:
  duration_seconds: 609
  completed: "2026-04-12T15:56:32Z"
  tasks_completed: 3
  tasks_total: 3
  files_modified: 6
---

# Phase 01 Plan 03: Migrate Heavy Experiment Lifecycle Skills to gigaevo CLI Summary

Migrated the 5 heaviest experiment lifecycle skills (85+ inline Python references) to use gigaevo CLI commands, removing all PYTHONPATH prefixes, manifest imports, skill_env.sh sources, and pm_audit references.

## One-liner

Zero PYTHONPATH across 5 heavy skills (launch/closeout/checkpoint/restart/run-experiment) with piped-JSON pattern for Redis queries

## Tasks Completed

| Task | Name | Commit | Key Changes |
|------|------|--------|-------------|
| 1 | Update experiment-launch and experiment-restart | 43996489 | 8+6 PYTHONPATH removed, pm_audit Step 9a deleted from launch, 17+12 gigaevo -e refs |
| 2a | Update experiment-closeout and experiment-checkpoint | 6386d8a2 | 9+5 PYTHONPATH removed, pm_audit Step 9a deleted from closeout, 10+18 gigaevo -e refs |
| 2b | Update run-experiment, merge-rules, phase-wide verification | 74e9d080 | 3 PYTHONPATH removed, /project-pm ref removed from merge-rules, 11 gigaevo -e refs |

## Deviations from Plan

None - plan executed exactly as written.

## Phase-Wide Verification Results

| Metric | Result |
|--------|--------|
| PYTHONPATH refs (excl. diagnose/evals) | 0 |
| `from tools.experiment.manifest` imports (excl. diagnose/evals) | 0 |
| pm_audit refs (excl. evals) | 0 |
| skill_env.sh refs (excl. diagnose) | 0 |
| gigaevo CLI refs across all skills/agents | 99 |

## Migration Pattern Applied

**Before (inline Python with PYTHONPATH):**
```bash
PYTHONPATH="$PROJ" $GIGAEVO_PYTHON -c "
from tools.experiment.manifest import load_manifest
m = load_manifest('$EXP')
assert m.status == 'running', f'BLOCKED: status={m.status}'
"
```

**After (gigaevo CLI):**
```bash
gigaevo -e "$EXP" manifest gate running
```

**Piped JSON pattern (for Redis/PID ops):**
```bash
gigaevo -e "$EXP" manifest get runs --format json | $GIGAEVO_PYTHON -c "
import sys, json, redis
runs = json.load(sys.stdin)
# ... Redis queries using run data from stdin
"
```

## Decisions Made

1. **Piped JSON for Redis queries**: CLI outputs run data as JSON, piped to inline Python for raw Redis operations. This keeps the manifest read in the CLI while allowing arbitrary Redis queries.
2. **Raw YAML for complex nested writes**: Step 8 checkpoint recording appends to a list in experiment.yaml -- too complex for `manifest update`. Used raw YAML manipulation (allowed per D-01).
3. **merge-rules.md project-pm removal**: Replaced `/project-pm` sync script reference with manual INDEX.md update instruction, consistent with D-04 deletion.

## Requirements Satisfied

- D-01 (clarified): Zero PYTHONPATH references; inline Python only for raw Redis, PID ops, yaml/json parsing
- D-03: Existing CLI commands used (gigaevo flush, gigaevo status, gigaevo checkpoint)
- D-04: pm_audit removed from experiment-launch (Step 9a) and experiment-closeout (Step 9a)
- D-07: All 5 remaining heavy skills updated in one pass
- D-08: Phase-wide grep verification passes: 0 PYTHONPATH, 0 manifest imports, 0 pm_audit, 99 CLI refs

## Self-Check: PASSED

- All 6 modified files exist on disk
- All 3 task commits verified (43996489, 6386d8a2, 74e9d080)
- Phase-wide PYTHONPATH count: 0 (excluding diagnose/evals)
- Phase-wide manifest import count: 0 (excluding diagnose/evals)
- Phase-wide pm_audit count: 0 (excluding evals)
- Phase-wide gigaevo CLI refs: 99
