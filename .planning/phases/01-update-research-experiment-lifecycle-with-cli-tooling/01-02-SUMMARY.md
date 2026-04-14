---
phase: 01-update-research-experiment-lifecycle-with-cli-tooling
plan: 02
subsystem: skills
tags: [cli, gigaevo, experiment-lifecycle, markdown, skills, agents]

requires:
  - phase: 01-01
    provides: "gigaevo manifest CLI subcommand (get/set/update/gate/pr-description)"
provides:
  - "6 skill/agent files migrated from inline Python manifest calls to gigaevo CLI"
  - "project-pm skill and agent deleted (4 files removed)"
  - "pm_audit references removed from experiment-design and experiment-implement"
  - "resource_manager.py references removed from experiment-implement and research-scheduler"
affects: [01-03, experiment-launch, experiment-closeout]

tech-stack:
  added: []
  patterns: ["gigaevo -e $EXP manifest gate/get/set/update replaces inline PYTHONPATH Python"]

key-files:
  created: []
  modified:
    - ".claude/skills/experiment-design/SKILL.md"
    - ".claude/skills/experiment-implement/SKILL.md"
    - ".claude/skills/experiment-diagnose/SKILL.md"
    - ".claude/skills/research-scheduler/SKILL.md"
    - ".claude/skills/auto-optimize-loop/SKILL.md"
    - ".claude/agents/anomaly-detector.md"

key-decisions:
  - "D-04: project-pm deleted entirely -- tracking hygiene deferred"
  - "D-05: diagnose.py PYTHONPATH invocation stays as-is (D-05 exemption)"
  - "D-06: resource_manager.py references removed, manual infra check via infrastructure.yaml"
  - "Allowed $GIGAEVO_PYTHON -c for raw Redis queries, PID ops, pure yaml/json parsing"

patterns-established:
  - "CLI-first skill pattern: gigaevo -e $EXP manifest gate/get/set/update for all manifest operations"
  - "Split pattern: manifest data via CLI, raw Redis via $GIGAEVO_PYTHON -c (no PYTHONPATH)"

requirements-completed: [D-01, D-04, D-05, D-06, D-07, D-08]

duration: 6min
completed: 2026-04-12
---

# Phase 01 Plan 02: Skill/Agent Migration to gigaevo CLI Summary

**Migrated 6 experiment lifecycle skills/agents from inline PYTHONPATH Python to gigaevo CLI calls; deleted project-pm entirely (skill + agent + scripts)**

## Performance

- **Duration:** 6 min
- **Started:** 2026-04-12T15:37:01Z
- **Completed:** 2026-04-12T15:43:Z
- **Tasks:** 2/2
- **Files modified:** 10 (4 deleted, 6 updated)

## Accomplishments

### Task 1: Delete project-pm and remove pm_audit references
- Deleted `.claude/skills/project-pm/` directory (SKILL.md, board_config.yaml, scripts/pm_audit.py)
- Deleted `.claude/agents/project-pm.md`
- Removed Step 8a (pm_audit sync) from experiment-design/SKILL.md
- Removed Step 13a (pm_audit sync) from experiment-implement/SKILL.md
- experiment-launch and experiment-closeout left untouched (Plan 03 scope)

### Task 2: Update 6 skill/agent files to use gigaevo CLI
- **experiment-design/SKILL.md**: Replaced `source skill_env.sh` with `PROJ=...`, replaced manifest gate/get inline Python with `gigaevo -e "$EXP" manifest gate preregistered` and `gigaevo -e "$EXP" manifest get stopping_rule`
- **experiment-implement/SKILL.md**: Replaced 8 inline manifest calls (gate, get runs, set status, update treatment_verification, update smoke_test) with gigaevo CLI equivalents; removed resource_manager.py call (D-06); removed PYTHONPATH from generate_launch.py
- **experiment-diagnose/SKILL.md**: Replaced Step 1 manifest load with `gigaevo -e manifest get runs/max_generations`; diagnose.py invocation kept per D-05
- **research-scheduler/SKILL.md**: Removed resource_manager.py --check (D-06), replaced with manual infrastructure.yaml check
- **auto-optimize-loop/SKILL.md**: Removed `PYTHONPATH=.` from default benchmark command
- **anomaly-detector.md**: Replaced manifest load/update in Steps 4a, 4b, 7, 8 with gigaevo CLI + pure Redis; split complex blocks into CLI (manifest) + $GIGAEVO_PYTHON -c (Redis)

## Verification Results

| Check | Result |
|-------|--------|
| PYTHONPATH refs (excl. diagnose.py) | 0 |
| resource_manager refs | 0 |
| pm_audit refs | 0 |
| inline manifest import refs (excl. diagnose.py) | 0 |
| project-pm directory exists | No |
| project-pm agent exists | No |
| experiment-design has gigaevo -e | Yes |
| experiment-implement has gigaevo -e | Yes |
| experiment-diagnose has gigaevo -e | Yes |
| anomaly-detector has gigaevo -e | Yes |

## Deviations from Plan

None -- plan executed exactly as written.

## Commits

| Task | Commit | Message |
|------|--------|---------|
| 1 | c41f86a1 | chore(01-02): delete project-pm skill/agent, remove pm_audit references |
| 2 | 6547523e | feat(01-02): migrate 6 skill/agent files to gigaevo CLI calls |

## Self-Check: PASSED

- All 4 deleted files confirmed absent
- All 6 modified files confirmed present
- Both commit hashes (c41f86a1, 6547523e) found in git log
