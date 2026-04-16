---
status: diagnosed
trigger: "cli-metrics-manifest-wiring: CLI doesn't handle adversarial experiments with heterogeneous metric sets"
created: 2026-04-13T00:00:00Z
updated: 2026-04-13T00:00:00Z
---

## Current Focus

hypothesis: CONFIRMED — CLI tools and manifest schema have zero awareness of population roles or per-population metric groups
test: Full code trace through manifest.py, run_resolver.py, status.py, plot_group.py, trajectory.py
expecting: N/A — root cause confirmed
next_action: Return diagnosis

## Symptoms

expected: Plot comparison for all existing metrics plotted correctly — comparable metrics together, incomparable metrics separated. Tables show role-appropriate metrics. Manifest specifies per-population reporting config.
actual: Different metrics mixed together. Incomparable metrics plotted on same axes. Tables show all metrics for all runs with nulls for irrelevant ones. No manifest schema for reporting config.
errors: No crashes — just bad/meaningless output
reproduction: Run gigaevo -e heilbron/asymmetric-iterations status or plot comparison
started: First usage of CLI with adversarial experiment having heterogeneous populations

## Eliminated

## Evidence

- timestamp: 2026-04-13T00:10:00Z
  checked: experiment.yaml manifest schema (tools/experiment/manifest.py)
  found: RunSpec has only (label, db, prefix, pipeline, problem_name, condition, chain_url, mutation_url, model_name, pid, log_path, extra_overrides, run_env). No population_role, no metric_group, no reporting_config.
  implication: Manifest has no concept of population role or per-population metric grouping.

- timestamp: 2026-04-13T00:11:00Z
  checked: experiment.yaml for heilbron/asymmetric-iterations
  found: 8 runs — 4 with problem_name=heilbron_adversarial/pop_a (Constructor/G) and 4 with problem_name=heilbron_adversarial/pop_b (Improver/D). population_role only exists in extra_overrides strings, not in manifest schema.
  implication: Population role is buried in extra_overrides (opaque to CLI), not a first-class manifest field.

- timestamp: 2026-04-13T00:12:00Z
  checked: pop_a/metrics.yaml vs pop_b/metrics.yaml
  found: pop_a has 8 metrics (fitness, is_valid, actual_fitness, quality, resistance, mean_improvement, best_post_improvement, n_opponents). pop_b has 8 metrics (fitness, is_valid, actual_fitness, mean_improvement_raw, mean_pre_quality, mean_post_quality, max_post_quality, n_opponents). Only 4 metrics are shared (fitness, is_valid, actual_fitness, n_opponents). 8 metrics are unique to one population.
  implication: Plotting all metrics on same axes mixes incomparable values. Status table shows nulls for population-specific metrics.

- timestamp: 2026-04-13T00:13:00Z
  checked: gigaevo/cli/run_resolver.py _resolve_from_experiment()
  found: For each run in manifest.runs, loads metric_names from problems/{problem_name}/metrics.yaml. This correctly discovers per-problem metrics. BUT the metric lists are passed per-RunConfig to monitoring — they are NOT used for grouping at the CLI layer.
  implication: Metrics ARE per-problem already at the RunConfig level, but the CLI presentation layer doesn't group or separate by population.

- timestamp: 2026-04-13T00:14:00Z
  checked: gigaevo/cli/status.py _snapshot_to_row() and _build_columns()
  found: _snapshot_to_row() iterates snapshot.metrics.items() and adds all metrics as columns. _build_columns() collects ALL metric column names across ALL rows into a single flat list. No grouping by population role or problem_name.
  implication: Status table shows union of all metrics across all populations, with None for metrics that don't exist in a given population.

- timestamp: 2026-04-13T00:15:00Z
  checked: gigaevo/cli/plot_group.py comparison command
  found: Takes a single --metric flag (default "fitness"). Plots ALL runs on the same axes for that metric. No way to filter by population, group runs by role, or plot different metrics for different populations.
  implication: Cannot compare Constructor actual_fitness against Improver actual_fitness meaningfully (different semantics). Cannot plot population-specific metrics at all.

- timestamp: 2026-04-13T00:16:00Z
  checked: gigaevo/cli/trajectory.py
  found: Takes a single --metric flag. Fetches same metric for ALL runs. Shows in a single table. No population-awareness.
  implication: Same issue as status and comparison plot.

- timestamp: 2026-04-13T00:17:00Z
  checked: ProblemSpec in manifest.py
  found: ProblemSpec is a SINGLE entry (not per-run). Fields: has_test_set, fitness_type, metric_name. There is only ONE metric_name for the whole experiment.
  implication: Manifest assumes homogeneous populations with a single primary metric. Adversarial experiments with heterogeneous populations break this assumption.

## Resolution

root_cause: |
  The CLI and manifest schema were designed for single-population experiments where all runs share the same problem type and identical metrics. There are FOUR distinct gaps:

  GAP 1 — Manifest schema lacks population role metadata:
  - RunSpec has no `population_role` field (constructor/improver)
  - ProblemSpec is singular — one metric_name for the whole experiment
  - population_role exists only buried in extra_overrides strings, invisible to the CLI

  GAP 2 — Manifest has no reporting/display configuration:
  - No schema for specifying which metrics to show in status tables per population
  - No schema for specifying which metrics to plot in comparison plots per population
  - No schema for specifying metric grouping for multi-panel plots
  - No schema for defining "comparable" metric pairs across populations

  GAP 3 — CLI status command merges all metrics into flat table:
  - _build_columns() unions all metric column names across all runs
  - Produces a wide table where half the columns are None for each population
  - No filtering by population role
  - No separate tables per population

  GAP 4 — CLI plot commands are single-metric, all-runs:
  - `comparison` plots one metric across all runs on same axes
  - No way to group runs by population type for separate panels
  - No way to specify different metrics for different populations
  - `arms-race` partially handles this (separate G/D panels) but only via --paired flag and same metric for both
  - No multi-metric comparison (e.g. actual_fitness for G, fitness for D)

  Files involved:
  - tools/experiment/manifest.py: RunSpec and ProblemSpec dataclasses
  - gigaevo/cli/run_resolver.py: _resolve_from_experiment() — already loads per-problem metrics but doesn't tag with role
  - gigaevo/cli/status.py: _snapshot_to_row(), _build_columns() — flat metric merge
  - gigaevo/cli/plot_group.py: comparison command — single --metric for all runs
  - gigaevo/cli/trajectory.py: trajectory command — single --metric for all runs

fix:
verification:
files_changed: []
