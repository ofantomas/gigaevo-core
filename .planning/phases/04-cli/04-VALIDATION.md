---
phase: 4
slug: cli
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-13
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Markdown skill files — no automated tests needed |
| **Config file** | none — skill files are instruction documents |
| **Quick run command** | `grep -r "GSD" .claude/skills/experiment-*/SKILL.md` |
| **Full suite command** | `/run-tests` (existing test suite for Python code) |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Verify skill file structure with grep
- **After every plan wave:** Run `/run-tests` for Python code changes
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 4-01-01 | 01 | 1 | D-07 | T-04-01 | N/A (Markdown) | grep | `grep -c "\[EVENT" experiments/_template/04_issues_log.md` | N/A | ⬜ pending |
| 4-01-02 | 01 | 1 | D-08 | T-04-02 | N/A (Markdown) | grep | `grep -c "KF-0" experiments/PATTERNS.md` | N/A | ⬜ pending |
| 4-02-01 | 02 | 2 | D-01, D-03, D-04 | T-04-03 | N/A (Markdown) | grep | `grep -c "implement-PLAN.md" .claude/skills/experiment-implement/SKILL.md && grep -c "Step 4b" .claude/skills/experiment-implement/SKILL.md && grep -c "Step 4c" .claude/skills/experiment-implement/SKILL.md && grep -c "superpowers:writing-plans" .claude/skills/experiment-implement/SKILL.md` | N/A | ⬜ pending |
| 4-02-02 | 02 | 2 | D-01, D-05, D-06 | T-04-04 | N/A (Markdown) | grep | `grep -c "launch-PLAN.md" .claude/skills/experiment-launch/SKILL.md && grep -c "Step 0a" .claude/skills/experiment-launch/SKILL.md && grep -c "\[EVENT" .claude/skills/experiment-launch/SKILL.md && grep -c "04_issues_log" .claude/skills/experiment-launch/SKILL.md` | N/A | ⬜ pending |
| 4-03-01 | 03 | 2 | D-06, D-07 | T-04-05 | N/A (Markdown) | grep | `grep -c "\[EVENT" .claude/skills/experiment-restart/SKILL.md && grep -c "04_issues_log" .claude/skills/experiment-restart/SKILL.md` | N/A | ⬜ pending |
| 4-03-02 | 03 | 2 | D-06, D-07 | T-04-06 | N/A (Markdown) | grep | `grep -c "\[EVENT" .claude/skills/experiment-checkpoint/SKILL.md && grep -c "\[EVENT" .claude/skills/experiment-diagnose/SKILL.md && grep -c "04_issues_log" .claude/skills/experiment-checkpoint/SKILL.md` | N/A | ⬜ pending |
| 4-04-01 | 04 | 2 | D-09 | T-04-07 | N/A (Markdown) | grep | `grep -c "Known Failures promotion" .claude/skills/experiment-closeout/SKILL.md && grep -c "KF-XX" .claude/skills/experiment-closeout/SKILL.md` | N/A | ⬜ pending |
| 4-04-02 | 04 | 2 | D-10 | T-04-08 | N/A (Markdown) | grep | `grep -c "06_fixes_applied.md" .claude/skills/post-experiment-fixes/SKILL.md && grep -c "Known Failure statuses" .claude/skills/post-experiment-fixes/SKILL.md && grep -c "Patterns promoted" .claude/skills/post-experiment-fixes/SKILL.md` | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

*No Wave 0 needed — this phase modifies Markdown skill files only, not Python code. All verification is via grep commands that check for expected content in the modified files. Existing test infrastructure (`/run-tests`) covers regression checks for Python code.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Skill file readability | D-01 through D-10 | Markdown instructions require human review | Read modified SKILL.md files, verify step clarity |
| GSD integration coherence | D-01, D-03, D-05 | Integration logic is in natural language | Verify GSD steps don't conflict with existing skill steps |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
