# Aggregator-First Metrics — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. RED → GREEN → commit on every task. Use `rtk git` never plain `git`.

**Goal:** Make the aggregator YAML the single source of truth for `program.metrics`. Evaluate.py becomes a primitives producer that returns `(intrinsic, artifact)`; a new `ParseMetricsStage` composes the final metrics dict from `artifact.per_opp_metrics` by calling the aggregator.

**Architecture:** New `ParseMetricsStage` stage inserted between `CallValidatorFunction` and `FetchMetrics`. `CallValidatorFunction` output renamed to `raw_validator_output`; `ParseMetricsStage` emits the existing `validation_result` name so `FetchMetrics` / `FetchArtifact` / `DGTrackerStage` are untouched. Aggregator wired as a top-level Hydra singleton referenced by both `ParseMetricsStage` and `lineage_filter.aggregator` via `${ref:aggregator}`.

**Tech Stack:** Python 3.11, Hydra 1.3, OmegaConf, pytest, ruff. Existing stack — no new deps.

**Scope (hard-cut, single PR):**
- Touches: `gigaevo/programs/stages/python_executors/execution.py` (new stage + rename edge), `gigaevo/adversarial/asymmetric_pipeline.py` (insert ParseMetricsStage into D and G subgraphs), `config/pipeline/heilbron_repro_v1.yaml` (+ G-specific sibling or override for constructor aggregator), `problems/heilbron_repro_v1/pop_{a,b}/evaluate.py` (hard-cut to new contract; delete INVALID), new tests, new golden-vector.
- Does NOT touch: `problems/heilbron_adversarial/*`, `custom.yaml` (used by non-Heilbron pipelines), HoVer / HotpotQA evaluate.py files, `metrics.yaml` consolidation (deferred).

**Definition of done:** unit tests green + golden-vector test green + schema-existence test green + 3-generation smoke of `A1_G` + `A1_D` on scratch Redis DB with logs showing (a) no KeyError, (b) `[LineageStage:SharedBenchmark] kept …` lines, (c) `[ParseMetricsStage]` emitting metrics with the correct key set.

---

## Pre-flight

- [ ] **Verify current branch and green baseline**

```bash
rtk git status    # expect: clean working tree on exp/heilbron/adversarial-repro-v2
rtk git log --oneline -5
```

Expected: last commit is `886f5962` (Task 6 — per-population aggregator YAML). Working tree clean.

```bash
/run-tests tests/programs/metrics/ tests/adversarial_pipeline/
```

Expected: all green.

If either fails, STOP — do not start the plan.

---

## Task 1: `ParseMetricsStage` + `NullAggregator` sentinel

**Files:**
- Modify: `gigaevo/programs/metrics/aggregators.py` (add `NullAggregator` sentinel class — never runs, signals "skip ParseMetricsStage")
- Modify: `gigaevo/programs/stages/python_executors/execution.py` (add new stage class, add new `Box` alias, register)
- Test: `tests/stages/test_parse_metrics_stage.py` (new file)
- Test: `tests/test_metrics_aggregators.py` (append NullAggregator tests)

The stage reads a `raw_validator_output` Box containing `(intrinsic_dict, artifact)` from `CallValidatorFunction`, calls `aggregator.aggregate(artifact["per_opp_metrics"], intrinsic)`, and emits the existing `validation_result` shape `(metrics_dict, artifact)` so downstream stages are unchanged.

`NullAggregator` is a sentinel subclass of `MetricsAggregator`. It is never actually *called* — the pipeline builder (Task 3) uses `isinstance(aggregator, NullAggregator)` to gate off ParseMetricsStage insertion entirely. This lets Hydra always resolve a concrete aggregator object (no null footgun) while letting non-Heilbron pipelines opt out cleanly via `aggregator=none`.

- [ ] **Step 1.1a (RED): write NullAggregator tests**

Append to `tests/test_metrics_aggregators.py`:

```python
class TestNullAggregator:
    def test_is_metrics_aggregator_subclass(self):
        from gigaevo.programs.metrics.aggregators import MetricsAggregator, NullAggregator
        assert issubclass(NullAggregator, MetricsAggregator)

    def test_output_keys_is_empty(self):
        from gigaevo.programs.metrics.aggregators import NullAggregator
        assert NullAggregator().output_keys == frozenset()

    def test_aggregate_is_a_noop_returning_empty(self):
        """NullAggregator is a sentinel — the builder gates on isinstance and
        never actually calls it. But if something does call it, return {}."""
        from gigaevo.programs.metrics.aggregators import NullAggregator
        assert NullAggregator().aggregate([], {}) == {}
        assert NullAggregator().aggregate([{"x": 1.0}], {"y": 2.0}) == {}
```

Run: `$GIGAEVO_PYTHON -m pytest tests/test_metrics_aggregators.py::TestNullAggregator -x --tb=short` → FAIL (no such class).

- [ ] **Step 1.1b (GREEN): add NullAggregator**

In `gigaevo/programs/metrics/aggregators.py`, after `ConfigurableAggregator`:

```python
class NullAggregator(MetricsAggregator):
    """Sentinel 'no aggregator configured' marker.

    The pipeline builder checks ``isinstance(aggregator, NullAggregator)``
    and skips installing ParseMetricsStage when true — the DAG keeps the
    legacy ``CallValidatorFunction → FetchMetrics`` edge, and evaluate.py's
    old-contract ``metrics`` dict flows through unchanged.

    This lets Hydra's ``aggregator=none`` default resolve to a real object
    (no null footgun in ``${ref:aggregator}``) while preserving the
    "non-Heilbron pipelines untouched" scope constraint.
    """

    @property
    def output_keys(self) -> frozenset[str]:
        return frozenset()

    def aggregate(self, per_opp, intrinsic):
        return {}
```

Add `"NullAggregator"` to `__all__`.

Run: `$GIGAEVO_PYTHON -m pytest tests/test_metrics_aggregators.py::TestNullAggregator -x --tb=short` → PASS.

Commit:
```bash
rtk git add gigaevo/programs/metrics/aggregators.py tests/test_metrics_aggregators.py
rtk git commit -m "feat(metrics): NullAggregator sentinel — signals 'no aggregator configured'"
```

- [ ] **Step 1.1 (RED): write failing ParseMetricsStage tests**

Create `tests/stages/test_parse_metrics_stage.py`:

