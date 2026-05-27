from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from gigaevo.database.program_storage import ProgramStorage
from gigaevo.evolution.mutation.constants import MUTATION_CONTEXT_METADATA_KEY
from gigaevo.memory.provider import MemoryProvider
from gigaevo.programs.core_types import ProgramStageResult, StageState
from gigaevo.programs.metrics.context import MetricsContext
from gigaevo.programs.metrics.formatter import MetricsFormatter
from gigaevo.programs.program import Program
from gigaevo.programs.program_state import ProgramState
from gigaevo.programs.stages.ancestry_selector import AncestrySelector
from gigaevo.programs.stages.base import Stage
from gigaevo.programs.stages.collector import (
    AncestorProgramIds,
    DescendantProgramIds,
    EvolutionaryStatisticsCollector,
)
from gigaevo.programs.stages.common import (
    FloatDictContainer,
    StringContainer,
    StringList,
)
from gigaevo.programs.stages.insights import InsightsOutput
from gigaevo.programs.stages.insights_lineage import (
    AncestralTransitionPath,
    LineagesFromAncestors,
    LineagesToDescendants,
    TransitionAnalysisList,
)
from gigaevo.programs.stages.memory_context import MemoryContextStage
from gigaevo.programs.stages.mutation_context import MutationContextStage

REFRESH_STATUS_METADATA_KEY = "archive_refresh"


class ArchiveContextRefresher:
    """Refresh mutation context for archive elites without lifecycle transitions."""

    def __init__(
        self,
        *,
        storage: ProgramStorage,
        metrics_context: MetricsContext,
        memory_provider: MemoryProvider,
        task_description: str,
        stage_timeout: float,
        include_ancestral_transition_path: bool = True,
        max_concurrency: int = 8,
    ) -> None:
        self.storage = storage
        self.metrics_context = metrics_context
        self.memory_provider = memory_provider
        self.task_description = task_description
        self.stage_timeout = stage_timeout
        self.include_ancestral_transition_path = include_ancestral_transition_path
        self.max_concurrency = max(1, int(max_concurrency))
        self.metrics_description = MetricsFormatter(
            metrics_context
        ).format_metrics_description()

    async def refresh_many(self, programs: list[Program]) -> int:
        if not programs:
            return 0
        sem = asyncio.Semaphore(self.max_concurrency)
        refreshed = 0

        async def _one(program: Program) -> bool:
            async with sem:
                return await self.refresh_one(program)

        for ok in await asyncio.gather(*[_one(p) for p in programs]):
            if ok:
                refreshed += 1
        return refreshed

    async def refresh_one(self, program: Program) -> bool:
        if program.state != ProgramState.DONE:
            logger.warning(
                "[ArchiveContextRefresher] Skipping {} in state {}",
                program.short_id,
                program.state,
            )
            return False

        refreshed_at = datetime.now(UTC).isoformat()
        try:
            descendant_ids = await self._run(
                "DescendantProgramIds",
                DescendantProgramIds(
                    storage=self.storage,
                    selector=AncestrySelector(
                        metrics_context=self.metrics_context,
                        strategy="best_fitness",
                        max_selected=1,
                    ),
                    timeout=self.stage_timeout,
                ),
                program,
            )
            ancestor_ids = await self._run(
                "AncestorProgramIds",
                AncestorProgramIds(
                    storage=self.storage,
                    selector=AncestrySelector(
                        metrics_context=self.metrics_context,
                        strategy="best_fitness",
                        max_selected=2,
                    ),
                    timeout=self.stage_timeout,
                ),
                program,
            )
            lineage_desc = await self._run(
                "LineagesToDescendants",
                LineagesToDescendants(
                    storage=self.storage,
                    source_stage_name="LineageStage",
                    timeout=self.stage_timeout,
                ),
                program,
                {
                    "descendant_ids": descendant_ids
                    if isinstance(descendant_ids, StringList)
                    else StringList(items=[])
                },
            )
            lineage_anc = await self._run(
                "LineagesFromAncestors",
                LineagesFromAncestors(
                    storage=self.storage,
                    source_stage_name="LineageStage",
                    timeout=self.stage_timeout,
                ),
                program,
                {
                    "ancestor_ids": ancestor_ids
                    if isinstance(ancestor_ids, StringList)
                    else StringList(items=[])
                },
            )
            lineage_path = None
            if self.include_ancestral_transition_path:
                lineage_path = await self._run(
                    "AncestralTransitionPath",
                    AncestralTransitionPath(
                        storage=self.storage,
                        metrics_context=self.metrics_context,
                        source_stage_name="LineageStage",
                        max_transitions=4,
                        timeout=self.stage_timeout,
                    ),
                    program,
                )
            evo_stats = await self._run(
                "EvolutionaryStatisticsCollector",
                EvolutionaryStatisticsCollector(
                    storage=self.storage,
                    metrics_context=self.metrics_context,
                    timeout=self.stage_timeout,
                ),
                program,
            )
            memory = await self._run(
                "MemoryContextStage",
                MemoryContextStage(
                    memory_provider=self.memory_provider,
                    task_description=self.task_description,
                    metrics_description=self.metrics_description,
                    timeout=self.stage_timeout,
                ),
                program,
            )

            mutation_inputs: dict[str, Any] = {
                "metrics": FloatDictContainer(data=program.metrics),
                "evolutionary_statistics": evo_stats,
                "memory": memory,
            }
            stored_insights = self._stored_output(program, "InsightsStage")
            if isinstance(stored_insights, InsightsOutput):
                mutation_inputs["insights"] = stored_insights
            stored_formatted = self._stored_output(program, "FormatterStage")
            if isinstance(stored_formatted, StringContainer):
                mutation_inputs["formatted"] = stored_formatted
            if isinstance(lineage_desc, TransitionAnalysisList):
                mutation_inputs["lineage_descendants"] = lineage_desc
            if isinstance(lineage_anc, TransitionAnalysisList):
                mutation_inputs["lineage_ancestors"] = lineage_anc
            if isinstance(lineage_path, TransitionAnalysisList):
                mutation_inputs["lineage_ancestor_path"] = lineage_path

            await self._run(
                "MutationContextStage",
                MutationContextStage(
                    metrics_context=self.metrics_context,
                    timeout=self.stage_timeout,
                ),
                program,
                mutation_inputs,
            )
            program.metadata[REFRESH_STATUS_METADATA_KEY] = {
                "status": "completed",
                "refreshed_at": refreshed_at,
            }
            await self.storage.update(program)
            return True
        except Exception as exc:
            program.metadata[REFRESH_STATUS_METADATA_KEY] = {
                "status": "failed",
                "refreshed_at": refreshed_at,
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
            }
            await self.storage.update(program)
            logger.exception(
                "[ArchiveContextRefresher] Refresh failed for {}", program.short_id
            )
            return False

    async def _run(
        self,
        name: str,
        stage: Stage,
        program: Program,
        inputs: dict[str, Any] | None = None,
    ) -> Any | None:
        stage.attach_inputs(inputs or {})
        result = await stage.execute(program)
        program.stage_results[name] = result
        if result.status == StageState.COMPLETED:
            return result.output
        return None

    @staticmethod
    def _stored_output(program: Program, stage_name: str) -> Any | None:
        result: ProgramStageResult | None = program.stage_results.get(stage_name)
        if result and result.status == StageState.COMPLETED:
            return result.output
        return None

    @staticmethod
    def has_context(program: Program) -> bool:
        return program.get_metadata(MUTATION_CONTEXT_METADATA_KEY) is not None
