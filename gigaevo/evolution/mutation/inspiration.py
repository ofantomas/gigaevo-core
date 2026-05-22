from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from typing import Any

from loguru import logger
from pydantic import BaseModel

from gigaevo.evolution.mutation.base import MutationSpec
from gigaevo.programs.metrics.context import MetricsContext
from gigaevo.programs.metrics.formatter import MetricsFormatter
from gigaevo.programs.program import Program


@dataclass(frozen=True)
class InspirationPromptContext:
    """Rendered inspiration cards plus trace metadata."""

    text: str
    program_ids: list[str]
    transition_ids: list[str]
    num_cards: int


_EMPTY_CONTEXT = InspirationPromptContext(
    text="", program_ids=[], transition_ids=[], num_cards=0
)


@dataclass(frozen=True)
class _TransitionCandidate:
    analysis: Any
    primary_effect: float
    outcome: str


def build_inspiration_prompt_context(
    programs: list[Program],
    *,
    metrics_context: MetricsContext,
    max_diff_hunks_per_card: int = 3,
    max_card_chars: int = 4000,
    source_stage_name: str = "LineageStage",
    max_transitions_per_donor: int = 3,
) -> InspirationPromptContext:
    """Format donor parent->child transitions for diff mutation prompts.

    A donor program contributes up to ``max_transitions_per_donor`` cards.
    Both improving and regressing nonzero primary-metric transitions are useful:
    improvements suggest mechanisms to adapt, regressions provide counterexamples.
    """
    if not programs or max_transitions_per_donor <= 0:
        return _EMPTY_CONTEXT

    formatter = MetricsFormatter(metrics_context)
    cards: list[str] = []
    program_ids: list[str] = []
    transition_ids: list[str] = []
    selected_effects: list[float] = []
    selected_outcomes: list[str] = []
    skip_counts: Counter[str] = Counter()

    for program in programs:
        candidates, donor_skip_counts = _collect_usable_transition_details(
            program, metrics_context, source_stage_name
        )
        if donor_skip_counts:
            skip_counts.update(
                {
                    f"analysis_{reason}": count
                    for reason, count in donor_skip_counts.items()
                }
            )
        if not candidates:
            continue

        for candidate in candidates[:max_transitions_per_donor]:
            analysis = candidate.analysis
            label = f"IT-{len(cards) + 1}"
            card = _format_transition_card(
                label,
                program,
                analysis,
                outcome=candidate.outcome,
                primary_effect=candidate.primary_effect,
                metrics_formatter=formatter,
                max_diff_hunks_per_card=max_diff_hunks_per_card,
                max_card_chars=max_card_chars,
            )
            cards.append(card)

            from_id = str(_get(analysis, "from_id", _get(analysis, "from", "")))
            to_id = str(_get(analysis, "to_id", _get(analysis, "to", program.id)))
            program_ids.append(to_id)
            transition_ids.append(f"{from_id}->{to_id}")
            selected_effects.append(candidate.primary_effect)
            selected_outcomes.append(candidate.outcome)

    logger.debug(
        "[inspiration] Rendered {} card(s) from {} donor(s) "
        "(primary_metric={}, higher_is_better={}); transitions={}; "
        "primary_effects={}; outcomes={}; skipped={}",
        len(cards),
        len(programs),
        metrics_context.get_primary_key(),
        metrics_context.is_higher_better(metrics_context.get_primary_key()),
        transition_ids,
        selected_effects,
        selected_outcomes,
        dict(skip_counts),
    )

    if not cards:
        return _EMPTY_CONTEXT

    text = "## Inspiration Transitions\n\n" + "\n\n".join(cards)
    return InspirationPromptContext(
        text=text,
        program_ids=program_ids,
        transition_ids=transition_ids,
        num_cards=len(cards),
    )


def _collect_usable_transition_details(
    program: Program, metrics_context: MetricsContext, source_stage_name: str
) -> tuple[list[_TransitionCandidate], Counter[str]]:
    analyses = _lineage_analyses(program, source_stage_name)
    skip_counts: Counter[str] = Counter()
    if not analyses:
        skip_counts["no_lineage_output"] += 1
        return [], skip_counts

    primary_key = metrics_context.get_primary_key()
    higher_is_better = metrics_context.is_higher_better(primary_key)
    candidates: list[_TransitionCandidate] = []

    for analysis in analyses:
        primary_effect, reason = _directional_primary_effect(
            analysis, primary_key, higher_is_better
        )
        if reason is not None:
            skip_counts[reason] += 1
            continue
        assert primary_effect is not None
        outcome = "improvement" if primary_effect > 0 else "regression"
        candidates.append(
            _TransitionCandidate(
                analysis=analysis,
                primary_effect=primary_effect,
                outcome=outcome,
            )
        )

    candidates.sort(key=lambda candidate: candidate.primary_effect)
    return candidates, skip_counts


