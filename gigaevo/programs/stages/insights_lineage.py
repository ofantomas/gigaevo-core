from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from loguru import logger

from gigaevo.database.program_storage import ProgramStorage
from gigaevo.llm.agents.factories import create_lineage_agent
from gigaevo.llm.agents.lineage import TransitionAnalysis
from gigaevo.llm.models import ChatOpenAI, MultiModelRouter
from gigaevo.programs.core_types import (
    ProgramStageResult,
    StageIO,
    VoidInput,
)
from gigaevo.programs.metrics.context import MetricsContext
from gigaevo.programs.program import Program
from gigaevo.programs.stages.base import Stage
from gigaevo.programs.stages.cache_handler import NO_CACHE
from gigaevo.programs.stages.common import ListOf
from gigaevo.programs.stages.langgraph_stage import LangGraphStage
from gigaevo.programs.stages.stage_registry import StageRegistry


class LineageAnalysesOutput(StageIO):
    """List of LineageAnalysis for each parent→child transition."""

    analyses: list[TransitionAnalysis]


class TransitionAnalysisList(StageIO):
    items: list[TransitionAnalysis]


@StageRegistry.register(
    description="Compute LLM lineage analysis (parent → child) using parent IDs"
)
class LineageStage(LangGraphStage):
    """
    Uses DAG input `parents` to fetch parent Programs, injects the current Program
    as `program`, calls the lineage agent, and returns analyses (same order as parents).
    """

    InputsModel: type[StageIO] = VoidInput
    OutputModel: type[StageIO] = LineageAnalysesOutput

    def __init__(
        self,
        *,
        llm: ChatOpenAI | MultiModelRouter,
        task_description: str,
        metrics_context: MetricsContext,
        storage: ProgramStorage,
        prompts_dir: str | Path | None = None,
        **kwargs: Any,
    ):
        # Inject live Program instance as `program` kwarg for the agent
        super().__init__(
            agent=create_lineage_agent(
                llm,
                task_description,
                metrics_context,
                prompts_dir=prompts_dir,
            ),
            program_kwarg="program",
            **kwargs,
        )
        self.storage = storage

    async def preprocess(
        self, program: Program, params: StageIO
    ) -> dict[str, Any] | ProgramStageResult:
        ids: list[str] = list(program.lineage.parents)
        return {"parents": await self.storage.mget(ids)}

    async def partial_output_on_exhausted(
        self, program: Program, exc: BaseException
    ) -> LineageAnalysesOutput:
        return LineageAnalysesOutput(analyses=[])


class LineagesToDescendantsInputs(StageIO):
    descendant_ids: ListOf[str]


@StageRegistry.register(
    description="From a list of descendant IDs, return analyses for current→child transitions."
)
class LineagesToDescendants(Stage):
    """
    Input:  ListOf[str](items=[child_id, ...])
    Output: ListOf[TransitionAnalysis] for transitions (this_program -> each selected child)
    """

    InputsModel = LineagesToDescendantsInputs
    OutputModel = TransitionAnalysisList
    cache_handler = NO_CACHE  # descendants and their lineage may evolve over time

    def __init__(
        self, *, storage: ProgramStorage, source_stage_name: str, **kwargs: Any
    ):
        super().__init__(**kwargs)
        self.storage = storage
        self.source_stage_name = source_stage_name

    async def compute(
        self, program: Program
    ) -> TransitionAnalysisList | ProgramStageResult:
        child_ids = list(
            cast(LineagesToDescendantsInputs, self.params).descendant_ids.items
        )
        if not child_ids:
            return ProgramStageResult.skipped(
                message="No descendant IDs provided for lineage analysis",
                stage=self.stage_name,
            )

        children: list[Program] = await self.storage.mget(child_ids)
        want_parent = program.id
        out: list[TransitionAnalysis] = []

        for child in children:
            res = child.stage_results.get(self.source_stage_name)
            if not res or res.output is None:
                continue

            analyses: LineageAnalysesOutput = res.output
            # from all parents of this child, pick the one where (from == current program) and (to == this child)
            for a in analyses.analyses:
                if a.from_id == want_parent:
                    out.append(a)
                    logger.info(
                        "[LineagesToDescendants] Added transition for {} -> {}",
                        a.from_id,
                        a.to_id,
                    )
                    break

        return TransitionAnalysisList(items=out)


class LineagesFromAncestorsInputs(StageIO):
    ancestor_ids: ListOf[str]


@StageRegistry.register(
    description="From a list of ancestor IDs, return analyses for parent→current transitions."
)
class LineagesFromAncestors(Stage):
    """
    Input:  ListOf[str](items=[parent_id, ...])
    Output: ListOf[TransitionAnalysis] for transitions (parent -> this_program)
    """

    InputsModel = LineagesFromAncestorsInputs
    OutputModel = TransitionAnalysisList
    cache_handler = NO_CACHE

    def __init__(
        self, *, storage: ProgramStorage, source_stage_name: str, **kwargs: Any
    ):
        super().__init__(**kwargs)
        self.source_stage_name = source_stage_name
        self.storage = storage

    async def compute(
        self, program: Program
    ) -> TransitionAnalysisList | ProgramStageResult:
        parent_ids: list[str] = list(
            cast(LineagesFromAncestorsInputs, self.params).ancestor_ids.items
        )
        if not parent_ids:
            return ProgramStageResult.skipped(
                message="No ancestor IDs provided for lineage analysis",
                stage=self.stage_name,
            )
        res: ProgramStageResult | None = program.stage_results.get(
            self.source_stage_name
        )
        if not res or res.output is None:
            return ProgramStageResult.skipped(
                message="No transitions computed for this program",
                stage=self.stage_name,
            )
        analyses: list[TransitionAnalysis] = res.output.analyses
        want_child = program.id
        out = [a for a in analyses if a.to_id == want_child and a.from_id in parent_ids]
        for a in out:
            logger.info(
                "[LineagesFromAncestors] Added transition for {} -> {}",
                a.from_id,
                a.to_id,
            )

        return TransitionAnalysisList(items=out)


