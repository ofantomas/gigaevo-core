from __future__ import annotations

import asyncio
import contextlib
import ctypes
from datetime import UTC, datetime
import gc
import os
import time
from typing import Any, NamedTuple

from loguru import logger
from pydantic import BaseModel, Field, computed_field, field_validator

from gigaevo.database.program_storage import ProgramStorage
from gigaevo.database.state_manager import ProgramStateManager
from gigaevo.evolution.scheduling.prioritizer import (
    CachedFirstPrioritizer,
    ProgramPrioritizer,
)
from gigaevo.programs.core_types import StageState
from gigaevo.programs.dag.dag import DAG
from gigaevo.programs.program import Program
from gigaevo.programs.program_state import ProgramState
from gigaevo.runner.dag_blueprint import DAGBlueprint
from gigaevo.utils.metrics_collector import start_metrics_collector
from gigaevo.utils.trackers.base import LogWriter

ORPHAN_RETRY_COUNT_METADATA_KEY = "dag_runner_orphan_retries"
ORPHAN_QUARANTINE_METADATA_KEY = "dag_runner_quarantine"
_ORPHAN_TERMINAL_EVIDENCE_STAGES = frozenset(
    {
        "EnsureMetricsStage",
        "FetchMetrics",
        "ParseMetricsStage",
        "MutationContextStage",
    }
)


class TaskInfo(NamedTuple):
    task: asyncio.Task
    program_id: str
    started_at: float


