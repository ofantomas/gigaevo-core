#!/usr/bin/env python3
"""CLI driver for the canonical 5-problem × 2-seed regression benchmark.

Usage:
    python tools/canonical_benchmark/run_benchmark.py --label my-change

What it does, in order, for each (problem, seed) pair:
1. (optional) Flush the target Redis DB.
2. Launch `python run.py problem.name=<p> pipeline=standard ...` and wait.
3. Extract the rank-1 Fitness via `gigaevo -r <p>@<db> -f json top -n 1`.
4. Aggregate all rows and write a markdown report + JSONL record.

Why run on every major breaking change: the canonical benchmark holds the
mutation/evolution machinery constant (no memory, no context stages) and
runs a fixed budget across diverse math problems. Regression there means the
core operator broke; uplift there means a real generic improvement.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

# Allow running via `python tools/canonical_benchmark/run_benchmark.py` from any
# CWD: add the repo root to sys.path before package import resolves.
_REPO_ROOT_FOR_IMPORT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT_FOR_IMPORT))

from tools.canonical_benchmark.benchmark import (  # noqa: E402
    CHAIN_VARIANTS,
    DEFAULT_MAX_MUTANTS,
    DEFAULT_NUM_PARENTS,
    PROBLEMS,
    SEEDS,
    BenchRow,
    ChainVariant,
    aggregate_results,
    build_chain_run_command,
    build_run_command,
    build_top_cmd,
    chain_db_for,
    db_for,
    format_chain_results_markdown,
    format_results_markdown,
    parse_top_n_fitness,
)

# Resolved at import time, can be overridden via --python-exe / --gigaevo-exe.
DEFAULT_PYTHON_EXE = "/home/jovyan/.mlspace/envs/evo/bin/python3"
DEFAULT_GIGAEVO_EXE = shutil.which("gigaevo") or "/home/user/conda/bin/gigaevo"
REPO_ROOT = Path(__file__).resolve().parents[2]
HISTORY_PATH = REPO_ROOT / "tools" / "canonical_benchmark" / "BENCHMARK_HISTORY.md"
JSONL_PATH = REPO_ROOT / "tools" / "canonical_benchmark" / "history.jsonl"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--label",
        required=True,
        help="Short human label for this benchmark run (e.g. 'pre-merge-bundle').",
    )
    p.add_argument(
        "--output-root",
        default=str(REPO_ROOT / "output" / "canonical_benchmark"),
        help="Parent dir for per-run hydra.run.dir outputs.",
    )
    p.add_argument(
        "--python-exe",
        default=DEFAULT_PYTHON_EXE,
    )
    p.add_argument(
        "--gigaevo-exe",
        default=DEFAULT_GIGAEVO_EXE,
    )
    p.add_argument(
        "--llm-base-url",
        required=True,
        help=(
            "LLM endpoint base URL injected into every spawn as "
            "``llm_base_url=...``. Required — the framework default in "
            "``config/constants/endpoints.yaml`` points at OpenRouter "
            "Gemini-3-Flash which is too slow for a 10-run benchmark, but "
            "the right replacement is environment-specific so no default is "
            "shipped. Example: ``http://localhost:4000/v1``."
        ),
    )
    p.add_argument(
        "--model-name",
        required=True,
        help=(
            "Model name injected into every spawn as ``model_name=...``. "
            "Required — must match a model served by ``--llm-base-url``."
        ),
    )
    p.add_argument(
        "--parallelism",
        type=int,
        default=1,
        help="How many run.py processes to launch concurrently. Default 1 (sequential). "
        "Set to len(problems)*len(seeds)=10 to run everything at once; the LLM endpoint "
        "is the bottleneck so practical parallelism depends on its throughput.",
    )
    p.add_argument(
        "--override",
        action="append",
        default=[],
        metavar="KEY=VAL",
        dest="extra_overrides",
        help="Extra Hydra override applied to EVERY run (repeatable). "
        "Appended AFTER the frozen canonical knobs, so it wins on collision. "
        "Example: --override stage_timeout=600 --override logging=quiet",
    )
    p.add_argument(
        "--per-run-timeout-sec",
        type=int,
        default=6 * 60 * 60,  # 6h per run
        help="Hard wall-clock cap per run.py invocation (default 6h).",
    )
    p.add_argument(
        "--profile",
        choices=("standard", "chain"),
        default="standard",
        help=(
            "Which benchmark matrix to run. ``standard`` (default) sweeps the "
            "5 canonical math problems × 2 seeds. ``chain`` sweeps the 10-row "
            "NeurIPS chain matrix (8 hover feedback×execution combos + "
            "ifbench + gsm8k) × 1 seed (by default). With ``chain`` the "
            "``--problems`` flag is ignored; use ``--variants`` instead."
        ),
    )
    p.add_argument(
        "--problems",
        nargs="*",
        default=list(PROBLEMS),
        help="Subset of problems to run for ``--profile standard`` (default: all 5).",
    )
    p.add_argument(
        "--variants",
        nargs="*",
        default=None,
        help=(
            "Subset of chain variant labels to run for ``--profile chain`` "
            "(default: all 10). Example: --variants hover_none_fast gsm8k_none_fast"
        ),
    )
    p.add_argument(
        "--seeds",
        nargs="*",
        type=int,
        default=None,
        help=(
            "Subset of seeds. Default depends on profile: ``standard`` → 0 1; "
            "``chain`` → 0. For ``chain`` with more than one seed pass "
            "``--reuse-dbs`` so the same DB is reused across seeds (Redis caps "
            "at 16 DBs and 10 variants × 2 seeds = 20 > 16)."
        ),
    )
    p.add_argument(
        "--reuse-dbs",
        action="store_true",
        help=(
            "For ``--profile chain --seeds 0 1`` only: extract then flush "
            "between seeds so the same DB serves multiple seeds in sequence. "
            "Forces parallelism=1 across seeds; variants within one seed can "
            "still run in parallel per ``--parallelism``."
        ),
    )
    p.add_argument(
        "--skip-flush",
        action="store_true",
        help="Don't `gigaevo flush` the target DBs before launching.",
    )
    p.add_argument(
        "--skip-launch",
        action="store_true",
        help="Only run extraction (assume runs already finished on their DBs).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands but do not execute.",
    )
    p.add_argument(
        "--no-history",
        action="store_true",
        help="Don't append the run to BENCHMARK_HISTORY.md or history.jsonl.",
    )
    return p.parse_args()


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def _git_head_short() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            check=True,
            timeout=10,
        )
        return result.stdout.strip() or "UNKNOWN"
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
    ):
        return "UNKNOWN"


def flush_db(gigaevo_exe: str, db: int, dry_run: bool) -> None:
    cmd = [gigaevo_exe, "flush", "--db", str(db), "--confirm"]
    print(f"  [flush] {' '.join(cmd)}", flush=True)
    if dry_run:
        return
    subprocess.run(cmd, check=False, timeout=60)


def launch_run(
    *,
    python_exe: str,
    problem: str,
    db: int,
    output_dir: Path,
    timeout_sec: int,
    dry_run: bool,
    llm_base_url: str,
    model_name: str,
    extra_overrides: list[str] | None = None,
) -> tuple[int, str, str]:
    """Launch one run.py invocation and wait. Returns (returncode, stdout_tail, stderr_tail).

    The spawn carries ``problem.name`` / ``redis.db`` / ``hydra.run.dir``
    (which identify the run) plus ``llm_base_url`` / ``model_name``
    (which pin the LLM target). Every other knob (pipeline, num_parents,
    max_mutants, memory, ideas_tracker, ...) comes from the framework
    defaults so a fresh user reproduces the same pipeline.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = build_run_command(
        python_exe=python_exe,
        problem=problem,
        db=db,
        output_dir=str(output_dir),
        llm_base_url=llm_base_url,
        model_name=model_name,
        extra_overrides=extra_overrides,
    )
    print(f"  [launch] {' '.join(cmd)}", flush=True)
    if dry_run:
        return 0, "(dry-run)", ""

    # OPENAI_API_KEY is loaded from .env by run.py — we don't need to inject
    # it. HTTP_PROXY/HTTPS_PROXY MUST be absent for run.py: the LLM endpoint
    # is reached directly, not through the corporate proxy.
    env = {**os.environ}
    env.pop("HTTP_PROXY", None)
    env.pop("HTTPS_PROXY", None)
    env.pop("http_proxy", None)
    env.pop("https_proxy", None)

    log_file = output_dir / "run.log"
    with log_file.open("w") as logf:
        try:
            proc = subprocess.run(
                cmd,
                cwd=REPO_ROOT,
                env=env,
                stdout=logf,
                stderr=subprocess.STDOUT,
                timeout=timeout_sec,
                check=False,
            )
            return proc.returncode, "", ""
        except subprocess.TimeoutExpired:
            return 124, "", "TIMEOUT"