def _directional_primary_effect(
    analysis: Any, primary_key: str, higher_is_better: bool
) -> tuple[float | None, str | None]:
    parent_metrics = _get(analysis, "parent_metrics", {}) or {}
    child_metrics = _get(analysis, "child_metrics", {}) or {}
    if primary_key not in parent_metrics or primary_key not in child_metrics:
        return None, "missing_primary_metric"

    try:
        parent_value = float(parent_metrics[primary_key])
        child_value = float(child_metrics[primary_key])
    except (TypeError, ValueError):
        return None, "non_numeric_primary_metric"

    if not math.isfinite(parent_value) or not math.isfinite(child_value):
        return None, "non_finite_primary_metric"

    delta = child_value - parent_value
    primary_effect = delta if higher_is_better else -delta
    if primary_effect == 0:
        return None, "equal_primary_metric"
    return primary_effect, None


def _lineage_analyses(program: Program, source_stage_name: str) -> list[Any]:
    result = program.stage_results.get(source_stage_name)
    if result is None or result.output is None:
        return []

    output = result.output
    analyses = _get(output, "analyses", None)
    if analyses is None:
        return []
    return list(analyses)


def _format_transition_card(
    label: str,
    program: Program,
    analysis: Any,
    *,
    outcome: str,
    primary_effect: float,
    metrics_formatter: MetricsFormatter,
    max_diff_hunks_per_card: int,
    max_card_chars: int,
) -> str:
    from_id = str(_get(analysis, "from_id", _get(analysis, "from", "")))
    to_id = str(_get(analysis, "to_id", _get(analysis, "to", program.id)))
    parent_metrics = _get(analysis, "parent_metrics", {}) or {}
    child_metrics = _get(analysis, "child_metrics", {}) or {}

    lines = [
        f"### Inspiration Transition {label}",
        f"Transition: parent {from_id[:8]} -> child {to_id[:8]}",
        f"Full IDs: parent={from_id}, child={to_id}",
        f"Outcome: {outcome} (direction-aware primary effect: {primary_effect:+.6g})",
        "",
        "Measured transition metrics:",
        metrics_formatter.format_delta_block(
            parent=parent_metrics, child=child_metrics, include_primary=True
        ),
    ]

    mutation_output = _format_mutation_output(program)
    if mutation_output:
        lines.extend(["", "Mutation output from donor child:", mutation_output])

    lineage = _format_lineage_insights(analysis)
    if lineage:
        lines.extend(["", "Lineage interpretation:", lineage])

    diff_hunks = _format_diff_hunks(analysis, max_diff_hunks_per_card)
    if diff_hunks:
        lines.extend(
            [
                "",
                "Diff hunks from donor transition (historical evidence only):",
                diff_hunks,
            ]
        )

    return _truncate("\n".join(lines), max_card_chars)


def _format_mutation_output(program: Program) -> str:
    output = program.metadata.get(MutationSpec.META_OUTPUT)
    if output is None:
        return ""
    data = _as_dict(output)
    if not data:
        return _truncate(str(output), 1200)

    lines: list[str] = []
    archetype = data.get("archetype")
    if archetype:
        lines.append(f"- archetype: {archetype}")

    insights_used = data.get("insights_used") or []
    if insights_used:
        lines.append("- insights_used:")
        lines.extend(f"  - {_one_line(item)}" for item in insights_used[:3])

    changes = data.get("changes") or []
    if changes:
        lines.append("- changes:")
        for change in changes[:5]:
            change_data = _as_dict(change)
            if change_data:
                desc = _one_line(change_data.get("description", ""))
                explanation = _one_line(change_data.get("explanation", ""))
                if desc and explanation:
                    lines.append(f"  - {desc} - {explanation}")
                elif desc:
                    lines.append(f"  - {desc}")
            else:
                lines.append(f"  - {_one_line(change)}")

    return "\n".join(lines)


def _format_lineage_insights(analysis: Any) -> str:
    insights_obj = _get(analysis, "insights", None)
    insights = _get(insights_obj, "insights", None)
    if not insights:
        return ""

    lines: list[str] = []
    for insight in insights:
        strategy = _get(insight, "strategy", "unknown")
        desc = _get(insight, "description", "")
        lines.append(f"- [{strategy}] {_one_line(desc)}")
    return "\n".join(lines)


def _format_diff_hunks(analysis: Any, max_diff_hunks_per_card: int) -> str:
    diff_blocks = list(_get(analysis, "diff_blocks", []) or [])
    if not diff_blocks:
        return ""

    lines: list[str] = []
    for i, block in enumerate(diff_blocks[:max_diff_hunks_per_card], start=1):
        lines.append(f"--- Donor diff hunk {i} ---")
        lines.append("```diff")
        lines.append(str(block).strip())
        lines.append("```")
    if len(diff_blocks) > max_diff_hunks_per_card:
        omitted = len(diff_blocks) - max_diff_hunks_per_card
        lines.append(f"... {omitted} more donor hunk(s) omitted")
    return "\n".join(lines)


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump()
    return {}


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _one_line(value: Any, max_len: int = 500) -> str:
    text = " ".join(str(value).split())
    return _truncate(text, max_len)


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    suffix = "\n... [truncated]"
    return text[: max(0, max_chars - len(suffix))].rstrip() + suffix
