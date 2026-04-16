# Phase 06 Plan 04: YAML Test Fixtures + Integration Tests

Created comprehensive test fixtures for all 3 experiment types and fixture-driven integration tests.

## Tasks Completed

### Task 1: YAML test fixtures
Created `tests/fixtures/watchdog/` with 3 fixture sets:
- `solo_hover/`: 2 runs, solo plugin, HoVer task, accuracy metric, baseline=0.76
- `adversarial_heilbron/`: 4 runs (2 G + 2 D), adversarial plugin, arms-race + comparison plot commands, baseline=0.03449
- `prompt_coevo/`: 4 runs (2 code + 2 prompt), prompt_coevo plugin, accuracy metric, baseline=0.80

Each includes experiment.yaml (Pydantic-valid), metrics.yaml, and redis_data.json. All 3 experiment.yaml files pass ExperimentManifest.from_yaml_file() validation.

### Task 2: Integration tests + CliRunner end-to-end tests
Integration tests in `test_watchdog_integration.py` (8 new tests):
- Solo: full cycle + telegram body with SOTA
- Adversarial: full cycle with 4 runs + G/D telegram sections + arms-race command args
- Prompt co-evo: full cycle with population grouping + telegram body with population groups

CliRunner tests in `test_watchdog_cmd.py` (6 new tests):
- `watchdog --help`, `status --help`, `plot comparison --help`, `plot arms-race --help`, `plot trajectory --help`
- Import chain test: verifies no ImportError on nonexistent experiment

## Verification
- All 3 fixture directories contain valid experiment.yaml, metrics.yaml, redis_data.json
- 12 integration tests pass with fakeredis + mock subprocess
- 19 CLI tests pass (excluding pre-existing metric_names failure)
- No real service calls in any tests
