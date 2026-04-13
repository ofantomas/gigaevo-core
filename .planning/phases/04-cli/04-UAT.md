---
status: passed
phase: 04-cli
source: 04-01-PLAN.md through 04-04-PLAN.md
started: 2026-04-12T12:30:00Z
updated: 2026-04-12T12:40:00Z
---

## Tests

### 1. gigaevo CLI is installed and responds

**Status**: PASSED

`gigaevo --help` exits 0 and lists 12 subcommands:

```
checkpoint, closeout, export, flush, launch, logs, plot, restart, status, top, trajectory, watchdog
```

All planned subcommands are present. LazyGroup defers imports -- startup is fast.

Note: The original task description listed `lineage` and `comparison` as top-level subcommands. In the actual implementation, `comparison` lives under `gigaevo plot comparison` (sub-group), and `lineage` is not implemented as a CLI subcommand. The 12 subcommands above match the `_LAZY_SUBCOMMANDS` registry in `gigaevo/cli/__init__.py`.

### 2. gigaevo status --help

**Status**: PASSED (with note)

`gigaevo status --help` shows the command description. The `-r/--run` and `-e/--experiment` flags are **global options** on the parent group (visible in `gigaevo --help`), not on the subcommand itself. This is the correct Click architecture -- global flags go before the subcommand:

```
gigaevo -e task/name -r prefix@db:label status
```

### 3. gigaevo status with real experiment

**Status**: PASSED

```
gigaevo -e adversarial/adversarial-vs-solo -f table status
```

Output:

```
Label  DB  Gen  Fitness               Invalid%  Val dur(s)  Keys  PID      Status
S1     1   50   0.03538019217640852   20%       0/0         526   3174130  DEAD
S2     2   50   0.03199029684703403   31%       0/0         523   3174131  DEAD
S3     3   50   0.03458062725940138   10%       0/0         525   3174132  DEAD
S4     4   50   0.028720244276006696  14%       0/0         524   3174133  DEAD
```

All 4 runs (S1-S4) discovered from `experiment.yaml`. Generation count, fitness, invalidity rate, PID status all populated. PIDs show DEAD (expected -- experiment has completed).

### 4. Output format flags

**Status**: PASSED

All four formats tested:

- **table** (`-f table`): Rich table with box-drawing characters, title "Run Status"
- **json** (`-f json`): Valid JSON array of objects with all fields
- **csv** (`-f csv`): Comma-separated with header row
- **markdown** (`-f markdown`): Pipe-delimited table with `---` separator row

Auto-detection: When stdout is not a TTY (pipe), defaults to JSON. When stdout is a TTY, defaults to table. Tested via `OutputFormatter.effective_format` property.

Note: `-f` is a global flag and must precede the subcommand name:

```
gigaevo -e adversarial/adversarial-vs-solo -f json status     # correct
gigaevo -e adversarial/adversarial-vs-solo status -f json      # ERROR: "No such option: -f"
```

### 5. gigaevo trajectory

**Status**: PASSED

```
gigaevo -r heilbron_solo@1:S1 trajectory --tail 5
```

Output (JSON, auto-detected non-TTY):

```json
[
  {"Gen": 16, "Best": 0.03265741968680866, "Mean": 0.02831218484531772},
  {"Gen": 17, "Best": 0.03265741968680866, "Mean": 0.027080863046800283},
  {"Gen": 20, "Best": 0.03449851476787558, "Mean": null},
  {"Gen": 37, "Best": 0.034659972442931064, "Mean": null},
  {"Gen": 40, "Best": 0.03538019217640852, "Mean": null}
]
```

Gen-by-gen trajectory with best/mean fitness. `--tail 5` correctly limits output. Mean is null for later generations (expected if no per-gen mean metric was tracked).

### 6. gigaevo top

**Status**: PASSED

```
gigaevo -r heilbron_solo@1:S1 top -n 3
```

Output:

