#!/usr/bin/env python3
"""Multi-run contention simulation for SteadyStateEvolutionEngine.

Simulates N concurrent evolution runs sharing a pool of M mutation servers.
Each LLM call's latency depends on the GLOBAL concurrent load on its assigned
server, using the real contention curve measured from Qwen3-235B.

Measured contention curve (10.226.72.211:8777, Qwen3-235B-A22B-Thinking):
  per_server_concurrent=1: 5.6s mean  (baseline)
  per_server_concurrent=2: 4.3s mean  (batching sweet spot)
  per_server_concurrent=4: 5.2s mean  (still OK)
  per_server_concurrent=8: 10.6s mean (saturated)

Usage:
    # 4 runs, 4 servers, static max_in_flight=8
    PYTHONPATH=. python benchmarks/bench_multirun.py --runs 4 --servers 4

    # Compare static vs adaptive
    PYTHONPATH=. python benchmarks/bench_multirun.py --runs 4 --servers 4 --compare

    # Sweep max_in_flight with 4 runs competing
    PYTHONPATH=. python benchmarks/bench_multirun.py --runs 4 --servers 4 --sweep
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
import random
import statistics
import time
from unittest.mock import AsyncMock, MagicMock

from gigaevo.evolution.engine.config import SteadyStateEngineConfig
from gigaevo.evolution.engine.steady_state import SteadyStateEvolutionEngine
from gigaevo.programs.program import Program
from gigaevo.programs.program_state import ProgramState

# ---------------------------------------------------------------------------
# Real contention model (piecewise linear interpolation)
# ---------------------------------------------------------------------------
# Measured data points: (per_server_concurrent, mean_latency_seconds)
_CONTENTION_CURVE = [
    (1, 5.6),
    (2, 4.3),  # batching sweet spot
    (4, 5.2),
    (8, 10.6),
    (12, 18.0),  # extrapolated
    (16, 28.0),  # extrapolated
]

# Base latency distribution params (exponential)
_LLM_MEAN_S = 25.0
_LLM_MIN_S = 5.0
_LLM_MAX_S = 90.0

# Simulation timescale: 1ms bench time = 1s real time
TIMESCALE = 0.001


def _contention_multiplier(per_server_n: float) -> float:
    """Piecewise linear interpolation of the real contention curve.

    Returns a multiplier relative to N=1 baseline (5.6s).
    """
    if per_server_n <= 0:
        per_server_n = 1

    baseline = _CONTENTION_CURVE[0][1]  # 5.6s at N=1

    # Find the bounding points
    for i in range(len(_CONTENTION_CURVE) - 1):
        n_lo, lat_lo = _CONTENTION_CURVE[i]
        n_hi, lat_hi = _CONTENTION_CURVE[i + 1]
        if n_lo <= per_server_n <= n_hi:
            frac = (per_server_n - n_lo) / (n_hi - n_lo)
            lat = lat_lo + frac * (lat_hi - lat_lo)
            return lat / baseline

    # Beyond measured range — extrapolate linearly from last two points
    n_lo, lat_lo = _CONTENTION_CURVE[-2]
    n_hi, lat_hi = _CONTENTION_CURVE[-1]
    slope = (lat_hi - lat_lo) / (n_hi - n_lo)
    lat = lat_hi + slope * (per_server_n - n_hi)
    return lat / baseline


# ---------------------------------------------------------------------------
# Shared server pool — tracks global load across all runs
# ---------------------------------------------------------------------------


class ServerPool:
    """Simulates M servers shared by all runs with round-robin assignment."""

    def __init__(self, num_servers: int):
        self.num_servers = num_servers
        self._load = [0] * num_servers  # concurrent requests per server
        self._next_server = 0
        self._lock = asyncio.Lock()

    async def acquire_server(self) -> int:
        """Pick a server (round-robin) and increment its load."""
        async with self._lock:
            server_id = self._next_server
            self._next_server = (self._next_server + 1) % self.num_servers
            self._load[server_id] += 1
            return server_id

    async def release_server(self, server_id: int) -> None:
        async with self._lock:
            self._load[server_id] -= 1

    def get_per_server_load(self, server_id: int) -> int:
        return self._load[server_id]

    @property
    def total_load(self) -> int:
        return sum(self._load)

    @property
    def max_load(self) -> int:
        return max(self._load) if self._load else 0


# ---------------------------------------------------------------------------
# Per-run metrics
# ---------------------------------------------------------------------------


@dataclass
class RunMetrics:
    label: str
    mutations_completed: int = 0
    max_concurrent: int = 0
    _concurrent: int = 0
    latencies: list[float] = field(default_factory=list)

    def throughput(self, sim_wall_s: float) -> float:
        return self.mutations_completed / sim_wall_s * 60 if sim_wall_s > 0 else 0

    def summary(self, sim_wall_s: float) -> str:
        rate = self.throughput(sim_wall_s)
        avg_lat = statistics.mean(self.latencies) if self.latencies else 0
        return (
            f"  {self.label}: {rate:>6.2f} mutants/min | "
            f"mutations={self.mutations_completed} | "
            f"max_concurrent={self.max_concurrent} | "
            f"avg_latency={avg_lat:.1f}s"
        )


# ---------------------------------------------------------------------------
# Single-run engine factory
# ---------------------------------------------------------------------------


async def create_run(
    label: str,
    pool: ServerPool,
    max_in_flight: int,
    max_generations: int,
    use_adaptive: bool,
) -> tuple[SteadyStateEvolutionEngine, RunMetrics, dict]:
    """Create one engine instance wired to the shared server pool."""
    metrics = RunMetrics(label=label)
    completed: dict[str, Program] = {}

    storage = AsyncMock()
    strategy = AsyncMock()
    writer = MagicMock()
    writer.bind.return_value = writer
    mt = MagicMock()
    mt.format_best_summary.return_value = ""

    storage.count_by_status.return_value = 0
    storage.get_all_by_status.return_value = []
    strategy.get_program_ids.return_value = []
    strategy.add.return_value = True
    strategy.select_elites.return_value = [
        Program(code="def solve(): return 42", state=ProgramState.DONE)
    ]

    config = SteadyStateEngineConfig(
        max_in_flight=max_in_flight,
        max_mutations_per_generation=max_in_flight,
        max_generations=max_generations,
        loop_interval=0.001,
    )

    # If not adaptive, monkey-patch to use plain Semaphore after construction
    engine = SteadyStateEvolutionEngine(
        storage=storage,
        strategy=strategy,
        mutation_operator=AsyncMock(),
        config=config,
        writer=writer,
        metrics_tracker=mt,
    )
    engine.config.program_acceptor = MagicMock()
    engine.config.program_acceptor.is_accepted.return_value = True

    if not use_adaptive:
        # Replace adaptive with a plain semaphore + no-op report_latency
        static_sem = asyncio.Semaphore(max_in_flight)
        static_sem.report_latency = lambda lat: None  # type: ignore[attr-defined]
        static_sem.capacity = max_in_flight  # type: ignore[attr-defined]
        engine._in_flight_sema = static_sem

    async def fake_generate(elites, **kwargs):
        metrics._concurrent += 1
        metrics.max_concurrent = max(metrics.max_concurrent, metrics._concurrent)

        # Acquire a server slot
        server_id = await pool.acquire_server()
        per_server = pool.get_per_server_load(server_id)

        # Sample base latency + apply real contention multiplier
        raw = random.expovariate(1.0 / _LLM_MEAN_S)
        base = max(_LLM_MIN_S, min(_LLM_MAX_S, raw))
        mult = _contention_multiplier(per_server)
        real_latency = base * mult
        sim_latency = real_latency * TIMESCALE

        await asyncio.sleep(sim_latency)
        await pool.release_server(server_id)

        prog = Program(code="def solve(): return 42", state=ProgramState.DONE)
        completed[prog.id] = prog
        metrics.mutations_completed += 1
        metrics.latencies.append(real_latency)
        metrics._concurrent -= 1
        return [prog.id]

    def mget_side(ids, **kw):
        return [completed[pid] for pid in ids if pid in completed]

    storage.mget.side_effect = mget_side

    def get_ids_side(status):
        if status == ProgramState.DONE.value:
            return [pid for pid, p in completed.items() if p.state == ProgramState.DONE]
        return []

    storage.get_ids_by_status.side_effect = get_ids_side

    # Track ingestion
    orig_ingest = engine._ingest_batch

    async def tracked_ingest(pids):
        result = await orig_ingest(pids)
        for pid in pids:
            if pid in completed:
                completed[pid].state = ProgramState.DISCARDED
        return result

    engine._ingest_batch = tracked_ingest

    # Monkey-patch _create_single_mutant directly on THIS engine instance
    # so each run uses its own fake_generate (avoids shared module patch).
    async def patched_create_single_mutant(elites):
        ids = await fake_generate(elites)
        if ids:
            engine.metrics.record_mutation_metrics(len(ids), 0)
        return ids

    engine._create_single_mutant = patched_create_single_mutant

    return engine, metrics


# ---------------------------------------------------------------------------
# Multi-run simulation
# ---------------------------------------------------------------------------


async def run_simulation(
    num_runs: int = 4,
    num_servers: int = 4,
    max_in_flight: int = 8,
    duration_s: float = 5.0,
    max_generations: int = 500,
    use_adaptive: bool = True,
) -> tuple[list[RunMetrics], float]:
    """Run num_runs engines concurrently sharing num_servers."""
    pool = ServerPool(num_servers)

    engines = []
    all_metrics = []

    for i in range(num_runs):
        label = f"{'adaptive' if use_adaptive else 'static'}-R{i + 1}"
        engine, metrics = await create_run(
            label, pool, max_in_flight, max_generations, use_adaptive
        )
        engines.append(engine)
        all_metrics.append(metrics)

    async def run_one(engine):
        try:
            await asyncio.wait_for(engine.run(), timeout=duration_s)
        except TimeoutError:
            engine._running = False

    # Run all engines concurrently
    tasks = [asyncio.create_task(run_one(eng)) for eng in engines]
    t0 = time.monotonic()
    await asyncio.gather(*tasks, return_exceptions=True)
    wall = time.monotonic() - t0
    sim_wall = wall / TIMESCALE

    return all_metrics, sim_wall


def print_results(
    label: str,
    all_metrics: list[RunMetrics],
    sim_wall: float,
):
    total_mutations = sum(m.mutations_completed for m in all_metrics)
    total_rate = total_mutations / sim_wall * 60 if sim_wall > 0 else 0
    all_lats = [lat for m in all_metrics for lat in m.latencies]
    avg_lat = statistics.mean(all_lats) if all_lats else 0
    p95_lat = sorted(all_lats)[int(len(all_lats) * 0.95)] if len(all_lats) >= 2 else 0

    print(f"\n=== {label} ===")
    print(f"Simulated wall clock: {sim_wall:.0f}s ({sim_wall / 60:.1f}min)")
    print(f"Total mutations:      {total_mutations}")
    print(f"Total throughput:     {total_rate:.2f} mutants/min (across all runs)")
    print(f"Avg LLM latency:      {avg_lat:.1f}s")
    print(f"P95 LLM latency:      {p95_lat:.1f}s")
    print()
    for m in all_metrics:
        print(m.summary(sim_wall))


def main():
    parser = argparse.ArgumentParser(description="Multi-run contention simulation")
    parser.add_argument("--runs", type=int, default=4)
    parser.add_argument("--servers", type=int, default=4)
    parser.add_argument("--max-in-flight", type=int, default=8)
    parser.add_argument("--duration", type=float, default=5.0, help="Bench seconds")
    parser.add_argument("--max-generations", type=int, default=500)
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Compare static vs adaptive side by side",
    )
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="Sweep max_in_flight for static mode",
    )
    args = parser.parse_args()

    if args.compare:
        random.seed(42)
        static_metrics, static_sim = asyncio.run(
            run_simulation(
                args.runs,
                args.servers,
                args.max_in_flight,
                args.duration,
                args.max_generations,
                use_adaptive=False,
            )
        )
        print_results(
            f"STATIC (max_in_flight={args.max_in_flight})",
            static_metrics,
            static_sim,
        )

        random.seed(42)
        adaptive_metrics, adaptive_sim = asyncio.run(
            run_simulation(
                args.runs,
                args.servers,
                args.max_in_flight,
                args.duration,
                args.max_generations,
                use_adaptive=True,
            )
        )
        print_results(
            f"ADAPTIVE (ceiling={args.max_in_flight})",
            adaptive_metrics,
            adaptive_sim,
        )

        # Delta
        s_total = sum(m.mutations_completed for m in static_metrics)
        a_total = sum(m.mutations_completed for m in adaptive_metrics)
        s_rate = s_total / static_sim * 60
        a_rate = a_total / adaptive_sim * 60
        print("\n--- Comparison ---")
        print(f"Static total:   {s_rate:.2f} mutants/min ({s_total} mutations)")
        print(f"Adaptive total: {a_rate:.2f} mutants/min ({a_total} mutations)")
        if s_rate > 0:
            print(f"Speedup:        {a_rate / s_rate:.2f}x")

    elif args.sweep:
        flight_values = [2, 4, 6, 8, 12, 16]
        print(
            f"=== Sweep: {args.runs} runs, {args.servers} servers "
            f"(static max_in_flight) ==="
        )
        for mif in flight_values:
            random.seed(42)
            metrics, sim_wall = asyncio.run(
                run_simulation(
                    args.runs,
                    args.servers,
                    mif,
                    args.duration,
                    args.max_generations,
                    use_adaptive=False,
                )
            )
            total = sum(m.mutations_completed for m in metrics)
            rate = total / sim_wall * 60 if sim_wall > 0 else 0
            lats = [lat for m in metrics for lat in m.latencies]
            avg_lat = statistics.mean(lats) if lats else 0
            print(
                f"  max_in_flight={mif:>2d} | "
                f"{rate:>6.2f} mutants/min | "
                f"mutations={total} | "
                f"avg_latency={avg_lat:.1f}s"
            )

    else:
        random.seed(42)
        metrics, sim_wall = asyncio.run(
            run_simulation(
                args.runs,
                args.servers,
                args.max_in_flight,
                args.duration,
                args.max_generations,
                use_adaptive=True,
            )
        )
        print_results(
            f"{args.runs} runs, {args.servers} servers, "
            f"max_in_flight={args.max_in_flight} (adaptive)",
            metrics,
            sim_wall,
        )


if __name__ == "__main__":
    main()
