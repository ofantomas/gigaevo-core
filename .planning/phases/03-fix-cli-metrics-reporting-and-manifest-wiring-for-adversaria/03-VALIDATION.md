---
phase: 3
slug: fix-cli-metrics-reporting-and-manifest-wiring-for-adversaria
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-04-13
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | `pytest.ini` |
| **Quick run command** | `/run-tests tests/cli/` |
| **Full suite command** | `/run-tests` |
| **Estimated runtime** | ~120 seconds (full), ~15 seconds (CLI subset) |

---

## Sampling Rate

- **After every task commit:** Run `/run-tests tests/cli/`
- **After every plan wave:** Run `/run-tests`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | MON-05, MAN-02, MON-03 | T-03-01, T-03-02 | N/A | unit | `/run-tests tests/cli/test_watchdog_cmd.py tests/monitoring/test_manifest_schema.py` | Yes (extend) | pending |
| 03-01-02 | 01 | 1 | MON-05, CLI-03 | T-03-01 | N/A | unit | `/run-tests tests/cli/test_trajectory_cmd.py tests/cli/test_top_cmd.py` | Yes (extend) | pending |
| 03-02-01 | 02 | 1 | MON-05, CLI-03 | T-03-03, T-03-04 | N/A | unit | `/run-tests tests/cli/test_status_cmd.py tests/cli/test_checkpoint_cmd.py` | Yes (extend) | pending |
| 03-02-02 | 02 | 1 | CLI-03, MAN-02 | — | N/A | unit | `/run-tests tests/cli/test_cli_group.py` | Yes (extend) | pending |

*Status: pending / green / red / flaky*

---

## Wave 0 Requirements

*Existing infrastructure covers all phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Watchdog displays all metrics for running experiment | MON-03 | Requires live experiment with Redis | Run `gigaevo status -e <exp>` against a live experiment and verify all metrics appear |
| Plot group renders multi-metric comparison | MON-05 | Requires actual plot output | Run `gigaevo plot comparison -e <exp>` and verify all metrics in legend |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 15s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