class DagRunnerMetrics(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    loop_iterations: int = 0
    dag_runs_started: int = 0
    dag_runs_completed: int = 0
    dag_errors: int = 0
    dag_timeouts: int = 0
    orphaned_programs_discarded: int = 0
    orphaned_programs_preserved: int = 0
    orphaned_programs_completed: int = 0
    orphaned_programs_requeued: int = 0
    orphaned_programs_quarantined: int = 0
    dag_build_failures: int = 0
    state_update_failures: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def uptime_seconds(self) -> int:
        return int((datetime.now(UTC) - self.started_at).total_seconds())

    @computed_field  # type: ignore[prop-decorator]
    @property
    def success_rate(self) -> float:
        finished = self.dag_runs_completed + self.dag_errors
        return 1.0 if finished == 0 else self.dag_runs_completed / finished

    @computed_field  # type: ignore[prop-decorator]
    @property
    def average_iterations_per_second(self) -> float:
        return (
            0.0
            if self.uptime_seconds == 0
            else self.loop_iterations / self.uptime_seconds
        )

    def increment_loop_iterations(self) -> None:
        self.loop_iterations += 1

    def increment_dag_runs_started(self) -> None:
        self.dag_runs_started += 1

    def increment_dag_runs_completed(self) -> None:
        self.dag_runs_completed += 1

    def increment_dag_errors(self) -> None:
        self.dag_errors += 1

    def record_timeout(self) -> None:
        self.dag_timeouts += 1
        self.dag_errors += 1

    def record_orphaned(self) -> None:
        self.orphaned_programs_discarded += 1
        self.dag_errors += 1

    def record_orphaned_preserved(self) -> None:
        self.orphaned_programs_preserved += 1

    def record_orphaned_completed(self) -> None:
        self.orphaned_programs_completed += 1

    def record_orphaned_requeued(self) -> None:
        self.orphaned_programs_requeued += 1

    def record_orphaned_quarantined(self) -> None:
        self.orphaned_programs_quarantined += 1
        self.orphaned_programs_discarded += 1
        self.dag_errors += 1

    def record_build_failure(self) -> None:
        self.dag_build_failures += 1
        self.dag_errors += 1

    def record_state_update_failure(self) -> None:
        self.state_update_failures += 1
        self.dag_errors += 1


class DagRunnerConfig(BaseModel):
    poll_interval: float = Field(
        default=0.5,
        gt=0,
        le=60.0,
        description="Interval in seconds to poll for new programs",
    )
    max_concurrent_dags: int = Field(
        default=8,
        gt=0,
        le=1000,
        description="Maximum number of DAGs to run concurrently",
    )
    prefetch_factor: int = Field(
        default=8,
        ge=1,
        le=64,
        description=(
            "How many batches of max_concurrent_dags to pre-create as tasks. "
            "The semaphore still limits actual concurrency; prefetched tasks "
            "wait on the semaphore and start immediately when a slot opens, "
            "eliminating poll-interval latency between consecutive DAGs."
        ),
    )
    metrics_collection_interval: float = Field(
        default=1.0, gt=0, description="Interval in seconds for metrics collection"
    )
    dag_timeout: float = Field(
        default=3600, gt=0, description="Timeout for DAG execution"
    )
    orphan_retry_budget: int = Field(
        default=3,
        ge=0,
        description=(
            "Number of times a live runner may requeue an orphaned RUNNING "
            "program before quarantining it as DISCARDED with metadata. "
            "Programs with terminal evidence are never quarantined by this path."
        ),
    )

    @field_validator("poll_interval")
    @classmethod
    def _validate_poll_interval(cls, v: float) -> float:
        if v < 0.01:
            raise ValueError("poll_interval must be >= 0.01s")
        if v > 30.0:
            logger.debug("Large poll_interval ({}s) may slow responsiveness", v)
        return v

    @field_validator("max_concurrent_dags")
    @classmethod
    def _validate_concurrency(cls, v: int) -> int:
        cpu = os.cpu_count() or 4
        if v > cpu * 4:
            logger.warning("max_concurrent_dags ({}) > 4x CPU count ({})", v, cpu)
        return v


class DagRunner:
    def __init__(
        self,
        storage: ProgramStorage,
        dag_blueprint: DAGBlueprint,
        config: DagRunnerConfig,
        writer: LogWriter,
        *,
        prioritizer: ProgramPrioritizer | None = None,
    ) -> None:
        self._storage = storage
        self._dag_blueprint = dag_blueprint
        self._state_manager = ProgramStateManager(storage)
        self._metrics = DagRunnerMetrics()
        self._config = config
        self._writer = writer.bind(path=["dag_runner"])
        self._prioritizer = prioritizer or CachedFirstPrioritizer()

        self._active: dict[str, TaskInfo] = {}
        self._sema = asyncio.Semaphore(self._config.max_concurrent_dags)

        self._task: asyncio.Task | None = None
        self._stopping = False
        self._last_gc_time: float = time.monotonic()

        # Batch queue: completed DAGs queue their RUNNING→DONE transition
        # here instead of writing individually.  _maintain flushes with
        # batch_transition_state (bulk SREM/SADD — 2 commands instead of 2N).
        self._done_queue: list[Program] = []

        # async metrics collector task (no threads)
        self._metrics_collector_task: asyncio.Task | None = None

    @property
    def task(self) -> asyncio.Task | None:
        return self._task

    def start(self) -> None:
        if self._task:
            logger.warning("[DagRunner] already running")
            return

        self._task = asyncio.create_task(self._run(), name="dag-scheduler")
        self._stopping = False

        async def _collect_metrics() -> dict[str, Any]:
            metrics_dict = self._metrics.model_dump(mode="json")
            metrics_dict["dag_active_count"] = float(self.active_count())
            return metrics_dict

        self._metrics_collector_task = start_metrics_collector(
            writer=self._writer,
            collect_fn=_collect_metrics,
            interval=self._config.metrics_collection_interval,
            stop_flag=lambda: self._stopping,
            task_name="dag-metrics-collector",
        )

    async def stop(self) -> None:
        self._stopping = True

        # cancel scheduler loop
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

        # cancel all active DAG tasks
        for info in list(self._active.values()):
            await self._cancel_task(info)
        self._active.clear()

        # flush any remaining DONE transitions
        await self._flush_done_queue()

        # cancel metrics collector task
        if self._metrics_collector_task:
            self._metrics_collector_task.cancel()
            self._metrics_collector_task = None

        await self._storage.close()

    def active_count(self) -> int:
        return sum(1 for info in self._active.values() if not info.task.done())

    async def _run(self) -> None:
        logger.info("[DagScheduler] start")
        try:
            while not self._stopping:
                try:
                    self._metrics.increment_loop_iterations()

                    # timeouts + harvest finished/failed tasks
                    await self._maintain()

                    # start new DAGs up to capacity
                    await self._launch()

                    # storage-side wait (stream or sleep)
                    await self._storage.wait_for_activity(self._config.poll_interval)

                except asyncio.CancelledError:
                    # allow clean shutdown; propagate to caller
                    raise
                except Exception:
                    # don’t kill the scheduler on a transient failure in one loop tick
                    logger.exception("[DagScheduler] iteration failed")
                    await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            logger.debug("[DagScheduler] cancelled")
            raise
        finally:
            logger.info("[DagScheduler] stopped")

    async def _maintain(self) -> None:
        now = time.monotonic()
        finished: list[TaskInfo] = []
        timed_out: list[TaskInfo] = []

        for info in list(self._active.values()):
            if info.task.done():
                finished.append(info)
            elif (now - info.started_at) > self._config.dag_timeout:
                timed_out.append(info)

        for info in timed_out:
            await self._cancel_task(info)
            self._active.pop(info.program_id, None)
            try:
                prog = await self._storage.get(info.program_id)
                if prog:
                    if prog.state == ProgramState.DONE:
                        # TOCTOU guard: the task completed successfully between the
                        # "timed out" classification and this point. Don't discard
                        # a program that already finished — it will be ingested normally.
                        logger.warning(
                            "[DagScheduler] program {} classified as timed out but "
                            "already DONE — skipping discard",
                            info.program_id[:8],
                        )
                        self._metrics.record_timeout()
                        continue
                    await self._state_manager.set_program_state(
                        prog, ProgramState.DISCARDED
                    )
                self._metrics.record_timeout()
                logger.error("[DagScheduler] program {} timed out", info.program_id[:8])
            except Exception as e:
                logger.error(
                    "[DagScheduler] discard after timeout failed for {}: {}",
                    info.program_id[:8],
                    e,
                )

        for info in finished:
            self._active.pop(info.program_id, None)
            try:
                info.task.result()
                self._metrics.increment_dag_runs_completed()
                logger.debug(
                    "[DagScheduler] harvested completed task for program {}",
                    info.program_id[:8],
                )
            except Exception as e:
                self._metrics.increment_dag_errors()
                logger.error(
                    "[DagScheduler] program {} failed: {}", info.program_id[:8], e
                )
            finally:
                del info

        # Flush any remaining RUNNING→DONE transitions
        await self._flush_done_queue()

        if finished or timed_out:
            now = time.monotonic()
            if now - self._last_gc_time > 30.0:
                gc.collect()
                try:
                    ctypes.CDLL("libc.so.6").malloc_trim(0)
                except Exception:
                    pass
                self._last_gc_time = now

            logger.debug(
                "[DagScheduler] Cleaned up {} finished + {} timed out tasks",
                len(finished),
                len(timed_out),
            )

    async def _launch(self) -> None:
        # Phase 1: fetch IDs only (2 x SMEMBERS, no MGET)
        try:
            queued_ids, running_ids = await asyncio.gather(
                self._storage.get_ids_by_status(ProgramState.QUEUED.value),
                self._storage.get_ids_by_status(ProgramState.RUNNING.value),
            )
        except Exception as e:
            logger.error("[DagScheduler] fetch-by-status failed: {}", e)
            return

        # Phase 2: handle orphaned RUNNING programs (fetch full data only for these)
        orphaned_ids = [pid for pid in running_ids if pid not in self._active]
        if orphaned_ids:
            try:
                orphaned = await self._storage.mget(orphaned_ids)
                for p in [p for p in orphaned if p is not None]:
                    await self._reconcile_orphaned_running_program(p)
            except Exception as e:
                logger.error("[DagScheduler] orphan fetch failed: {}", e)

        # Phase 3: launch fresh programs up to capacity (fetch only what we need)
        # Prefetch: create up to max_concurrent_dags * prefetch_factor tasks.
        # The semaphore limits actual concurrency; extra tasks wait on the
        # semaphore and start immediately when a slot opens — no poll delay.
        max_active = self._config.max_concurrent_dags * self._config.prefetch_factor
        capacity = max_active - len(self._active)
        if capacity <= 0:
            return

        to_launch_ids = [pid for pid in queued_ids if pid not in self._active][
            :capacity
        ]
        if not to_launch_ids:
            return

        try:
            fresh = await self._storage.mget(to_launch_ids)
        except Exception as e:
            logger.error("[DagScheduler] mget for launch failed: {}", e)
            return

        launched: list[Program] = []
        allowed_ids = set(to_launch_ids)
        candidates = [p for p in fresh if p is not None]
        candidates = self._prioritizer.prioritize(candidates)
        for program in candidates:
            if program.id in self._active or program.id not in allowed_ids:
                continue

            try:
                dag: DAG = self._dag_blueprint.build(
                    self._state_manager,
                    writer=self._writer,
                    caller_handles_persist=True,
                )
            except Exception as e:
                import traceback

                logger.error(
                    "[DagScheduler] DAG build failed for {}: {}", program.short_id, e
                )
                logger.error("[DagScheduler] Traceback:\n{}", traceback.format_exc())
                self._metrics.record_build_failure()
                try:
                    await self._state_manager.set_program_state(
                        program, ProgramState.DISCARDED
                    )
                except Exception as se:
                    logger.error(
                        "[DagScheduler] state update failed for {}: {}",
                        program.short_id,
                        se,
                    )
                    self._metrics.record_state_update_failure()
                continue

            async def _run_one(prog: Program = program, dag_inst: DAG = dag) -> None:
                async with self._sema:
                    await self._execute_dag(dag_inst, prog)

            task = asyncio.create_task(_run_one(), name=f"dag-{program.short_id}")
            self._active[program.id] = TaskInfo(task, program.id, time.monotonic())
            launched.append(program)

        # Batch transition QUEUED → RUNNING (3 RT instead of 2N RT)
        if launched:
            launched_ids = [p.id for p in launched]
            try:
                count = await self._storage.batch_transition_by_ids(
                    launched_ids,
                    ProgramState.QUEUED.value,
                    ProgramState.RUNNING.value,
                )
                # Update in-memory state to match Redis so _execute_dag
                # sees RUNNING (not stale QUEUED) when transitioning to DONE.
                for prog in launched:
                    prog.state = ProgramState.RUNNING
                self._metrics.dag_runs_started += count
                logger.info("[DagScheduler] launched {} programs", count)
            except Exception as e:
                logger.error("[DagScheduler] batch mark-started failed: {}", e)
                # Cancel tasks whose state transition failed
                for pid in launched_ids:
                    info = self._active.pop(pid, None)
                    if info and not info.task.done():
                        info.task.cancel()

    async def _execute_dag(self, dag: DAG, program: Program) -> None:
        ok = True
        eval_start = time.monotonic()
        try:
            await dag.run(program)
        except Exception as exc:
            ok = False
            logger.error(
                "[DagScheduler] DAG run failed for {}: {}", program.short_id, exc
            )
        finally:
            # Eagerly release references to allow GC of heavy objects.
            dag.teardown()

        # Update scheduling predictor with actual eval duration (even for
        # failures — duration-until-failure is informative and avoids
        # survivorship bias where complex programs are underestimated)
        predictor = self._prioritizer.predictor
        if predictor is not None:
            eval_duration = time.monotonic() - eval_start
            predictor.update(program, eval_duration)

        if ok:
            # Queue for batch RUNNING→DONE transition
            # (bulk SREM/SADD — 2 commands instead of 2N).
            self._done_queue.append(program)
            # Flush when batch reaches concurrency limit to avoid latency
            if len(self._done_queue) >= self._config.max_concurrent_dags:
                await self._flush_done_queue()
            logger.debug(
                "[DagScheduler] DAG completed for {} (queued for batch)",
                program.short_id,
            )
        else:
            try:
                await self._state_manager.set_program_state(
                    program, ProgramState.DISCARDED
                )
            except Exception as se:
                self._metrics.record_state_update_failure()
                logger.error(
                    "[DagScheduler] state update failed for {}: {}",
                    program.short_id,
                    se,
            )

    def _has_terminal_evidence(self, program: Program) -> bool:
        """Return whether a RUNNING orphan has evidence of completed DAG work."""
        if program.metrics:
            return True
        for stage_name in _ORPHAN_TERMINAL_EVIDENCE_STAGES:
            result = program.stage_results.get(stage_name)
            if result is not None and result.status == StageState.COMPLETED:
                return True
        return False

    async def _reconcile_orphaned_running_program(self, program: Program) -> None:
        """Resolve a RUNNING status-set entry that is not owned by this runner.

        A missing `_active` entry is not proof of invalid work. The stored
        program may already be DONE, or may have terminal stage evidence from a
        DAG that completed before the scheduler crashed or lost local state.
        Only retryable non-terminal RUNNING programs are requeued; repeated
        non-terminal orphans are explicitly quarantined with metadata.
        """
        try:
            if program.state == ProgramState.DONE:
                await self._storage.transition_status(
                    program.id,
                    ProgramState.RUNNING.value,
                    ProgramState.DONE.value,
                )
                self._metrics.record_orphaned_preserved()
                logger.warning(
                    "[DagScheduler] orphaned program {} already DONE — preserved",
                    program.short_id,
                )
                return

            if program.state == ProgramState.DISCARDED:
                await self._storage.transition_status(
                    program.id,
                    ProgramState.RUNNING.value,
                    ProgramState.DISCARDED.value,
                )
                self._metrics.record_orphaned_preserved()
                logger.warning(
                    "[DagScheduler] orphaned program {} already DISCARDED — "
                    "cleaned status set",
                    program.short_id,
                )
                return

            if program.state == ProgramState.QUEUED:
                await self._storage.transition_status(
                    program.id,
                    ProgramState.RUNNING.value,
                    ProgramState.QUEUED.value,
                )
                self._metrics.record_orphaned_preserved()
                logger.warning(
                    "[DagScheduler] orphaned program {} blob is QUEUED — "
                    "cleaned RUNNING status membership",
                    program.short_id,
                )
                return

            if self._has_terminal_evidence(program):
                program.set_metadata(
                    ORPHAN_QUARANTINE_METADATA_KEY,
                    {
                        "action": "finalized_done",
                        "reason": "orphaned_running_with_terminal_evidence",
                    },
                )
                await self._state_manager.set_program_state(program, ProgramState.DONE)
                self._metrics.record_orphaned_completed()
                logger.warning(
                    "[DagScheduler] orphaned program {} had terminal evidence — "
                    "finalized as DONE",
                    program.short_id,
                )
                return

            retries = int(program.metadata.get(ORPHAN_RETRY_COUNT_METADATA_KEY, 0) or 0)
            if retries >= self._config.orphan_retry_budget:
                program.set_metadata(
                    ORPHAN_QUARANTINE_METADATA_KEY,
                    {
                        "action": "quarantined_discarded",
                        "reason": "orphan_retry_budget_exhausted",
                        "retry_count": retries,
                    },
                )
                await self._state_manager.set_program_state(
                    program, ProgramState.DISCARDED
                )
                self._metrics.record_orphaned_quarantined()
                logger.error(
                    "[DagScheduler] orphaned program {} exhausted retry budget "
                    "({}) — quarantined as DISCARDED",
                    program.short_id,
                    retries,
                )
                return

            program.set_metadata(ORPHAN_RETRY_COUNT_METADATA_KEY, retries + 1)
            requeued = await self._storage.requeue_running_program(program)
            if requeued:
                self._metrics.record_orphaned_requeued()
                logger.warning(
                    "[DagScheduler] orphaned program {} requeued for retry "
                    "({}/{})",
                    program.short_id,
                    retries + 1,
                    self._config.orphan_retry_budget,
                )
            else:
                self._metrics.record_orphaned_preserved()
                logger.warning(
                    "[DagScheduler] orphaned program {} was no longer RUNNING "
                    "during reconciliation",
                    program.short_id,
                )
        except Exception as se:
            self._metrics.record_state_update_failure()
            logger.error(
                "[DagScheduler] orphan reconciliation failed for {}: {}",
                program.short_id,
                se,
            )

    async def _flush_done_queue(self) -> None:
        """Batch-transition queued DONE programs to Redis."""
        if not self._done_queue:
            return
        batch = self._done_queue[:]
        self._done_queue.clear()
        try:
            await self._storage.batch_transition_state(
                batch,
                ProgramState.RUNNING.value,
                ProgramState.DONE.value,
            )
            logger.debug(
                "[DagScheduler] batch RUNNING→DONE for {} programs", len(batch)
            )
        except Exception as e:
            logger.error(
                "[DagScheduler] batch RUNNING→DONE failed for {} programs: {}",
                len(batch),
                e,
            )

    async def _cancel_task(self, info: TaskInfo) -> None:
        if info.task.done():
            return
        info.task.cancel()
        try:
            await asyncio.wait_for(info.task, timeout=2.0)
        except asyncio.CancelledError:
            pass
        except TimeoutError:
            logger.warning(
                "[DagScheduler] task for {} did not terminate within 2s after cancel; "
                "atomic_state_transition merge will resolve any concurrent state race",
                info.program_id[:8],
            )
