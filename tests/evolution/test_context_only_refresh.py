from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock

import pytest

from gigaevo.evolution.engine.refresh import (
    CONTEXT_REFRESH_METADATA_KEY,
    ContextOnlyParentRefresher,
)
from gigaevo.evolution.mutation.constants import MUTATION_CONTEXT_METADATA_KEY
from gigaevo.programs.core_types import StageIO
from gigaevo.programs.program import Program
from gigaevo.programs.program_state import ProgramState
from gigaevo.programs.stages.base import Stage
from gigaevo.programs.stages.cache_handler import NO_CACHE
from gigaevo.programs.stages.common import (
    FloatDictContainer,
    StringContainer,
    StringList,
)
from gigaevo.runner.dag_blueprint import DAGBlueprint


class _DescendantStage(Stage):
    InputsModel = StageIO
    OutputModel = StringList
    cache_handler = NO_CACHE

    async def compute(self, program: Program) -> StringList:
        return StringList(items=list(program.lineage.children))


class _IntraInputs(StageIO):
    children_ids: StringList | None


class _IntraStage(Stage):
    InputsModel = _IntraInputs
    OutputModel = StringContainer
    cache_handler = NO_CACHE

    async def compute(self, program: Program) -> StringContainer:  # noqa: ARG002
        params = cast(_IntraInputs, self.params)
        children = params.children_ids.items if params.children_ids is not None else []
        return StringContainer(data=f"children:{','.join(children)}")


class _MutationContextInputs(StageIO):
    metrics: FloatDictContainer | None
    memory: StringContainer | None


class _MutationContextStage(Stage):
    InputsModel = _MutationContextInputs
    OutputModel = StringContainer
    cache_handler = NO_CACHE

    async def compute(self, program: Program) -> StringContainer:
        params = cast(_MutationContextInputs, self.params)
        text = params.memory.data if params.memory is not None else ""
        program.set_metadata(MUTATION_CONTEXT_METADATA_KEY, text)
        return StringContainer(data=text)


def _blueprint() -> DAGBlueprint:
    return DAGBlueprint(
        nodes={
            "DescendantProgramIds": lambda: _DescendantStage(timeout=1),
            "IntraMemoryStage": lambda: _IntraStage(timeout=1),
            "MutationContextStage": lambda: _MutationContextStage(timeout=1),
        },
        data_flow_edges=[],
    )


@pytest.mark.asyncio
async def test_context_only_refresh_preserves_done_and_rebuilds_context() -> None:
    parent = Program(code="def solve(): return 1", state=ProgramState.DONE)
    parent.metrics = {"fitness": 1.0}
    parent.lineage.children = ["child-1"]

    storage = AsyncMock()
    storage.get.return_value = parent

    refresher = ContextOnlyParentRefresher(
        storage=storage,
        dag_blueprint=_blueprint(),
    )

    result = await refresher.refresh_if_stale([parent])

    assert result.stale_count == 1
    assert result.refreshed == [parent]
    assert parent.state == ProgramState.DONE
    assert parent.code == "def solve(): return 1"
    assert parent.metrics == {"fitness": 1.0}
    assert parent.get_metadata(MUTATION_CONTEXT_METADATA_KEY) == "children:child-1"
    assert parent.metadata[CONTEXT_REFRESH_METADATA_KEY]["status"] == "completed"
    storage.update.assert_awaited_once_with(parent)
