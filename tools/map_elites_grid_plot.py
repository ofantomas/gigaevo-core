#!/usr/bin/env python3
"""Visualize the current 2-D MAP-Elites archive grid for a GigaEvo run.

Example:
    PYTHONPATH=. python tools/map_elites_grid_plot.py \
        --run full_sella_diff@6:full-sella-diff \
        --output outputs/plots/full_sella_map_grid.png
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, replace
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import redis

from tools.status import parse_run_arg
from tools.utils import RedisRunConfig, fetch_evolution_dataframe


@dataclass(frozen=True)
class GridSpec:
    x_metric: str
    y_metric: str
    fitness_metric: str
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    x_bins: int
    y_bins: int
    minimize: bool


def _metric_col(metric: str) -> str:
    return metric if metric.startswith("metric_") else f"metric_{metric}"


def _metric_series(df: pd.DataFrame, metric: str) -> pd.Series:
    col = _metric_col(metric)
    if col not in df.columns and metric == "fitness":
        col = _metric_col("mean_rel_steps")
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce")


def _axis_label(metric: str) -> str:
    labels = {
        "fitness": "Average relative number of steps (fitness)",
        "mean_rel_steps": "Average relative number of steps",
        "mean_rel_energy": "Average relative energy recovery",
    }
    return labels.get(metric, metric)


def _parse_cell(field: str) -> tuple[int, int] | None:
    try:
        values = tuple(int(part) for part in field.split(","))
    except ValueError:
        return None
    if len(values) != 2:
        return None
    return values


def _cell_for_metrics(x: float, y: float, spec: GridSpec) -> tuple[int, int]:
    def index(value: float, lo: float, hi: float, bins: int) -> int:
        if hi == lo:
            return 0
        normalized = (min(max(value, lo), hi) - lo) / (hi - lo)
        return min(int(normalized * bins), bins - 1)

    return (
        index(x, spec.x_min, spec.x_max, spec.x_bins),
        index(y, spec.y_min, spec.y_max, spec.y_bins),
    )


def _is_better(candidate: float, incumbent: float, minimize: bool) -> bool:
    if np.isnan(incumbent):
        return True
    return candidate < incumbent if minimize else candidate > incumbent


def _load_archive_mapping(
    *,
    host: str,
    port: int,
    db: int,
    archive_key: str,
) -> dict[tuple[int, int], str]:
    client = redis.Redis(host=host, port=port, db=db, decode_responses=True)
    try:
        raw = client.hgetall(archive_key)
    finally:
        client.close()

    mapping: dict[tuple[int, int], str] = {}
    for field, program_id in raw.items():
        cell = _parse_cell(field)
        if cell is not None:
            mapping[cell] = program_id
    return mapping


def _archive_records(
    df: pd.DataFrame,
    mapping: dict[tuple[int, int], str],
    spec: GridSpec,
) -> pd.DataFrame:
    if not mapping:
        return pd.DataFrame()

    by_id = df.set_index("program_id", drop=False)
    rows: list[dict] = []
    for (ix, iy), program_id in mapping.items():
        if program_id not in by_id.index:
            rows.append({"program_id": program_id, "cell_x": ix, "cell_y": iy})
            continue
        row = by_id.loc[program_id]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        rows.append(
            {
                "program_id": program_id,
                "short_id": str(program_id)[:8],
                "cell_x": ix,
                "cell_y": iy,
                "x": pd.to_numeric(row.get(_metric_col(spec.x_metric)), errors="coerce"),
                "y": pd.to_numeric(row.get(_metric_col(spec.y_metric)), errors="coerce"),
                "fitness": pd.to_numeric(
                    row.get(_metric_col(spec.fitness_metric)), errors="coerce"
                ),
                "is_valid": pd.to_numeric(
                    row.get(_metric_col("is_valid"), 1.0), errors="coerce"
                ),
                "state": row.get("state"),
                "generation": row.get("lineage_generation"),
            }
        )
    return pd.DataFrame(rows)


def _reconstruct_archive(df: pd.DataFrame, spec: GridSpec) -> pd.DataFrame:
    data = df.copy()
    data["x"] = _metric_series(data, spec.x_metric)
    data["y"] = _metric_series(data, spec.y_metric)
    data["fitness"] = _metric_series(data, spec.fitness_metric)
    data["is_valid"] = _metric_series(data, "is_valid")
    data = data[
        data["x"].notna()
        & data["y"].notna()
        & data["fitness"].notna()
        & (data["fitness"].abs() < 999)
        & (data["x"].abs() < 999)
        & (data["y"].abs() < 999)
        & ((data["is_valid"].isna()) | (data["is_valid"] > 0))
    ].copy()

    best: dict[tuple[int, int], pd.Series] = {}
    for _, row in data.iterrows():
        cell = _cell_for_metrics(float(row["x"]), float(row["y"]), spec)
        incumbent = best.get(cell)
        if incumbent is None or _is_better(
            float(row["fitness"]), float(incumbent["fitness"]), spec.minimize
        ):
            best[cell] = row

    rows = []
    for (ix, iy), row in best.items():
        rows.append(
            {
                "program_id": row["program_id"],
                "short_id": str(row["program_id"])[:8],
                "cell_x": ix,
                "cell_y": iy,
                "x": row["x"],
                "y": row["y"],
                "fitness": row["fitness"],
                "is_valid": row.get("is_valid", np.nan),
                "state": row.get("state"),
                "generation": row.get("lineage_generation"),
            }
        )
    return pd.DataFrame(rows)


def _build_grid(records: pd.DataFrame, spec: GridSpec) -> np.ndarray:
    grid = np.full((spec.y_bins, spec.x_bins), np.nan, dtype=float)
    for _, row in records.iterrows():
        x = float(row["x"])
        y = float(row["y"])
        fitness = float(row["fitness"])
        if np.isfinite(x) and np.isfinite(y) and np.isfinite(fitness):
            ix, iy = _cell_for_metrics(x, y, spec)
            current = grid[iy, ix]
            if _is_better(fitness, current, spec.minimize):
                grid[iy, ix] = fitness
    return grid


def _auto_axis_bounds(
    values: pd.Series, fallback_min: float, fallback_max: float
) -> tuple[float, float]:
    clean = pd.to_numeric(values, errors="coerce")
    clean = clean[np.isfinite(clean) & (clean.abs() < 999)]
    if clean.empty:
        return fallback_min, fallback_max

    lo = float(clean.min())
    hi = float(clean.max())
    if lo == hi:
        pad = max(abs(lo) * 0.02, 1e-6)
    else:
        pad = 0.1 * (hi - lo)
    return lo - pad, hi + pad


def _resolve_plot_bounds(
    records: pd.DataFrame, spec: GridSpec, bounds_mode: str
) -> GridSpec:
    if bounds_mode == "configured":
        return spec
    x_min, x_max = _auto_axis_bounds(records["x"], spec.x_min, spec.x_max)
    y_min, y_max = _auto_axis_bounds(records["y"], spec.y_min, spec.y_max)
    return replace(spec, x_min=x_min, x_max=x_max, y_min=y_min, y_max=y_max)


def plot_map_grid(
    records: pd.DataFrame,
    *,
    output: Path,
    label: str,
    archive_key: str,
    source: str,
    spec: GridSpec,
    bounds_mode: str,
    annotate_best: int,
    dpi: int,
) -> None:
    if records.empty:
        raise SystemExit("No MAP-Elites archive records to plot.")

    spec = _resolve_plot_bounds(records, spec, bounds_mode)
    grid = _build_grid(records, spec)
    occupied = int(np.isfinite(grid).sum())
    total_cells = spec.x_bins * spec.y_bins
    archive_elites = len(records)

    cmap = plt.get_cmap("viridis_r" if spec.minimize else "viridis").copy()
    cmap.set_bad("#f2f2f2")

    fig, ax = plt.subplots(figsize=(13, 7.5))
    fig.patch.set_facecolor("white")

    extent = (spec.x_min, spec.x_max, spec.y_min, spec.y_max)
    x_edges = np.linspace(spec.x_min, spec.x_max, spec.x_bins + 1)
    y_edges = np.linspace(spec.y_min, spec.y_max, spec.y_bins + 1)
    x_centers = (x_edges[:-1] + x_edges[1:]) / 2
    y_centers = (y_edges[:-1] + y_edges[1:]) / 2

    image = ax.imshow(
        np.ma.masked_invalid(grid),
        origin="lower",
        interpolation="nearest",
        aspect="auto",
        extent=extent,
        cmap=cmap,
    )

    ax.set_xticks(x_edges, minor=True)
    ax.set_yticks(y_edges, minor=True)
    ax.grid(which="minor", color="white", linewidth=0.45, alpha=0.7)
    ax.tick_params(which="minor", bottom=False, left=False)

    if annotate_best > 0:
        ranked = records.dropna(subset=["fitness"]).sort_values(
            "fitness", ascending=spec.minimize
        )
        for _, row in ranked.head(annotate_best).iterrows():
            ix, iy = _cell_for_metrics(float(row["x"]), float(row["y"]), spec)
            cx = x_centers[ix]
            cy = y_centers[iy]
            ax.text(
                cx,
                cy,
                f"{row['short_id']}\n{float(row['fitness']):.3g}",
                ha="center",
                va="center",
                fontsize=6.5,
                color="white",
            )

    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_xlabel(_axis_label(spec.x_metric), fontsize=12)
    ax.set_ylabel(_axis_label(spec.y_metric), fontsize=12)
    ax.set_title(
        f"MAP-Elites archive - {label}\n"
        f"{occupied}/{total_cells} performance cells, {archive_elites} archive elites, color = {spec.fitness_metric}",
        fontsize=13,
        pad=12,
    )

    cbar = fig.colorbar(image, ax=ax, pad=0.02)
    direction = "lower is better" if spec.minimize else "higher is better"
    cbar.set_label(f"{spec.fitness_metric} ({direction})", rotation=270, labelpad=22)

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=dpi, bbox_inches="tight")
    plt.close(fig)

    best = records.dropna(subset=["fitness"]).sort_values(
        "fitness", ascending=spec.minimize
    )
    best_msg = ""
    if not best.empty:
        best_row = best.iloc[0]
        best_msg = (
            f"; best={best_row['short_id']} "
            f"{spec.fitness_metric}={float(best_row['fitness']):.6g}"
        )
    print(f"Saved: {output}")
    print(f"performance cells {occupied}/{total_cells}; archive elites {archive_elites}{best_msg}")


async def async_main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot current 2-D MAP-Elites archive grid."
    )
    parser.add_argument(
        "--run",
        required=True,
        metavar="PREFIX@DB[:LABEL]",
        help="Run spec, e.g. full_sella_diff@6:full-sella-diff",
    )
    parser.add_argument("--redis-host", default="localhost")
    parser.add_argument("--redis-port", type=int, default=6379)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--island-id", default="fitness_island")
    parser.add_argument(
        "--archive-key",
        help="Override Redis archive hash key. Default: island_<island-id>:archive",
    )
    parser.add_argument("--x-metric", default="fitness")
    parser.add_argument("--y-metric", default="mean_rel_energy")
    parser.add_argument("--fitness-metric", default="fitness")
    parser.add_argument("--x-min", type=float, default=0.8)
    parser.add_argument("--x-max", type=float, default=1.5)
    parser.add_argument("--y-min", type=float, default=0.999)
    parser.add_argument("--y-max", type=float, default=1.05)
    parser.add_argument("--x-bins", type=int, default=40)
    parser.add_argument("--y-bins", type=int, default=10)
    parser.add_argument(
        "--bounds-mode",
        choices=["auto", "configured"],
        default="auto",
        help=(
            "auto infers performance-axis bounds from archive occupants; "
            "configured uses --x-min/--x-max/--y-min/--y-max."
        ),
    )
    parser.add_argument(
        "--maximize",
        action="store_true",
        help="Use if higher fitness is better. Default is minimization.",
    )
    parser.add_argument(
        "--reconstruct",
        action="store_true",
        help="Ignore Redis archive and reconstruct best cell occupants from all programs.",
    )
    parser.add_argument("--annotate-best", type=int, default=0)
    parser.add_argument(
        "--no-points",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--metric-axes", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--dpi", type=int, default=150)
    args = parser.parse_args()

    prefix, db, label = parse_run_arg(args.run)
    cfg = RedisRunConfig(
        redis_host=args.redis_host,
        redis_port=args.redis_port,
        redis_db=db,
        redis_prefix=prefix,
        label=label,
    )
    spec = GridSpec(
        x_metric=args.x_metric,
        y_metric=args.y_metric,
        fitness_metric=args.fitness_metric,
        x_min=args.x_min,
        x_max=args.x_max,
        y_min=args.y_min,
        y_max=args.y_max,
        x_bins=args.x_bins,
        y_bins=args.y_bins,
        minimize=not args.maximize,
    )

    df = await fetch_evolution_dataframe(cfg, add_stage_results=False)
    if df.empty:
        raise SystemExit(f"No programs found for {cfg.display_label()}")

    archive_key = args.archive_key or f"island_{args.island_id}:archive"
    mapping = {}
    source = "reconstructed"
    if not args.reconstruct:
        mapping = _load_archive_mapping(
            host=args.redis_host,
            port=args.redis_port,
            db=db,
            archive_key=archive_key,
        )
    if mapping:
        records = _archive_records(df, mapping, spec)
        source = "redis archive"
    else:
        records = _reconstruct_archive(df, spec)
        source = "reconstructed"

    plot_map_grid(
        records,
        output=args.output,
        label=cfg.display_label(),
        archive_key=archive_key,
        source=source,
        spec=spec,
        bounds_mode=args.bounds_mode,
        annotate_best=args.annotate_best,
        dpi=args.dpi,
    )


if __name__ == "__main__":
    asyncio.run(async_main())