def primary_metric_higher_is_better(problem: str) -> bool:
    """Read ``problems/<problem>/metrics.yaml`` and return its primary direction.

    Returns True (maximize) when the primary metric has ``higher_is_better:
    true`` or no explicit flag. Returns False (minimize) only when the YAML
    explicitly sets ``higher_is_better: false`` — which forces the benchmark
    to query ``gigaevo top --minimize`` instead of the default descending
    sort. The benchmark used to ignore this and pulled the sentinel value
    (e.g. 1000.0 for erdos_minimum_overlap) as if it were the best result —
    that's the bug this helper exists to prevent.

    Defaults to True if the metrics file is absent or unparsable so the
    function never raises and a typo in the problem name doesn't silently
    flip the sort direction.
    """
    import yaml  # local import: pure unit tests of build_top_cmd shouldn't need yaml

    path = REPO_ROOT / "problems" / problem / "metrics.yaml"
    if not path.exists():
        return True
    try:
        with path.open() as fh:
            doc = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return True
    for spec in (doc.get("specs") or {}).values():
        if isinstance(spec, dict) and spec.get("is_primary"):
            return bool(spec.get("higher_is_better", True))
    return True


def extract_fitness(
    gigaevo_exe: str, problem: str, db: int, dry_run: bool
) -> tuple[float | None, str]:
    """Query `gigaevo top -n 1` for the best fitness on (problem, db).

    The command picks up ``--minimize`` automatically for problems whose
    primary metric is lower-is-better (see ``primary_metric_higher_is_better``)
    so the row reflects the run's actual best program, not the sentinel.
    """
    higher_is_better = primary_metric_higher_is_better(problem)
    cmd = build_top_cmd(
        gigaevo_exe=gigaevo_exe,
        problem=problem,
        db=db,
        higher_is_better=higher_is_better,
    )
    print(f"  [extract] {' '.join(cmd)}", flush=True)
    if dry_run:
        return None, "(dry-run)"
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, check=False
        )
    except subprocess.TimeoutExpired:
        return None, "extract-timeout"
    if result.returncode != 0:
        return None, f"extract-rc={result.returncode}"
    fitness = parse_top_n_fitness(result.stdout)
    state = "done" if fitness is not None else "no-rows"
    return fitness, state


