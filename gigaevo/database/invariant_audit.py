from __future__ import annotations

from dataclasses import dataclass, field

from gigaevo.database.program_storage import ProgramStorage
from gigaevo.evolution.strategies.base import EvolutionStrategy
from gigaevo.programs.metrics.context import VALIDITY_KEY
from gigaevo.programs.program_state import ProgramState


@dataclass
class InvariantIssue:
    kind: str
    program_id: str
    detail: str


@dataclass
class InvariantAuditResult:
    issues: list[InvariantIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def summary(self, *, limit: int = 20) -> str:
        if not self.issues:
            return "status/archive invariants clean"
        shown = self.issues[:limit]
        lines = [
            f"{len(self.issues)} status/archive invariant issue(s):",
            *[
                f"- {issue.kind}: {issue.program_id[:8]} {issue.detail}"
                for issue in shown
            ],
        ]
        if len(self.issues) > limit:
            lines.append(f"- ... {len(self.issues) - limit} more")
        return "\n".join(lines)


async def audit_status_archive_invariants(
    storage: ProgramStorage,
    strategy: EvolutionStrategy | None = None,
) -> InvariantAuditResult:
    """Read-only runtime audit for lifecycle/status/archive consistency."""
    result = InvariantAuditResult()

    status_ids: dict[ProgramState, set[str]] = {}
    for state in ProgramState:
        status_ids[state] = set(await storage.get_ids_by_status(state.value))

    all_status_ids: set[str] = set().union(*status_ids.values()) if status_ids else set()
    programs = await storage.mget(list(all_status_ids))
    by_id = {p.id: p for p in programs}

    for pid in sorted(all_status_ids - set(by_id)):
        memberships = [
            state.value for state, ids in status_ids.items() if pid in ids
        ]
        result.issues.append(
            InvariantIssue(
                "missing_program_blob",
                pid,
                f"present in status sets {memberships}",
            )
        )

    for pid, program in by_id.items():
        memberships = [
            state.value for state, ids in status_ids.items() if pid in ids
        ]
        if len(memberships) != 1:
            result.issues.append(
                InvariantIssue(
                    "bad_status_membership",
                    pid,
                    f"memberships={memberships} json_state={program.state.value}",
                )
            )
        elif memberships[0] != program.state.value:
            result.issues.append(
                InvariantIssue(
                    "status_json_mismatch",
                    pid,
                    f"status={memberships[0]} json_state={program.state.value}",
                )
            )

    if strategy is None:
        return result

    archive_ids = set(await strategy.get_program_ids())
    if not archive_ids:
        return result
    archive_programs = await storage.mget(list(archive_ids))
    archive_by_id = {p.id: p for p in archive_programs}

    for pid in sorted(archive_ids - set(archive_by_id)):
        result.issues.append(
            InvariantIssue("archive_missing_program", pid, "archive ID has no blob")
        )

    for pid, program in archive_by_id.items():
        if program.state in (ProgramState.DISCARDED, ProgramState.QUARANTINED):
            result.issues.append(
                InvariantIssue(
                    "archive_terminal_member",
                    pid,
                    f"archive member has terminal state={program.state.value}",
                )
            )
        if program.state != ProgramState.DONE:
            result.issues.append(
                InvariantIssue(
                    "archive_non_done",
                    pid,
                    f"archive member has state={program.state.value}",
                )
            )
        if pid not in status_ids.get(ProgramState.DONE, set()):
            result.issues.append(
                InvariantIssue(
                    "archive_not_in_done_status",
                    pid,
                    "archive member missing from done status set",
                )
            )
        if program.metrics.get(VALIDITY_KEY, 0.0) <= 0:
            result.issues.append(
                InvariantIssue(
                    "archive_invalid_metrics",
                    pid,
                    f"{VALIDITY_KEY}={program.metrics.get(VALIDITY_KEY)}",
                )
            )

    return result
