from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import Path
from typing import Any, Generic, TypeVar, cast

import cloudpickle
from loguru import logger

from gigaevo.exceptions import ValidationError
from gigaevo.programs.core_types import (
    ProgramStageResult,
    StageError,
    StageIO,
    VoidInput,
)
from gigaevo.programs.metrics.aggregators import MetricsAggregator
from gigaevo.programs.program import Program
from gigaevo.programs.stages.base import Stage
from gigaevo.programs.stages.common import AnyContainer, Box
from gigaevo.programs.stages.python_executors.wrapper import (
    ExecRunnerError,
    run_exec_runner,
)
from gigaevo.programs.stages.stage_registry import StageRegistry
from gigaevo.programs.utils import dedent_code

T = TypeVar("T")


class PythonCodeExecutor(Stage, Generic[T]):
    """
    Execute a user function from dynamic code in an isolated subprocess.

    The subprocess has resource limits applied for safety:
    - Memory limits (via resource.RLIMIT_AS) prevent RAM exhaustion
    - Timeout limits prevent infinite loops
    - Output size limits prevent excessive data generation

    The output is a Box[T] containing the result of the function call.

    Args:
        function_name: Name of the function to call in the user code
        python_path: Additional paths to add to sys.path
        max_output_size: Maximum size of output in bytes (default: 64MB)
        max_memory_mb: Maximum memory in MB (default: None = unlimited)
        timeout: Maximum execution time in seconds (inherited from Stage)

    Subclasses must implement `_build_call(self, program) -> (args, kwargs)`.
    """

    InputsModel: type[StageIO] = VoidInput
    OutputModel = Box[T]  # type: ignore[valid-type]  # bound TypeVar used as generic alias in base class

    def __init__(
        self,
        *,
        function_name: str = "run_code",
        python_path: list[Path] | None = None,
        max_output_size: int = 64 * 1024 * 1024,
        max_memory_mb: int | None = None,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.function_name = function_name
        self.python_path = python_path or []
        self.max_output_size = int(max_output_size)
        self.max_memory_mb = int(max_memory_mb) if max_memory_mb is not None else None

    def _code_str(self, program: Program) -> str:
        return program.code

    def _build_call(self, program: Program) -> tuple[Sequence[Any], dict[str, Any]]:
        return (), {}

    def parse_output(self, x: Any) -> T:
        """Parse raw subprocess return value; override in subclasses."""
        return cast(T, x)

    async def compute(self, program: Program) -> ProgramStageResult | Box[Any]:
        stage_name = self.__class__.__name__
        code_str = self._code_str(program)
        args, kwargs = self._build_call(program)

        logger.debug(
            "[{}] calling '{}' with {} arg(s), {} kwarg(s)",
            stage_name,
            self.function_name,
            len(args),
            len(kwargs),
        )

        try:
            value, stdout_bytes, stderr_text = await run_exec_runner(
                code=dedent_code(code_str),
                function_name=self.function_name,
                args=args,
                kwargs=kwargs,
                python_path=self.python_path,
                env_updates={
                    "GIGAEVO_PROGRAM_ID": program.id,
                    "GIGAEVO_PROGRAM_ID_SHORT": program.id[:8],
                },
                timeout=int(self.timeout),
                max_memory_mb=self.max_memory_mb,
                max_output_size=self.max_output_size,
            )

            value_parsed = self.parse_output(value)

            logger.debug(
                "[{}] {} ok | result_type={}",
                stage_name,
                program.id[:8],
                type(value_parsed).__name__,
            )

            del stdout_bytes
            del stderr_text

            return self.__class__.OutputModel(data=value_parsed)

        except ExecRunnerError as e:
            # Detect memory limit errors
            error_type = "SubprocessError"
            error_msg = str(e)

            if e.stderr and (
                "MemoryError" in e.stderr or "Cannot allocate memory" in e.stderr
            ):
                error_type = "MemoryLimitExceeded"
                error_msg = (
                    f"Process exceeded memory limit of {self.max_memory_mb} MB"
                    if self.max_memory_mb
                    else "Process ran out of memory"
                )

            logger.warning(
                "[{}] {} FAILED for {}: {}",
                stage_name,
                error_type,
                program.id[:8],
                error_msg[:200],
            )
            return ProgramStageResult.failure(
                error=StageError(
                    type=error_type,
                    message=error_msg,
                    stage=stage_name,
                    traceback=e.stderr,
                )
            )
        except Exception as e:
            logger.warning(
                "[{}] Exception for {}: {}",
                stage_name,
                program.id[:8],
                str(e)[:200],
            )
            return ProgramStageResult.failure(
                error=StageError.from_exception(e, stage=stage_name)
            )


class ContextInputModel(StageIO):
    context: AnyContainer | None


@StageRegistry.register(
    description="Call a function defined in Program.code, wiring optional DAG input."
)
class CallProgramFunction(PythonCodeExecutor):
    """Calls the user function in Program.code. Accepts optional input from DAG wiring."""

    InputsModel = ContextInputModel
    OutputModel = Box[Any]

    def _build_call(self, program: Program) -> tuple[Sequence[Any], dict[str, Any]]:
        params = cast(ContextInputModel, self.params)
        args: list[Any] = []
        context: AnyContainer | None = params.context
        if context is not None:
            args.append(context.data)
        return args, {}


@StageRegistry.register(
    description="Call a function in Program.code with fixed args provided at construction."
)
class CallProgramFunctionWithFixedArgs(PythonCodeExecutor):
    """Calls the user function in Program.code with fixed args (and/or kwargs) supplied when building the stage."""

    OutputModel = Box[Any]

    def __init__(
        self,
        *,
        args: Sequence[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        **kw: Any,
    ):
        super().__init__(**kw)
        self._fixed_args = list(args or [])
        self._fixed_kwargs = dict(kwargs or {})

    def _build_call(self, program: Program) -> tuple[Sequence[Any], dict[str, Any]]:
        return self._fixed_args, self._fixed_kwargs


@StageRegistry.register(
    description="Call a function defined in a Python file (no DAG inputs)."
)
class CallFileFunction(PythonCodeExecutor):
    """Loads Python code from a file and calls a function (default: build_context)."""

    OutputModel = Box[Any]

    def __init__(
        self, *, path: Path, function_name: str = "build_context", **kwargs: Any
    ):
        super().__init__(
            function_name=function_name, python_path=[Path(path).parent], **kwargs
        )
        p = Path(path)
        if not p.exists():
            raise ValidationError(f"Python file not found: {p}")
        try:
            self._file_code = p.read_text(encoding="utf-8")
        except OSError as e:
            raise ValidationError(f"Failed to read file: {e}") from e

    def _code_str(self, program: Program) -> str:
        return self._file_code

    def _build_call(self, program: Program) -> tuple[Sequence[Any], dict[str, Any]]:
        return [], {}


class ValidatorInput(StageIO):
    payload: AnyContainer
    context: AnyContainer | None
    cache_on: AnyContainer | None = None


ValidatorOutput = Box[tuple[dict[str, float], Any]]
# Task 2: rename the stage's output label to advertise that it's a RAW
# (pre-aggregator) tuple. Identical runtime type; ParseMetricsStage wraps it
# before FetchMetrics / FetchArtifact / DGTrackerStage see their expected
# `validation_result` shape.
RawValidatorOutput = ValidatorOutput


@StageRegistry.register(
    description="Call a validator function from a Python file on program output (+ optional context)."
)
class CallValidatorFunction(PythonCodeExecutor):
    """Loads validator file and calls function `validate(context?, program_output)`."""

    InputsModel = ValidatorInput
    OutputModel = RawValidatorOutput  # raw (intrinsic, artifact) from evaluate.py

    def __init__(self, *, path: Path, function_name: str = "validate", **kwargs: Any):
        super().__init__(
            function_name=function_name, python_path=[Path(path).parent], **kwargs
        )
        p = Path(path)
        if not p.exists():
            raise ValidationError(f"Validator file not found: {p}")
        try:
            self._validator_code = p.read_text(encoding="utf-8")
        except OSError as e:
            raise ValidationError(f"Failed to read validator file: {e}") from e

    def _code_str(self, program: Program) -> str:
        return self._validator_code

    def parse_output(self, x: Any) -> tuple[dict[str, float], Any]:
        # Validate the return type early to give a clear error pointing back to
        # validate().  Allowing None or non-dict/tuple values through produces
        # cryptic downstream errors (e.g. "TypeError: {**None}") with no hint
        # that the problem is in the researcher's validate() return value.
        if isinstance(x, tuple):
            return x
        if not isinstance(x, dict):
            raise ValueError(
                f"validate() must return a dict or (dict, artifact) tuple, "
                f"got {type(x).__name__!r}: {x!r}"
            )
        return (x, None)

    @classmethod
    def compute_hash(cls, params: StageIO) -> str | None:
        """Compute a stable cache key for validator inputs.

        Validator payloads may contain callables returned by
        ``CallProgramFunction``. Hashing those by cloudpickle directly is too
        sensitive to callable object identity and can make unchanged validator
        inputs miss cache repeatedly. We normalize callables by module,
        qualname, code shape, defaults, and closure contents where available.

        ``cache_on`` is intentionally included even though compute ignores it;
        adversarial pipelines wire opponent IDs there so changing opponent
        samples invalidates validation without passing extra runtime args to
        evaluate()/validate().
        """
        p = cast(ValidatorInput, params)
        normalized = {
            "payload": _stable_cache_value(p.payload),
            "context": _stable_cache_value(p.context),
            "cache_on": _stable_cache_value(p.cache_on),
        }
        encoded = json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:16]

    def _build_call(self, program: Program) -> tuple[Sequence[Any], dict[str, Any]]:
        params = cast(ValidatorInput, self.params)
        payload = params.payload.data
        if params.context is not None:
            context = params.context.data
        else:
            context = None
        return ([context, payload] if context is not None else [payload]), {}


def _stable_cache_value(value: Any) -> Any:
    """Return a JSON-serializable representation suitable for cache keys."""
    seen: set[int] = set()
    return _stable_cache_value_inner(value, seen)


def _stable_cache_value_inner(value: Any, seen: set[int]) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    obj_id = id(value)
    if obj_id in seen:
        return {"__cycle__": type(value).__qualname__}
    seen.add(obj_id)
    try:
        if isinstance(value, StageIO):
            return {
                "__stage_io__": type(value).__qualname__,
                "data": _stable_cache_value_inner(value.model_dump(), seen),
            }
        if isinstance(value, Mapping):
            return {
                str(k): _stable_cache_value_inner(v, seen)
                for k, v in sorted(value.items(), key=lambda item: str(item[0]))
            }
        if isinstance(value, (list, tuple)):
            return [_stable_cache_value_inner(v, seen) for v in value]
        if isinstance(value, (set, frozenset)):
            items = [_stable_cache_value_inner(v, seen) for v in value]
            return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
        if isinstance(value, bytes):
            return {
                "__bytes_sha256__": hashlib.sha256(value).hexdigest(),
                "len": len(value),
            }
        if callable(value):
            return _stable_callable_cache_value(value, seen)
        if hasattr(value, "model_dump"):
            return {
                "__model__": type(value).__qualname__,
                "data": _stable_cache_value_inner(value.model_dump(), seen),
            }
        if hasattr(value, "tolist"):
            try:
                return {
                    "__array_like__": type(value).__qualname__,
                    "shape": list(getattr(value, "shape", ())),
                    "dtype": str(getattr(value, "dtype", "")),
                    "data": _stable_cache_value_inner(value.tolist(), seen),
                }
            except Exception:
                pass
        try:
            payload = cloudpickle.dumps(value)
            return {
                "__pickle_sha256__": hashlib.sha256(payload).hexdigest(),
                "type": f"{type(value).__module__}.{type(value).__qualname__}",
            }
        except Exception:
            return {
                "__repr__": repr(value),
                "type": f"{type(value).__module__}.{type(value).__qualname__}",
            }
    finally:
        seen.discard(obj_id)


def _stable_callable_cache_value(fn: Any, seen: set[int]) -> dict[str, Any]:
    code = getattr(fn, "__code__", None)
    if code is not None:
        code_payload = {
            "co_code": code.co_code.hex(),
            "co_consts": repr(code.co_consts),
            "co_names": code.co_names,
            "co_varnames": code.co_varnames,
            "co_argcount": code.co_argcount,
            "co_kwonlyargcount": code.co_kwonlyargcount,
        }
        code_hash = hashlib.sha256(
            json.dumps(code_payload, sort_keys=True, default=repr).encode("utf-8")
        ).hexdigest()[:16]
    else:
        code_hash = None

    closure_values: list[Any] = []
    for cell in getattr(fn, "__closure__", None) or ():
        try:
            closure_values.append(
                _stable_cache_value_inner(cell.cell_contents, seen)
            )
        except ValueError:
            closure_values.append({"__empty_cell__": True})

    return {
        "__callable__": True,
        "module": getattr(fn, "__module__", None),
        "qualname": getattr(fn, "__qualname__", getattr(fn, "__name__", None)),
        "code_hash": code_hash,
        "defaults": _stable_cache_value_inner(getattr(fn, "__defaults__", None), seen),
        "kwdefaults": _stable_cache_value_inner(
            getattr(fn, "__kwdefaults__", None), seen
        ),
        "closure": closure_values,
    }


# ---------------------------------------------------------------------------
# ParseMetricsStage — composes program.metrics from primitives.
# ---------------------------------------------------------------------------
#
# CallValidatorFunction now emits `raw_validator_output` (the raw
# (intrinsic, artifact) tuple from evaluate.py). ParseMetricsStage consumes
# it, applies the aggregator, and emits the legacy `validation_result`
# shape so FetchMetrics / FetchArtifact / DGTrackerStage are untouched.


class RawValidatorInput(StageIO):
    raw_validator_output: RawValidatorOutput


@StageRegistry.register(
    description="Compose program.metrics from per-opponent primitives via aggregator."
)
class ParseMetricsStage(Stage):
    """Aggregator-driven metrics composition.

    evaluate.py returns `(intrinsic, artifact)`. This stage:
      1. Pulls `artifact["per_opp_metrics"]` (list of per-fight dicts).
      2. Calls `aggregator.aggregate(per_opp, intrinsic)` → `metrics`.
      3. Emits `(metrics, artifact)` so downstream is unchanged.

    Candidate failure (empty / missing per_opp_metrics, or artifact=None)
    falls through to `aggregator.invalid_defaults` — no per-stage special-
    casing. `invalid_defaults.is_valid = 0.0` captures "no signal" uniformly.
    """

    InputsModel = RawValidatorInput
    OutputModel = Box[tuple[dict[str, float], Any]]

    def __init__(self, *, aggregator: MetricsAggregator, **kwargs: Any):
        super().__init__(**kwargs)
        if aggregator is None:
            raise ValueError(
                "ParseMetricsStage: aggregator required — no silent fallback."
            )
        self._aggregator = aggregator

    async def compute(self, program: Program) -> Box[tuple[dict[str, float], Any]]:
        params = cast(RawValidatorInput, self.params)
        raw = params.raw_validator_output.data
        if not isinstance(raw, tuple) or len(raw) != 2:
            raise ValueError(
                f"ParseMetricsStage expected (intrinsic, artifact) tuple from "
                f"CallValidatorFunction, got {type(raw).__name__!r}"
            )
        intrinsic, artifact = raw
        per_opp = []
        if isinstance(artifact, dict):
            per_opp = list(artifact.get("per_opp_metrics") or [])
        metrics = self._aggregator.aggregate(per_opp, dict(intrinsic or {}))
        logger.info(
            "[ParseMetricsStage] {} keys={} n_per_opp={}",
            program.id[:8],
            sorted(metrics.keys()),
            len(per_opp),
        )
        return Box[tuple[dict[str, float], Any]](data=(metrics, artifact))


class ValidationResult(StageIO):
    validation_result: ValidatorOutput


@StageRegistry.register(
    description="Extract metrics dict from a validation result (ValidatorOutput)."
)
class FetchMetrics(Stage):
    InputsModel = ValidationResult
    OutputModel = Box[dict[str, float]]

    async def compute(self, program: Program) -> Box[dict[str, float]]:
        params = cast(ValidationResult, self.params)
        metrics = params.validation_result.data[0]
        logger.info(
            "[FetchMetrics] {} metrics={}",
            program.id[:8],
            {k: f"{v:.4f}" if isinstance(v, float) else v for k, v in metrics.items()},
        )
        return Box[dict[str, float]](data=metrics)


@StageRegistry.register(
    description="Extract execution artifact from a validation result (ValidatorOutput)."
)
class FetchArtifact(Stage):
    InputsModel = ValidationResult
    OutputModel = Box[Any]

    async def compute(self, program: Program) -> Box[Any]:
        params = cast(ValidationResult, self.params)
        return Box[Any](data=params.validation_result.data[1])
