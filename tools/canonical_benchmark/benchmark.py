"""Canonical regression benchmark — pure logic.

Frozen contract:
- ``python run.py problem.name=<P> redis.db=<N> hydra.run.dir=<DIR>`` — the
  spawned command carries NO config overrides. Everything that defines the
  benchmark (pipeline, num_parents, max_mutants, LLM endpoint, ...) is read
  from the repository's framework defaults, so a fresh user running
  ``python run.py problem.name=heilbron`` reproduces a canonical row.
- Framework defaults at time of writing: ``pipeline=standard``
  (``IntraMemoryPipelineBuilder``), ``num_parents=1``, ``max_mutants=250``.
- LLM endpoint (``llm_base_url`` + ``model_name``) is REQUIRED at
  invocation — the framework default points at OpenRouter Gemini-3-Flash
  which is too slow for a 10-run sweep, but selecting an alternative is
  the caller's responsibility (no opinion baked in).
- 5 problems × 2 seeds = 10 runs per benchmark invocation.
- Per-(problem,seed) Redis DB in [0..9] so runs are isolated.

Pure logic only: no subprocess, no Redis, no filesystem. The CLI driver
(`run_benchmark.py`) wires these primitives together.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import json
import math

PROBLEMS: tuple[str, ...] = (
    "heilbron",
    "hexagon_pack",
    "alphaevolve/packing_circles/n_26",
    "alphaevolve/erdos_minimum_overlap",
    "alphaevolve/sums_diffs_finite_sets",
)
SEEDS: tuple[int, ...] = (0, 1)

# Informational only — used in the markdown report header. The benchmark does
# NOT inject these as Hydra overrides; they document the expected framework
# defaults so readers of BENCHMARK_HISTORY.md can spot drift. Bump these
# alongside ``config/constants/evolution.yaml``.
DEFAULT_MAX_MUTANTS = 250
DEFAULT_NUM_PARENTS = 1


@dataclass(frozen=True)
class ChainVariant:
    """One row of the chain benchmark matrix: a (problem, runner-preset) pair."""

    label: str  # e.g. "hover_none_fast"
    problem: str  # e.g. "chains/hover/static_soft"
    runner: str  # e.g. "none" — selects config/chains/runner/<runner>.yaml


# Mirrors the NeurIPS matrix from feat/carl-runner-implementation's
# scripts/launch_experiments.py — 8 hover feedback×execution combos + 1 each for
# ifbench / gsm8k / hotpotqa / aime. Task paths point at the paper's canonical
# `chains/neurips_test/<task>/static` dirs so the benchmark matches the
# pre-registered NeurIPS configuration. Labels match the original launcher.
CHAIN_VARIANTS: tuple[ChainVariant, ...] = (
    ChainVariant("hover_none_fast", "chains/neurips_test/hover/static", "none"),
    ChainVariant("hover_simple_fast", "chains/neurips_test/hover/static", "simple"),
    ChainVariant("hover_dataset_fast", "chains/neurips_test/hover/static", "dataset"),
    ChainVariant("hover_metrics_fast", "chains/neurips_test/hover/static", "metrics"),
    ChainVariant("hover_none_sc", "chains/neurips_test/hover/static", "self_critic"),
    ChainVariant(
        "hover_simple_sc", "chains/neurips_test/hover/static", "self_critic_simple"
    ),
    ChainVariant(
        "hover_dataset_sc", "chains/neurips_test/hover/static", "self_critic_dataset"
    ),
    ChainVariant(
        "hover_metrics_sc", "chains/neurips_test/hover/static", "self_critic_metrics"
    ),
    ChainVariant("ifbench_none_fast", "chains/neurips_test/ifbench/static", "none"),
    ChainVariant("gsm8k_none_fast", "chains/neurips_test/gsm8k/static", "none"),
    ChainVariant("hotpotqa_none_fast", "chains/neurips_test/hotpotqa/static", "none"),
    ChainVariant("aime_none_fast", "chains/neurips_test/aime/static", "none"),
)


@dataclass(frozen=True)
class BenchRow:
    """One (problem, seed) result extracted via `gigaevo top -n 1`.

    ``variant_label`` is optional. For the standard 5-problem benchmark each
    problem appears exactly once per seed so ``variant_label`` stays None and
    aggregation groups on ``problem``. For the chain benchmark several variants
    can share one ``problem`` (e.g. 8 hover variants only differ by runner
    preset), so ``variant_label`` becomes the grouping key.
    """

    problem: str
    seed: int
    fitness: float | None
    mutants_evaluated: int
    state: str  # "done" | "error" | "timeout" | "running"
    variant_label: str | None = None


def db_for(problem_idx: int, seed_idx: int) -> int:
    """Map (problem_idx, seed_idx) to a unique Redis DB in [0..9].

    Layout: db = problem_idx * 2 + seed_idx. Problem 0 owns DBs (0, 1),
    problem 4 owns (8, 9). Keeps the canonical benchmark off DBs 10-15
    which higher experiments (Heilbron 800-iter on db=11, etc.) tend to use.
    """
    if not 0 <= problem_idx < len(PROBLEMS):
        raise ValueError(f"problem_idx {problem_idx} out of range [0, {len(PROBLEMS)})")
    if not 0 <= seed_idx < len(SEEDS):
        raise ValueError(f"seed_idx {seed_idx} out of range [0, {len(SEEDS)})")
    return problem_idx * len(SEEDS) + seed_idx


def chain_db_for(variant_idx: int, seed_idx: int = 0) -> int:
    """Map a (chain_variant, seed) to a Redis DB in [0..15].

    10 variants × 1 seed → DBs 0..9 (default). For seed_idx > 0 we need a
    --reuse-dbs strategy in the caller because 10 × 2 = 20 > 16 (Redis caps at
    16 DBs); the helper here still returns a deterministic db for variant_idx
    so the caller can sequence runs through the same DB after a flush.
    """
    if not 0 <= variant_idx < len(CHAIN_VARIANTS):
        raise ValueError(
            f"variant_idx {variant_idx} out of range [0, {len(CHAIN_VARIANTS)})"
        )
    if seed_idx < 0:
        raise ValueError(f"seed_idx {seed_idx} must be >= 0")
    return variant_idx


def build_run_command(
    *,
    python_exe: str,
    problem: str,
    db: int,
    output_dir: str,
    llm_base_url: str,
    model_name: str,
    extra_overrides: Iterable[str] | None = None,
) -> list[str]:
    """Construct the `python run.py ...` command for a single benchmark run.

    Pinned spawn args: ``problem.name``, ``redis.db``, ``hydra.run.dir``,
    plus ``llm_base_url`` and ``model_name``. The first three identify the
    run; the latter two pin the LLM target — both are caller-supplied so
    no opinion about which endpoint or model gets shipped lives in this
    file.

    Every other knob (pipeline, num_parents, max_mutants, memory,
    ideas_tracker, ...) comes from the repository's framework defaults so
    a fresh user running ``python run.py problem.name=X`` reproduces the
    same pipeline — the LLM endpoint is the ONE exception, intentionally
    parameterised because the framework default is too slow for a 10-run
    sweep but the right replacement is environment-specific.

    ``extra_overrides`` are passed through verbatim AFTER every pinned
    override so they win Hydra's "last value wins" rule on collision —
    letting users opt in to e.g. ``--override ideas_tracker=default`` for
    uplift sweeps, or ``--override stage_timeout=600`` for dev iterations.
    """
    cmd = [
        python_exe,
        "run.py",
        f"problem.name={problem}",
        f"redis.db={db}",
        f"hydra.run.dir={output_dir}",
        f"llm_base_url={llm_base_url}",
        f"model_name={model_name}",
    ]
    if extra_overrides:
        cmd.extend(extra_overrides)
    return cmd


def build_chain_run_command(
    *,
    python_exe: str,
    variant: ChainVariant,
    db: int,
    output_dir: str,
    llm_base_url: str,
    model_name: str,
    extra_overrides: Iterable[str] | None = None,
) -> list[str]:
    """Like ``build_run_command`` but adds ``chains/runner=<preset>``.

    Chain tasks require selecting a runner preset from
    ``config/chains/runner/*.yaml``; the preset emits the
    ``GIGAEVO_CHAIN_RUNNER_CONFIG`` env var that the chain runner reads.
    Everything else (pipeline, num_parents, max_mutants) still comes from
    framework defaults so chain rows are reproducible from a single
    ``problem.name`` + ``chains/runner`` pair.
    """
    overrides = [f"chains/runner={variant.runner}"]
    if extra_overrides:
        overrides.extend(extra_overrides)
    return build_run_command(
        python_exe=python_exe,
        problem=variant.problem,
        db=db,
        output_dir=output_dir,
        llm_base_url=llm_base_url,
        model_name=model_name,
        extra_overrides=overrides,
    )


def build_top_cmd(
    *,
    gigaevo_exe: str,
    problem: str,
    db: int,
    higher_is_better: bool = True,
) -> list[str]:
    """Construct the ``gigaevo top -n 1`` command for a benchmark (problem, db).

    For minimization problems (``higher_is_better=False``) the command must
    include ``--minimize``, otherwise ``gigaevo top`` returns the highest
    fitness — which for problems like ``alphaevolve/erdos_minimum_overlap``
    (sentinel = 1000.0, valid range = [0.380924, 1.0]) is the invalid
    sentinel rather than the run's actual best program. Mis-reading the
    sentinel as a result silently corrupts the benchmark row, so the
    direction MUST come from each problem's ``metrics.yaml`` rather than a
    hard-coded default.
    """
    cmd = [gigaevo_exe, "-r", f"{problem}@{db}", "-f", "json", "top", "-n", "1"]
    if not higher_is_better:
        cmd.append("--minimize")
    return cmd


def parse_top_n_fitness(stdout: str) -> float | None:
    """Extract rank-1 Fitness from `gigaevo -f json top -n 1` stdout.

    Returns None on any parse error or missing/non-numeric Fitness — the
    aggregator distinguishes None (failed extraction) from numeric values.
    """
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, list) or not payload:
        return None
    first = payload[0]
    if not isinstance(first, dict):
        return None
    raw = first.get("Fitness")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    return None


def aggregate_results(rows: Iterable[BenchRow]) -> dict[str, dict]:
    """Group rows by ``variant_label`` (when set) or ``problem`` otherwise.

    None fitness values are surfaced via `n_failed` but excluded from stats —
    they would otherwise NaN-poison the mean and corrupt the regression signal.
    """
    by_problem: dict[str, list[BenchRow]] = {}
    for row in rows:
        key = row.variant_label or row.problem
        by_problem.setdefault(key, []).append(row)

    out: dict[str, dict] = {}
    for problem, problem_rows in by_problem.items():
        numeric = [r.fitness for r in problem_rows if r.fitness is not None]
        n_failed = sum(1 for r in problem_rows if r.fitness is None)
        if numeric:
            mean = sum(numeric) / len(numeric)
            if len(numeric) >= 2:
                # Sample standard deviation (Bessel-corrected, divides by n-1).
                # Matches what people expect for a 2-seed delta.
                var = sum((x - mean) ** 2 for x in numeric) / (len(numeric) - 1)
                std = math.sqrt(var)
            else:
                std = 0.0
            stats = {
                "mean": mean,
                "std": std,
                "min": min(numeric),
                "max": max(numeric),
                "n": len(numeric),
                "n_failed": n_failed,
                "values": numeric,
            }
        else:
            stats = {
                "mean": None,
                "std": None,
                "min": None,
                "max": None,
                "n": 0,
                "n_failed": n_failed,
                "values": [],
            }
        out[problem] = stats
    return out


def _fmt(value: float | None, decimals: int = 4) -> str:
    if value is None:
        return "N/A"
    return f"{value:.{decimals}f}"


def format_results_markdown(
    *,
    label: str,
    commit: str,
    timestamp: str,
    rows: list[BenchRow],
    extra_overrides: list[str] | None = None,
    parallelism: int | None = None,
) -> str:
    """Render a self-contained markdown report for one benchmark invocation.

    Layout: header metadata → per-problem aggregate table → raw per-seed table
    → failure callouts (if any). Suitable both for printing to terminal and
    for appending into the rolling BENCHMARK_HISTORY.md registry.
    """
    agg = aggregate_results(rows)
    failed = [r for r in rows if r.fitness is None]

    lines: list[str] = []
    lines.append(f"## Canonical benchmark — `{label}`")
    lines.append("")
    lines.append(f"- **Commit:** `{commit}`")
    lines.append(f"- **Timestamp:** {timestamp}")
    lines.append(
        f"- **Config:** framework defaults — expected `pipeline=standard`, "
        f"`num_parents={DEFAULT_NUM_PARENTS}`, `max_mutants={DEFAULT_MAX_MUTANTS}`, "
        f"seeds={list(SEEDS)}. (Spawn passes `problem.name`, `redis.db`, "
        f"`hydra.run.dir`, `llm_base_url`, `model_name` — see "
        f"`tools/canonical_benchmark/README.md`.)"
    )
    if extra_overrides:
        lines.append(f"- **Extra overrides:** `{' '.join(extra_overrides)}`")
    if parallelism is not None:
        lines.append(f"- **Parallelism:** {parallelism}")
    lines.append("")

    lines.append("### Aggregate (per problem, 2 seeds)")
    lines.append("")
    lines.append("| Problem | Mean | Std | Min | Max | n | n_failed |")
    lines.append("|---|---|---|---|---|---|---|")
    for problem in PROBLEMS:
        stats = agg.get(problem)
        if stats is None:
            lines.append(f"| {problem} | N/A | N/A | N/A | N/A | 0 | 0 |")
            continue
        lines.append(
            "| {p} | {m} | {s} | {lo} | {hi} | {n} | {nf} |".format(
                p=problem,
                m=_fmt(stats["mean"]),
                s=_fmt(stats["std"]),
                lo=_fmt(stats["min"]),
                hi=_fmt(stats["max"]),
                n=stats["n"],
                nf=stats["n_failed"],
            )
        )
    lines.append("")

    lines.append("### Raw per-seed")
    lines.append("")
    lines.append("| Problem | Seed | DB | Fitness | Mutants | State |")
    lines.append("|---|---|---|---|---|---|")
    for row in rows:
        problem_idx = PROBLEMS.index(row.problem) if row.problem in PROBLEMS else -1
        seed_idx = SEEDS.index(row.seed) if row.seed in SEEDS else -1
        db = db_for(problem_idx, seed_idx) if problem_idx >= 0 and seed_idx >= 0 else -1
        lines.append(
            f"| {row.problem} | {row.seed} | {db} | {_fmt(row.fitness)} | "
            f"{row.mutants_evaluated} | {row.state} |"
        )

    if failed:
        lines.append("")
        lines.append("### Failed extractions")
        lines.append("")
        for row in failed:
            lines.append(
                f"- `{row.problem}@seed{row.seed}`: state={row.state}, "
                f"mutants={row.mutants_evaluated}"
            )

    lines.append("")
    return "\n".join(lines)


def format_chain_results_markdown(
    *,
    label: str,
    commit: str,
    timestamp: str,
    rows: list[BenchRow],
    seeds: Iterable[int],
    extra_overrides: list[str] | None = None,
    parallelism: int | None = None,
) -> str:
    """Render a markdown report for the chain benchmark matrix.

    Rows are expected to carry ``variant_label`` so aggregation groups by
    (problem, runner-preset) pair rather than just by problem.
    """
    agg = aggregate_results(rows)
    failed = [r for r in rows if r.fitness is None]
    seeds_list = list(seeds)

    lines: list[str] = []
    lines.append(f"## Chain benchmark — `{label}`")
    lines.append("")
    lines.append(f"- **Commit:** `{commit}`")
    lines.append(f"- **Timestamp:** {timestamp}")
    lines.append(
        f"- **Config:** framework defaults — expected `pipeline=standard`, "
        f"`num_parents={DEFAULT_NUM_PARENTS}`, `max_mutants={DEFAULT_MAX_MUTANTS}`, "
        f"seeds={seeds_list}. (Spawn passes `problem.name`, `redis.db`, "
        f"`hydra.run.dir`, `llm_base_url`, `model_name`, `chains/runner=<preset>` "
        f"— see `tools/canonical_benchmark/README.md`.)"
    )
    if extra_overrides:
        lines.append(f"- **Extra overrides:** `{' '.join(extra_overrides)}`")
    if parallelism is not None:
        lines.append(f"- **Parallelism:** {parallelism}")
    lines.append("")

    lines.append(f"### Aggregate (per variant, {len(seeds_list)} seed(s))")
    lines.append("")
    lines.append(
        "| Variant | Problem | Runner | Mean | Std | Min | Max | n | n_failed |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for variant in CHAIN_VARIANTS:
        stats = agg.get(variant.label)
        if stats is None:
            lines.append(
                f"| {variant.label} | {variant.problem} | {variant.runner} "
                f"| N/A | N/A | N/A | N/A | 0 | 0 |"
            )
            continue
        lines.append(
            "| {v} | {p} | {r} | {m} | {s} | {lo} | {hi} | {n} | {nf} |".format(
                v=variant.label,
                p=variant.problem,
                r=variant.runner,
                m=_fmt(stats["mean"]),
                s=_fmt(stats["std"]),
                lo=_fmt(stats["min"]),
                hi=_fmt(stats["max"]),
                n=stats["n"],
                nf=stats["n_failed"],
            )
        )
    lines.append("")

    lines.append("### Raw per-seed")
    lines.append("")
    lines.append("| Variant | Seed | DB | Fitness | Mutants | State |")
    lines.append("|---|---|---|---|---|---|")
    variant_idx_by_label = {v.label: i for i, v in enumerate(CHAIN_VARIANTS)}
    for row in rows:
        variant_label = row.variant_label or row.problem
        variant_idx = variant_idx_by_label.get(variant_label, -1)
        db = chain_db_for(variant_idx) if variant_idx >= 0 else -1
        lines.append(
            f"| {variant_label} | {row.seed} | {db} | {_fmt(row.fitness)} | "
            f"{row.mutants_evaluated} | {row.state} |"
        )

    if failed:
        lines.append("")
        lines.append("### Failed extractions")
        lines.append("")
        for row in failed:
            label_str = row.variant_label or row.problem
            lines.append(
                f"- `{label_str}@seed{row.seed}`: state={row.state}, "
                f"mutants={row.mutants_evaluated}"
            )

    lines.append("")
    return "\n".join(lines)
