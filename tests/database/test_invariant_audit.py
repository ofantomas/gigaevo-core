from __future__ import annotations

from gigaevo.database.invariant_audit import audit_status_archive_invariants
from gigaevo.programs.metrics.context import VALIDITY_KEY
from gigaevo.programs.program_state import ProgramState


class _Strategy:
    def __init__(self, ids: list[str]):
        self._ids = ids

    async def get_program_ids(self) -> list[str]:
        return self._ids


async def test_audit_detects_status_json_mismatch_without_mutating(
    fakeredis_storage, make_program
):
    prog = make_program(state=ProgramState.DISCARDED)
    await fakeredis_storage.add(prog)

    redis_conn = fakeredis_storage._conn._redis
    discarded_key = fakeredis_storage._keys.status_set(ProgramState.DISCARDED.value)
    running_key = fakeredis_storage._keys.status_set(ProgramState.RUNNING.value)
    await redis_conn.sadd(running_key, prog.id)
    await redis_conn.srem(discarded_key, prog.id)

    result = await audit_status_archive_invariants(fakeredis_storage)

    assert any(issue.kind == "status_json_mismatch" for issue in result.issues)
    assert prog.id in await fakeredis_storage.get_ids_by_status(
        ProgramState.RUNNING.value
    )
    assert prog.id not in await fakeredis_storage.get_ids_by_status(
        ProgramState.DISCARDED.value
    )


async def test_audit_detects_terminal_archive_member(fakeredis_storage, make_program):
    prog = make_program(state=ProgramState.QUARANTINED)
    prog.metrics = {VALIDITY_KEY: 1.0}
    await fakeredis_storage.add(prog)

    result = await audit_status_archive_invariants(
        fakeredis_storage, _Strategy([prog.id])
    )

    kinds = {issue.kind for issue in result.issues}
    assert "archive_terminal_member" in kinds
    assert "archive_non_done" in kinds
