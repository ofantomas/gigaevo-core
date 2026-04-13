---
phase: 04-cli
plan: 01
subsystem: docs
tags: [issues-log, patterns, known-failures, experiment-lifecycle]

# Dependency graph
requires: []
provides:
  - "Updated issues log template with EVENT vs ISSUE format guidance"
  - "Known Failures section in PATTERNS.md with 5 real entries (KF-01 through KF-05)"
affects: [04-02, 04-03, 04-04, experiment-implement, experiment-launch, post-experiment-fixes]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "EVENT entries for auto-captured lifecycle events (brief, structured)"
    - "ISSUE entries for manual intervention documentation (detailed)"
    - "Known Failure table with ID, Trigger, Symptoms, Root Cause, Fix, Status, Affected Types, Source"

key-files:
  created: []
  modified:
    - experiments/_template/04_issues_log.md
    - experiments/PATTERNS.md

key-decisions:
  - "EVENT entries use [EVENT <ISO-timestamp>] prefix for grep-ability"
  - "Known Failures table uses KF-XX IDs for cross-referencing from skills"

patterns-established:
  - "Known Failure IDs (KF-XX) for structured failure tracking"
  - "EVENT vs ISSUE distinction in issues log"

requirements-completed: [D-07, D-08]

# Metrics
duration: 6min
completed: 2026-04-13
---

# Phase 04-cli Plan 01: Foundation Knowledge Stores Summary

**Issues log EVENT/ISSUE format guidance and PATTERNS.md Known Failures section with 5 entries from heilbron/asymmetric-iterations**

## Performance

- **Duration:** 6 min
- **Started:** 2026-04-13T14:20:06Z
- **Completed:** 2026-04-13T14:26:30Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Updated issues log template with clear EVENT vs ISSUE entry type guidance, distinguishing auto-captured lifecycle events from manual issue entries
- Added Known Failures section to PATTERNS.md with 5 real entries (KF-01 through KF-05) extracted from heilbron/asymmetric-iterations issues log
- Updated PATTERNS.md footer to reference /post-experiment-fixes skill

## Task Commits

Each task was committed atomically:

1. **Task 1: Update issues log template with EVENT vs ISSUE format guidance** - `29b498b2` (feat)
2. **Task 2: Add Known Failures section to PATTERNS.md with real entries** - `a7220556` (feat)

## Files Created/Modified
- `experiments/_template/04_issues_log.md` - Added Entry Types section with EVENT (auto-captured) and ISSUE (manual) format examples
- `experiments/PATTERNS.md` - Added Known Failures table (KF-01 through KF-05) between Platform Failure Modes and Recurring Design Flaws sections; updated footer

## Decisions Made
None - followed plan as specified

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- EVENT format established for plans 02-04 to reference when adding auto-capture snippets to lifecycle skills
- Known Failures table established for plans 02-04 to reference when adding pattern-promotion steps
- All 5 KF entries are populated with real data from heilbron/asymmetric-iterations

## Self-Check: PASSED

- All files exist on disk
- All commit hashes verified in git log

---
*Phase: 04-cli*
*Completed: 2026-04-13*
