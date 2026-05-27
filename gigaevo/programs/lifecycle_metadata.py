from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from gigaevo.programs.program import Program


INTERPRETATION_METADATA_KEY = "interpretation"
INTERPRETATION_STATUS_KEY = "interpretation_status"
INTERPRETATION_PARTIAL_STAGES_KEY = "interpretation_partial_stages"
INTERPRETATION_UPDATED_AT_KEY = "interpretation_updated_at"

DISCARD_METADATA_KEY = "discard"
DISCARD_REASON_KEY = "discard_reason"
DISCARDED_AT_KEY = "discarded_at"


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def mark_interpretation_partial(
    program: Program,
    *,
    stage_name: str,
    attempts: int,
    exc: BaseException,
) -> None:
    """Record that an optional interpretation stage exhausted its retry budget."""
    updated_at = _utcnow_iso()
    interpretation = program.metadata.get(INTERPRETATION_METADATA_KEY)
    if not isinstance(interpretation, dict):
        interpretation = {}

    interpretation[stage_name] = {
        "status": "partial",
        "attempts": attempts,
        "error_type": type(exc).__name__,
        "error": str(exc)[:500],
        "updated_at": updated_at,
    }
    program.metadata[INTERPRETATION_METADATA_KEY] = interpretation

    partial_stages = program.metadata.get(INTERPRETATION_PARTIAL_STAGES_KEY)
    if not isinstance(partial_stages, list):
        partial_stages = []
    if stage_name not in partial_stages:
        partial_stages.append(stage_name)

    program.metadata[INTERPRETATION_STATUS_KEY] = "partial"
    program.metadata[INTERPRETATION_PARTIAL_STAGES_KEY] = sorted(partial_stages)
    program.metadata[INTERPRETATION_UPDATED_AT_KEY] = updated_at


def build_discard_metadata(
    *,
    reason: str,
    source: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build compact JSON-native metadata for intentional scientific discards."""
    discarded_at = _utcnow_iso()
    record: dict[str, Any] = {
        "reason": reason,
        "source": source,
        "at": discarded_at,
    }
    if details:
        record["details"] = details
    return {
        DISCARD_REASON_KEY: reason,
        DISCARDED_AT_KEY: discarded_at,
        DISCARD_METADATA_KEY: record,
    }


def mark_discarded(
    program: Program,
    *,
    reason: str,
    source: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Attach explicit discard provenance before a DISCARDED transition."""
    program.metadata.update(
        build_discard_metadata(reason=reason, source=source, details=details)
    )
