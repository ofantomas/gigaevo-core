# Canonical Regression Benchmark

A fixed-configuration smoke test for the GigaEvo mutation/evolution machinery.
Run this **on every major breaking change** to detect generic regressions
before merging.

## What it measures

Best fitness found after a fixed mutation budget on 5 diverse math problems,
with 2 seeds each, holding the core evolution loop constant. The expectation
is that **a real generic improvement lifts the mean across most problems**
and **a regression drops at least one problem materially**.

**Identity guarantee**: the benchmark spawns

```
python run.py problem.name=<P> redis.db=<N> hydra.run.dir=<DIR> \
    llm_base_url=<URL> model_name=<NAME>
```

with NO other config overrides. The pipeline (the in-DAG intra-memory
pipeline via `pipeline=standard` → `IntraMemoryPipelineBuilder`) and the
mutation budget (`num_parents=1`, `max_mutants=250`) come from the
repo's framework defaults, so a fresh user typing
`python run.py problem.name=heilbron` reproduces the same pipeline and
budget. The LLM endpoint is the ONE exception — the benchmark requires
`--llm-base-url` and `--model-name` at every invocation because the
framework default in `config/constants/endpoints.yaml` (OpenRouter
Gemini-3-Flash) is too slow for a 10-run benchmark (~14-18h wall-clock).
No default endpoint is shipped because the right replacement is
environment-specific; pick whatever serves your benchmark hardware best
and **keep it pinned across rows** so wall-clock and fitness stay
comparable.

## Frozen contract (read from repository defaults)

| Knob | Value | Source |
|---|---|---|
| `pipeline` | `standard` (`IntraMemoryPipelineBuilder`) | `config/pipeline/auto.yaml` → `select_pipeline_builder` → `IntraMemoryPipelineBuilder` for non-contextual problems. Intra-card + prescriptive suggestion stages, no cross-population channel, no IdeaTracker post_run_hook. |
| `num_parents` | `1` | `config/constants/evolution.yaml`. One-parent → archetype mutation is the canonical mutation operator. |
| `max_mutants` | `250` | `config/constants/evolution.yaml`. ~1-4h per run; fits a 10-run benchmark in one workday at parallelism 5. |
| `seeds` | `[0, 1]` | Two seeds give a min std-of-mean signal at minimum compute. |
| LLM endpoint | Required CLI args `--llm-base-url` / `--model-name` (no default) | The framework default in `config/constants/endpoints.yaml` is OpenRouter Gemini-3-Flash which is too slow for a 10-run benchmark. The right replacement is environment-specific (local proxy, alternative provider, ...); shipping a default would tempt drift. Pick whatever serves your hardware best and keep it pinned across rows so wall-clock and fitness stay comparable. |

To measure the **extra-channel uplift** over this baseline, opt in on the CLI
via `--override ideas_tracker=default --override memory=local` (which leaves
`pipeline=standard` and merely turns on the post_run_hook + a local card
store). To measure the **live intra+extra pipeline**, use
`--override pipeline=intra_extra_memory --override ideas_tracker=default --override memory=local`.
Either combination is recorded into `history.jsonl` so rows stay
apples-to-apples within their override set.

Bumping any of these framework defaults voids comparability with the rows
already in `BENCHMARK_HISTORY.md`. Add a column or branch the file rather
than redefining the defaults silently.

## Problem set

| Problem | Type | Why included |
|---|---|---|
| `heilbron` | Geometric (Heilbron triangles) | Most historically benchmarked problem in the repo — anchor against prior cycles. |
| `hexagon_pack` | Geometric (hexagonal packing) | Different geometric flavor; tests evolutionary search on a different solution shape. |
| `alphaevolve/packing_circles/n_26` | Geometric (circle packing) | AlphaEvolve-style construction problem; size 26 is tractable. |
| `alphaevolve/erdos_minimum_overlap` | Combinatorial/analysis | Function-on-integers problem; tests non-geometric mutation. |
| `alphaevolve/sums_diffs_finite_sets` | Combinatorial (additive combinatorics) | Subset-construction problem; tests discrete mutation. |

The mix is **3 geometric + 1 analysis + 1 combinatorics** to keep the signal
robust against bias toward any one mutation style. None requires a scientific
breakthrough to score above zero — that's deliberate.

## DB allocation

Each `(problem, seed)` pair owns its own Redis DB to keep results isolated:

| Problem | Seed 0 | Seed 1 |
|---|---|---|
| heilbron | db=0 | db=1 |
| hexagon_pack | db=2 | db=3 |
| alphaevolve/packing_circles/n_26 | db=4 | db=5 |
| alphaevolve/erdos_minimum_overlap | db=6 | db=7 |
| alphaevolve/sums_diffs_finite_sets | db=8 | db=9 |

DBs 10-15 are intentionally reserved for higher-budget experimental runs.

## Usage

From the repo root:

```bash
python tools/canonical_benchmark/run_benchmark.py \
    --label "pre-merge-bundle" \
    --llm-base-url http://localhost:4000/v1 \
    --model-name your-served-model
```

Common options:

| Flag | Use |
|---|---|
| `--label LABEL` | **Required.** Short human label for the row in `BENCHMARK_HISTORY.md`. |
| `--llm-base-url URL` | **Required.** LLM endpoint base URL injected as `llm_base_url=...`. No default — see "LLM endpoint" row in the contract table above. |
| `--model-name NAME` | **Required.** Model name injected as `model_name=...`. Must match a model served by `--llm-base-url`. |
| `--parallelism N` | Launch up to N `run.py` processes concurrently. Default 1 (sequential). The LLM endpoint is typically the bottleneck — practical parallelism depends on its throughput; `--parallelism 10` fires all problems × seeds simultaneously. |
| `--override KEY=VAL` | **Common override applied to every run** (repeatable). Appended after the minimal spawn args (`problem.name`, `redis.db`, `hydra.run.dir`) so it wins on collision. Example: `--override stage_timeout=600 --override logging=quiet`. Records into `history.jsonl` so you can tell apart rows produced with different overrides. |
| `--problems P [P ...]` | Run a subset (e.g. `--problems heilbron hexagon_pack`). |
| `--seeds S [S ...]` | Run a subset of seeds. |
| `--skip-flush` | Don't flush Redis DBs first. Use if you intentionally want to resume. |
| `--skip-launch` | Only run extraction. Use if runs already finished. |
| `--dry-run` | Print commands without executing. |
| `--no-history` | Don't append to `BENCHMARK_HISTORY.md` / `history.jsonl`. |
| `--per-run-timeout-sec N` | Hard wall-clock cap per run.py (default 6h). |

There is intentionally no `--max-mutants` or `--num-parents` flag: those
would let the benchmark diverge from what a fresh-user
`python run.py problem.name=<P>` invocation actually runs. Bump the
matching `config/constants/*.yaml` if you need to change the contract —
or use `--override` if you just want a one-off probe.

The LLM endpoint flags exist because the framework default
(OpenRouter Gemini-3-Flash) is too slow for a 10-run benchmark, and the
right replacement is environment-specific so no default is shipped.
Whatever endpoint you pick, **keep it pinned across rows** in
`BENCHMARK_HISTORY.md`; one-off retargets belong on a side branch or
under a distinct `--label`.

### Parallel runs

When `--parallelism > 1`, each `(problem, seed)` pair gets its own Redis DB
(see allocation table above), so two pairs never share state. The LLM proxy
serves all concurrent requests on the same endpoint — at parallelism 10 you
will see throttling. Recommended:

```bash
# Default: sequential, ~10× per-run wall-clock
python tools/canonical_benchmark/run_benchmark.py --label foo

# 5-at-a-time: ~2× per-run wall-clock
python tools/canonical_benchmark/run_benchmark.py --label foo --parallelism 5

# All-at-once: ~1× per-run wall-clock, possible proxy throttling
python tools/canonical_benchmark/run_benchmark.py --label foo --parallelism 10
```

### Common overrides

Use `--override` when you want every benchmark run to carry the same extra
Hydra knob. Two motivating cases:

```bash
# Cap stage timeout for faster iteration during development:
python tools/canonical_benchmark/run_benchmark.py --label dev-fast \
    --override stage_timeout=180 --override dag_timeout=600

# Uplift sweep — same fresh-user spawn but turn on the extra-memory channel:
python tools/canonical_benchmark/run_benchmark.py --label intra-extra \
    --override pipeline=intra_extra_memory \
    --override ideas_tracker=default --override memory=local
```

Because `--override` is appended after the minimal spawn args and Hydra
applies overrides left-to-right, **your override always wins on collision** —
but keep in mind that changing one of the contract knobs (pipeline,
num_parents, max_mutants) via `--override` voids comparability with prior
rows in `BENCHMARK_HISTORY.md`. The JSONL record preserves what overrides
were active so you can filter apples-to-apples.

The script writes per-run Hydra output to `output/canonical_benchmark/<problem>_s<seed>_db<N>/`.

## Reading the report

The script prints — and (unless `--no-history`) appends to
`BENCHMARK_HISTORY.md` — a markdown report with two tables:

- **Aggregate (per problem, 2 seeds)** — mean / std / min / max / n / n_failed.
  `n_failed` counts seeds where extraction returned no rank-1 row (a run
  crashed early or the validator filtered everything out).
- **Raw per-seed** — one row per `(problem, seed, db)` with the rank-1 fitness
  pulled from `gigaevo top -n 1`.

A machine-readable copy goes to `history.jsonl` for downstream comparison
scripts.

## When a regression fires

1. Compare the new row's `Aggregate` mean to the most recent prior row in
   `BENCHMARK_HISTORY.md` with the same `pipeline` / `num_parents` /
   `max_mutants` triple.
2. Per-problem drop of `> 1σ` (where σ = the prior row's reported std) is the
   alarm threshold for a single problem. Drops on `≥ 2` problems are likely
   a real generic regression.
3. If `n_failed > 0`, the script wasn't able to extract a fitness for that
   seed — inspect the per-run log under
   `output/canonical_benchmark/<problem>_s<seed>_db<N>/run.log` before drawing
   conclusions.

## Why a benchmark and not a unit test

A unit test pins behavior at a specific input. The mutation operator is
non-deterministic (LLM-driven), so the value we care about is the *expected*
best-of-N after a fixed budget. The only way to measure that honestly is by
running the actual evolution loop and inspecting the resulting Redis state —
which is exactly what this script does.
