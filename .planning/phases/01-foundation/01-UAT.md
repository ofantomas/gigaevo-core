---
status: passed
phase: 01-foundation
source: 01-01-SUMMARY.md, 01-02-SUMMARY.md, 01-03-SUMMARY.md
started: 2026-04-12T12:00:00Z
updated: 2026-04-12T12:26:00Z
---

## Current Test

number: 8
name: All monitoring tests pass
result: PASS

## Tests

### 1. RunSpec parsing
expected: `RunSpec.parse("heilbron_solo@4:S1")` returns prefix="heilbron_solo", db=4, label="S1". Import from gigaevo.monitoring works.
result: PASS — prefix, db, label all correct. Import from gigaevo.monitoring works.

### 2. ExperimentMonitor collects snapshots from live Redis
expected: `ExperimentMonitor(redis_host="localhost").collect([RunConfig(prefix="heilbron_solo", db=1, label="S1")])` returns a list with one RunSnapshot containing gen, fitness, program counts from the live experiment data.
result: PASS — RunConfig takes run_spec=RunSpec(...). collect() returns RunSnapshot with generation, metrics, total/valid programs from live Redis.

### 3. RunSnapshot computed properties
expected: A RunSnapshot with total_count=100 and valid_count=80 has `invalid_rate` of 0.2. A snapshot with gen unchanged across checks has `is_stalled=True`.
result: PASS — invalid_rate=0.2 correct. is_stalled uses multi-signal detection (gen+running+total); True when all 3 match, False when any signal shows progress.

### 4. ExperimentManifest loads real experiment.yaml
expected: `ExperimentManifest.from_yaml_file("experiments/adversarial/adversarial-vs-solo/experiment.yaml")` succeeds, returns manifest with name="adversarial/adversarial-vs-solo", 4 runs, status="running".
result: PASS — Loads successfully. experiment.name="adversarial/adversarial-vs-solo", 4 runs [S1,S2,S3,S4], status="running", max_gen=50. Note: name is at m.experiment.name, not m.name.

### 5. ExperimentManifest JSON Schema export
expected: `export_json_schema()` returns a valid JSON string that can be parsed as a JSON Schema document with required fields like "experiment", "runs", "problem".
result: PASS — model_json_schema() returns valid JSON Schema with type=object, title=ExperimentManifest, required=[schema_version, experiment], 12 properties including experiment/runs/problem.

### 6. AlertDetector stall detection
expected: When fed snapshots where generation count is unchanged for 3+ checks, running_count=0, and total_count unchanged, AlertDetector.check() returns an Alert with type=STALL and severity=WARNING.
result: PASS — Stall detected on cycle 2 (after baseline established in cycle 1). Alert type=STALL, severity=WARN. Multi-signal: requires gen unchanged AND running=0 AND total unchanged.

### 7. AlertDetector cooldown suppression
expected: After an alert fires, subsequent check() calls within cooldown_cycles do NOT re-emit the same alert type. After cooldown expires, the alert can fire again.
result: PASS — With cooldown_cycles=2: fires on cycle 2, suppressed cycles 3-4, fires again on cycle 5. Exact semantics verified.

### 8. All monitoring tests pass
expected: Running `pytest tests/monitoring/ -x -q` passes all 135 tests with no failures or errors.
result: PASS — 339 tests passed in 29.64s (includes Phase 1-3 monitoring tests; original 135 count was Phase 1 only).

## Summary

total: 8
passed: 8
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

[none]
