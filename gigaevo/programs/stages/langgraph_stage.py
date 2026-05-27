from __future__ import annotations

import asyncio
import time
from typing import Any

from loguru import logger

from gigaevo.llm.agents.base import LangGraphAgent
from gigaevo.programs.core_types import (
    ProgramStageResult,
    StageError,
    StageIO,
    VoidInput,
    VoidOutput,
)
from gigaevo.programs.program import Program
from gigaevo.programs.lifecycle_metadata import mark_interpretation_partial
from gigaevo.programs.stages.base import Stage


class LangGraphStage(Stage):
    """
    Generic wrapper for LangGraph/LangChain-like agents with lifecycle hooks.

    Subclasses MUST define:
      - InputsModel (StageIO): strict schema for agent inputs (Optionals mark optional DAG inputs)
      - OutputModel (StageIO): strict output schema

    Execution flow:
      1) Validate DAG inputs -> self.params (InputsModel)
      2) kwargs0 = preprocess(program, self.params)
           - May return dict[str, Any] (kwargs to pass to agent)
           - Or return ProgramStageResult to short-circuit (e.g., SKIPPED/FAILED)
      3) Inject program under `program_kwarg` (if set) + merge `extra_kwargs`
      4) result = agent(...) via ainvoke/arun/invoke/run/callable
      5) out = postprocess(program, result)
           - May return OutputModel or ProgramStageResult
           - Defaults coerce result to OutputModel (single-field wrap or dict->validate)
    """

    InputsModel: type[StageIO] = VoidInput
    OutputModel: type[StageIO] = VoidOutput

    def __init__(
        self,
        *,
        agent: LangGraphAgent,
        program_kwarg: str | None = None,
        max_attempts: int = 1,
        retry_backoff_seconds: float = 2.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.agent = agent
        self.program_kwarg = program_kwarg
        self.max_attempts = max(1, int(max_attempts))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))
        logger.info(
            "[{}] Initialized with agent={} program_kwarg={} max_attempts={}",
            self.stage_name,
            getattr(agent, "__class__", type(agent)).__name__,
            self.program_kwarg,
            self.max_attempts,
        )

    async def preprocess(
        self, program: Program, params: StageIO
    ) -> dict[str, Any] | ProgramStageResult:
        """
        Build kwargs for the agent call from validated params.
        Default: pass through all fields from InputsModel.
        """
        fields = self.__class__.InputsModel.model_fields
        kwargs: dict[str, Any] = {}
        for name in fields.keys():
            v = getattr(params, name)
            kwargs[name] = v
        return kwargs

    async def postprocess(
        self, program: Program, agent_result: Any
    ) -> StageIO | ProgramStageResult:
        """
        Coerce/validate agent_result to OutputModel (or return a ProgramStageResult).
        Default behavior:
          - if already OutputModel -> return
          - if OutputModel has a single field and the value matches field type -> wrap
          - if dict-like -> model_validate into OutputModel
          - else -> TypeError (handled by base Stage exception policy)
        """
        # Already correct type
        if isinstance(agent_result, self.__class__.OutputModel):
            return agent_result

        out_fields = self.__class__.OutputModel.model_fields

        # Try single-field wrapper (let Pydantic validate)
        if len(out_fields) == 1:
            ((field_name, _),) = out_fields.items()
            try:
                return self.__class__.OutputModel(**{field_name: agent_result})
            except Exception:
                # Pydantic validation failed, continue to try other coercion methods
                pass

        # Dict-like -> validate
        if isinstance(agent_result, dict):
            return self.__class__.OutputModel.model_validate(agent_result)

        raise TypeError(
            f"{self.stage_name}: agent returned {type(agent_result).__name__}; "
            f"cannot coerce to {self.__class__.OutputModel.__name__}"
        )

    async def partial_output_on_exhausted(
        self, program: Program, exc: BaseException
    ) -> StageIO | None:
        """Return a partial output after retries are exhausted, or None to fail.

        LLM interpretation stages can override this to keep valid programs usable
        when interpretation is unavailable. Validation and execution stages should
        generally keep the default hard-failure behavior.
        """
        return None

    async def _agent_call(self, kwargs: dict[str, Any]) -> Any:
        return await self.agent.arun(**kwargs)

    async def compute(self, program: Program) -> StageIO | ProgramStageResult:
        # 1) Preprocess
        prep = await self.preprocess(program, self.params)
        if isinstance(prep, ProgramStageResult):
            return prep
        kwargs = dict(prep)

        # 2) Inject current program if requested
        if self.program_kwarg is not None:
            if self.program_kwarg in kwargs:
                raise ValueError(
                    f"{self.stage_name}: program_kwarg '{self.program_kwarg}' collides with a preprocessed arg."
                )
            kwargs[self.program_kwarg] = program

        # 3) Call agent with bounded immediate retries.
        deadline = time.monotonic() + self.timeout
        last_exc: BaseException | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                remaining = max(0.1, deadline - time.monotonic())
                result = await asyncio.wait_for(
                    self._agent_call(kwargs), timeout=remaining
                )
                # 4) Postprocess
                return await self.postprocess(program, result)
            except Exception as exc:
                last_exc = exc
                if attempt >= self.max_attempts:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                sleep_s = min(self.retry_backoff_seconds * attempt, remaining)
                logger.warning(
                    "[{}] {} attempt {}/{} failed: {}; retrying in {:.1f}s",
                    self.stage_name,
                    program.id[:8],
                    attempt,
                    self.max_attempts,
                    str(exc)[:200],
                    sleep_s,
                )
                if sleep_s > 0:
                    await asyncio.sleep(sleep_s)

        assert last_exc is not None
        mark_interpretation_partial(
            program,
            stage_name=self.stage_name,
            attempts=self.max_attempts,
            exc=last_exc,
        )
        partial_output = await self.partial_output_on_exhausted(program, last_exc)
        if partial_output is not None:
            logger.warning(
                "[{}] {} exhausted {}/{} attempts; continuing with partial output",
                self.stage_name,
                program.id[:8],
                self.max_attempts,
                self.max_attempts,
            )
            return partial_output
        return ProgramStageResult.failure(
            error=StageError.from_exception(last_exc, stage=self.stage_name)
        )