```python
"""Tests for ParseMetricsStage — composes program.metrics from primitives."""

from __future__ import annotations

import pytest

from gigaevo.programs.metrics.aggregators import (
    ConfigurableAggregator,
    ConstantSpec,
    IntrinsicSpec,
    ReduceSpec,
)
from gigaevo.programs.metrics.context import MetricSpec, MetricsContext
from gigaevo.programs.stages.common import Box
from gigaevo.programs.stages.python_executors.execution import (
    ParseMetricsStage,
    RawValidatorOutput,
)


def _ctx() -> MetricsContext:
    return MetricsContext(
        specs={
            "fitness": MetricSpec(description="fitness", higher_is_better=True, is_primary=True),
            "is_valid": MetricSpec(description="validity", higher_is_better=True),
        }
    )


def _agg() -> ConfigurableAggregator:
    return ConfigurableAggregator(
        outputs={
            "is_valid": ConstantSpec(value=1.0),
            "n_opponents": ReduceSpec(op="count"),
            "fitness": ReduceSpec(op="mean", field="score"),
            "quality": IntrinsicSpec(key="quality", default=0.0),
        },
        invalid_defaults={"is_valid": 0.0, "n_opponents": 0.0, "fitness": -1.0, "quality": 0.0},
        metrics_context=_ctx(),
    )


@pytest.mark.asyncio
async def test_aggregator_required_raises_on_none():
    with pytest.raises(ValueError, match="aggregator required"):
        ParseMetricsStage(aggregator=None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_composes_metrics_from_per_opp(dummy_program):
    stage = ParseMetricsStage(aggregator=_agg())
    artifact = {
        "role": "improver",
        "per_opp_metrics": [
            {"score": 0.4, "is_valid": 1.0},
            {"score": 0.6, "is_valid": 1.0},
        ],
    }
    raw = Box(data=({"quality": 0.7}, artifact))
    stage.params = type("P", (), {"raw_validator_output": raw})()
    out = await stage.compute(dummy_program)
    metrics, out_artifact = out.data
    assert metrics["fitness"] == pytest.approx(0.5)
    assert metrics["n_opponents"] == 2.0
    assert metrics["quality"] == 0.7
    assert out_artifact is artifact  # passthrough by reference


@pytest.mark.asyncio
async def test_empty_per_opp_returns_invalid_defaults(dummy_program):
    stage = ParseMetricsStage(aggregator=_agg())
    raw = Box(data=({}, {"role": "improver", "per_opp_metrics": []}))
    stage.params = type("P", (), {"raw_validator_output": raw})()
    out = await stage.compute(dummy_program)
    metrics, _ = out.data
    assert metrics == {"is_valid": 0.0, "n_opponents": 0.0, "fitness": -1.0, "quality": 0.0}


@pytest.mark.asyncio
async def test_missing_per_opp_metrics_key_treated_as_candidate_failure(dummy_program):
    stage = ParseMetricsStage(aggregator=_agg())
    raw = Box(data=({}, {"role": "improver"}))  # no per_opp_metrics
    stage.params = type("P", (), {"raw_validator_output": raw})()
    out = await stage.compute(dummy_program)
    metrics, _ = out.data
    assert metrics["is_valid"] == 0.0
    assert metrics["fitness"] == -1.0


@pytest.mark.asyncio
async def test_none_artifact_treated_as_candidate_failure(dummy_program):
    stage = ParseMetricsStage(aggregator=_agg())
    raw = Box(data=({}, None))
    stage.params = type("P", (), {"raw_validator_output": raw})()
    out = await stage.compute(dummy_program)
    metrics, _ = out.data
    assert metrics["is_valid"] == 0.0


@pytest.mark.asyncio
async def test_raises_on_non_tuple_input(dummy_program):
    stage = ParseMetricsStage(aggregator=_agg())
    raw = Box(data={"not": "a tuple"})
    stage.params = type("P", (), {"raw_validator_output": raw})()
    with pytest.raises(ValueError, match="tuple"):
        await stage.compute(dummy_program)
```

Add a `dummy_program` fixture in `tests/conftest.py` if not already present — or create local:

```python
@pytest.fixture
def dummy_program():
    from gigaevo.programs.program import Program
    return Program.create_root(code="def entrypoint(): return 0")
```

- [ ] **Step 1.2: run tests to confirm RED**

```bash
$GIGAEVO_PYTHON -m pytest tests/stages/test_parse_metrics_stage.py -x --tb=short
```

Expected: `ImportError` on `ParseMetricsStage`/`RawValidatorOutput`. All tests fail.

- [ ] **Step 1.3 (GREEN): add the stage**

In `gigaevo/programs/stages/python_executors/execution.py`, add AFTER `CallValidatorFunction` class and BEFORE `ValidationResult` class:

```python
# ---------------------------------------------------------------------------
# ParseMetricsStage — composes program.metrics from primitives.
# ---------------------------------------------------------------------------
#
# CallValidatorFunction now emits `raw_validator_output` (the raw
# (intrinsic, artifact) tuple from evaluate.py). ParseMetricsStage consumes
# it, applies the aggregator, and emits the legacy `validation_result`
# shape so FetchMetrics / FetchArtifact / DGTrackerStage are untouched.

RawValidatorOutput = Box[tuple[dict[str, float], Any]]


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
        return Box(data=(metrics, artifact))
```

Add required imports at top of file (if missing):

```python
from gigaevo.programs.metrics.aggregators import MetricsAggregator
```

- [ ] **Step 1.4: run tests to confirm GREEN**

```bash
$GIGAEVO_PYTHON -m pytest tests/stages/test_parse_metrics_stage.py -x --tb=short
```

Expected: 6 passed.

- [ ] **Step 1.5: lint and commit**

```bash
ruff check gigaevo/programs/stages/python_executors/execution.py tests/stages/test_parse_metrics_stage.py
ruff format --check gigaevo/programs/stages/python_executors/execution.py tests/stages/test_parse_metrics_stage.py
rtk git add gigaevo/programs/stages/python_executors/execution.py tests/stages/test_parse_metrics_stage.py
rtk git commit -m "feat(stages): ParseMetricsStage — aggregator-driven metrics composition"
```

---

## Task 2: Rename `CallValidatorFunction` output edge to `raw_validator_output`

**Files:**
- Modify: `gigaevo/programs/stages/python_executors/execution.py` (rename OutputModel alias; `parse_output` signature unchanged)
- Test: `tests/stages/test_python_executors.py` (update test that asserts the edge/output name if present)

Only cosmetic — the stage still returns `(dict, artifact)`. The consumers are the DAG builders, which we update in Task 3.

- [ ] **Step 2.1 (RED): write failing test for output type alias**

Add to `tests/stages/test_python_executors.py` (append, do not modify other tests):

```python
def test_call_validator_output_is_raw_alias():
    """Task 2: CallValidatorFunction emits RawValidatorOutput (pre-aggregator)."""
    from gigaevo.programs.stages.python_executors.execution import (
        CallValidatorFunction,
        RawValidatorOutput,
    )
    assert CallValidatorFunction.OutputModel is RawValidatorOutput
```

- [ ] **Step 2.2: run test to confirm RED**

```bash
$GIGAEVO_PYTHON -m pytest tests/stages/test_python_executors.py::test_call_validator_output_is_raw_alias -x --tb=short
```

Expected: FAIL (OutputModel is `ValidatorOutput`, not `RawValidatorOutput`).

