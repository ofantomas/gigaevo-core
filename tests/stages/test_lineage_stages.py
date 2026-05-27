"""Tests for LineagesToDescendants and LineagesFromAncestors stages."""

from __future__ import annotations

from unittest.mock import AsyncMock

from gigaevo.llm.agents.insights import ProgramInsights
from gigaevo.llm.agents.lineage import (
    TransitionAnalysis,
    TransitionInsight,
    TransitionInsights,
)
from gigaevo.programs.core_types import ProgramStageResult, StageState
from gigaevo.programs.metrics.context import MetricsContext, MetricSpec
from gigaevo.programs.program import Program
from gigaevo.programs.program_state import ProgramState
from gigaevo.programs.stages.cache_handler import NO_CACHE
from gigaevo.programs.stages.common import ListOf
from gigaevo.programs.stages.insights_lineage import (
    AncestralTransitionPath,
    LineageAnalysesOutput,
    LineagesFromAncestors,
    LineagesToDescendants,
)
from gigaevo.programs.stages.insights import InsightsStage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(*, higher_is_better: bool = True) -> MetricsContext:
    return MetricsContext(
        specs={
            "score": MetricSpec(
                description="main score",
                is_primary=True,
                higher_is_better=higher_is_better,
                lower_bound=0.0,
                upper_bound=100.0,
            )
        }
    )


def _prog(score: float = 50.0) -> Program:
    program = Program(code="def solve(): return 42", state=ProgramState.RUNNING)
    program.add_metrics({"score": score})
    return program


def _make_insights() -> TransitionInsights:
    return TransitionInsights(
        insights=[
            TransitionInsight(strategy="imitation", description="Copied pattern"),
            TransitionInsight(strategy="avoidance", description="Avoided pitfall"),
            TransitionInsight(strategy="exploration", description="New approach"),
        ]
    )


def test_transition_insights_accepts_legacy_bare_list():
    insights = TransitionInsights.model_validate(
        [
            {"strategy": "refinement", "description": "Tuned a threshold."},
            {"strategy": "avoidance", "description": "Avoided a fragile branch."},
            {"strategy": "exploration", "description": "Tried a new controller."},
        ]
    )

    assert [item.strategy for item in insights.insights] == [
        "refinement",
        "avoidance",
        "exploration",
    ]


async def test_insights_stage_exhaustion_writes_partial_metadata(monkeypatch):
    agent = AsyncMock()
    agent.arun.side_effect = ValueError("bad insights output")
    monkeypatch.setattr(
        "gigaevo.programs.stages.insights.create_insights_agent",
        lambda *args, **kwargs: agent,
    )

    stage = InsightsStage(
        llm=object(),
        task_description="task",
        metrics_context=_ctx(),
        timeout=5.0,
        max_attempts=2,
        retry_backoff_seconds=0.0,
    )
    stage.__class__.cache_handler = NO_CACHE
    stage.attach_inputs({})
    program = _prog()

    result = await stage.execute(program)

    assert result.status == StageState.COMPLETED
    assert result.output.insights == ProgramInsights(insights=[])
    assert agent.arun.await_count == 2
    assert program.metadata["interpretation_status"] == "partial"
    assert program.metadata["interpretation_partial_stages"] == ["InsightsStage"]
    assert program.metadata["interpretation"]["InsightsStage"]["status"] == "partial"


def _make_analysis(from_id: str, to_id: str) -> TransitionAnalysis:
    return TransitionAnalysis(
        from_id=from_id,
        to_id=to_id,
        parent_metrics={"score": 50.0},
        child_metrics={"score": 70.0},
        diff_blocks=["+ new line"],
        insights=_make_insights(),
    )


# ---------------------------------------------------------------------------
# TestLineagesToDescendants
# ---------------------------------------------------------------------------