def count_mutants(gigaevo_exe: str, problem: str, db: int, dry_run: bool) -> int:
    """Lightweight: ask gigaevo top -n 1 for Gen and assume it tracks mutant count proxy.

    For a more honest count we'd query `evolution_runs:*` set cardinality on the
    DB; this proxy is good enough for the report (the run command pins
    max_mutants=250 so it's either ~max or hit timeout/error)."""
    if dry_run:
        return 0
    # Try `gigaevo status` which prints generation + key count.
    try:
        result = subprocess.run(
            [gigaevo_exe, "-r", f"{problem}@{db}", "-f", "json", "status"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode == 0:
            payload = json.loads(result.stdout)
            if isinstance(payload, list) and payload:
                row = payload[0]
                # `generation` is a per-island advance counter; close enough as proxy.
                return int(row.get("Gen") or row.get("generation") or 0)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, ValueError, TypeError):
        pass
    return 0


def run_one(args: argparse.Namespace, problem: str, seed: int) -> BenchRow:
    problem_idx = PROBLEMS.index(problem)
    seed_idx = SEEDS.index(seed)
    db = db_for(problem_idx, seed_idx)
    safe_name = problem.replace("/", "_")
    run_out = Path(args.output_root) / f"{safe_name}_s{seed}_db{db}"

    print(f"\n=== {problem} seed={seed} db={db} ===", flush=True)
    if not args.skip_launch and not args.skip_flush:
        flush_db(args.gigaevo_exe, db, args.dry_run)
    if not args.skip_launch:
        rc, _out, _err = launch_run(
            python_exe=args.python_exe,
            problem=problem,
            db=db,
            output_dir=run_out,
            timeout_sec=args.per_run_timeout_sec,
            dry_run=args.dry_run,
            llm_base_url=args.llm_base_url,
            model_name=args.model_name,
            extra_overrides=args.extra_overrides,
        )
        if rc != 0:
            print(f"  [warn] run.py exit={rc}", flush=True)

    fitness, state = extract_fitness(args.gigaevo_exe, problem, db, args.dry_run)
    mutants = count_mutants(args.gigaevo_exe, problem, db, args.dry_run)
    return BenchRow(
        problem=problem,
        seed=seed,
        fitness=fitness,
        mutants_evaluated=mutants,
        state=state,
    )


def launch_chain_run(
    *,
    python_exe: str,
    variant: ChainVariant,
    db: int,
    output_dir: Path,
    timeout_sec: int,
    dry_run: bool,
    llm_base_url: str,
    model_name: str,
    extra_overrides: list[str] | None = None,
) -> tuple[int, str, str]:
    """Like ``launch_run`` but inserts ``chains/runner=<preset>`` first."""
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = build_chain_run_command(
        python_exe=python_exe,
        variant=variant,
        db=db,
        output_dir=str(output_dir),
        llm_base_url=llm_base_url,
        model_name=model_name,
        extra_overrides=extra_overrides,
    )
    print(f"  [launch] {' '.join(cmd)}", flush=True)
    if dry_run:
        return 0, "(dry-run)", ""

    env = {**os.environ}
    env.pop("HTTP_PROXY", None)
    env.pop("HTTPS_PROXY", None)
    env.pop("http_proxy", None)
    env.pop("https_proxy", None)

    log_file = output_dir / "run.log"
    with log_file.open("w") as logf:
        try:
            proc = subprocess.run(
                cmd,
                cwd=REPO_ROOT,
                env=env,
                stdout=logf,
                stderr=subprocess.STDOUT,
                timeout=timeout_sec,
                check=False,
            )
            return proc.returncode, "", ""
        except subprocess.TimeoutExpired:
            return 124, "", "TIMEOUT"


def run_chain_one(
    args: argparse.Namespace, variant: ChainVariant, seed: int
) -> BenchRow:
    variant_idx = next(
        i for i, v in enumerate(CHAIN_VARIANTS) if v.label == variant.label
    )
    db = chain_db_for(variant_idx)
    run_out = Path(args.output_root) / f"{variant.label}_s{seed}_db{db}"

    print(f"\n=== {variant.label} seed={seed} db={db} ===", flush=True)
    if not args.skip_launch and not args.skip_flush:
        flush_db(args.gigaevo_exe, db, args.dry_run)
    if not args.skip_launch:
        rc, _out, _err = launch_chain_run(
            python_exe=args.python_exe,
            variant=variant,
            db=db,
            output_dir=run_out,
            timeout_sec=args.per_run_timeout_sec,
            dry_run=args.dry_run,
            llm_base_url=args.llm_base_url,
            model_name=args.model_name,
            extra_overrides=args.extra_overrides,
        )
        if rc != 0:
            print(f"  [warn] run.py exit={rc}", flush=True)

    fitness, state = extract_fitness(
        args.gigaevo_exe, variant.problem, db, args.dry_run
    )
    mutants = count_mutants(args.gigaevo_exe, variant.problem, db, args.dry_run)
    return BenchRow(
        problem=variant.problem,
        seed=seed,
        fitness=fitness,
        mutants_evaluated=mutants,
        state=state,
        variant_label=variant.label,
    )


def _resolve_seeds(args: argparse.Namespace) -> list[int]:
    if args.seeds is not None:
        return list(args.seeds)
    return [0] if args.profile == "chain" else list(SEEDS)


def _resolve_chain_variants(args: argparse.Namespace) -> list[ChainVariant]:
    if not args.variants:
        return list(CHAIN_VARIANTS)
    by_label = {v.label: v for v in CHAIN_VARIANTS}
    selected: list[ChainVariant] = []
    for label in args.variants:
        if label not in by_label:
            raise SystemExit(
                f"--variants: unknown label '{label}'. "
                f"Known labels: {sorted(by_label.keys())}"
            )
        selected.append(by_label[label])
    return selected


def _run_chain_profile(
    args: argparse.Namespace, commit: str, timestamp: str
) -> tuple[list[BenchRow], float]:
    variants = _resolve_chain_variants(args)
    seeds = _resolve_seeds(args)
    if len(seeds) > 1 and not args.reuse_dbs:
        raise SystemExit(
            "--profile chain with more than one seed requires --reuse-dbs "
            "(Redis caps at 16 DBs and 10 variants × 2 seeds = 20 > 16). "
            "Either pass --seeds 0 (default), or pass --seeds 0 1 --reuse-dbs."
        )

    rows: list[BenchRow] = []
    t0 = time.time()
    for seed in seeds:
        print(f"\n--- chain seed={seed} ---", flush=True)
        if args.parallelism == 1:
            for variant in variants:
                rows.append(run_chain_one(args, variant, seed))
        else:
            with ThreadPoolExecutor(max_workers=args.parallelism) as ex:
                futs = {ex.submit(run_chain_one, args, v, seed): v for v in variants}
                for fut in as_completed(futs):
                    rows.append(fut.result())
    elapsed = time.time() - t0

    label_idx = {v.label: i for i, v in enumerate(CHAIN_VARIANTS)}
    rows.sort(key=lambda r: (label_idx.get(r.variant_label or "", 999), r.seed))
    return rows, elapsed


def main() -> int:
    args = parse_args()
    if args.parallelism < 1:
        print("--parallelism must be >= 1", file=sys.stderr)
        return 2
    seeds = _resolve_seeds(args)
    commit = _git_head_short()
    timestamp = _now_iso()
    print(
        f"Canonical benchmark: profile={args.profile} label={args.label} "
        f"commit={commit} ts={timestamp}",
        flush=True,
    )
    if args.profile == "chain":
        variants = _resolve_chain_variants(args)
        print(
            f"  variants={[v.label for v in variants]} seeds={seeds}",
            flush=True,
        )
    else:
        print(f"  problems={list(args.problems)} seeds={seeds}", flush=True)
    print(
        f"  spawn: python run.py problem.name=<P> redis.db=<N> hydra.run.dir=<DIR> "
        f"llm_base_url={args.llm_base_url} model_name={args.model_name} "
        f"(framework defaults expected: num_parents={DEFAULT_NUM_PARENTS}, "
        f"max_mutants={DEFAULT_MAX_MUTANTS})",
        flush=True,
    )
    print(f"  parallelism={args.parallelism}", flush=True)
    if args.extra_overrides:
        print(f"  extra_overrides={args.extra_overrides}", flush=True)

    if args.profile == "chain":
        rows, elapsed = _run_chain_profile(args, commit, timestamp)
        report = format_chain_results_markdown(
            label=args.label,
            commit=commit,
            timestamp=timestamp,
            rows=rows,
            seeds=seeds,
            extra_overrides=args.extra_overrides,
            parallelism=args.parallelism,
        )
        report += f"\n_Total wall-clock: {elapsed / 60:.1f} min_\n"
        print("\n" + "=" * 60 + "\n", flush=True)
        print(report, flush=True)

        if not args.no_history and not args.dry_run:
            _append_history(
                report,
                label=args.label,
                commit=commit,
                timestamp=timestamp,
                rows=rows,
                elapsed=elapsed,
                extra_overrides=list(args.extra_overrides),
                parallelism=args.parallelism,
            )
            _maybe_notify_chain(
                label=args.label, commit=commit, rows=rows, elapsed=elapsed
            )
        return 0

    pairs: list[tuple[str, int]] = [(p, s) for p in args.problems for s in seeds]
    rows: list[BenchRow] = []
    t0 = time.time()
    if args.parallelism == 1:
        for problem, seed in pairs:
            rows.append(run_one(args, problem, seed))
    else:
        with ThreadPoolExecutor(max_workers=args.parallelism) as ex:
            futures = {ex.submit(run_one, args, p, s): (p, s) for p, s in pairs}
            for fut in as_completed(futures):
                rows.append(fut.result())
    elapsed = time.time() - t0

    rows.sort(
        key=lambda r: (
            PROBLEMS.index(r.problem) if r.problem in PROBLEMS else 999,
            r.seed,
        )
    )
    report = format_results_markdown(
        label=args.label,
        commit=commit,
        timestamp=timestamp,
        rows=rows,
        extra_overrides=args.extra_overrides,
        parallelism=args.parallelism,
    )
    report += f"\n_Total wall-clock: {elapsed / 60:.1f} min_\n"

    print("\n" + "=" * 60 + "\n", flush=True)
    print(report, flush=True)

    if not args.no_history and not args.dry_run:
        _append_history(
            report,
            label=args.label,
            commit=commit,
            timestamp=timestamp,
            rows=rows,
            elapsed=elapsed,
            extra_overrides=list(args.extra_overrides),
            parallelism=args.parallelism,
        )
        _maybe_notify(label=args.label, commit=commit, rows=rows, elapsed=elapsed)

    return 0


def _append_history(
    report: str,
    *,
    label: str,
    commit: str,
    timestamp: str,
    rows: list[BenchRow],
    elapsed: float,
    extra_overrides: list[str],
    parallelism: int,
) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_PATH.open("a") as fh:
        fh.write("\n---\n\n")
        fh.write(report)
    agg = aggregate_results(rows)
    record = {
        "label": label,
        "commit": commit,
        "timestamp": timestamp,
        "elapsed_sec": elapsed,
        "extra_overrides": extra_overrides,
        "parallelism": parallelism,
        "aggregate": {
            p: {k: v for k, v in stats.items() if k != "values"}
            for p, stats in agg.items()
        },
        "rows": [
            {
                "problem": r.problem,
                "seed": r.seed,
                "fitness": r.fitness,
                "mutants": r.mutants_evaluated,
                "state": r.state,
            }
            for r in rows
        ],
    }
    with JSONL_PATH.open("a") as fh:
        fh.write(json.dumps(record) + "\n")
    print(
        f"\nAppended to {HISTORY_PATH.relative_to(REPO_ROOT)} and {JSONL_PATH.name}.",
        flush=True,
    )


def _maybe_notify(
    *, label: str, commit: str, rows: list[BenchRow], elapsed: float
) -> None:
    """Best-effort Telegram ping. Failures must not fail the benchmark."""
    try:
        from tools.telegram_notify import notify
    except Exception:  # noqa: BLE001
        return
    agg = aggregate_results(rows)
    lines = [
        f"Canonical benchmark complete: {label} @ {commit} ({elapsed / 60:.0f} min)"
    ]
    for problem in PROBLEMS:
        stats = agg.get(problem)
        if stats and stats.get("mean") is not None:
            lines.append(f"  {problem}: mean={stats['mean']:.4f}")
        else:
            lines.append(f"  {problem}: N/A")
    try:
        notify("\n".join(lines), parse_mode="")
    except Exception:  # noqa: BLE001
        pass


def _maybe_notify_chain(
    *, label: str, commit: str, rows: list[BenchRow], elapsed: float
) -> None:
    try:
        from tools.telegram_notify import notify
    except Exception:  # noqa: BLE001
        return
    agg = aggregate_results(rows)
    lines = [f"Chain benchmark complete: {label} @ {commit} ({elapsed / 60:.0f} min)"]
    for variant in CHAIN_VARIANTS:
        stats = agg.get(variant.label)
        if stats and stats.get("mean") is not None:
            lines.append(f"  {variant.label}: mean={stats['mean']:.4f}")
        else:
            lines.append(f"  {variant.label}: N/A")
    try:
        notify("\n".join(lines), parse_mode="")
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    sys.exit(main())
