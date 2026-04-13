# Phase 05 Plan 04: Skill/Agent CLI Audit and CLAUDE.md Update

Audited all experiment lifecycle skills and agents for CLI correctness. Updated CLAUDE.md CLI reference.

## Tasks Completed

### Task 1: Audit experiment lifecycle skills
All 10 experiment lifecycle skills audited. All `gigaevo` invocations use valid subcommands with correct flag positions. No non-existent commands found. The `from tools.telegram_notify` references in run-experiment/SKILL.md are Python library imports (not CLI commands) and have no CLI equivalent — retained as-is.

### Task 2: Audit agents + update CLAUDE.md
- anomaly-detector.md: All gigaevo invocations verified correct
- CLAUDE.md: Added `manifest` to inline commands list and CLI command table
- No PYTHONPATH workarounds found in agents

## Verification
- Zero PYTHONPATH workarounds in agents
- All gigaevo invocations use valid registered subcommands
- CLAUDE.md CLI table includes manifest row
- CLAUDE.md inline list includes manifest

## Self-Check: PASSED