class TestLineagesToDescendants:
    async def test_empty_child_ids_returns_skipped(self):
        """Empty descendant_ids → SKIPPED."""
        storage = AsyncMock()
        stage = LineagesToDescendants(
            storage=storage,
            source_stage_name="lineage_analysis",
            timeout=5.0,
        )
        stage.__class__.cache_handler = NO_CACHE
        stage.attach_inputs({"descendant_ids": ListOf[str](items=[])})
        result = await stage.execute(_prog())

        assert result.status == StageState.SKIPPED

    async def test_no_matching_analyses_returns_empty(self):
        """Children exist but have no result for source_stage_name → empty list."""
        storage = AsyncMock()
        child = _prog()
        child.stage_results = {}  # no results at all
        storage.mget.return_value = [child]

        stage = LineagesToDescendants(
            storage=storage,
            source_stage_name="lineage_analysis",
            timeout=5.0,
        )
        stage.__class__.cache_handler = NO_CACHE

        parent = _prog()
        stage.attach_inputs({"descendant_ids": ListOf[str](items=[child.id])})
        result = await stage.execute(parent)

        assert result.status == StageState.COMPLETED
        assert result.output.items == []

    async def test_correct_analysis_extracted(self):
        """Child has analysis for this parent → correct TransitionAnalysis returned."""
        storage = AsyncMock()
        parent = _prog()
        child = _prog()

        # Child has a LineageAnalysesOutput with analyses for parent→child
        analysis = _make_analysis(from_id=parent.id, to_id=child.id)
        # Also has an unrelated analysis from another parent
        other_analysis = _make_analysis(from_id="other-parent", to_id=child.id)
        output = LineageAnalysesOutput(analyses=[other_analysis, analysis])

        child.stage_results["lineage_analysis"] = ProgramStageResult.success(
            output=output
        )
        storage.mget.return_value = [child]

        stage = LineagesToDescendants(
            storage=storage,
            source_stage_name="lineage_analysis",
            timeout=5.0,
        )
        stage.__class__.cache_handler = NO_CACHE
        stage.attach_inputs({"descendant_ids": ListOf[str](items=[child.id])})
        result = await stage.execute(parent)

        assert result.status == StageState.COMPLETED
        assert len(result.output.items) == 1
        assert result.output.items[0].from_id == parent.id
        assert result.output.items[0].to_id == child.id

    async def test_no_analysis_for_this_parent(self):
        """Child has analyses but not for this parent → empty list."""
        storage = AsyncMock()
        parent = _prog()
        child = _prog()

        other_analysis = _make_analysis(from_id="other-parent", to_id=child.id)
        output = LineageAnalysesOutput(analyses=[other_analysis])
        child.stage_results["lineage_analysis"] = ProgramStageResult.success(
            output=output
        )
        storage.mget.return_value = [child]

        stage = LineagesToDescendants(
            storage=storage,
            source_stage_name="lineage_analysis",
            timeout=5.0,
        )
        stage.__class__.cache_handler = NO_CACHE
        stage.attach_inputs({"descendant_ids": ListOf[str](items=[child.id])})
        result = await stage.execute(parent)

        assert result.status == StageState.COMPLETED
        assert result.output.items == []

    async def test_child_with_null_output_skipped(self):
        """Child has result but output is None → skipped in iteration."""
        storage = AsyncMock()
        parent = _prog()
        child = _prog()
        child.stage_results["lineage_analysis"] = ProgramStageResult.success(
            output=None
        )
        storage.mget.return_value = [child]

        stage = LineagesToDescendants(
            storage=storage,
            source_stage_name="lineage_analysis",
            timeout=5.0,
        )
        stage.__class__.cache_handler = NO_CACHE
        stage.attach_inputs({"descendant_ids": ListOf[str](items=[child.id])})
        result = await stage.execute(parent)

        assert result.status == StageState.COMPLETED
        assert result.output.items == []


# ---------------------------------------------------------------------------
# TestLineagesFromAncestors
# ---------------------------------------------------------------------------


