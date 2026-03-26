"""Realistic benchmark for SteadyStateEvolutionEngine throughput.

Simulates real-world latencies calibrated from production HoVer experiment logs:
- LLM mutation calls: 10-60s (exponential, mean ~25s)
- Redis/storage operations: ~1ms

Measures: mutants produced per simulated minute, max concurrency, pipeline fill.

Usage:
    PYTHONPATH=. python benchmarks/bench_steady_state.py [--duration 2.0] [--max-in-flight 8]
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


def _sim_mutation_latency() -> float:
    raw = random.expovariate(1.0 / MUTATION_LLM_MEAN_S)
    return max(MUTATION_LLM_MIN_S, min(MUTATION_LLM_MAX_S, raw)) * TIMESCALE


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

    def summary(self, wall_clock: float) -> str:
        sim_wall = wall_clock / TIMESCALE
        sim_rate = self.mutations_completed / sim_wall * 60 if sim_wall > 0 else 0

        if self.pipeline_fill_snapshots:
            fills = [f for _, f in self.pipeline_fill_snapshots]
            avg_fill = sum(fills) / len(fills)
        else:
            avg_fill = 0

        first_full = None
        for t, f in self.pipeline_fill_snapshots:
            if f >= 7:
                first_full = (t - self.t0) / TIMESCALE
                break

        lines = [
            "=== Steady-State Engine Benchmark ===",
            f"Wall clock (bench):     {wall_clock:.2f}s",
            f"Simulated wall clock:   {sim_wall:.0f}s ({sim_wall / 60:.1f}min)",
            f"Mutations completed:    {self.mutations_completed}",
            f"Programs ingested:      {self.programs_ingested}",
            f"Epochs completed:       {self.epochs_completed}",
            f"Throughput (simulated): {sim_rate:.2f} mutants/min",
            f"Max concurrent LLM:     {self.max_concurrent}",
            f"Avg pipeline fill:      {avg_fill:.1f} / 8",
            f"Time to fill pipeline:  {first_full:.0f}s sim"
            if first_full
            else "Time to fill pipeline:  never reached",
        ]
        return "\n".join(lines)


async def run_benchmark(
    duration_s: float = 2.0,
    max_in_flight: int = 8,
    max_generations: int = 200,
) -> BenchMetrics:
    metrics = BenchMetrics(t0=time.monotonic())

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
        await asyncio.sleep(_sim_mutation_latency())
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


def main():
    parser = argparse.ArgumentParser(description="Benchmark steady-state engine")
    parser.add_argument("--duration", type=float, default=2.0, help="Bench seconds")
    parser.add_argument("--max-in-flight", type=int, default=8)
    parser.add_argument("--max-generations", type=int, default=200)
    args = parser.parse_args()

    random.seed(42)
    t0 = time.monotonic()
    m = asyncio.run(
        run_benchmark(
            duration_s=args.duration,
            max_in_flight=args.max_in_flight,
            max_generations=args.max_generations,
        )
    )
    wall = time.monotonic() - t0
    print(m.summary(wall))


if __name__ == "__main__":
    main()
