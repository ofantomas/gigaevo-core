"""Realistic benchmark for SteadyStateEvolutionEngine throughput.

Simulates real-world latencies calibrated from production HoVer experiment logs:
- LLM mutation calls: 10-60s (exponential, mean ~25s)
- Redis/storage operations: ~1ms
- **LLM contention**: per-request latency increases with concurrent load
  on GPU servers (continuous batching overhead, KV cache pressure).

Models contention as: latency_multiplier = 1 + alpha * max(0, concurrent_per_server - 1)
where alpha is the per-request slowdown factor (0.15 = conservative).

Measures: mutants produced per simulated minute, max concurrency, pipeline fill.

Usage:
    PYTHONPATH=. python benchmarks/bench_steady_state.py [--duration 3.0] [--max-in-flight 8]
    PYTHONPATH=. python benchmarks/bench_steady_state.py --sweep         # find sweet spot
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
import random
import time
from unittest.mock import AsyncMock, MagicMock, patch

from gigaevo.evolution.engine.config import SteadyStateEngineConfig
from gigaevo.evolution.engine.steady_state import SteadyStateEvolutionEngine
from gigaevo.programs.program import Program
from gigaevo.programs.program_state import ProgramState

# ---------------------------------------------------------------------------
# Timing distributions (calibrated from production logs)
# ---------------------------------------------------------------------------

MUTATION_LLM_MEAN_S = 25.0  # mean LLM call latency for mutation
MUTATION_LLM_MIN_S = 5.0  # floor
MUTATION_LLM_MAX_S = 90.0  # cap
TIMESCALE = 0.001  # speed up: 1ms simulates 1s real time

# ---------------------------------------------------------------------------
# Contention model
# ---------------------------------------------------------------------------
# When N requests hit a GPU server concurrently, per-request latency grows.
# Continuous batching helps but doesn't eliminate the overhead — KV cache
# pressure, memory bandwidth saturation, and decode interference all
# increase latency sublinearly with batch size.
#
# Model: latency_multiplier = 1 + alpha * max(0, per_server_concurrent - 1)
#   alpha=0.0  → no contention (ideal, unrealistic)
#   alpha=0.15 → conservative (5 servers, light per-server load)
#   alpha=0.3  → moderate (fewer servers or heavier models)
#   alpha=0.5  → heavy (single server, large model)

CONTENTION_ALPHA = 0.15  # default: conservative for 5-server pool
NUM_SERVERS = 5  # number of LLM servers in the pool


def _sim_mutation_latency(concurrent: int, alpha: float, num_servers: int) -> float:
    """Simulate LLM mutation latency with contention scaling."""
    raw = random.expovariate(1.0 / MUTATION_LLM_MEAN_S)
    base = max(MUTATION_LLM_MIN_S, min(MUTATION_LLM_MAX_S, raw))

    # Per-server concurrency determines slowdown
    per_server = max(1, concurrent) / max(1, num_servers)
    multiplier = 1.0 + alpha * max(0.0, per_server - 1.0)

    return base * multiplier * TIMESCALE


# ---------------------------------------------------------------------------
# Instrumentation
# ---------------------------------------------------------------------------


@dataclass
class BenchMetrics:
    mutations_completed: int = 0
    programs_ingested: int = 0
    epochs_completed: int = 0
    max_concurrent: int = 0
    _concurrent: int = 0
    pipeline_fill_snapshots: list[tuple[float, int]] = field(default_factory=list)
    t0: float = 0.0
    max_in_flight: int = 8
    contention_alpha: float = 0.15
    num_servers: int = 5

    def summary(self, wall_clock: float, compact: bool = False) -> str:
        sim_wall = wall_clock / TIMESCALE
        sim_rate = self.mutations_completed / sim_wall * 60 if sim_wall > 0 else 0

        if self.pipeline_fill_snapshots:
            fills = [f for _, f in self.pipeline_fill_snapshots]
            avg_fill = sum(fills) / len(fills)
        else:
            avg_fill = 0

        first_full = None
        threshold = max(1, self.max_in_flight - 1)
        for t, f in self.pipeline_fill_snapshots:
            if f >= threshold:
                first_full = (t - self.t0) / TIMESCALE
                break

        if compact:
            return (
                f"max_in_flight={self.max_in_flight:>2d} | "
                f"{sim_rate:>6.2f} mutants/min | "
                f"max_concurrent={self.max_concurrent:>2d} | "
                f"avg_fill={avg_fill:.1f}/{self.max_in_flight} | "
                f"mutations={self.mutations_completed}"
            )

        lines = [
            "=== Steady-State Engine Benchmark ===",
            f"Wall clock (bench):     {wall_clock:.2f}s",
            f"Simulated wall clock:   {sim_wall:.0f}s ({sim_wall / 60:.1f}min)",
            f"Mutations completed:    {self.mutations_completed}",
            f"Programs ingested:      {self.programs_ingested}",
            f"Epochs completed:       {self.epochs_completed}",
            f"Throughput (simulated): {sim_rate:.2f} mutants/min",
            f"Max concurrent LLM:     {self.max_concurrent}",
            f"Avg pipeline fill:      {avg_fill:.1f} / {self.max_in_flight}",
            f"Contention model:       alpha={self.contention_alpha}, "
            f"servers={self.num_servers}",
            f"Time to fill pipeline:  {first_full:.0f}s sim"
            if first_full
            else "Time to fill pipeline:  never reached",
        ]
        return "\n".join(lines)


async def run_benchmark(
    duration_s: float = 2.0,
    max_in_flight: int = 8,
    max_generations: int = 200,
    contention_alpha: float = CONTENTION_ALPHA,
    num_servers: int = NUM_SERVERS,
) -> BenchMetrics:
    metrics = BenchMetrics(
        t0=time.monotonic(),
        max_in_flight=max_in_flight,
        contention_alpha=contention_alpha,
        num_servers=num_servers,
    )

    # Simple mocks
    storage = AsyncMock()
    strategy = AsyncMock()
    writer = MagicMock()
    writer.bind.return_value = writer
    metrics_tracker = MagicMock()
    metrics_tracker.format_best_summary.return_value = ""

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

    engine = SteadyStateEvolutionEngine(
        storage=storage,
        strategy=strategy,
        mutation_operator=AsyncMock(),
        config=config,
        writer=writer,
        metrics_tracker=metrics_tracker,
    )
    engine.config.program_acceptor = MagicMock()
    engine.config.program_acceptor.is_accepted.return_value = True

    # Track completed programs for ingestion
    completed_programs: dict[str, Program] = {}

    async def fake_generate(elites, **kwargs):
        metrics._concurrent += 1
        metrics.max_concurrent = max(metrics.max_concurrent, metrics._concurrent)
        latency = _sim_mutation_latency(
            metrics._concurrent, contention_alpha, num_servers
        )
        await asyncio.sleep(latency)
        prog = Program(code="def solve(): return 42", state=ProgramState.DONE)
        completed_programs[prog.id] = prog
        metrics.mutations_completed += 1
        metrics._concurrent -= 1
        return [prog.id]

    def mget_side(ids, **kw):
        return [completed_programs[pid] for pid in ids if pid in completed_programs]

    storage.mget.side_effect = mget_side

    def get_ids_side(status):
        if status == ProgramState.DONE.value:
            return [
                pid
                for pid, p in completed_programs.items()
                if p.state == ProgramState.DONE
            ]
        return []

    storage.get_ids_by_status.side_effect = get_ids_side

    # Track epochs
    original_epoch = engine._epoch_refresh

    async def tracked_epoch():
        await original_epoch()
        metrics.epochs_completed += 1

    engine._epoch_refresh = tracked_epoch

    # Track ingestion
    original_ingest = engine._ingest_batch

    async def tracked_ingest(pids):
        result = await original_ingest(pids)
        added, _ = result
        metrics.programs_ingested += added
        # Mark ingested programs as processed
        for pid in pids:
            if pid in completed_programs:
                completed_programs[pid].state = ProgramState.DISCARDED
        return result

    engine._ingest_batch = tracked_ingest

    # Monitor pipeline fill
    async def monitor():
        while engine._running:
            async with engine._in_flight_lock:
                fill = len(engine._in_flight)
            metrics.pipeline_fill_snapshots.append((time.monotonic(), fill))
            await asyncio.sleep(0.002)

    with patch(
        "gigaevo.evolution.engine.steady_state.generate_mutations",
        side_effect=fake_generate,
    ):
        monitor_task = asyncio.create_task(monitor())
        try:
            await asyncio.wait_for(engine.run(), timeout=duration_s)
        except TimeoutError:
            engine._running = False
        finally:
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass

    return metrics


async def sweep_max_in_flight(
    duration_s: float,
    max_generations: int,
    contention_alpha: float,
    num_servers: int,
    flight_values: list[int],
) -> list[BenchMetrics]:
    """Run benchmark for each max_in_flight value and return all metrics."""
    results = []
    for mif in flight_values:
        random.seed(42)  # same seed for fair comparison
        t0 = time.monotonic()
        m = await run_benchmark(
            duration_s=duration_s,
            max_in_flight=mif,
            max_generations=max_generations,
            contention_alpha=contention_alpha,
            num_servers=num_servers,
        )
        wall = time.monotonic() - t0
        sim_wall = wall / TIMESCALE
        m._wall = wall  # type: ignore[attr-defined]
        m._sim_rate = m.mutations_completed / sim_wall * 60 if sim_wall > 0 else 0  # type: ignore[attr-defined]
        results.append(m)
    return results


def main():
    parser = argparse.ArgumentParser(description="Benchmark steady-state engine")
    parser.add_argument("--duration", type=float, default=3.0, help="Bench seconds")
    parser.add_argument("--max-in-flight", type=int, default=8)
    parser.add_argument("--max-generations", type=int, default=200)
    parser.add_argument(
        "--alpha",
        type=float,
        default=CONTENTION_ALPHA,
        help="Contention slowdown factor per concurrent request per server",
    )
    parser.add_argument(
        "--servers",
        type=int,
        default=NUM_SERVERS,
        help="Number of LLM servers in pool",
    )
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="Sweep max_in_flight from 1 to 16 and find sweet spot",
    )
    parser.add_argument(
        "--sweep-alpha",
        action="store_true",
        help="Sweep contention alpha values for given max_in_flight",
    )
    args = parser.parse_args()

    if args.sweep:
        flight_values = [1, 2, 3, 4, 6, 8, 10, 12, 16]
        print(
            f"=== Sweep: max_in_flight (alpha={args.alpha}, servers={args.servers}) ==="
        )
        results = asyncio.run(
            sweep_max_in_flight(
                args.duration,
                args.max_generations,
                args.alpha,
                args.servers,
                flight_values,
            )
        )
        best = max(results, key=lambda m: m._sim_rate)  # type: ignore[attr-defined]
        for m in results:
            marker = " <-- BEST" if m is best else ""
            print(m.summary(m._wall, compact=True) + marker)  # type: ignore[attr-defined]
        print(f"\nSweet spot: max_in_flight={best.max_in_flight}")
        print(f"Peak throughput: {best._sim_rate:.2f} mutants/min")  # type: ignore[attr-defined]

    elif args.sweep_alpha:
        alphas = [0.0, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5]
        print(
            f"=== Sweep: contention alpha (max_in_flight={args.max_in_flight}, "
            f"servers={args.servers}) ==="
        )
        for alpha in alphas:
            random.seed(42)
            t0 = time.monotonic()
            m = asyncio.run(
                run_benchmark(
                    duration_s=args.duration,
                    max_in_flight=args.max_in_flight,
                    max_generations=args.max_generations,
                    contention_alpha=alpha,
                    num_servers=args.servers,
                )
            )
            wall = time.monotonic() - t0
            sim_wall = wall / TIMESCALE
            rate = m.mutations_completed / sim_wall * 60 if sim_wall > 0 else 0
            print(
                f"alpha={alpha:.2f} | {rate:>6.2f} mutants/min | "
                f"mutations={m.mutations_completed}"
            )

    else:
        random.seed(42)
        t0 = time.monotonic()
        m = asyncio.run(
            run_benchmark(
                duration_s=args.duration,
                max_in_flight=args.max_in_flight,
                max_generations=args.max_generations,
                contention_alpha=args.alpha,
                num_servers=args.servers,
            )
        )
        wall = time.monotonic() - t0
        print(m.summary(wall))


if __name__ == "__main__":
    main()
