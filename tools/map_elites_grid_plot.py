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
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as path_effects
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
        ix = int(row["cell_x"])
        iy = int(row["cell_y"])
        fitness = float(row["fitness"])
        if 0 <= ix < spec.x_bins and 0 <= iy < spec.y_bins and np.isfinite(fitness):
            current = grid[iy, ix]
            if _is_better(fitness, current, spec.minimize):
                grid[iy, ix] = fitness
    return grid


def plot_map_grid(
    records: pd.DataFrame,
    *,
    output: Path,
    label: str,
    archive_key: str,
    source: str,
    spec: GridSpec,
    annotate_best: int,
    show_points: bool,
    metric_axes: bool,
    dpi: int,
) -> None:
    if records.empty:
        raise SystemExit("No MAP-Elites archive records to plot.")

    grid = _build_grid(records, spec)
    occupied = int(np.isfinite(grid).sum())
    total_cells = spec.x_bins * spec.y_bins

    cmap = plt.get_cmap("viridis_r" if spec.minimize else "viridis").copy()
    cmap.set_bad("#f2f2f2")

    fig, ax = plt.subplots(figsize=(13, 7.5))
    fig.patch.set_facecolor("white")

    if metric_axes:
        extent = (spec.x_min, spec.x_max, spec.y_min, spec.y_max)
        x_edges = np.linspace(spec.x_min, spec.x_max, spec.x_bins + 1)
        y_edges = np.linspace(spec.y_min, spec.y_max, spec.y_bins + 1)
        x_centers = (x_edges[:-1] + x_edges[1:]) / 2
        y_centers = (y_edges[:-1] + y_edges[1:]) / 2
        x_label = spec.x_metric
        y_label = spec.y_metric
    else:
        extent = (-0.5, spec.x_bins - 0.5, -0.5, spec.y_bins - 0.5)
        x_edges = np.arange(-0.5, spec.x_bins + 0.5, 1.0)
        y_edges = np.arange(-0.5, spec.y_bins + 0.5, 1.0)
        x_centers = np.arange(spec.x_bins)
        y_centers = np.arange(spec.y_bins)
        x_label = f"{spec.x_metric} cell"
        y_label = f"{spec.y_metric} cell"

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

    if show_points:
        valid_points = records[
            records["x"].notna() & records["y"].notna() & records["fitness"].notna()
        ]
        point_x = valid_points["x"] if metric_axes else valid_points["cell_x"]
        point_y = valid_points["y"] if metric_axes else valid_points["cell_y"]
        ax.scatter(
            point_x,
            point_y,
            s=18,
            color="black",
            alpha=0.35,
            linewidths=0,
        )

    if annotate_best > 0:
        ranked = records.dropna(subset=["fitness"]).sort_values(
            "fitness", ascending=spec.minimize
        )
        for _, row in ranked.head(annotate_best).iterrows():
            ix = int(row["cell_x"])
            iy = int(row["cell_y"])
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
                path_effects=[
                    path_effects.withStroke(linewidth=1.4, foreground="black")
                ],
            )

    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.set_title(
        f"MAP-Elites grid - {label}\n"
        f"{occupied}/{total_cells} occupied cells, color = {spec.fitness_metric}, source = {source}",
        fontsize=14,
    )

    cbar = fig.colorbar(image, ax=ax, pad=0.02)
    direction = "lower is better" if spec.minimize else "higher is better"
    cbar.set_label(f"{spec.fitness_metric} ({direction})", rotation=270, labelpad=22)

    ax.text(
        0.01,
        -0.13,
        f"archive key: {archive_key}",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=9,
        color="#444444",
    )

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
    print(f"occupied {occupied}/{total_cells}{best_msg}")


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
    parser.add_argument("--no-points", action="store_true")
    parser.add_argument(
        "--metric-axes",
        action="store_true",
        help=(
            "Use configured metric bounds on axes. By default Redis archives are "
            "shown in cell coordinates because dynamic MAP bounds are not persisted."
        ),
    )
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
        annotate_best=args.annotate_best,
        show_points=not args.no_points,
        metric_axes=args.metric_axes or source == "reconstructed",
        dpi=args.dpi,
    )


if __name__ == "__main__":
    asyncio.run(async_main())