class TestLineagesFromAncestors:
    async def test_empty_parent_ids_returns_skipped(self):
        """Empty ancestor_ids → SKIPPED."""
        storage = AsyncMock()
        stage = LineagesFromAncestors(
            storage=storage,
            source_stage_name="lineage_analysis",
            timeout=5.0,
        )
        stage.__class__.cache_handler = NO_CACHE
        stage.attach_inputs({"ancestor_ids": ListOf[str](items=[])})
        result = await stage.execute(_prog())

        assert result.status == StageState.SKIPPED

    async def test_no_source_result_returns_skipped(self):
        """Current program has no result for source_stage_name → SKIPPED."""
        storage = AsyncMock()
        prog = _prog()
        prog.stage_results = {}

        stage = LineagesFromAncestors(
            storage=storage,
            source_stage_name="lineage_analysis",
            timeout=5.0,
        )
        stage.__class__.cache_handler = NO_CACHE
        stage.attach_inputs({"ancestor_ids": ListOf[str](items=["parent1"])})
        result = await stage.execute(prog)

        assert result.status == StageState.SKIPPED

    async def test_correct_analysis_filtered(self):
        """Program has analyses from multiple parents → only matching ones returned."""
        storage = AsyncMock()
        prog = _prog()

        parent1_id = "parent-1"
        parent2_id = "parent-2"
        unrelated_id = "other-parent"

        a1 = _make_analysis(from_id=parent1_id, to_id=prog.id)
        a2 = _make_analysis(from_id=parent2_id, to_id=prog.id)
        a_other = _make_analysis(from_id=unrelated_id, to_id=prog.id)

        output = LineageAnalysesOutput(analyses=[a1, a2, a_other])
        prog.stage_results["lineage_analysis"] = ProgramStageResult.success(
            output=output
        )

        stage = LineagesFromAncestors(
            storage=storage,
            source_stage_name="lineage_analysis",
            timeout=5.0,
        )
        stage.__class__.cache_handler = NO_CACHE
        # Only request parent1 and parent2, not unrelated
        stage.attach_inputs(
            {"ancestor_ids": ListOf[str](items=[parent1_id, parent2_id])}
        )
        result = await stage.execute(prog)

        assert result.status == StageState.COMPLETED
        assert len(result.output.items) == 2
        from_ids = {a.from_id for a in result.output.items}
        assert from_ids == {parent1_id, parent2_id}

    async def test_no_matching_ancestor_returns_empty(self):
        """Program has analyses from other parents, not the requested one → empty list."""
        storage = AsyncMock()
        prog = _prog()

        a_other = _make_analysis(from_id="unrelated-parent", to_id=prog.id)
        output = LineageAnalysesOutput(analyses=[a_other])
        prog.stage_results["lineage_analysis"] = ProgramStageResult.success(
            output=output
        )

        stage = LineagesFromAncestors(
            storage=storage,
            source_stage_name="lineage_analysis",
            timeout=5.0,
        )
        stage.__class__.cache_handler = NO_CACHE
        stage.attach_inputs({"ancestor_ids": ListOf[str](items=["requested-parent"])})
        result = await stage.execute(prog)

        assert result.status == StageState.COMPLETED
        assert result.output.items == []

    async def test_null_output_returns_skipped(self):
        """Source stage result has None output → SKIPPED."""
        storage = AsyncMock()
        prog = _prog()
        prog.stage_results["lineage_analysis"] = ProgramStageResult.success(output=None)

        stage = LineagesFromAncestors(
            storage=storage,
            source_stage_name="lineage_analysis",
            timeout=5.0,
        )
        stage.__class__.cache_handler = NO_CACHE
        stage.attach_inputs({"ancestor_ids": ListOf[str](items=["parent1"])})
        result = await stage.execute(prog)

        assert result.status == StageState.SKIPPED


# ---------------------------------------------------------------------------
# TestAncestralTransitionPath
# ---------------------------------------------------------------------------


def _link(parent: Program, child: Program, stage_name: str = "lineage_analysis") -> None:
    child.lineage.parents = [parent.id]
    child.lineage.generation = parent.lineage.generation + 1
    parent.lineage.add_child(child.id)
    analysis = _make_analysis(from_id=parent.id, to_id=child.id)
    child.stage_results[stage_name] = ProgramStageResult.success(
        output=LineageAnalysesOutput(analyses=[analysis])
    )


def _storage_for(programs: list[Program]) -> AsyncMock:
    by_id = {program.id: program for program in programs}
    storage = AsyncMock()
    storage.mget.side_effect = lambda ids: [by_id[pid] for pid in ids if pid in by_id]
    return storage


