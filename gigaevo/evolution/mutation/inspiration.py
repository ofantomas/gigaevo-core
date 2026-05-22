from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
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
class _TransitionSelection:
    analysis: Any | None
    reason: str
    improvement: float | None = None
    skip_counts: Counter[str] | None = None


def build_inspiration_prompt_context(
    programs: list[Program],
    *,
    metrics_context: MetricsContext,
    max_diff_hunks_per_card: int = 3,
    max_card_chars: int = 4000,
    source_stage_name: str = "LineageStage",
) -> InspirationPromptContext:
    """Format successful donor parent->child transitions for diff mutation prompts.

    A donor program contributes at most one card: its best successful transition
    according to the primary metric. Programs without lineage output or without
    a parent-relative improvement are skipped.
    """
    if not programs:
        return _EMPTY_CONTEXT

    formatter = MetricsFormatter(metrics_context)
    cards: list[str] = []
    program_ids: list[str] = []
    transition_ids: list[str] = []
    selected_improvements: list[float] = []
    skip_counts: Counter[str] = Counter()

    for program in programs:
        selection = _select_best_successful_transition_details(
            program, metrics_context, source_stage_name
        )
        analysis = selection.analysis
        if analysis is None:
            skip_counts[selection.reason] += 1
            if selection.skip_counts:
                skip_counts.update(
                    {
                        f"analysis_{reason}": count
                        for reason, count in selection.skip_counts.items()
                    }
                )
            continue

        label = f"IT-{len(cards) + 1}"
        card = _format_transition_card(
            label,
            program,
            analysis,
            metrics_formatter=formatter,
            max_diff_hunks_per_card=max_diff_hunks_per_card,
            max_card_chars=max_card_chars,
        )
        cards.append(card)

        from_id = str(_get(analysis, "from_id", _get(analysis, "from", "")))
        to_id = str(_get(analysis, "to_id", _get(analysis, "to", program.id)))
        program_ids.append(to_id)
        transition_ids.append(f"{from_id}->{to_id}")
        if selection.improvement is not None:
            selected_improvements.append(selection.improvement)

    logger.debug(
        "[inspiration] Rendered {} card(s) from {} donor(s) "
        "(primary_metric={}, higher_is_better={}); transitions={}; "
        "improvements={}; skipped={}",
        len(cards),
        len(programs),
        metrics_context.get_primary_key(),
        metrics_context.is_higher_better(metrics_context.get_primary_key()),
        transition_ids,
        selected_improvements,
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


def _select_best_successful_transition(
    program: Program, metrics_context: MetricsContext, source_stage_name: str
) -> Any | None:
    return _select_best_successful_transition_details(
        program, metrics_context, source_stage_name
    ).analysis


def _select_best_successful_transition_details(
    program: Program, metrics_context: MetricsContext, source_stage_name: str
) -> _TransitionSelection:
    analyses = _lineage_analyses(program, source_stage_name)
    if not analyses:
        return _TransitionSelection(
            analysis=None,
            reason="no_lineage_output",
            skip_counts=Counter(),
        )

    primary_key = metrics_context.get_primary_key()
    higher_is_better = metrics_context.is_higher_better(primary_key)
    successful: list[tuple[float, Any]] = []
    skip_counts: Counter[str] = Counter()

    for analysis in analyses:
        parent_metrics = _get(analysis, "parent_metrics", {}) or {}
        child_metrics = _get(analysis, "child_metrics", {}) or {}
        if primary_key not in parent_metrics or primary_key not in child_metrics:
            skip_counts["missing_primary_metric"] += 1
            continue

        parent_value = float(parent_metrics[primary_key])
        child_value = float(child_metrics[primary_key])
        delta = child_value - parent_value
        if delta == 0:
            skip_counts["equal_primary_metric"] += 1
            continue
        if (delta > 0) != higher_is_better:
            skip_counts["worse_primary_metric"] += 1
            continue

        improvement = delta if higher_is_better else -delta
        successful.append((improvement, analysis))

    if not successful:
        reason = "no_improving_primary_metric"
        if skip_counts:
            reason = skip_counts.most_common(1)[0][0]
        return _TransitionSelection(
            analysis=None,
            reason=reason,
            skip_counts=skip_counts,
        )

    improvement, analysis = max(successful, key=lambda item: item[0])
    return _TransitionSelection(
        analysis=analysis,
        reason="selected",
        improvement=improvement,
        skip_counts=skip_counts,
    )


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
