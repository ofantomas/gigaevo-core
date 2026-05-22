#!/usr/bin/env python3
"""Plot Sella energy recovery vs fitness for one GigaEvo Redis run.

Example:
    PYTHONPATH=. python tools/sella_energy_fitness_plot.py \
        --run full_sella_diff@6:full-sella-diff \
        --output outputs/plots/full_sella_energy_fitness.png \
        --x-lower-lim 1.2 \
        --x-upper-lim 2.0
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from tools.status import parse_run_arg
from tools.utils import RedisRunConfig, fetch_evolution_dataframe


DEFAULT_X_METRIC = "fitness"
DEFAULT_Y_METRIC = "mean_rel_energy"


def _metric_col(metric: str) -> str:
    return metric if metric.startswith("metric_") else f"metric_{metric}"


def _coerce_metric(df: pd.DataFrame, metric: str) -> pd.Series:
    col = _metric_col(metric)
    if col not in df.columns and metric == "fitness":
        col = _metric_col("mean_rel_steps")
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce")


def _parse_bounds(value: str | None) -> tuple[float, float] | None:
    if value is None:
        return None
    left, right = value.split(",", 1)
    return float(left), float(right)


def _format_time_ticks(cbar, values: np.ndarray) -> None:
    if len(values) == 0:
        return
    lo = float(np.nanmin(values))
    hi = float(np.nanmax(values))
    if not np.isfinite(lo) or not np.isfinite(hi):
        return
    ticks = np.linspace(lo, hi, min(7, max(2, len(np.unique(values)))))
    cbar.set_ticks(ticks)
    dates = [mdates.num2date(t) for t in ticks]
    unique_days = {(d.year, d.month, d.day) for d in dates}
    fmt = "%H:%M" if len(unique_days) == 1 else "%b-%d\n%H:%M"
    cbar.set_ticklabels([d.strftime(fmt) for d in dates])


def _filtered_points(
    df: pd.DataFrame,
    *,
    x_metric: str,
    y_metric: str,
    sentinel_cutoff: float,
    include_invalid: bool,
) -> tuple[pd.DataFrame, dict[str, int]]:
    data = df.copy()
    data["_x"] = _coerce_metric(data, x_metric)
    data["_y"] = _coerce_metric(data, y_metric)
    data["_is_valid"] = (
        _coerce_metric(data, "is_valid")
        if _metric_col("is_valid") in data.columns
        else pd.Series(1.0, index=data.index)
    )
    data["_created_at"] = pd.to_datetime(data.get("created_at"), errors="coerce")

    missing = data["_x"].isna() | data["_y"].isna()
    missing_count = int(missing.sum())

    finite_xy = np.isfinite(data["_x"]) & np.isfinite(data["_y"])
    sentinel = (
        finite_xy
        & ~missing
        & (
            (data["_x"].abs() >= sentinel_cutoff)
            | (data["_y"].abs() >= sentinel_cutoff)
        )
    )
    sentinel_count = int(sentinel.sum())

    invalid = (
        ~missing
        & ~sentinel
        & data["_is_valid"].notna()
        & (data["_is_valid"] <= 0)
    )
    invalid_count = int(invalid.sum())

    keep = ~missing & ~sentinel
    if not include_invalid:
        keep &= ~invalid

    counts = {
        "total": int(len(data)),
        "missing": missing_count,
        "sentinel": sentinel_count,
        "invalid": invalid_count,
        "plotted": int(keep.sum()),
    }
    return data[keep].copy(), counts


def plot_energy_vs_fitness(
    df: pd.DataFrame,
    *,
    output: Path,
    label: str,
    x_metric: str,
    y_metric: str,
    x_label: str,
    y_label: str,
    title: str | None,
    subtitle: str | None,
    xlim: tuple[float, float] | None,
    x_lower_lim: float | None,
    x_upper_lim: float | None,
    ylim: tuple[float, float] | None,
    sentinel_cutoff: float,
    include_invalid: bool,
    point_size: float,
    dpi: int,
) -> None:
    filtered, counts = _filtered_points(
        df,
        x_metric=x_metric,
        y_metric=y_metric,
        sentinel_cutoff=sentinel_cutoff,
        include_invalid=include_invalid,
    )

    if filtered.empty:
        raise SystemExit("No plottable programs after filtering.")

    if filtered["_created_at"].notna().any():
        color_values = mdates.date2num(filtered["_created_at"].to_numpy())
        color_label = "time"
    else:
        color_values = pd.to_numeric(filtered["atomic_counter"], errors="coerce")
        color_label = "atomic counter"

    fig, ax = plt.subplots(figsize=(11.5, 9.0))
    fig.patch.set_facecolor("white")

    sc = ax.scatter(
        filtered["_x"],
        filtered["_y"],
        c=color_values,
        cmap="viridis",
        s=point_size,
        alpha=0.82,
        edgecolors="none",
    )

    roots = filtered[filtered.get("is_root", False).astype(bool)]
    if not roots.empty:
        ax.scatter(
            roots["_x"],
            roots["_y"],
            marker="*",
            s=430,
            color="red",
            edgecolor="black",
            linewidth=1.5,
            label=f"seed (n={len(roots)})",
            zorder=5,
        )

    if xlim is not None:
        ax.set_xlim(*xlim)
    if x_lower_lim is not None:
        ax.set_xlim(left=x_lower_lim)
    if x_upper_lim is not None:
        ax.set_xlim(right=x_upper_lim)
    if ylim is not None:
        ax.set_ylim(*ylim)

    xlo, xhi = ax.get_xlim()
    ylo, yhi = ax.get_ylim()
    ref_lo = max(xlo, ylo)
    ref_hi = min(xhi, yhi)
    if ref_lo < ref_hi:
        ax.plot(
            [ref_lo, ref_hi],
            [ref_lo, ref_hi],
            linestyle="--",
            color="black",
            linewidth=1.1,
            alpha=0.65,
            label="y = x",
        )

    stats_label = (
        f"plotted {counts['plotted']}/{counts['total']}; "
        f"dropped: invalid={counts['invalid']}, "
        f"sentinel={counts['sentinel']}, missing={counts['missing']}"
    )
    ax.scatter([], [], color="none", label=stats_label)

    plot_title = title or f"Energy recovery vs fitness (color = time) - {label}"
    ax.set_title(plot_title, fontsize=16, pad=34)
    if subtitle:
        ax.text(
            0.5,
            1.01,
            subtitle,
            transform=ax.transAxes,
            ha="center",
            va="bottom",
            fontsize=12,
        )

    ax.set_xlabel(x_label, fontsize=12)
    ax.set_ylabel(y_label, fontsize=12)
    ax.grid(True, alpha=0.25)
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, 0.995),
        framealpha=0.82,
        fontsize=10,
    )

    cbar = fig.colorbar(sc, ax=ax, pad=0.02)
    cbar.set_label(color_label, rotation=270, labelpad=22)
    if color_label == "time":
        _format_time_ticks(cbar, np.asarray(color_values, dtype=float))

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=dpi, bbox_inches="tight")
    plt.close(fig)

    print(f"Saved: {output}")
    print(stats_label)


async def async_main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot energy recovery vs fitness for a GigaEvo Redis run."
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
    parser.add_argument("--x-metric", default=DEFAULT_X_METRIC)
    parser.add_argument("--y-metric", default=DEFAULT_Y_METRIC)
    parser.add_argument(
        "--x-label",
        default="Average relative number of steps (fitness)",
    )
    parser.add_argument(
        "--y-label",
        default="Average relative energy recovery",
    )
    parser.add_argument("--title")
    parser.add_argument("--subtitle")
    parser.add_argument("--xlim", help="Comma-separated bounds, e.g. 1.0,5.0")
    parser.add_argument(
        "--x-lower-lim",
        "--x-lower-limit",
        "--x-min",
        "--xmin",
        dest="x_lower_lim",
        type=float,
        help="Lower x-axis bound; keeps the upper bound automatic unless --xlim or --x-upper-lim is set.",
    )
    parser.add_argument(
        "--x-upper-lim",
        "--x-upper-limit",
        "--x-max",
        "--xmax",
        dest="x_upper_lim",
        type=float,
        help="Upper x-axis bound; keeps the lower bound automatic unless --xlim or --x-lower-lim is set.",
    )
    parser.add_argument("--ylim", help="Comma-separated bounds, e.g. 0.999,1.016")
    parser.add_argument("--sentinel-cutoff", type=float, default=999.0)
    parser.add_argument("--include-invalid", action="store_true")
    parser.add_argument("--point-size", type=float, default=28.0)
    parser.add_argument("--dpi", type=int, default=150)
    args = parser.parse_args()

    xlim = _parse_bounds(args.xlim)
    effective_xlo = args.x_lower_lim if args.x_lower_lim is not None else None
    effective_xhi = args.x_upper_lim if args.x_upper_lim is not None else None
    if xlim is not None:
        effective_xlo = xlim[0] if effective_xlo is None else effective_xlo
        effective_xhi = xlim[1] if effective_xhi is None else effective_xhi
    if (
        effective_xlo is not None
        and effective_xhi is not None
        and effective_xlo >= effective_xhi
    ):
        raise SystemExit("x-axis lower limit must be less than upper limit.")

    prefix, db, label = parse_run_arg(args.run)
    cfg = RedisRunConfig(
        redis_host=args.redis_host,
        redis_port=args.redis_port,
        redis_db=db,
        redis_prefix=prefix,
        label=label,
    )
    df = await fetch_evolution_dataframe(cfg, add_stage_results=False)
    if df.empty:
        raise SystemExit(f"No programs found for {cfg.display_label()}")

    plot_energy_vs_fitness(
        df,
        output=args.output,
        label=cfg.display_label(),
        x_metric=args.x_metric,
        y_metric=args.y_metric,
        x_label=args.x_label,
        y_label=args.y_label,
        title=args.title,
        subtitle=args.subtitle,
        xlim=xlim,
        x_lower_lim=args.x_lower_lim,
        x_upper_lim=args.x_upper_lim,
        ylim=_parse_bounds(args.ylim),
        sentinel_cutoff=args.sentinel_cutoff,
        include_invalid=args.include_invalid,
        point_size=args.point_size,
        dpi=args.dpi,
    )


if __name__ == "__main__":
    asyncio.run(async_main())
