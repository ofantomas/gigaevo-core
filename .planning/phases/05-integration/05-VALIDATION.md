---
phase: 05
slug: integration
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-13
---

# Phase 05 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pyproject.toml |
| **Quick run command** | `/run-tests tests/cli/ tests/monitoring/` |
| **Full suite command** | `/run-tests` |
| **Estimated runtime** | ~120 seconds |

---

## Sampling Rate

- **After every task commit:** Run `/run-tests tests/cli/ tests/monitoring/`
- **After every plan wave:** Run `/run-tests`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-01-01 | 01 | 1 | D-04, D-06 | — | N/A | unit (TDD) | `/run-tests tests/monitoring/test_manifest_ops.py -x` | W0 (TDD creates) | ⬜ pending |
| 05-01-02 | 01 | 1 | D-06 | — | N/A | unit (TDD) | `/run-tests tests/cli/test_flush_ops.py tests/utils/test_dataframes.py tests/utils/test_plotting.py -x` | W0 (TDD creates) | ⬜ pending |
| 05-02-01 | 02 | 2 | D-01, D-03, D-05 | — | N/A | unit (TDD) | `/run-tests tests/monitoring/test_watchdog_plugin.py tests/monitoring/test_manifest_schema.py -x` | W0 (TDD creates) | ⬜ pending |
| 05-02-02 | 02 | 2 | D-02 | — | N/A | unit (TDD) | `/run-tests tests/monitoring/plugins/ tests/monitoring/test_watchdog_plugin.py -x` | W0 (TDD creates) | ⬜ pending |
| 05-03-01 | 03 | 2 | D-05, D-07 | — | N/A | integration | `bash -c 'count=$(grep -rn "from tools\\." gigaevo/cli/ gigaevo/monitoring/ \| grep -v "#" \| wc -l); test "$count" -eq 0'` | ✅ (grep) | ⬜ pending |
| 05-03-02 | 03 | 2 | D-07 | — | N/A | unit | `/run-tests tests/cli/ -x` | ✅ existing | ⬜ pending |
| 05-04-01 | 04 | 3 | D-08 | — | N/A | audit | `grep -rn "gigaevo " .claude/skills/ \| head -100` | ✅ (grep) | ⬜ pending |
| 05-04-02 | 04 | 3 | D-09 | — | N/A | audit | `grep -c "manifest" CLAUDE.md` | ✅ (grep) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

*TDD tasks create test files inline — no Wave 0 scaffolding needed. Existing test infrastructure (pytest, conftest.py) covers all phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| CLI commands don't crash with running experiment | reliability | Requires live Redis + running runs | Run `gigaevo status` against active experiment |
| Skill/agent audit correctness | D-08, D-09 | grep checks syntax not semantics | Manually verify 2-3 skills invoke correct CLI commands |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 120s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