@StageRegistry.register(
    description="Collect stored lineage analyses along bounded parent ancestry paths."
)
class AncestralTransitionPath(Stage):
    """Return stored transition analyses from bounded ancestral history.

    For a linear path p1 -> p2 -> p3 -> p4 -> p5, executing this stage on p5
    returns analyses for p1->p2, p2->p3, p3->p4 in chronological order. The
    immediate parent->current transition is intentionally excluded because
    LineagesFromAncestors already renders it in the Parents section.
    If a program has multiple parents, the stage starts one branch per immediate
    parent, ranks branches by direction-aware primary metric, and then follows
    the best parent chain behind each branch. Analyses are read from each child
    program's stored ``LineageStage`` result; this stage never calls the lineage
    LLM.
    """

    InputsModel: type[StageIO] = VoidInput
    OutputModel = TransitionAnalysisList
    cache_handler = NO_CACHE

    def __init__(
        self,
        *,
        storage: ProgramStorage,
        metrics_context: MetricsContext,
        source_stage_name: str = "LineageStage",
        max_transitions: int = 4,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.storage = storage
        self.metrics_context = metrics_context
        self.source_stage_name = source_stage_name
        self.max_transitions = max(1, int(max_transitions))

    async def compute(
        self, program: Program
    ) -> TransitionAnalysisList | ProgramStageResult:
        ranked_parents = await self._rank_parents(program)
        if not ranked_parents:
            return ProgramStageResult.skipped(
                message="No parents available for ancestral transition path",
                stage=self.stage_name,
            )

        frontiers: list[tuple[int, Program, Program, set[str]]] = []
        for branch_index, immediate_parent in enumerate(ranked_parents):
            next_parent = await self._select_parent(immediate_parent)
            if next_parent is not None:
                frontiers.append(
                    (
                        branch_index,
                        immediate_parent,
                        next_parent,
                        {program.id, immediate_parent.id},
                    )
                )

        if not frontiers:
            return ProgramStageResult.skipped(
                message=(
                    "No ancestral transitions available behind immediate parents"
                ),
                stage=self.stage_name,
            )

        collected: list[tuple[int, int, int, TransitionAnalysis]] = []
        seen_edges: set[tuple[str, str]] = set()
        sequence = 0

        for _depth in range(self.max_transitions):
            if not frontiers or len(collected) >= self.max_transitions:
                break

            next_frontiers: list[tuple[int, Program, Program, set[str]]] = []
            for branch_index, child, parent, visited in frontiers:
                if len(collected) >= self.max_transitions:
                    break
                if parent.id in visited:
                    logger.warning(
                        "[AncestralTransitionPath] Stopping at cycle {} -> {}",
                        parent.id,
                        child.id,
                    )
                    continue

                edge = (parent.id, child.id)
                if edge not in seen_edges:
                    analysis = self._find_analysis(child, parent.id)
                    if analysis is not None:
                        collected.append(
                            (
                                child.lineage.generation,
                                branch_index,
                                sequence,
                                analysis,
                            )
                        )
                        sequence += 1
                        seen_edges.add(edge)
                        logger.info(
                            "[AncestralTransitionPath] Added transition for {} -> {}",
                            analysis.from_id,
                            analysis.to_id,
                        )

                next_parent = await self._select_parent(parent)
                if next_parent is not None:
                    next_frontiers.append(
                        (branch_index, parent, next_parent, visited | {parent.id})
                    )

            frontiers = next_frontiers

        collected.sort(key=lambda item: (item[0], item[1], item[2]))
        return TransitionAnalysisList(items=[analysis for *_rest, analysis in collected])

    async def _rank_parents(self, child: Program) -> list[Program]:
        parent_ids = list(child.lineage.parents)
        if not parent_ids:
            return []

        parents = await self.storage.mget(parent_ids)
        if not parents:
            logger.info(
                "[AncestralTransitionPath] No stored parents found for {}",
                child.id,
            )
            return []

        primary_key = self.metrics_context.get_primary_key()
        higher_is_better = self.metrics_context.is_higher_better(primary_key)
        indexed = {parent.id: index for index, parent in enumerate(parents)}
        scored = [
            (parent.metrics[primary_key], indexed[parent.id], parent)
            for parent in parents
            if primary_key in parent.metrics
        ]
        unscored = [parent for parent in parents if primary_key not in parent.metrics]

        if unscored:
            logger.warning(
                "[AncestralTransitionPath] {} parents for {} lack primary metric {}; "
                "placing them after scored parents",
                len(unscored),
                child.id,
                primary_key,
            )

        if higher_is_better:
            scored.sort(key=lambda item: (-item[0], item[1]))
        else:
            scored.sort(key=lambda item: (item[0], item[1]))
        ordered = [parent for _score, _index, parent in scored]
        ordered.extend(sorted(unscored, key=lambda parent: indexed[parent.id]))
        return ordered

    async def _select_parent(self, child: Program) -> Program | None:
        ranked = await self._rank_parents(child)
        return ranked[0] if ranked else None

    def _find_analysis(
        self, child: Program, parent_id: str
    ) -> TransitionAnalysis | None:
        res: ProgramStageResult | None = child.stage_results.get(self.source_stage_name)
        if not res or res.output is None:
            return None

        analyses = getattr(res.output, "analyses", None)
        if analyses is None:
            return None

        for analysis in analyses:
            if analysis.from_id == parent_id and analysis.to_id == child.id:
                return analysis
        return None