- [ ] **Step 2.3 (GREEN): point `CallValidatorFunction.OutputModel` at `RawValidatorOutput`**

In `gigaevo/programs/stages/python_executors/execution.py`:

- Keep the `ValidatorOutput = Box[tuple[dict[str, float], Any]]` alias (for back-compat with `ValidationResult` consumers — it's an identical type, just a name).
- Change `CallValidatorFunction.OutputModel = ValidatorOutput` to `OutputModel = RawValidatorOutput`.

That's the only change. The return type of `parse_output` is unchanged (runtime tuple); only the StageIO label changes.

- [ ] **Step 2.4: run tests to confirm GREEN and nothing else broke**

```bash
/run-tests tests/stages/ tests/programs/
```

Expected: the new test passes; existing tests in the suite still pass (no consumer of `ValidatorOutput` exists outside `ValidationResult` itself, which we will rewire in Task 3).

- [ ] **Step 2.5: commit**

```bash
rtk git add gigaevo/programs/stages/python_executors/execution.py tests/stages/test_python_executors.py
rtk git commit -m "refactor(stages): rename CallValidatorFunction output to raw_validator_output"
```

---

## Task 3: Wire `ParseMetricsStage` into `AsymmetricPipelineBuilder`

**Files:**
- Modify: `gigaevo/adversarial/asymmetric_pipeline.py` (construct ParseMetricsStage, insert node, rewire edges in BOTH D and G subgraphs)
- Test: `tests/adversarial_pipeline/test_asymmetric_pipeline.py` (add 3 tests)

The adversarial pipeline is built programmatically, not in custom.yaml. The builder currently adds edges `CallValidatorFunction → FetchMetrics`, `CallValidatorFunction → FetchArtifact`, and `CallValidatorFunction → DGTrackerStage`. We insert `ParseMetricsStage` between `CallValidatorFunction` and the three consumers, connecting `CallValidatorFunction` via `raw_validator_output` to `ParseMetricsStage`, and `ParseMetricsStage` via `validation_result` to the three consumers.

- [ ] **Step 3.1 (RED): write failing tests**

Append to `tests/adversarial_pipeline/test_asymmetric_pipeline.py`:

```python
def test_parse_metrics_stage_present_in_d_pipeline(dummy_d_builder):
    """D-side pipeline must include ParseMetricsStage between CallValidator and FetchMetrics."""
    blueprint = dummy_d_builder.build()
    node_names = {n.name for n in blueprint.nodes}
    assert "ParseMetricsStage" in node_names


def test_parse_metrics_stage_present_in_g_pipeline(dummy_g_builder):
    """G-side pipeline must also include ParseMetricsStage (aggregator = constructor YAML)."""
    blueprint = dummy_g_builder.build()
    node_names = {n.name for n in blueprint.nodes}
    assert "ParseMetricsStage" in node_names


def test_call_validator_feeds_parse_metrics_stage(dummy_d_builder):
    """Edge contract: CallValidatorFunction → ParseMetricsStage on raw_validator_output;
    ParseMetricsStage → FetchMetrics / FetchArtifact / DGTrackerStage on validation_result."""
    blueprint = dummy_d_builder.build()
    edges = blueprint.data_flow_edges
    cv_to_pm = [e for e in edges if e.source_stage == "CallValidatorFunction"]
    assert len(cv_to_pm) == 1
    assert cv_to_pm[0].destination_stage == "ParseMetricsStage"
    assert cv_to_pm[0].input_name == "raw_validator_output"

    pm_outs = {(e.destination_stage, e.input_name) for e in edges if e.source_stage == "ParseMetricsStage"}
    assert ("FetchMetrics", "validation_result") in pm_outs
    assert ("FetchArtifact", "validation_result") in pm_outs
    assert ("DGTrackerStage", "validation_result") in pm_outs


def test_null_aggregator_preserves_legacy_dag(dummy_d_builder_null_aggregator):
    """Builder with NullAggregator keeps legacy edges (non-Heilbron scope unchanged).

    CallValidatorFunction still feeds FetchMetrics / FetchArtifact / DGTrackerStage
    directly; ParseMetricsStage is NOT present. The `dummy_d_builder_null_aggregator`
    fixture passes `aggregator=NullAggregator()`.
    """
    blueprint = dummy_d_builder_null_aggregator.build()
    node_names = {n.name for n in blueprint.nodes}
    assert "ParseMetricsStage" not in node_names
    cv_dests = {(e.destination_stage, e.input_name) for e in blueprint.data_flow_edges if e.source_stage == "CallValidatorFunction"}
    assert ("FetchMetrics", "validation_result") in cv_dests
    assert ("FetchArtifact", "validation_result") in cv_dests
```

Existing fixtures `dummy_d_builder` and `dummy_g_builder` must already exist — if the test file uses a different pattern, adapt. Add `dummy_d_builder_no_aggregator` as a fixture that omits the top-level aggregator.

- [ ] **Step 3.2: run tests to confirm RED**

```bash
$GIGAEVO_PYTHON -m pytest tests/adversarial_pipeline/test_asymmetric_pipeline.py -x -k "parse_metrics or call_validator_feeds" --tb=short
```

Expected: FAIL (no `ParseMetricsStage` in blueprint).

- [ ] **Step 3.3 (GREEN): wire ParseMetricsStage in builder**

In `gigaevo/adversarial/asymmetric_pipeline.py`:

1. Add constructor kwarg `aggregator: MetricsAggregator` (required, but accepts `NullAggregator` as the "none configured" signal) to `AdversarialAsymmetricPipelineBuilder.__init__`. Do NOT default to None; Hydra always resolves `aggregator=none` to a `NullAggregator` instance.
2. **Gate the ParseMetricsStage insertion on `isinstance(self._aggregator, NullAggregator)`.** Non-Heilbron adversarial pipelines (e.g. `heilbron_adversarial`, `adversarial_coevo`) get `aggregator=none` → `NullAggregator` → legacy DAG preserved. Heilbron_repro_v1 gets a real `ConfigurableAggregator` → ParseMetricsStage inserted. This preserves the "non-Heilbron pipelines unchanged" scope constraint from Q6.
3. When `not isinstance(self._aggregator, NullAggregator)`, in the method that assembles nodes/edges (likely `build()` or `_install_stages()`), insert:
   - A new node `ParseMetricsStage` instantiated with `aggregator=self._aggregator`.
   - An edge `CallValidatorFunction → ParseMetricsStage` on `raw_validator_output`.
4. For EVERY existing edge with `source_stage == "CallValidatorFunction"` (FetchMetrics, FetchArtifact, DGTrackerStage), rewrite it so `source_stage = "ParseMetricsStage"` (input_name `validation_result` unchanged).
5. Preserve existing `ExecutionOrderDependency` semantics — if any `exec_order_deps` reference `CallValidatorFunction`, add a dependency `ParseMetricsStage → CallValidatorFunction` (success) and do NOT change the downstream ones (since ParseMetricsStage runs immediately after).

Concrete approach: after the builder constructs all nodes and edges normally, run a post-processing pass that inserts ParseMetricsStage and rewrites edges. This keeps the diff minimal and applies uniformly to both D and G.

Add to `asymmetric_pipeline.py` (near the end of `build`):

```python
# Insert ParseMetricsStage between CallValidatorFunction and its consumers.
# evaluate.py now returns (intrinsic, artifact); ParseMetricsStage composes
# program.metrics via self._aggregator and emits validation_result so
# FetchMetrics / FetchArtifact / DGTrackerStage see their expected shape.
nodes.append(
    NodeSpec(
        name="ParseMetricsStage",
        stage=ParseMetricsStage(
            aggregator=self._aggregator,
            timeout=DEFAULT_SIMPLE_STAGE_TIMEOUT,
        ),
    )
)
rewritten_edges: list[DataFlowEdge] = []
for e in edges:
    if e.source_stage == "CallValidatorFunction" and e.input_name == "validation_result":
        rewritten_edges.append(
            DataFlowEdge(
                source_stage="ParseMetricsStage",
                destination_stage=e.destination_stage,
                input_name="validation_result",
            )
        )
    else:
        rewritten_edges.append(e)
rewritten_edges.append(
    DataFlowEdge(
        source_stage="CallValidatorFunction",
        destination_stage="ParseMetricsStage",
        input_name="raw_validator_output",
    )
)
edges = rewritten_edges
```

Use the correct imports / actual class names (`DataFlowEdge`, `NodeSpec`, whatever the builder's blueprint representation is).

- [ ] **Step 3.4: run tests to confirm GREEN**

```bash
/run-tests tests/adversarial_pipeline/test_asymmetric_pipeline.py
```

Expected: all 4 new tests pass; none of the existing ones regress.

- [ ] **Step 3.5: commit**

```bash
rtk git add gigaevo/adversarial/asymmetric_pipeline.py tests/adversarial_pipeline/test_asymmetric_pipeline.py
rtk git commit -m "feat(adversarial): insert ParseMetricsStage between CallValidator and consumers"
```

---

## Task 4: Hydra wiring — `aggregator=none` default + `aggregator=heilbron_{improver,constructor}` overrides

**Files:**
- Create: `config/aggregator/none.yaml` (NullAggregator sentinel; default for every config)
- Modify: `config/config.yaml` (add `- aggregator: none` to defaults list, alongside `memory: none`, `ideas_tracker: none`)
- Modify: `config/pipeline/heilbron_repro_v1.yaml` (add `pipeline_builder.aggregator: ${ref:aggregator}` and `pipeline_builder.lineage_filter.aggregator: ${ref:aggregator}`; REMOVE the existing `- /aggregator/heilbron_improver@pipeline_builder.lineage_filter.aggregator` targeted default)
- Do NOT modify `config/pipeline/adversarial_asymmetric.yaml`. `heilbron_adversarial` and other adversarial tasks that inherit from it get `aggregator=none` automatically from the top-level default → `NullAggregator` → legacy DAG preserved.
- Test: `tests/entrypoint/test_aggregator_hydra_wiring.py` — Hydra compose tests asserting (a) default is NullAggregator, (b) `aggregator=heilbron_improver` and `aggregator=heilbron_constructor` override cleanly without the `+` prefix, (c) heilbron_repro_v1 + `aggregator=heilbron_improver` resolves both pipeline_builder.aggregator and pipeline_builder.lineage_filter.aggregator to the SAME singleton, (d) heilbron_adversarial still composes cleanly with the default NullAggregator.

**Key decision**: `aggregator=` (regular override), NOT `+aggregator=` (add-new-key). Enabled by making it a real Hydra config group with a `none` default at the top-level `config.yaml`. Launch syntax stays clean: `aggregator=heilbron_improver`.

Decision recap (Q3): D and G need different aggregators. We achieve this by making the top-level `aggregator` a Hydra group: `config/aggregator/heilbron_improver.yaml` for D runs, `config/aggregator/heilbron_constructor.yaml` for G runs. The launch command picks it via `+aggregator=heilbron_improver` (D) / `+aggregator=heilbron_constructor` (G).

The pipeline config references the top-level via `${ref:aggregator}` for BOTH `pipeline_builder.aggregator` (for ParseMetricsStage) and `pipeline_builder.lineage_filter.aggregator` (for SBF-Lineage, D-only). The same singleton is shared across the two references.

- [ ] **Step 4.1 (RED): add Hydra compose test**

Create `tests/entrypoint/test_aggregator_hydra_wiring.py`:

```python
"""Hydra composition test — aggregator group with `none` default + per-role overrides."""

from __future__ import annotations

import pytest
from hydra import compose, initialize_config_dir
from pathlib import Path

CONFIG_DIR = str(Path(__file__).resolve().parents[2] / "config")


def _compose(overrides):
    with initialize_config_dir(config_dir=CONFIG_DIR, version_base=None):
        return compose(config_name="config", overrides=overrides)


def test_default_aggregator_is_null():
    """Top-level default resolves to NullAggregator — no Heilbron pipeline needed."""
    cfg = _compose([
        "pipeline=adversarial_asymmetric",
        "problem.name=heilbron_adversarial/pop_b",
        "redis.db=0",
        "opponent_redis_db=1",
        "opponent_redis_prefix=heilbron_adversarial/pop_a",
        "population_role=improver",
        "feedback_mode=composition",
    ])
    assert cfg.aggregator._target_.endswith("NullAggregator")


def test_heilbron_repro_v1_d_uses_regular_override_not_plus_prefix():
    """aggregator= (no + prefix) — because `aggregator: none` is in defaults."""
    cfg = _compose([
        "pipeline=heilbron_repro_v1",
        "aggregator=heilbron_improver",  # NO '+' prefix
        "problem.name=heilbron_repro_v1/pop_b",
        "redis.db=0",
        "opponent_redis_db=1",
        "opponent_redis_prefix=heilbron_repro_v1/pop_a",
        "population_role=improver",
        "feedback_mode=composition",
    ])
    assert cfg.aggregator._target_.endswith("ConfigurableAggregator")
    # ${ref:aggregator} resolves the SAME singleton into both slots
    assert cfg.pipeline_builder.aggregator._target_ == cfg.aggregator._target_
    assert cfg.pipeline_builder.lineage_filter.aggregator._target_ == cfg.aggregator._target_
    assert "mean_improvement_raw" in cfg.aggregator.outputs


def test_heilbron_repro_v1_g_uses_constructor_aggregator():
    cfg = _compose([
        "pipeline=heilbron_repro_v1",
        "aggregator=heilbron_constructor",
        "problem.name=heilbron_repro_v1/pop_a",
        "redis.db=1",
        "opponent_redis_db=0",
        "opponent_redis_prefix=heilbron_repro_v1/pop_b",
        "population_role=constructor",
        "feedback_mode=composition",
    ])
    assert "resistance" in cfg.aggregator.outputs
    assert cfg.pipeline_builder.aggregator._target_ == cfg.aggregator._target_


def test_heilbron_adversarial_inherits_null_default():
    """heilbron_adversarial doesn't set aggregator — stays NullAggregator → legacy DAG."""
    cfg = _compose([
        "pipeline=adversarial_asymmetric",
        "problem.name=heilbron_adversarial/pop_b",
        "redis.db=0",
        "opponent_redis_db=1",
        "opponent_redis_prefix=heilbron_adversarial/pop_a",
        "population_role=improver",
        "feedback_mode=composition",
    ])
    assert cfg.aggregator._target_.endswith("NullAggregator")


def test_heilbron_repro_v1_without_aggregator_override_is_null():
    """heilbron_repro_v1 without `aggregator=...` override gets NullAggregator.
    The builder's isinstance(NullAggregator) check will skip ParseMetricsStage —
    a valid (if silent) configuration. Launch scripts MUST set aggregator=... to
    opt in. (Preflight contract checks in experiment.yaml catch missing overrides.)"""
    cfg = _compose([
        "pipeline=heilbron_repro_v1",
        "problem.name=heilbron_repro_v1/pop_b",
        "redis.db=0",
        "opponent_redis_db=1",
        "opponent_redis_prefix=heilbron_repro_v1/pop_a",
        "population_role=improver",
        "feedback_mode=composition",
    ])
    assert cfg.aggregator._target_.endswith("NullAggregator")
```

- [ ] **Step 4.2: run test to confirm RED**

```bash
$GIGAEVO_PYTHON -m pytest tests/entrypoint/test_aggregator_hydra_wiring.py -x --tb=short
```

Expected: fail with `pipeline_builder.aggregator` not found or `${ref:aggregator}` unresolved.

- [ ] **Step 4.3a (GREEN): create `config/aggregator/none.yaml`**

```yaml
# @package _global_
# Null-object aggregator. Sentinel that the pipeline builder recognizes via
# isinstance(aggregator, NullAggregator) and treats as 'no aggregator wired —
# use legacy CallValidatorFunction → FetchMetrics DAG'. Default for every
# run; override with `aggregator=heilbron_improver` (etc.) to opt in.
aggregator:
  _target_: gigaevo.programs.metrics.aggregators.NullAggregator
```

- [ ] **Step 4.3b (GREEN): add `aggregator: none` to top-level defaults**

In `config/config.yaml`, add to the `defaults:` list (alongside `memory: none`):

```yaml
  - aggregator: none         # NullAggregator; override with aggregator=heilbron_improver|heilbron_constructor
```

- [ ] **Step 4.3c (GREEN): update `heilbron_repro_v1.yaml`**

In `config/pipeline/heilbron_repro_v1.yaml`:

1. **REMOVE** the existing line from the `defaults:` list:
   ```yaml
   - /aggregator/heilbron_improver@pipeline_builder.lineage_filter.aggregator
   ```

2. **ADD** to the body of the file (appended after the existing overrides), a `pipeline_builder:` override block that points both ParseMetricsStage's aggregator and lineage_filter's aggregator at the shared top-level singleton:

   ```yaml
   pipeline_builder:
     # Aggregator singleton composing program.metrics from per-opp primitives.
     # The same singleton is shared by ParseMetricsStage (program.metrics) and
     # SBF-Lineage (shared-subset TransitionEvidence metrics) — drift impossible.
     # Top-level default is NullAggregator; launch must pass
     # `aggregator=heilbron_improver` (D) or `aggregator=heilbron_constructor` (G).
     aggregator: ${ref:aggregator}
     lineage_filter:
       _target_: gigaevo.adversarial.asymmetric_pipeline.LineageFilterConfig
       min_shared: 1
       inject_shared_evidence: true
       aggregator: ${ref:aggregator}
   ```

Note: `heilbron_repro_v1.yaml` does NOT select a default aggregator (that would force the D aggregator onto G runs). Per-run launch script picks `aggregator=heilbron_improver` (D) or `aggregator=heilbron_constructor` (G). `config/pipeline/adversarial_asymmetric.yaml` stays untouched so `heilbron_adversarial` inherits the top-level `aggregator=none` default and keeps the legacy DAG.

- [ ] **Step 4.4: verify with `--cfg job` for both roles**

```bash
$GIGAEVO_PYTHON run.py --cfg job pipeline=heilbron_repro_v1 aggregator=heilbron_improver \
  problem.name=heilbron_repro_v1/pop_b redis.db=0 opponent_redis_db=1 \
  opponent_redis_prefix=heilbron_repro_v1/pop_a population_role=improver \
  feedback_mode=composition 2>&1 | grep -A2 "^aggregator:\|pipeline_builder.aggregator:" | head -20

$GIGAEVO_PYTHON run.py --cfg job pipeline=heilbron_repro_v1 aggregator=heilbron_constructor \
  problem.name=heilbron_repro_v1/pop_a redis.db=1 opponent_redis_db=0 \
  opponent_redis_prefix=heilbron_repro_v1/pop_b population_role=constructor \
  feedback_mode=composition 2>&1 | grep -A2 "^aggregator:\|pipeline_builder.aggregator:" | head -20
```

Expected: both resolve; `aggregator.outputs` differ between the two. NOTE the regular `aggregator=...` override (no `+` prefix).

- [ ] **Step 4.5: run the Hydra compose tests to confirm GREEN**

```bash
$GIGAEVO_PYTHON -m pytest tests/entrypoint/test_aggregator_hydra_wiring.py -x --tb=short
```

Expected: 3 passed.

- [ ] **Step 4.6: commit**

```bash
rtk git add config/aggregator/none.yaml config/config.yaml config/pipeline/heilbron_repro_v1.yaml tests/entrypoint/test_aggregator_hydra_wiring.py
rtk git commit -m "feat(config): aggregator=none default + ${ref:aggregator} singleton wiring"
```

---

## Task 5: Migrate `problems/heilbron_repro_v1/pop_b/evaluate.py` (D-side — improver)

**Files:**
- Modify: `problems/heilbron_repro_v1/pop_b/evaluate.py` (hard-cut to `(intrinsic, artifact)`; delete `INVALID` dict)
- Test: update `tests/problems/heilbron_repro_v1/test_pop_b_evaluate.py` (or wherever the pop_b parity test lives); add golden-vector test

The new contract: `evaluate(...)` returns `({}, artifact)` on success (intrinsic is empty for the improver — all D metrics are per-opp reductions) and `({}, {"role": "improver", "per_opp_metrics": []})` on candidate failure. The aggregator's `invalid_defaults` handles sentinels.

- [ ] **Step 5.1 (RED): add golden-vector test**

Create `tests/problems/heilbron_repro_v1/test_pop_b_golden_vector.py`:

```python
"""Golden-vector test — pop_b/evaluate.py + heilbron_improver aggregator produces
exact metric values for a fixed input.

This replaces the old parity test: instead of checking that the new pipeline
matches the old Python reduction, we pin the EXPECTED VALUES so future drift
in either side is caught.
"""

from __future__ import annotations

import json
from pathlib import Path

import hydra
import pytest
from hydra import compose, initialize_config_dir

from gigaevo.programs.metrics.context import MetricSpec, MetricsContext

PROBLEM_DIR = Path(__file__).resolve().parents[2].parent / "problems/heilbron_repro_v1/pop_b"
CONFIG_DIR = str(Path(__file__).resolve().parents[2].parent / "config")

EXPECTED = {
    "is_valid": 1.0,
    "n_opponents": 2.0,
    "fitness": 0.35,           # mean of [0.5, 0.2]
    "actual_fitness": 0.35,    # max of [0.35, 0.31]
    "mean_pre_quality": 0.30,
    "mean_post_quality": 0.33, # mean of [0.35, 0.31]
    "max_post_quality": 0.35,
    "mean_improvement_raw": 0.03,  # mean of [0.05, 0.01]
}

FIXTURE = {
    "per_opp_metrics": [
        {"pre_q": 0.30, "post_q": 0.35, "delta": 0.05, "score": 0.5, "is_valid": 1.0},
        {"pre_q": 0.30, "post_q": 0.31, "delta": 0.01, "score": 0.2, "is_valid": 1.0},
    ],
    "role": "improver",
    "n_opponents": 2,
}


def test_pop_b_improver_golden_vector():
    with initialize_config_dir(config_dir=CONFIG_DIR, version_base=None):
        cfg = compose(config_name="config", overrides=[
            "+aggregator=heilbron_improver",
            "problem.name=heilbron_repro_v1/pop_b",
            "redis.db=0",
        ])
    metrics_ctx = MetricsContext(
        specs={
            "fitness": MetricSpec(description="fitness", higher_is_better=True, is_primary=True),
            "is_valid": MetricSpec(description="validity", higher_is_better=True),
        }
    )
    agg = hydra.utils.instantiate(cfg.aggregator, metrics_context=metrics_ctx)
    out = agg.aggregate(FIXTURE["per_opp_metrics"], intrinsic={})
    for k, v in EXPECTED.items():
        assert out[k] == pytest.approx(v), f"{k}: got {out[k]} expected {v}"


def test_pop_b_schema_existence():
    """Every key emitted by the aggregator must be declared in metrics.yaml too.

    Lightweight sanity — fails loudly if we rename or drop an output without
    coordinating with the MetricsContext / metrics.yaml.
    """
    import yaml
    metrics_yaml = PROBLEM_DIR / "metrics.yaml"
    declared = set(yaml.safe_load(metrics_yaml.read_text())["metrics"].keys())
    with initialize_config_dir(config_dir=CONFIG_DIR, version_base=None):
        cfg = compose(config_name="config", overrides=[
            "+aggregator=heilbron_improver",
            "problem.name=heilbron_repro_v1/pop_b",
            "redis.db=0",
        ])
    agg_keys = set(cfg.aggregator.outputs.keys())
    missing = agg_keys - declared
    assert not missing, f"aggregator emits keys not declared in metrics.yaml: {missing}"
```

- [ ] **Step 5.2: run test to confirm RED or GREEN baseline**

```bash
$GIGAEVO_PYTHON -m pytest tests/problems/heilbron_repro_v1/test_pop_b_golden_vector.py -x --tb=short
```

Expected: GREEN. Aggregator already matches old Python reductions (verified by Task 6 parity test). This test LOCKS the values — any drift in `heilbron_improver.yaml` or `per_opp_metrics` shape will fail here.

If RED: the aggregator YAML has a bug or the fixture was computed wrong. Fix before proceeding.

- [ ] **Step 5.3 (MIGRATE): hard-cut `evaluate.py`**

Read `problems/heilbron_repro_v1/pop_b/evaluate.py`. Find:
1. The final return statement that builds `metrics = {...}` (hand-rolled reductions).
2. The `INVALID` dict (sentinel values).
3. The candidate-failure branches returning `(INVALID, artifact)`.

Replace with:
- Success path: `return ({}, artifact)` — artifact contains `per_opp_metrics`, `role="improver"`, `n_opponents`, `per_opp_delta` (back-compat).
- Failure path: `return ({}, {"role": "improver", "per_opp_metrics": [], "n_opponents": 0, "is_valid": False})`.
- Delete `INVALID` dict entirely.
- Delete the `metrics = {...}` construction (all the `mean(...)`, `max(...)` lines).

Keep the loop that builds `per_opp_metrics[i]`. That's the primitives producer.

- [ ] **Step 5.4: delete the OLD pop_b parity test**

Per Q8 decision: parity tests are replaced by golden-vector + schema-existence. Find and DELETE the old `test_pop_b_per_opp_metrics_plus_yaml_aggregator_reproduces_metrics` test (introduced in Task 2 of the prior plan). Use:

```bash
rtk git grep -l "test_pop_b_per_opp_metrics_plus_yaml_aggregator_reproduces_metrics"
```

Delete those assertions or the test file if it contains ONLY parity tests.

- [ ] **Step 5.5: run the full Heilbron test suite**

```bash
/run-tests tests/problems/heilbron_repro_v1/ tests/adversarial_pipeline/
```

Expected: all green. The new golden-vector + schema tests pass; parity tests are gone; adversarial_pipeline suite is insensitive to the evaluate.py contract change (it uses mocks).

- [ ] **Step 5.6: commit**

```bash
rtk git add problems/heilbron_repro_v1/pop_b/evaluate.py tests/problems/heilbron_repro_v1/
rtk git commit -m "feat(heilbron/pop_b): evaluate.py returns (intrinsic, artifact); delete INVALID"
```

---

## Task 6: Migrate `problems/heilbron_repro_v1/pop_a/evaluate.py` (G-side — constructor)

**Files:**
- Modify: `problems/heilbron_repro_v1/pop_a/evaluate.py`
- Test: new `tests/problems/heilbron_repro_v1/test_pop_a_golden_vector.py`; delete old pop_a parity test.

Same pattern as Task 5, but `intrinsic` is non-empty for the constructor: pop_a's `quality` and `actual_fitness` are candidate-level (computed from the program output alone, not from any fight). They must be passed as `intrinsic`, not reduced from per-opp.

- [ ] **Step 6.1 (RED): add pop_a golden-vector test**

Create `tests/problems/heilbron_repro_v1/test_pop_a_golden_vector.py`:

```python
"""Golden-vector test — pop_a/evaluate.py + heilbron_constructor aggregator."""

from __future__ import annotations

from pathlib import Path

import hydra
import pytest
from hydra import compose, initialize_config_dir

from gigaevo.programs.metrics.context import MetricSpec, MetricsContext

CONFIG_DIR = str(Path(__file__).resolve().parents[2].parent / "config")
PROBLEM_DIR = Path(__file__).resolve().parents[2].parent / "problems/heilbron_repro_v1/pop_a"

# Fixture: candidate has intrinsic quality=0.4 (set of 27 points); each D
# improved it to post_q in [0.45, 0.52]. resistance_score = 1.0 iff D did
# NOT improve (delta <= 0), so here both D's improved → resistance=0.0 each.
FIXTURE_INTRINSIC = {"quality": 0.4, "actual_fitness": 0.4}
FIXTURE_PER_OPP = [
    {"pre_q": 0.4, "post_q": 0.45, "delta": 0.05, "score": 0.0, "resistance_score": 0.0, "is_valid": 1.0},
    {"pre_q": 0.4, "post_q": 0.52, "delta": 0.12, "score": 0.0, "resistance_score": 0.0, "is_valid": 1.0},
]
EXPECTED = {
    "is_valid": 1.0,
    "n_opponents": 2.0,
    "quality": 0.4,
    "actual_fitness": 0.4,
    "resistance": 0.0,          # mean of [0, 0]
    "fitness": 0.2,             # 0.5*0.4 + 0.5*0.0
    "mean_improvement": 0.085,  # mean of [0.05, 0.12]
    "best_post_improvement": 0.12,
}


def test_pop_a_constructor_golden_vector():
    with initialize_config_dir(config_dir=CONFIG_DIR, version_base=None):
        cfg = compose(config_name="config", overrides=[
            "+aggregator=heilbron_constructor",
            "problem.name=heilbron_repro_v1/pop_a",
            "redis.db=1",
        ])
    metrics_ctx = MetricsContext(
        specs={
            "fitness": MetricSpec(description="fitness", higher_is_better=True, is_primary=True),
            "is_valid": MetricSpec(description="validity", higher_is_better=True),
        }
    )
    agg = hydra.utils.instantiate(cfg.aggregator, metrics_context=metrics_ctx)
    out = agg.aggregate(FIXTURE_PER_OPP, intrinsic=FIXTURE_INTRINSIC)
    for k, v in EXPECTED.items():
        assert out[k] == pytest.approx(v), f"{k}: got {out[k]} expected {v}"


def test_pop_a_schema_existence():
    import yaml
    metrics_yaml = PROBLEM_DIR / "metrics.yaml"
    declared = set(yaml.safe_load(metrics_yaml.read_text())["metrics"].keys())
    with initialize_config_dir(config_dir=CONFIG_DIR, version_base=None):
        cfg = compose(config_name="config", overrides=[
            "+aggregator=heilbron_constructor",
            "problem.name=heilbron_repro_v1/pop_a",
            "redis.db=1",
        ])
    agg_keys = set(cfg.aggregator.outputs.keys())
    missing = agg_keys - declared
    assert not missing, f"aggregator emits keys not declared in metrics.yaml: {missing}"
```

- [ ] **Step 6.2: run test to confirm GREEN baseline**

```bash
$GIGAEVO_PYTHON -m pytest tests/problems/heilbron_repro_v1/test_pop_a_golden_vector.py -x --tb=short
```

Expected: GREEN. (If RED, check `heilbron_constructor.yaml` — it has a LinearSpec that must read intrinsic `quality` and computed `resistance`.)

- [ ] **Step 6.3 (MIGRATE): hard-cut `pop_a/evaluate.py`**

Pattern:
- Success: `return ({"quality": q, "actual_fitness": q}, artifact)` where `artifact.per_opp_metrics` includes `resistance_score`, `pre_q`, `post_q`, `delta`, `score`, `is_valid`.
- Failure: `return ({}, {"role": "constructor", "per_opp_metrics": [], "n_opponents": 0, "is_valid": False})`.
- Delete `INVALID` dict.
- Delete rolled-up metrics dict.

Keep the per-opponent loop + the `quality` / `actual_fitness` computation (these are candidate-level — they belong in `intrinsic`).

- [ ] **Step 6.4: delete old pop_a parity test**

```bash
rtk git grep -l "test_pop_a_per_opp_metrics_plus_yaml_aggregator_reproduces_metrics"
```

Delete matching assertions / file.

- [ ] **Step 6.5: run tests**

```bash
/run-tests tests/problems/heilbron_repro_v1/ tests/adversarial_pipeline/
```

Expected: all green.

- [ ] **Step 6.6: commit**

```bash
rtk git add problems/heilbron_repro_v1/pop_a/evaluate.py tests/problems/heilbron_repro_v1/
rtk git commit -m "feat(heilbron/pop_a): evaluate.py returns (intrinsic={quality,actual_fitness}, artifact)"
```

---

## Task 7: Launch-script update for `aggregator=...` override

**Files:**
- Modify: `experiments/heilbron/adversarial-repro-v2/launch.sh` (or equivalent)
- Modify: `experiments/heilbron/adversarial-repro-v2/cfg_run_*.yaml` (if they carry extra_overrides)
- Modify: `experiments/heilbron/adversarial-repro-v2/experiment.yaml` (`contract.config.extra` block — add `aggregator: heilbron_improver` for D runs, `aggregator: heilbron_constructor` for G runs, per the preflight contract)

D runs: `aggregator=heilbron_improver`. G runs: `aggregator=heilbron_constructor`. Regular override (no `+` prefix) because the top-level default is `aggregator=none`.

- [ ] **Step 7.1: grep for launch paths**

```bash
rtk git grep -l "opponent_redis_db" experiments/heilbron/adversarial-repro-v2/
ls experiments/heilbron/adversarial-repro-v2/cfg_run_*.yaml 2>/dev/null
```

- [ ] **Step 7.2: add `aggregator=` override**

For each `cfg_run_*_G*.yaml`, append to `extra_overrides`:

```yaml
- "aggregator=heilbron_constructor"
```

For each `cfg_run_*_D*.yaml`, append:

```yaml
- "aggregator=heilbron_improver"
```

For `experiment.yaml`, add to `contract.config.extra` (document the invariant) — note this is a per-run override; experiment.yaml may only carry one value, so pin the D value (since heilbron_repro_v1 is the D-replication target) and let individual cfg_run files override:

```yaml
contract:
  config:
    extra:
      aggregator: heilbron_improver  # pinned; G cfg_run files override to heilbron_constructor
```

- [ ] **Step 7.3: dry-run preview**

For one D cfg and one G cfg, run `--cfg job` preview and grep for `aggregator:`. Expected: non-empty, correct outputs set — and aggregator._target_ is `ConfigurableAggregator` (not `NullAggregator`).

- [ ] **Step 7.4: commit**

```bash
rtk git add experiments/heilbron/adversarial-repro-v2/
rtk git commit -m "feat(v2): set aggregator=heilbron_{improver,constructor} per role"
```

---

## Task 8: Integration smoke test — 3-generation A1_G + A1_D on scratch DB

**Files:** no code changes; runtime verification only.

- [ ] **Step 8.1: flush scratch DBs**

```bash
gigaevo flush --db 14 --confirm
gigaevo flush --db 15 --confirm
```

- [ ] **Step 8.2: launch 3-gen A1_D (DB 14 faces G on 15)**

```bash
cd experiments/heilbron/adversarial-repro-v2
$GIGAEVO_PYTHON ../../../run.py \
  pipeline=heilbron_repro_v1 \
  +aggregator=heilbron_improver \
  problem.name=heilbron_repro_v1/pop_b \
  redis.db=14 \
  opponent_redis_db=15 \
  opponent_redis_prefix=heilbron_repro_v1/pop_a \
  population_role=improver \
  feedback_mode=composition \
  d_sees_g_source=true d_archive_persistent=true \
  experiment.max_generations=3 \
  2>&1 | tee /tmp/smoke_A1_D.log &
SMOKE_D_PID=$!
```

- [ ] **Step 8.3: launch 3-gen A1_G in parallel**

```bash
$GIGAEVO_PYTHON ../../../run.py \
  pipeline=heilbron_repro_v1 \
  +aggregator=heilbron_constructor \
  problem.name=heilbron_repro_v1/pop_a \
  redis.db=15 \
  opponent_redis_db=14 \
  opponent_redis_prefix=heilbron_repro_v1/pop_b \
  population_role=constructor \
  feedback_mode=composition \
  experiment.max_generations=3 \
  2>&1 | tee /tmp/smoke_A1_G.log &
SMOKE_G_PID=$!

wait $SMOKE_D_PID $SMOKE_G_PID
```

- [ ] **Step 8.4: verify logs (three assertions)**

```bash
# (1) No KeyError
! grep -E "KeyError|'fitness'" /tmp/smoke_A1_D.log /tmp/smoke_A1_G.log

# (2) ParseMetricsStage emits metrics with correct key set
grep "\[ParseMetricsStage\]" /tmp/smoke_A1_D.log | head -3
grep "\[ParseMetricsStage\]" /tmp/smoke_A1_G.log | head -3
# expect 'fitness', 'is_valid', 'n_opponents' in the key list

# (3) SBF-Lineage kept lines (D-only)
grep "\[LineageStage:SharedBenchmark\] kept" /tmp/smoke_A1_D.log | head -3
```

All three must pass. If any fail, STOP and diagnose.

- [ ] **Step 8.5: verify Redis state**

```bash
# Programs in D's archive have full metrics dict (not partial)
$GIGAEVO_PYTHON -c "
import redis, json
r = redis.Redis(host='localhost', port=6379, db=14)
# Pick one program and inspect its metrics
for key in r.scan_iter('heilbron_repro_v1/pop_b:program:*', count=5):
    p = r.hgetall(key)
    if b'metrics' in p:
        m = json.loads(p[b'metrics'])
        print(list(m.keys()))
        break
"
```

Expected: `['is_valid', 'n_opponents', 'fitness', 'actual_fitness', 'mean_pre_quality', 'mean_post_quality', 'max_post_quality', 'mean_improvement_raw']` (D schema).

- [ ] **Step 8.6: smoke cleanup**

```bash
gigaevo flush --db 14 --confirm
gigaevo flush --db 15 --confirm
```

---

## Task 9: Final regression sweep

- [ ] **Step 9.1: full targeted test run**

```bash
/run-tests tests/programs/ tests/stages/ tests/adversarial_pipeline/ tests/entrypoint/ tests/problems/heilbron_repro_v1/
```

Expected: all green. Pay attention to ANY new failure not in the pre-existing 25-failure catalog from the main branch baseline.

- [ ] **Step 9.2: lint**

```bash
ruff check . && ruff format --check .
```

Expected: clean.

- [ ] **Step 9.3: final commit (if any pending) and push**

```bash
rtk git status
rtk git log --oneline exp/heilbron/adversarial-repro-v2 ^main | head -20
rtk git push
```

- [ ] **Step 9.4: update PR description**

```bash
gh pr edit <PR#> --body "$(cat <<'EOF'
## Aggregator-First Metrics (landed on top of v2 preregistration)

Summary: makes config/aggregator/*.yaml the single source of truth for
program.metrics. evaluate.py becomes a primitives producer; new
ParseMetricsStage composes metrics from artifact.per_opp_metrics.

**Scope:** heilbron_repro_v1/pop_{a,b} only. Non-Heilbron pipelines unchanged.

**Hard cut:** no back-compat branch. Old evaluate.py contract deleted in
the same PR as the new framework.

Test plan:
- [x] ParseMetricsStage unit tests (6)
- [x] Hydra compose tests — D + G get different aggregators
- [x] Pop_b golden-vector test + schema-existence test
- [x] Pop_a golden-vector test + schema-existence test
- [x] Pipeline-builder wiring tests (ParseMetricsStage present D+G, edges rewired)
- [x] 3-gen smoke A1_G + A1_D — no KeyError, [ParseMetricsStage] emits full schema, [LineageStage:SharedBenchmark] kept lines
EOF
)"
```

---

## Appendix: risk register

| Risk | Mitigation |
|---|---|
| `${ref:aggregator}` resolves to a different singleton than the top-level `aggregator` | Hydra compose test (Task 4) asserts `cfg.pipeline_builder.aggregator._target_ == cfg.aggregator._target_` and that `lineage_filter.aggregator` matches the same. |
| A cfg_run forgets `+aggregator=` override → Hydra fails loudly | Intentional (Q5). Add a preflight check in `experiment-implement` down the line; out of scope for this plan. |
| Golden-vector values drift silently when `heilbron_improver.yaml` changes | That's the test's job. Golden-vector + schema-existence are the two drift guards (Q8). |
| Non-Heilbron pipelines (custom.yaml) regress | Out of scope; they don't insert ParseMetricsStage and continue to use `FetchMetrics` reading directly from `CallValidatorFunction`. The `CallValidatorFunction.OutputModel` rename is type-compatible. |
| Frozen experiment copies on disk break | Running experiments use their own frozen evaluate.py + frozen pipeline configs. The new plan only touches working-tree files; already-running jobs are unaffected. v2 HAS NOT launched yet (Q9 = "this branch before restart"), so no live jobs need protection. |

## Out of scope

- `problems/heilbron_adversarial/*` (Q1: scope limited to heilbron_repro_v1)
- `problems/hover/*`, `problems/hotpotqa/*` (non-Heilbron, unchanged)
- `metrics.yaml` consolidation (Q7: deferred)
- Tanh-smoothed resistance primitive (`TanhSpec`) — out of scope; heilbron_repro_v1 uses hard-floor only.
- G-side SBF-Lineage filter (deferred to IDEAS.yaml)
