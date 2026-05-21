# Canonical Benchmark History

Append-only registry of canonical benchmark runs. Each section below was
produced by `tools/canonical_benchmark/run_benchmark.py` and represents the
state of the harness at a specific commit + label.

**Format:** one section per run, separated by `---`. Rows below this header
are written by the script — do not hand-edit.

**Read order:** newest at the bottom. Compare a new row against the most
recent prior row with the same `Config:` line.

**Frozen knobs** (changes here void comparability with all prior rows):
`pipeline=standard num_parents=1 max_mutants=250 seeds=[0, 1]`.

See `README.md` for problem set, DB allocation, and interpretation guide.

---

---

## Canonical benchmark — `qwen3-local-defaults-bump`

- **Commit:** `dcbdc5c0`
- **Timestamp:** 2026-05-20T10:06:55+00:00
- **Config:** framework defaults — expected `pipeline=standard`, `num_parents=1`, `max_mutants=250`, seeds=[0, 1]. (Spawn passes `problem.name`, `redis.db`, `hydra.run.dir`, `llm_base_url`, `model_name` — see `tools/canonical_benchmark/README.md`.)
- **Parallelism:** 5

### Aggregate (per problem, 2 seeds)

| Problem | Mean | Std | Min | Max | n | n_failed |
|---|---|---|---|---|---|---|
| heilbron | 0.0277 | 0.0007 | 0.0272 | 0.0282 | 2 | 0 |
| hexagon_pack | -4.4147 | 0.0698 | -4.4641 | -4.3654 | 2 | 0 |
| alphaevolve/packing_circles/n_26 | 2.6209 | 0.0051 | 2.6173 | 2.6245 | 2 | 0 |
| alphaevolve/erdos_minimum_overlap | 0.3816 | 0.0000 | 0.3816 | 0.3816 | 2 | 0 |
| alphaevolve/sums_diffs_finite_sets | 1.1070 | 0.0013 | 1.1061 | 1.1079 | 2 | 0 |

### Raw per-seed

| Problem | Seed | DB | Fitness | Mutants | State |
|---|---|---|---|---|---|
| heilbron | 0 | 0 | 0.0272 | 143 | done |
| heilbron | 1 | 1 | 0.0282 | 211 | done |
| hexagon_pack | 0 | 2 | -4.3654 | 176 | done |
| hexagon_pack | 1 | 3 | -4.4641 | 116 | done |
| alphaevolve/packing_circles/n_26 | 0 | 4 | 2.6245 | 192 | done |
| alphaevolve/packing_circles/n_26 | 1 | 5 | 2.6173 | 188 | done |
| alphaevolve/erdos_minimum_overlap | 0 | 6 | 0.3816 | 248 | done |
| alphaevolve/erdos_minimum_overlap | 1 | 7 | 0.3816 | 248 | done |
| alphaevolve/sums_diffs_finite_sets | 0 | 8 | 1.1079 | 125 | done |
| alphaevolve/sums_diffs_finite_sets | 1 | 9 | 1.1061 | 106 | done |

_Total wall-clock: 721.8 min_

_Note: `alphaevolve/erdos_minimum_overlap` rows were hand-recomputed after this run. The auto-written `gigaevo top -n 1` extract omitted `--minimize` and surfaced the 1000.0 invalid sentinel as the result. Re-querying `gigaevo top -n 1 --minimize` on db=6/7 returned the actual best fitness (seed 0: 0.38160721863401736, seed 1: 0.3815984102272179) — the values above. `higher_is_better=false` is encoded in `problems/alphaevolve/erdos_minimum_overlap/metrics.yaml`, so future runs through `tools/canonical_benchmark/run_benchmark.py:primary_metric_higher_is_better` should pick `--minimize` automatically._