class TestAncestralTransitionPath:
    async def test_linear_path_returns_chronological_transitions(self):
        """p1 -> p2 -> p3 -> p4 -> p5 excludes the immediate p4 -> p5 edge."""
        p1, p2, p3, p4, p5 = [_prog(score=float(i)) for i in range(1, 6)]
        _link(p1, p2)
        _link(p2, p3)
        _link(p3, p4)
        _link(p4, p5)

        stage = AncestralTransitionPath(
            storage=_storage_for([p1, p2, p3, p4]),
            metrics_context=_ctx(),
            source_stage_name="lineage_analysis",
            max_transitions=4,
            timeout=5.0,
        )
        stage.attach_inputs({})
        result = await stage.execute(p5)

        assert result.status == StageState.COMPLETED
        assert [(a.from_id, a.to_id) for a in result.output.items] == [
            (p1.id, p2.id),
            (p2.id, p3.id),
            (p3.id, p4.id),
        ]

    async def test_max_transitions_keeps_recent_window_chronological(self):
        """Bounded path keeps latest N non-immediate transitions, oldest -> newest."""
        p1, p2, p3, p4, p5, p6 = [_prog(score=float(i)) for i in range(1, 7)]
        _link(p1, p2)
        _link(p2, p3)
        _link(p3, p4)
        _link(p4, p5)
        _link(p5, p6)

        stage = AncestralTransitionPath(
            storage=_storage_for([p1, p2, p3, p4, p5]),
            metrics_context=_ctx(),
            source_stage_name="lineage_analysis",
            max_transitions=3,
            timeout=5.0,
        )
        stage.attach_inputs({})
        result = await stage.execute(p6)

        assert [(a.from_id, a.to_id) for a in result.output.items] == [
            (p2.id, p3.id),
            (p3.id, p4.id),
            (p4.id, p5.id),
        ]

    async def test_missing_lineage_stage_skips_only_that_transition(self):
        """Missing stored analysis is non-fatal and does not stop walking the path."""
        p1, p2, p3, p4, p5 = [_prog(score=float(i)) for i in range(1, 6)]
        _link(p1, p2)
        _link(p2, p3)
        _link(p3, p4)
        _link(p4, p5)
        p3.stage_results = {}

        stage = AncestralTransitionPath(
            storage=_storage_for([p1, p2, p3, p4]),
            metrics_context=_ctx(),
            source_stage_name="lineage_analysis",
            max_transitions=4,
            timeout=5.0,
        )
        stage.attach_inputs({})
        result = await stage.execute(p5)

        assert [(a.from_id, a.to_id) for a in result.output.items] == [
            (p1.id, p2.id),
            (p3.id, p4.id),
        ]

    async def test_branching_ranks_parent_branches_higher_is_better(self):
        low_root = _prog(score=1.0)
        high_root = _prog(score=2.0)
        low = _prog(score=10.0)
        high = _prog(score=20.0)
        child = _prog(score=30.0)
        _link(low_root, low)
        _link(high_root, high)
        child.lineage.parents = [low.id, high.id]
        child.lineage.generation = max(
            low.lineage.generation, high.lineage.generation
        ) + 1
        child.stage_results["lineage_analysis"] = ProgramStageResult.success(
            output=LineageAnalysesOutput(
                analyses=[
                    _make_analysis(from_id=low.id, to_id=child.id),
                    _make_analysis(from_id=high.id, to_id=child.id),
                ]
            )
        )

        stage = AncestralTransitionPath(
            storage=_storage_for([low_root, high_root, low, high]),
            metrics_context=_ctx(higher_is_better=True),
            source_stage_name="lineage_analysis",
            timeout=5.0,
        )
        stage.attach_inputs({})
        result = await stage.execute(child)

        assert [(a.from_id, a.to_id) for a in result.output.items] == [
            (high_root.id, high.id),
            (low_root.id, low.id),
        ]

    async def test_branching_ranks_parent_branches_lower_is_better(self):
        low_root = _prog(score=1.0)
        high_root = _prog(score=2.0)
        low = _prog(score=10.0)
        high = _prog(score=20.0)
        child = _prog(score=30.0)
        _link(low_root, low)
        _link(high_root, high)
        child.lineage.parents = [high.id, low.id]
        child.lineage.generation = max(
            low.lineage.generation, high.lineage.generation
        ) + 1
        child.stage_results["lineage_analysis"] = ProgramStageResult.success(
            output=LineageAnalysesOutput(
                analyses=[
                    _make_analysis(from_id=high.id, to_id=child.id),
                    _make_analysis(from_id=low.id, to_id=child.id),
                ]
            )
        )

        stage = AncestralTransitionPath(
            storage=_storage_for([high_root, low_root, high, low]),
            metrics_context=_ctx(higher_is_better=False),
            source_stage_name="lineage_analysis",
            timeout=5.0,
        )
        stage.attach_inputs({})
        result = await stage.execute(child)

        assert [(a.from_id, a.to_id) for a in result.output.items] == [
            (low_root.id, low.id),
            (high_root.id, high.id),
        ]

    async def test_only_immediate_parent_returns_skipped(self):
        """The duplicate immediate parent->current edge is left to Parents."""
        parent = _prog(score=10.0)
        child = _prog(score=20.0)
        _link(parent, child)

        stage = AncestralTransitionPath(
            storage=_storage_for([parent]),
            metrics_context=_ctx(),
            source_stage_name="lineage_analysis",
            timeout=5.0,
        )
        stage.attach_inputs({})
        result = await stage.execute(child)

        assert result.status == StageState.SKIPPED

    async def test_root_program_returns_skipped(self):
        stage = AncestralTransitionPath(
            storage=AsyncMock(),
            metrics_context=_ctx(),
            source_stage_name="lineage_analysis",
            timeout=5.0,
        )
        stage.attach_inputs({})
        result = await stage.execute(_prog())

        assert result.status == StageState.SKIPPED