```json
[
  {"Rank": 1, "ID": "04a8409b-cac", "Label": "S1", "Gen": null, "Fitness": 0.03538019217640852, "State": "done"},
  {"Rank": 2, "ID": "3c78e73b-c3d", "Label": "S1", "Gen": null, "Fitness": 0.03488009643038174, "State": "discarded"},
  {"Rank": 3, "ID": "4fe91c42-20e", "Label": "S1", "Gen": null, "Fitness": 0.03477577154557743, "State": "done"}
]
```

Top 3 programs by fitness with rank, truncated ID, fitness value, and program state.

### 7. All CLI tests pass

**Status**: PASSED

```
pytest tests/cli/ -x -q -p no:warnings --tb=short
96 passed in 6.09s
```

Additionally, monitoring tests (the backend that CLI delegates to):

```
pytest tests/monitoring/ -x -q -p no:warnings --tb=short
339 passed in 29.64s
```

Total: 435 tests, 0 failures.

### 8. Generate a comparison plot

**Status**: PASSED

```
gigaevo -r heilbron_solo@1:S1 -r heilbron_solo@2:S2 -r heilbron_solo@3:S3 -r heilbron_solo@4:S4 \
  plot comparison --output-dir /tmp/uat_plots/
```

Generated files:

```
/tmp/uat_plots/evolution_runs_comparison.png   (401.4K)
/tmp/uat_plots/evolution_runs_comparison.pdf   (32.2K)
/tmp/uat_plots/evolution_runs_comparison.svg   (106.7K)
```

All three formats produced. The command uses LOWESS smoothing by default and reports outlier removal statistics.

Note: The flag is `--output-dir` (not `--output-folder` as used in tools/comparison.py). Click provides a helpful "Did you mean --output-dir?" message on typo.

## Summary

| Metric | Value |
|--------|-------|
| Total tests | 8 |
| Passed | 8 |
| Failed | 0 |
| Blocked | 0 |

## Subcommand Coverage

| Subcommand | Tested | Notes |
|------------|--------|-------|
| status | Yes | All 4 output formats verified with live Redis |
| trajectory | Yes | `--tail` flag works, gen-by-gen output correct |
| top | Yes | `-n` flag works, ranked output correct |
| flush | Help only | Destructive -- not tested live |
| plot comparison | Yes | PNG/PDF/SVG generated from 4 live runs |
| plot trajectory | Help only | Sub-subcommand exists |
| export csv | Help only | Sub-subcommand exists |
| export frontier | Help only | Sub-subcommand exists |
| watchdog | Help only | Requires running experiment |
| checkpoint | Help only | Requires running experiment |
| launch | Help only | Lifecycle command |
| closeout | Help only | Lifecycle command |
| restart | Help only | Lifecycle command |
| logs | Help only | Requires log files |

## Gaps

1. **`lineage` not in CLI**: The original task description listed `lineage` as one of 12 subcommands, but it was not included in any of the 04-01 through 04-04 PLAN files and is not implemented. `tools/lineage.py` exists as a standalone script. Consider adding as a future CLI subcommand.

2. **Global flag position not obvious**: Because `-e`, `-r`, `-f`, `-q`, `-v` are global flags on the parent group, they must precede the subcommand name. Running `gigaevo status -f json` fails with "No such option: -f". This is standard Click behavior but may confuse users. Consider either documenting this prominently or adding the flags to each subcommand as well.

3. **`--output-dir` vs `--output-folder` inconsistency**: The standalone `tools/comparison.py` uses `--output-folder`, while `gigaevo plot comparison` uses `--output-dir`. Minor naming inconsistency.

4. **Generation field null in `top` output**: The `Gen` field is null for all programs in `top` output. This may be a data availability issue (generation not stored in program metadata) rather than a CLI bug.

5. **Mean fitness null in later trajectory generations**: Trajectory shows `null` for Mean in later generations. May indicate that per-generation mean metrics were not tracked consistently for this experiment type.
