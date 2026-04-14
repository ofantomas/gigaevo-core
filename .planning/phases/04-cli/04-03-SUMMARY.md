---
phase: 04-cli
plan: 03
subsystem: experiment-lifecycle-skills
tags: [event-capture, issues-log, lifecycle-automation]
dependency_graph:
  requires: [04-01]
  provides: [event-auto-capture-in-lifecycle-skills]
  affects: [experiment-restart, experiment-checkpoint, experiment-diagnose]
tech_stack:
  patterns: [bash-heredoc-append, issues-log-EVENT-format]
key_files:
  modified:
    - .claude/skills/experiment-restart/SKILL.md
    - .claude/skills/experiment-checkpoint/SKILL.md
    - .claude/skills/experiment-diagnose/SKILL.md
decisions:
  - Used bash cat >> heredoc append pattern for all event capture snippets
  - Stopping rule violation in checkpoint uses template placeholder (Claude fills in at runtime)
  - Diagnose event uses VERDICT placeholder filled from Step 8 outcome
metrics:
  duration: 6m
  completed: 2026-04-13T14:37:00Z
  tasks_completed: 2
  tasks_total: 2
  files_modified: 3
---

# Phase 04 Plan 03: Event Auto-Capture in Lifecycle Skills Summary

Bash event-capture snippets added to experiment-restart, experiment-checkpoint, and experiment-diagnose skills so lifecycle events auto-append to 04_issues_log.md using the [EVENT timestamp] format from Plan 01.

## Tasks Completed

### Task 1: Add event auto-capture to experiment-restart SKILL.md
- **Commit**: 75fbf078
- **Changes**: Inserted two event-capture bash blocks into experiment-restart/SKILL.md
  - Point 1 (after Step 2 confirmation): Logs "Experiment restart initiated" with per-run generation progress
  - Point 2 (after Step 4 flush): Logs "Redis flush completed" with experiment name
- **Both events**: Use Category restart, append to 04_issues_log.md via cat >> heredoc

### Task 2: Add event auto-capture to experiment-checkpoint and experiment-diagnose
- **Commit**: 6c5b0b4c
- **Changes**:
  - experiment-checkpoint/SKILL.md: Added checkpoint-recorded event at end of Step 8 (captures average generation), and stopping-rule-violation event template at end of Step 2a (Claude fills in when WARNING detected)
  - experiment-diagnose/SKILL.md: Replaced existing Issues log section with auto-capture EVENT entry for all diagnose completions, plus escalation to full ISSUE entry for CRITICAL/MAJOR findings

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

| Check | Expected | Actual |
|-------|----------|--------|
| restart [EVENT count | >= 2 | 2 |
| checkpoint [EVENT count | >= 2 | 2 |
| diagnose [EVENT count | >= 1 | 1 |
| All step numbering preserved | yes | yes |
| All gates preserved | yes | yes |

## Self-Check: PASSED

All 3 modified files exist. Both commit hashes (75fbf078, 6c5b0b4c) verified in git log.
