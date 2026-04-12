---
plan: 01-02
phase: 01-foundation
status: complete
---

# Summary: 01-02 ExperimentManifest Pydantic Schema

## What was built

A strict Pydantic v2 schema for experiment.yaml (`ExperimentManifest`) with status-gated validation, actionable error messages, YAML loading (string and file), JSON Schema export, and backward compatibility with all 17 existing experiment.yaml files in the repo. The schema lives in `gigaevo/monitoring/manifest_schema.py` alongside (not replacing) the existing `tools/experiment/manifest.py`.

## Key files created

- `gigaevo/monitoring/manifest_schema.py` -- Pydantic v2 models: `ExperimentManifest`, `ExperimentSection`, `ManifestRunSpec`, `ProblemSpec`, `LaunchInfo`, `BaselineInfo`, `SmokeTestInfo`, plus `export_json_schema()` utility
- `tests/monitoring/test_manifest_schema.py` -- 39 tests covering valid loading (all 5 statuses), validation errors (11 cases), actionable error messages, JSON Schema export, YAML loading, round-trip serialization, manifest-optional independence, and integration with real experiment.yaml files
- `gigaevo/monitoring/__init__.py` -- updated with `ExperimentManifest` and `export_json_schema` exports (additive to 01-01 exports)

## Test results

```
tests/monitoring/test_experiment_monitor.py .....                        [  5%]
tests/monitoring/test_manifest_schema.py .......................................  [ 44%]
tests/monitoring/test_redis_queries.py .................                 [ 61%]
tests/monitoring/test_run_spec.py .......................                [ 84%]
tests/monitoring/test_snapshot.py ...............                        [100%]

99 passed in 1.24s
```

All 17 real experiment.yaml files in the repo validate successfully through the Pydantic schema.

## Issues encountered

- `mutation_url` had to be made optional (`str | None = None`) because two older experiments (`hover/dynamic-crossover`, `hover/steady-state-validation`) have `mutation_url: null` in their manifests. This is a backward-compatibility accommodation, documented with an inline comment.
- Unused `ExperimentSection` import and import sort order flagged by ruff -- auto-fixed in Task 4.
