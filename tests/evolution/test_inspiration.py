from __future__ import annotations

from gigaevo.evolution.mutation.base import MutationSpec
from gigaevo.evolution.mutation.inspiration import build_inspiration_prompt_context
from gigaevo.llm.agents.lineage import (
    TransitionAnalysis,
    TransitionInsight,
    TransitionInsights,
)
from gigaevo.programs.core_types import ProgramStageResult
from gigaevo.programs.metrics.context import MetricsContext, MetricSpec
from gigaevo.programs.program import Program
from gigaevo.programs.stages.insights_lineage import LineageAnalysesOutput


def _metrics_context(*, higher_is_better: bool = True) -> MetricsContext:
    return MetricsContext(
        specs={
            "fitness": MetricSpec(
                description="Fitness",
                is_primary=True,
                higher_is_better=higher_is_better,
            ),
            "mean_rel_energy": MetricSpec(
                description="Energy",
                higher_is_better=True,
            ),
        }
    )


def _analysis(parent: Program, child: Program, *, parent_f: float, child_f: float):
    return TransitionAnalysis(
        from_id=parent.id,
        to_id=child.id,
        parent_metrics={"fitness": parent_f, "mean_rel_energy": 1.0},
        child_metrics={"fitness": child_f, "mean_rel_energy": 1.01},
        diff_blocks=["@@ -1 +1 @@\n-return 1\n+return 2"],
        insights=TransitionInsights(
            insights=[
                TransitionInsight(
                    strategy="refinement",
                    description="Relaxed a narrow bound and improved the primary metric.",
                ),
                TransitionInsight(
                    strategy="exploration",
                    description="Introduced a donor search pattern worth adapting.",
                ),
                TransitionInsight(
                    strategy="imitation",
                    description="Preserved the robust fallback path.",
                ),
            ]
        ),
    )


def test_builds_card_from_successful_transition() -> None:
    parent = Program(code="def solve(): return 1")
    child = Program(code="def solve(): return 2")
    child.stage_results["LineageStage"] = ProgramStageResult.success(
        output=LineageAnalysesOutput(
            analyses=[_analysis(parent, child, parent_f=1.0, child_f=2.0)]
        )
    )
    child.metadata[MutationSpec.META_OUTPUT] = {
        "archetype": "Guided Innovation",
        "insights_used": ["useful insight"],
        "changes": [
            {
                "description": "Relaxed a restrictive bound",
                "explanation": "The wider search recovered better candidates.",
            }
        ],
    }

    context = build_inspiration_prompt_context(
        [child], metrics_context=_metrics_context(), max_diff_hunks_per_card=1
    )

    assert context.num_cards == 1
    assert context.program_ids == [child.id]
    assert context.transition_ids == [f"{parent.id}->{child.id}"]
    assert "### Inspiration Transition IT-1" in context.text
    assert "Guided Innovation" in context.text
    assert "Donor diff hunk 1" in context.text


def test_skips_missing_or_regressing_lineage() -> None:
    parent = Program(code="def solve(): return 1")
    child = Program(code="def solve(): return 2")
    child.stage_results["LineageStage"] = ProgramStageResult.success(
        output=LineageAnalysesOutput(
            analyses=[_analysis(parent, child, parent_f=2.0, child_f=1.0)]
        )
    )
    missing = Program(code="def solve(): return 3")

    context = build_inspiration_prompt_context(
        [child, missing], metrics_context=_metrics_context()
    )

    assert context.num_cards == 0
    assert context.text == ""
