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


def _attach_lineage(program: Program, analyses: list[object]) -> None:
    program.stage_results["LineageStage"] = ProgramStageResult.success(
        output={"analyses": analyses}
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
    assert "Outcome: improvement" in context.text
    assert "Guided Innovation" in context.text
    assert "Donor diff hunk 1" in context.text


def test_renders_regressing_lineage_and_skips_missing_lineage() -> None:
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

    assert context.num_cards == 1
    assert context.program_ids == [child.id]
    assert context.transition_ids == [f"{parent.id}->{child.id}"]
    assert "Outcome: regression" in context.text


def test_lower_is_better_labels_improvement_and_regression() -> None:
    parent = Program(code="def solve(): return 1")
    child = Program(code="def solve(): return 2")
    worse_parent = Program(code="def solve(): return 3")

    _attach_lineage(
        child,
        [
            _analysis(parent, child, parent_f=2.0, child_f=1.0),
            _analysis(worse_parent, child, parent_f=1.0, child_f=2.0),
        ],
    )

    context = build_inspiration_prompt_context(
        [child], metrics_context=_metrics_context(higher_is_better=False)
    )

    assert context.num_cards == 2
    assert context.text.count("Outcome: improvement") == 1
    assert context.text.count("Outcome: regression") == 1


def test_renders_at_most_three_transitions_per_donor_sorted_by_effect() -> None:
    child = Program(code="def solve(): return 2")
    parents = [Program(code=f"def solve(): return {i}") for i in range(4)]
    _attach_lineage(
        child,
        [
            _analysis(parents[0], child, parent_f=10.0, child_f=5.0),
            _analysis(parents[1], child, parent_f=6.0, child_f=5.0),
            _analysis(parents[2], child, parent_f=3.0, child_f=5.0),
            _analysis(parents[3], child, parent_f=1.0, child_f=5.0),
        ],
    )

    context = build_inspiration_prompt_context(
        [child], metrics_context=_metrics_context()
    )

    assert context.num_cards == 3
    assert context.transition_ids == [
        f"{parents[0].id}->{child.id}",
        f"{parents[1].id}->{child.id}",
        f"{parents[2].id}->{child.id}",
    ]
    assert context.text.count("Outcome: regression") == 2
    assert context.text.count("Outcome: improvement") == 1


def test_skips_missing_non_finite_and_zero_primary_metric_changes() -> None:
    child = Program(code="def solve(): return 2")
    valid_parent = Program(code="def solve(): return 1")
    zero_parent = Program(code="def solve(): return 0")
    missing_parent = Program(code="def solve(): return 3")
    non_finite_parent = Program(code="def solve(): return 4")
    bad_parent = Program(code="def solve(): return 5")

    _attach_lineage(
        child,
        [
            _analysis(valid_parent, child, parent_f=1.0, child_f=2.0),
            _analysis(zero_parent, child, parent_f=2.0, child_f=2.0),
            {
                "from_id": missing_parent.id,
                "to_id": child.id,
                "parent_metrics": {"mean_rel_energy": 1.0},
                "child_metrics": {"fitness": 3.0, "mean_rel_energy": 1.0},
                "diff_blocks": [],
                "insights": {"insights": []},
            },
            {
                "from_id": non_finite_parent.id,
                "to_id": child.id,
                "parent_metrics": {"fitness": float("nan"), "mean_rel_energy": 1.0},
                "child_metrics": {"fitness": 3.0, "mean_rel_energy": 1.0},
                "diff_blocks": [],
                "insights": {"insights": []},
            },
            {
                "from_id": bad_parent.id,
                "to_id": child.id,
                "parent_metrics": {
                    "fitness": "not-a-number",
                    "mean_rel_energy": 1.0,
                },
                "child_metrics": {"fitness": 3.0, "mean_rel_energy": 1.0},
                "diff_blocks": [],
                "insights": {"insights": []},
            },
        ],
    )

    context = build_inspiration_prompt_context(
        [child], metrics_context=_metrics_context()
    )

    assert context.num_cards == 1
    assert context.transition_ids == [f"{valid_parent.id}->{child.id}"]
    assert "Outcome: improvement" in context.text
