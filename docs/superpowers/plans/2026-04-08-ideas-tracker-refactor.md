# IdeasTracker Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 22-file `gigaevo/memory/ideas_tracker/` with 5 clean files using Pydantic models, a unified `Analyzer` protocol, and an in-memory logger — preserving all existing behaviour.

**Architecture:** New source files are created alongside the old tree (Tasks 1–5). Existing tests are updated (Task 6). CLI is updated (Task 7). Old files are deleted (Task 8). At every commit, existing tests stay green. The `components/` and `utils/` directories are replaced by `models.py`, `idea_bank.py`, `llm.py`, and `analyzers.py`. `IdeaTracker` and `_SessionLog` live in the existing `ideas_tracker.py`.

**Tech Stack:** Python 3.12, Pydantic v2 (`BaseModel`, `Field`, `model_copy`, `model_dump`), sentence-transformers, scikit-learn (DBSCAN), openai SDK (sync + async), loguru, pytest, asyncio

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `gigaevo/memory/ideas_tracker/models.py` | All Pydantic models + normalise helpers + `program_to_record` |
| Create | `gigaevo/memory/ideas_tracker/idea_bank.py` | `IdeaBank` + usage-payload helpers |
| Create | `gigaevo/memory/ideas_tracker/llm.py` | `LLMClient` + private `_PromptLoader` |
| Create | `gigaevo/memory/ideas_tracker/analyzers.py` | `Analyzer` protocol + `ClassifyingAnalyzer` + `ClusteringAnalyzer` |
| Rewrite | `gigaevo/memory/ideas_tracker/ideas_tracker.py` | `IdeaTracker` + `_SessionLog` |
| Modify | `gigaevo/memory/ideas_tracker/cli.py` | Update to construct analyzer before `IdeaTracker` |
| Create | `tests/memory/test_models.py` | Unit tests for models + normalise + `program_to_record` |
| Create | `tests/memory/test_idea_bank.py` | Unit tests for `IdeaBank` |
| Modify | `tests/memory/test_ideas_tracker_pipeline.py` | Update import paths + constructor |
| git mv | `components/prompts/` → `prompts/` | Prompt text files (no content changes) |
| Delete | `gigaevo/memory/ideas_tracker/components/` | Entire directory |
| Delete | `gigaevo/memory/ideas_tracker/utils/` (except `origin_analysis.py`) | Superseded by new files |

---

## Task 1: Create `models.py`

**Files:**
- Create: `gigaevo/memory/ideas_tracker/models.py`
- Create: `tests/memory/test_models.py`

- [ ] **Step 1.1: Write the failing tests**

```python
# tests/memory/test_models.py
"""Tests for gigaevo.memory.ideas_tracker.models."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from gigaevo.memory.ideas_tracker.models import (
    AnalysisResult,
    ClassificationChunk,
    EmbeddedIdea,
    Idea,
    IdeaExplanation,
    IdeaUpdate,
    ProgramRecord,
    normalize_improvement_item,
    normalize_improvements,
    program_to_record,
    programs_to_records,
)


class TestNormalizeImprovementItem:
    def test_string_becomes_description(self) -> None:
        result = normalize_improvement_item("Use BFS traversal")
        assert result == {"description": "Use BFS traversal", "explanation": ""}

    def test_dict_with_description_and_explanation(self) -> None:
        result = normalize_improvement_item({"description": "Add cache", "explanation": "reduces calls"})
        assert result["description"] == "Add cache"
        assert result["explanation"] == "reduces calls"

    def test_dict_with_alternative_description_key(self) -> None:
        result = normalize_improvement_item({"summary": "Switched algo", "reason": "faster"})
        assert result["description"] == "Switched algo"
        assert result["explanation"] == "faster"

    def test_non_dict_non_string_uses_stringify(self) -> None:
        result = normalize_improvement_item(42)
        assert result["description"] == "42"
        assert result["explanation"] == ""

    def test_empty_dict_returns_unspecified(self) -> None:
        result = normalize_improvement_item({})
        assert result["description"] == "Unspecified change"

    def test_none_returns_unspecified(self) -> None:
        result = normalize_improvement_item(None)
        assert result["description"] == "Unspecified change"


class TestNormalizeImprovements:
    def test_none_returns_empty_list(self) -> None:
        assert normalize_improvements(None) == []

    def test_list_of_dicts(self) -> None:
        result = normalize_improvements([{"description": "A"}, {"description": "B"}])
        assert len(result) == 2
        assert result[0]["description"] == "A"

    def test_single_non_list_is_wrapped(self) -> None:
        result = normalize_improvements("Single change")
        assert len(result) == 1
        assert result[0]["description"] == "Single change"


class TestIdeaModel:
    def test_id_auto_generated(self) -> None:
        idea = Idea(description="Use BFS")
        assert len(idea.id) == 36  # UUID4 length

    def test_two_ideas_have_different_ids(self) -> None:
        a = Idea(description="A")
        b = Idea(description="B")
        assert a.id != b.id

    def test_explanation_defaults_to_empty(self) -> None:
        idea = Idea(description="test")
        assert idea.explanation.entries == []
        assert idea.explanation.summary == ""

    def test_model_dump_is_serialisable(self) -> None:
        idea = Idea(description="test", programs=["p1"])
        d = idea.model_dump()
        assert d["description"] == "test"
        assert d["programs"] == ["p1"]


class TestAnalysisResult:
    def test_defaults_to_empty_lists(self) -> None:
        result = AnalysisResult()
        assert result.new_ideas == []
        assert result.updates == []

    def test_holds_ideas_and_updates(self) -> None:
        idea = Idea(description="Cache retrieval")
        update = IdeaUpdate(idea_id="abc-123", programs=["p1"])
        result = AnalysisResult(new_ideas=[idea], updates=[update])
        assert len(result.new_ideas) == 1
        assert len(result.updates) == 1


class TestProgramToRecord:
    def _make_program(
        self,
        *,
        fitness: float = 0.75,
        fitness_key: str = "fitness",
        generation: int = 3,
        parents: list[str] | None = None,
        mutation_output: dict | None = None,
    ) -> MagicMock:
        prog = MagicMock()
        prog.id = "prog-uuid-001"
        prog.code = "def solve(): return 42"
        prog.metrics = {fitness_key: fitness}
        prog.lineage.generation = generation
        prog.lineage.parents = parents or ["parent-uuid-001"]
        prog.metadata = {}
        if mutation_output is not None:
            prog.metadata["mutation_output"] = mutation_output
        return prog

    def test_basic_field_mapping(self) -> None:
        prog = self._make_program(
            fitness=7.5,
            generation=4,
            mutation_output={"insights_used": ["Use BFS"], "archetype": "exploration"},
        )
        record = program_to_record(prog, "Solve TSP", "TSP optimisation")
        assert record.id == "prog-uuid-001"
        assert record.fitness == 7.5
        assert record.generation == 4
        assert record.insights == ["Use BFS"]
        assert record.strategy == "exploration"
        assert record.task_description == "Solve TSP"
        assert record.task_description_summary == "TSP optimisation"

    def test_missing_mutation_output_defaults_to_empty(self) -> None:
        prog = self._make_program()
        record = program_to_record(prog, "task", "summary")
        assert record.insights == []
        assert record.strategy == ""
        assert record.improvements == []

    def test_invalid_mutation_output_type_defaults_to_empty(self) -> None:
        prog = self._make_program()
        prog.metadata["mutation_output"] = "not a dict"
        record = program_to_record(prog, "task", "summary")
        assert record.insights == []

    def test_custom_fitness_key(self) -> None:
        prog = self._make_program(fitness_key="accuracy", fitness=0.95)
        record = program_to_record(prog, "task", "summary", fitness_key="accuracy")
        assert record.fitness == 0.95

    def test_programs_to_records_returns_ids(self) -> None:
        progs = [self._make_program() for _ in range(3)]
        for i, p in enumerate(progs):
            p.id = f"id-{i}"
        records, ids = programs_to_records(progs, "task", "summary")
        assert len(records) == 3
        assert ids == {"id-0", "id-1", "id-2"}
```

- [ ] **Step 1.2: Run tests to confirm they fail**

```bash
cd /mnt/virtual_ai0001071-04017_SR004-nfs1/CFS-SR008/workspace/mathemage/gigaevo-core-internal
PYTHONPATH=. /home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/memory/test_models.py -v 2>&1 | tail -5
```

Expected: `ModuleNotFoundError: No module named 'gigaevo.memory.ideas_tracker.models'`

- [ ] **Step 1.3: Create `gigaevo/memory/ideas_tracker/models.py`**

```python
"""
Data models for the IdeasTracker module.

All cross-module data-transfer types are Pydantic BaseModel, providing
validation and serialisation via model_dump(). IdeaCluster is a plain
class — it is a mutable working object internal to ClusteringAnalyzer.
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Improvement normalisation  (mutation output → canonical dict format)
# ---------------------------------------------------------------------------

_DESCRIPTION_KEYS = (
    "description", "summary", "title", "change", "what_changed",
    "pattern", "improvement", "name",
)
_EXPLANATION_KEYS = (
    "explanation", "rationale", "reason", "why", "motivation",
    "expected_effect", "impact", "details", "justification",
)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        parts = [f"{k}: {_stringify(v)}" for k, v in value.items() if _stringify(v)]
        return "; ".join(parts)
    if isinstance(value, (list, tuple, set)):
        return "; ".join(p for p in (_stringify(i) for i in value) if p)
    return str(value).strip()


def normalize_improvement_item(idea: Any) -> dict[str, str]:
    """Coerce a mutation change payload into {"description": ..., "explanation": ...}."""
    if isinstance(idea, str):
        return {"description": idea.strip(), "explanation": ""}
    if not isinstance(idea, dict):
        return {"description": _stringify(idea) or "Unspecified change", "explanation": ""}

    description = next(
        (_stringify(idea[k]) for k in _DESCRIPTION_KEYS if k in idea and _stringify(idea[k])),
        "",
    )
    explanation = next(
        (_stringify(idea[k]) for k in _EXPLANATION_KEYS if k in idea and _stringify(idea[k])),
        "",
    )
    extras = [
        f"{k}: {_stringify(v)}"
        for k, v in idea.items()
        if k not in _DESCRIPTION_KEYS and k not in _EXPLANATION_KEYS and _stringify(v)
    ]
    if not description and extras:
        description, extras = extras[0], extras[1:]
    if not explanation and extras:
        explanation = "; ".join(extras)
    if not description:
        description = explanation or "Unspecified change"
    return {"description": description, "explanation": explanation}


def normalize_improvements(ideas: Any) -> list[dict[str, str]]:
    """Normalise any mutation changes payload to a list of {description, explanation} dicts."""
    if ideas is None:
        return []
    if isinstance(ideas, list):
        return [normalize_improvement_item(i) for i in ideas]
    return [normalize_improvement_item(ideas)]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class IdeaExplanation(BaseModel):
    """Accumulated motivations and synthesised usage summary for an Idea."""

    entries: list[str] = Field(default_factory=list)
    summary: str = ""


class Idea(BaseModel):
    """
    A tracked improvement idea extracted from evolutionary programs.

    Produced by an Analyzer and stored in IdeaBank. Enriched with keywords
    and an explanation summary after initial classification.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    description: str
    category: str = ""
    strategy: str = ""
    task_description: str = ""
    task_description_summary: str = ""
    last_generation: int = 0
    programs: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    explanation: IdeaExplanation = Field(default_factory=IdeaExplanation)
    usage: dict[str, Any] = Field(default_factory=dict)
    aliases: list[dict[str, Any]] = Field(default_factory=list)


class ProgramRecord(BaseModel):
    """
    Metadata extracted from a Program for idea analysis.

    Created from a raw Program object; carries only the fields that
    analysers need (no stage results, no raw execution data).
    """

    id: str
    fitness: float
    generation: int
    parents: list[str] = Field(default_factory=list)
    insights: list[str] = Field(default_factory=list)
    improvements: list[dict[str, str]] = Field(default_factory=list)
    strategy: str = ""
    task_description: str = ""
    task_description_summary: str = ""
    code: str = ""


class IdeaUpdate(BaseModel):
    """Instruction to update an existing Idea already present in IdeaBank."""

    idea_id: str
    programs: list[str] = Field(default_factory=list)
    generation: int = 0
    new_description: str | None = None
    motivation: str | None = None


class AnalysisResult(BaseModel):
    """
    Output of Analyzer.analyze().

    new_ideas: ideas to add to the bank.
    updates: modifications to apply to ideas already in the bank.
    """

    new_ideas: list[Idea] = Field(default_factory=list)
    updates: list[IdeaUpdate] = Field(default_factory=list)


class EmbeddedIdea(BaseModel):
    """
    An improvement card with its sentence-embedding vector.

    Used internally by ClusteringAnalyzer during the embed → cluster → refine pipeline.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    description: str
    source_program_id: str = ""
    cluster_id: str = ""
    change_motivation: str = ""
    embedding: list[float] = Field(default_factory=list)


class ClassificationChunk(BaseModel):
    """A chunk of IdeaBank ideas prepared for one LLM classification call."""

    text: str
    short_ids: list[dict[str, str]]


# ---------------------------------------------------------------------------
# Program → ProgramRecord conversion
# ---------------------------------------------------------------------------

def program_to_record(
    program: Any,
    task_description: str,
    task_description_summary: str,
    fitness_key: str = "fitness",
) -> ProgramRecord:
    """Convert a Program to a ProgramRecord for analyser consumption."""
    mutation_output = program.metadata.get("mutation_output", {})
    if not isinstance(mutation_output, dict):
        mutation_output = {}
    return ProgramRecord(
        id=program.id,
        fitness=program.metrics.get(fitness_key, 0.0),
        generation=program.lineage.generation,
        parents=list(program.lineage.parents),
        insights=mutation_output.get("insights_used") or [],
        improvements=normalize_improvements(mutation_output.get("changes")),
        strategy=mutation_output.get("archetype") or "",
        task_description=task_description,
        task_description_summary=task_description_summary,
        code=program.code,
    )


def programs_to_records(
    programs: list[Any],
    task_description: str,
    task_description_summary: str,
    fitness_key: str = "fitness",
) -> tuple[list[ProgramRecord], set[str]]:
    """Convert a list of Programs to (list[ProgramRecord], set of their ids)."""
    records = [
        program_to_record(p, task_description, task_description_summary, fitness_key)
        for p in programs
    ]
    return records, {p.id for p in programs}
```

- [ ] **Step 1.4: Run tests to confirm they pass**

```bash
PYTHONPATH=. /home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/memory/test_models.py -v 2>&1 | tail -10
```

Expected: all tests PASSED.

- [ ] **Step 1.5: Commit**

```bash
cd /mnt/virtual_ai0001071-04017_SR004-nfs1/CFS-SR008/workspace/mathemage/gigaevo-core-internal
rtk git add gigaevo/memory/ideas_tracker/models.py tests/memory/test_models.py
rtk git commit -m "$(cat <<'EOF'
refactor(ideas-tracker): add models.py — Pydantic models + normalise helpers

Replaces data_components.py and records_converter.py with clean Pydantic
BaseModel types and module-level conversion functions.
EOF
)"
```

---

## Task 2: Create `idea_bank.py`

**Files:**
- Create: `gigaevo/memory/ideas_tracker/idea_bank.py`
- Create: `tests/memory/test_idea_bank.py`

- [ ] **Step 2.1: Write the failing tests**

```python
# tests/memory/test_idea_bank.py
"""Tests for gigaevo.memory.ideas_tracker.idea_bank.IdeaBank."""
from __future__ import annotations

import pytest

from gigaevo.memory.ideas_tracker.idea_bank import IdeaBank, merge_usage_payloads
from gigaevo.memory.ideas_tracker.models import (
    AnalysisResult,
    Idea,
    IdeaExplanation,
    IdeaUpdate,
)


def _idea(description: str = "Test idea", **kwargs) -> Idea:
    return Idea(description=description, **kwargs)


class TestIdeaBankAdd:
    def test_add_single_idea(self) -> None:
        bank = IdeaBank()
        idea = _idea("Use BFS")
        bank.add(idea)
        assert len(bank.all_ideas()) == 1

    def test_add_reassigns_duplicate_id(self) -> None:
        bank = IdeaBank()
        idea = _idea("First")
        bank.add(idea)
        duplicate = idea.model_copy()
        bank.add(duplicate)
        ids = [i.id for i in bank.all_ideas()]
        assert len(set(ids)) == 2  # both ideas have unique ids

    def test_get_returns_idea_by_id(self) -> None:
        bank = IdeaBank()
        idea = _idea("Cache results")
        bank.add(idea)
        assert bank.get(idea.id) is not None
        assert bank.get(idea.id).description == "Cache results"

    def test_get_returns_none_for_unknown_id(self) -> None:
        bank = IdeaBank()
        assert bank.get("nonexistent") is None


class TestIdeaBankApply:
    def test_apply_adds_new_ideas(self) -> None:
        bank = IdeaBank()
        result = AnalysisResult(new_ideas=[_idea("A"), _idea("B")])
        bank.apply(result)
        assert len(bank.all_ideas()) == 2

    def test_apply_runs_updates(self) -> None:
        bank = IdeaBank()
        idea = _idea("Original description", programs=["p0"])
        bank.add(idea)
        upd = IdeaUpdate(idea_id=idea.id, programs=["p1"], generation=5)
        bank.apply(AnalysisResult(updates=[upd]))
        updated = bank.get(idea.id)
        assert "p1" in updated.programs
        assert updated.last_generation == 5


class TestIdeaBankUpdate:
    def test_update_appends_programs(self) -> None:
        bank = IdeaBank()
        idea = _idea("Idea", programs=["p0"])
        bank.add(idea)
        bank.update(IdeaUpdate(idea_id=idea.id, programs=["p1", "p2"]))
        assert set(bank.get(idea.id).programs) == {"p0", "p1", "p2"}

    def test_update_deduplicates_programs(self) -> None:
        bank = IdeaBank()
        idea = _idea("Idea", programs=["p0"])
        bank.add(idea)
        bank.update(IdeaUpdate(idea_id=idea.id, programs=["p0"]))
        assert bank.get(idea.id).programs.count("p0") == 1

    def test_update_bumps_generation_if_greater(self) -> None:
        bank = IdeaBank()
        idea = _idea("Idea", last_generation=3)
        bank.add(idea)
        bank.update(IdeaUpdate(idea_id=idea.id, generation=7))
        assert bank.get(idea.id).last_generation == 7

    def test_update_does_not_lower_generation(self) -> None:
        bank = IdeaBank()
        idea = _idea("Idea", last_generation=10)
        bank.add(idea)
        bank.update(IdeaUpdate(idea_id=idea.id, generation=2))
        assert bank.get(idea.id).last_generation == 10

    def test_update_new_description_archives_old(self) -> None:
        bank = IdeaBank()
        idea = _idea("Old description")
        bank.add(idea)
        bank.update(IdeaUpdate(idea_id=idea.id, new_description="New description"))
        updated = bank.get(idea.id)
        assert updated.description == "New description"
        assert len(updated.aliases) == 1

    def test_update_appends_motivation_to_explanation(self) -> None:
        bank = IdeaBank()
        idea = _idea("Idea", explanation=IdeaExplanation(entries=["first"]))
        bank.add(idea)
        bank.update(IdeaUpdate(idea_id=idea.id, motivation="second reason"))
        updated = bank.get(idea.id)
        assert "second reason" in updated.explanation.entries

    def test_update_returns_false_for_unknown_id(self) -> None:
        bank = IdeaBank()
        assert bank.update(IdeaUpdate(idea_id="ghost")) is False


class TestIdeaBankEnrich:
    def test_enrich_sets_keywords_and_summary(self) -> None:
        bank = IdeaBank()
        idea = _idea("Some idea")
        bank.add(idea)
        bank.enrich(idea.id, keywords=["bfs", "graph"], summary="Uses BFS", task_summary="TSP")
        enriched = bank.get(idea.id)
        assert enriched.keywords == ["bfs", "graph"]
        assert enriched.explanation.summary == "Uses BFS"
        assert enriched.task_description_summary == "TSP"

    def test_enrich_returns_false_for_unknown_id(self) -> None:
        bank = IdeaBank()
        assert bank.enrich("ghost", keywords=[], summary="", task_summary="") is False


class TestIdeaBankChunks:
    def test_empty_bank_returns_empty_chunks(self) -> None:
        bank = IdeaBank(chunk_size=5)
        assert bank.classification_chunks() == []

    def test_chunk_size_splits_correctly(self) -> None:
        bank = IdeaBank(chunk_size=3)
        for i in range(7):
            bank.add(_idea(f"Idea {i}"))
        chunks = bank.classification_chunks()
        assert len(chunks) == 3  # 3 + 3 + 1

    def test_chunk_text_contains_short_ids(self) -> None:
        bank = IdeaBank(chunk_size=5)
        bank.add(_idea("Cache calls"))
        chunk = bank.classification_chunks()[0]
        assert "Cache calls" in chunk.text
        assert len(chunk.short_ids) == 1
        assert "short_id" in chunk.short_ids[0]


class TestMergeUsagePayloads:
    def test_merge_combines_deltas(self) -> None:
        existing = {"used": {"entries": [{"task_description_summary": "task", "fitness_delta_per_use": [2.0], "used_count": 1, "median_delta_fitness": 2.0}], "total": {"total_used": 1, "median_delta_fitness": 2.0}}}
        incoming = {"used": {"entries": [{"task_description_summary": "task", "fitness_delta_per_use": [4.0], "used_count": 1, "median_delta_fitness": 4.0}], "total": {"total_used": 1, "median_delta_fitness": 4.0}}}
        merged = merge_usage_payloads(existing, incoming)
        deltas = merged["used"]["entries"][0]["fitness_delta_per_use"]
        assert sorted(deltas) == [2.0, 4.0]
```

- [ ] **Step 2.2: Run tests to confirm they fail**

```bash
PYTHONPATH=. /home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/memory/test_idea_bank.py -v 2>&1 | tail -5
```

Expected: `ModuleNotFoundError: No module named 'gigaevo.memory.ideas_tracker.idea_bank'`

- [ ] **Step 2.3: Create `gigaevo/memory/ideas_tracker/idea_bank.py`**

```python
"""
IdeaBank: stores and manages Idea objects for an IdeaTracker session.

Also contains usage-payload helpers (build, merge) previously in utils/helpers.py.
"""
from __future__ import annotations

import math
import statistics as _statistics
from typing import Any
from uuid import uuid4

from gigaevo.memory.ideas_tracker.models import (
    AnalysisResult,
    ClassificationChunk,
    Idea,
    IdeaExplanation,
    IdeaUpdate,
)


# ---------------------------------------------------------------------------
# Usage-payload helpers  (was utils/helpers.py)
# ---------------------------------------------------------------------------

def _to_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def _median(values: list[float]) -> float | None:
    return float(_statistics.median(values)) if values else None


def _build_usage_payload(task_to_deltas: dict[str, list[float]]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    total_deltas: list[float] = []
    for task_summary in sorted(task_to_deltas):
        deltas = [d for raw in task_to_deltas[task_summary] if (d := _to_float(raw)) is not None]
        if not deltas:
            continue
        entries.append({
            "task_description_summary": task_summary,
            "used_count": len(deltas),
            "fitness_delta_per_use": deltas,
            "median_delta_fitness": _median(deltas),
        })
        total_deltas.extend(deltas)
    return {
        "used": {
            "entries": entries,
            "total": {
                "total_used": len(total_deltas),
                "median_delta_fitness": _median(total_deltas),
            },
        }
    }


def _extract_task_deltas(usage: Any) -> dict[str, list[float]]:
    if not isinstance(usage, dict):
        return {}
    used = usage.get("used")
    if not isinstance(used, dict):
        return {}
    entries = used.get("entries")
    if not isinstance(entries, list):
        return {}
    result: dict[str, list[float]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        task = str(entry.get("task_description_summary") or "").strip()
        if not task:
            continue
        raw_deltas = entry.get("fitness_delta_per_use") or entry.get("fitness_deltas")
        if not isinstance(raw_deltas, list):
            continue
        deltas = [d for raw in raw_deltas if (d := _to_float(raw)) is not None]
        if deltas:
            result.setdefault(task, []).extend(deltas)
    return result


def merge_usage_payloads(existing: Any, incoming: Any) -> dict[str, Any]:
    """Merge two usage-payload dicts, combining per-task fitness-delta lists."""
    existing_deltas = _extract_task_deltas(existing)
    incoming_deltas = _extract_task_deltas(incoming)
    if not existing_deltas and not incoming_deltas:
        return dict(existing) if isinstance(existing, dict) else (dict(incoming) if isinstance(incoming, dict) else {})
    merged: dict[str, list[float]] = {k: list(v) for k, v in existing_deltas.items()}
    for task, deltas in incoming_deltas.items():
        merged.setdefault(task, []).extend(deltas)
    base: dict[str, Any] = dict(existing) if isinstance(existing, dict) else {}
    if isinstance(incoming, dict):
        for k, v in incoming.items():
            if k != "used":
                base[k] = v
    base["used"] = _build_usage_payload(merged)["used"]
    return base


# ---------------------------------------------------------------------------
# IdeaBank
# ---------------------------------------------------------------------------

class IdeaBank:
    """
    Stores and manages Idea objects for an IdeaTracker session.

    Provides add/get/update/enrich operations and produces chunked
    representations for LLM classification calls (ClassifyingAnalyzer).
    All mutations return a new Idea via model_copy — the internal list
    is updated in place but ideas themselves are treated as immutable.
    """

    def __init__(self, chunk_size: int = 5) -> None:
        self._ideas: list[Idea] = []
        self._ids: set[str] = set()
        self._chunk_size = chunk_size

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def add(self, idea: Idea) -> None:
        """Append an Idea. Reassigns id if it already exists in the bank."""
        if idea.id in self._ids:
            idea = idea.model_copy(update={"id": str(uuid4())})
        self._ideas.append(idea)
        self._ids.add(idea.id)

    def apply(self, result: AnalysisResult) -> None:
        """Add all new_ideas and apply all updates from an AnalysisResult."""
        for idea in result.new_ideas:
            self.add(idea)
        for upd in result.updates:
            self.update(upd)

    def update(self, upd: IdeaUpdate) -> bool:
        """Apply an IdeaUpdate to an existing Idea. Returns False if not found."""
        idx = self._index(upd.idea_id)
        if idx is None:
            return False
        idea = self._ideas[idx]
        patches: dict[str, Any] = {}

        if upd.programs:
            merged_programs = list(dict.fromkeys(idea.programs + upd.programs))
            patches["programs"] = merged_programs

        if upd.generation and upd.generation > idea.last_generation:
            patches["last_generation"] = upd.generation

        if upd.new_description is not None:
            archive_entry = {
                f"{upd.idea_id}-update": {
                    "description": idea.description,
                    "programs": list(idea.programs),
                    "explanations": list(idea.explanation.entries),
                }
            }
            patches["aliases"] = idea.aliases + [archive_entry]
            patches["description"] = upd.new_description

        new_entries = idea.explanation.entries + ([upd.motivation] if upd.motivation else [])
        patches["explanation"] = IdeaExplanation(
            entries=new_entries,
            summary=idea.explanation.summary,
        )

        self._ideas[idx] = idea.model_copy(update=patches)
        return True

    def enrich(
        self,
        idea_id: str,
        *,
        keywords: list[str],
        summary: str,
        task_summary: str,
    ) -> bool:
        """Set keywords, explanation summary, and task_description_summary. Returns False if not found."""
        idx = self._index(idea_id)
        if idx is None:
            return False
        idea = self._ideas[idx]
        self._ideas[idx] = idea.model_copy(update={
            "keywords": keywords,
            "explanation": IdeaExplanation(
                entries=idea.explanation.entries,
                summary=summary,
            ),
            "task_description_summary": task_summary,
        })
        return True

    def apply_usage_updates(self, usage_updates: dict[str, dict[str, Any]]) -> None:
        """Merge per-card usage payloads into matching ideas."""
        for i, idea in enumerate(self._ideas):
            update = usage_updates.get(str(idea.id or ""))
            if update:
                self._ideas[i] = idea.model_copy(
                    update={"usage": merge_usage_payloads(idea.usage, update)}
                )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get(self, idea_id: str) -> Idea | None:
        """Return the Idea with the given id, or None."""
        idx = self._index(idea_id)
        return self._ideas[idx] if idx is not None else None

    def all_ideas(self) -> list[Idea]:
        """Return all ideas in insertion order."""
        return list(self._ideas)

    def classification_chunks(self) -> list[ClassificationChunk]:
        """
        Return ideas grouped into fixed-size chunks for LLM classification.

        Each chunk contains a formatted text block and short-id mappings,
        matching the format expected by ClassifyingAnalyzer._classify_against_bank.
        """
        if not self._ideas:
            return []
        chunks: list[ClassificationChunk] = []
        for i in range(0, len(self._ideas), self._chunk_size):
            batch = self._ideas[i : i + self._chunk_size]
            short_ids = [
                {
                    "id": idea.id,
                    "short_id": idea.id.split("-")[0],
                    "description": idea.description,
                }
                for idea in batch
            ]
            text = "".join(f"[{s['short_id']}]: {s['description']} \n " for s in short_ids)
            chunks.append(ClassificationChunk(text=text, short_ids=short_ids))
        return chunks

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _index(self, idea_id: str) -> int | None:
        if idea_id not in self._ids:
            return None
        return next((i for i, x in enumerate(self._ideas) if x.id == idea_id), None)
```

- [ ] **Step 2.4: Run tests to confirm they pass**

```bash
PYTHONPATH=. /home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/memory/test_idea_bank.py -v 2>&1 | tail -10
```

Expected: all tests PASSED.

- [ ] **Step 2.5: Commit**

```bash
rtk git add gigaevo/memory/ideas_tracker/idea_bank.py tests/memory/test_idea_bank.py
rtk git commit -m "$(cat <<'EOF'
refactor(ideas-tracker): add idea_bank.py — IdeaBank replaces three-layer bank

Replaces RecordListV2 + RecordBank + RecordManager with a single flat class.
Usage-payload helpers from utils/helpers.py are co-located here.
EOF
)"
```

---

## Task 3: Create `llm.py` and move prompt files

**Files:**
- Create: `gigaevo/memory/ideas_tracker/llm.py`
- git mv: `gigaevo/memory/ideas_tracker/components/prompts/` → `gigaevo/memory/ideas_tracker/prompts/`

- [ ] **Step 3.1: Move the prompts directory**

```bash
cd /mnt/virtual_ai0001071-04017_SR004-nfs1/CFS-SR008/workspace/mathemage/gigaevo-core-internal
rtk git mv gigaevo/memory/ideas_tracker/components/prompts gigaevo/memory/ideas_tracker/prompts
```

Verify:
```bash
ls gigaevo/memory/ideas_tracker/prompts/
```

Expected: directories like `classify/`, `classify_ext/`, `keywords/`, `usage_summary/`, etc.

- [ ] **Step 3.2: Create `gigaevo/memory/ideas_tracker/llm.py`**

No new tests needed for this file — it wraps OpenAI (tested via mocking in higher layers).
The existing `test_ideas_tracker_pipeline.py` already mocks `_create_llm_clients`.

```python
"""
LLM client for the IdeasTracker module.

LLMClient wraps an OpenAI-compatible API with prompt-file loading.
Prompts are stored in prompts/{step}/system.txt and prompts/{step}/user.txt
adjacent to this file. _PromptLoader is a private implementation detail.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from loguru import logger
from openai import AsyncOpenAI, OpenAI


class _PromptLoader:
    """Loads prompt text files from the prompts/ directory next to llm.py."""

    def __init__(self) -> None:
        self._dir = Path(__file__).resolve().parent / "prompts"

    def load(self, step: str, prompt_type: str, insert: str | dict[str, str] = "") -> str:
        """
        Load prompts/{step}/{prompt_type}.txt and optionally fill placeholders.

        For user prompts with a string insert, replaces <INSERT>.
        For user prompts with a dict insert, replaces each key with its value.
        """
        path = self._dir / step / f"{prompt_type}.txt"
        if not path.is_file():
            raise FileNotFoundError(f"No prompt at {path}")
        text = path.read_text(encoding="utf-8")
        if prompt_type == "user":
            if isinstance(insert, dict):
                for placeholder, content in insert.items():
                    text = text.replace(placeholder, content)
            else:
                text = text.replace("<INSERT>", insert)
        return text


def _init_clients(base_url: str | None) -> tuple[OpenAI, AsyncOpenAI, bool]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set.")
    env_base = (
        os.getenv("OPENAI_BASE_URL") or os.getenv("BASE_URL") or os.getenv("LLM_BASE_URL")
    )
    effective_url = env_base or base_url
    if not effective_url and api_key.startswith("sk-or-"):
        effective_url = "https://openrouter.ai/api/v1"
    is_openrouter = bool(effective_url and "openrouter.ai" in effective_url)
    kwargs: dict[str, Any] = {"api_key": api_key}
    if effective_url:
        kwargs["base_url"] = effective_url
    return OpenAI(**kwargs), AsyncOpenAI(**kwargs), is_openrouter


class LLMClient:
    """
    OpenAI-compatible LLM client with prompt-file loading.

    Prompts are loaded from prompts/{step}/system.txt and prompts/{step}/user.txt
    next to this file. Supports sync and async calls with optional concurrency limiting.

    Args:
        model: Model identifier (e.g. "google/gemini-3-flash-preview").
        base_url: Optional API base URL override. Falls back to OPENAI_BASE_URL env var.
        max_concurrent: Max parallel async calls. -1 means unlimited.
    """

    def __init__(
        self,
        model: str,
        base_url: str | None = None,
        max_concurrent: int = -1,
    ) -> None:
        self.model = model
        self._sync, self._async, self._is_openrouter = _init_clients(
            str(base_url).strip() if base_url is not None else None
        )
        self._prompts = _PromptLoader()
        self._semaphore = asyncio.Semaphore(max_concurrent) if max_concurrent > 0 else None

    def _build_request(
        self, step: str, content: str | dict[str, str], reasoning: dict | None
    ) -> dict[str, Any]:
        system = self._prompts.load(step, "system")
        user = self._prompts.load(step, "user", content)
        kwargs: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "model": self.model,
            "temperature": 0,
        }
        if self._is_openrouter and reasoning:
            kwargs["extra_body"] = {"reasoning": reasoning}
        if not self._is_openrouter and "Qwen3.5" in self.model:
            kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
        return kwargs

    def call(
        self,
        step: str,
        content: str | dict[str, str] = "",
        reasoning: dict | None = None,
    ) -> str:
        """Synchronous LLM call for the given prompt step."""
        try:
            request = self._build_request(step, content, reasoning)
            return self._sync.chat.completions.create(**request).choices[0].message.content or ""
        except Exception as e:
            logger.error(f"LLMClient.call({step!r}) failed: {e}")
            return ""

    async def call_async(
        self,
        step: str,
        content: str | dict[str, str] = "",
        reasoning: dict | None = None,
    ) -> str:
        """Asynchronous LLM call for the given prompt step."""
        request = self._build_request(step, content, reasoning)

        async def _do() -> str:
            try:
                resp = await self._async.chat.completions.create(**request)
                return resp.choices[0].message.content or ""
            except Exception as e:
                logger.error(f"LLMClient.call_async({step!r}) failed: {e}")
                return ""

        if self._semaphore:
            async with self._semaphore:
                return await _do()
        return await _do()
```

- [ ] **Step 3.3: Run the full test suite to confirm nothing broke**

```bash
PYTHONPATH=. /home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/memory/ -v 2>&1 | tail -15
```

Expected: all existing tests still PASSED (llm.py is a new file, no old code broken yet).

- [ ] **Step 3.4: Commit**

```bash
rtk git add gigaevo/memory/ideas_tracker/llm.py gigaevo/memory/ideas_tracker/prompts/
rtk git commit -m "$(cat <<'EOF'
refactor(ideas-tracker): add llm.py + move prompts/ to package root

LLMClient absorbs PromptManager as private _PromptLoader.
Prompt files moved from components/prompts/ to prompts/.
EOF
)"
```

---

## Task 4: Create `analyzers.py`

**Files:**
- Create: `gigaevo/memory/ideas_tracker/analyzers.py`

No new test file needed — `ClusteringAnalyzer` and `ClassifyingAnalyzer` require real LLMs or deep mocking. Coverage via the integration tests updated in Task 6. We do add one small unit test for the private helper `_split_id` to protect the most fragile parsing logic.

- [ ] **Step 4.1: Add helper unit tests to `test_models.py`**

Append to `tests/memory/test_models.py`:

```python
# Append at end of tests/memory/test_models.py


class TestSplitId:
    """Tests for analyzers._split_id — protects the most fragile LLM-output parser."""

    def test_split_id_from_analyzers(self) -> None:
        # Import here to avoid failing before analyzers.py exists in Tasks 1-3
        from gigaevo.memory.ideas_tracker.analyzers import _split_id

        assert _split_id("abc123:2") == ("abc123", 2)

    def test_split_id_without_sequence_defaults_to_one(self) -> None:
        from gigaevo.memory.ideas_tracker.analyzers import _split_id

        assert _split_id("[abc123]") == ("abc123", 1)

    def test_split_id_strips_brackets(self) -> None:
        from gigaevo.memory.ideas_tracker.analyzers import _split_id

        assert _split_id("[abc123:3]") == ("abc123", 3)
```

- [ ] **Step 4.2: Run these tests to confirm they fail**

```bash
PYTHONPATH=. /home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/memory/test_models.py::TestSplitId -v 2>&1 | tail -5
```

Expected: `ImportError` — `analyzers` not found yet.

- [ ] **Step 4.3: Create `gigaevo/memory/ideas_tracker/analyzers.py`**

```python
"""
Idea analysers for IdeasTracker.

Analyzer      — Protocol that both analysers implement.
ClassifyingAnalyzer — Sequential per-program LLM classification against the idea bank.
ClusteringAnalyzer  — Batch embedding + DBSCAN + async LLM refinement pipeline.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from copy import copy
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import numpy as np
from dotenv import load_dotenv
from loguru import logger
from sentence_transformers import SentenceTransformer
from sklearn.cluster import DBSCAN
from tqdm import tqdm

from gigaevo.memory.ideas_tracker.idea_bank import IdeaBank
from gigaevo.memory.ideas_tracker.llm import LLMClient
from gigaevo.memory.ideas_tracker.models import (
    AnalysisResult,
    EmbeddedIdea,
    Idea,
    IdeaExplanation,
    IdeaUpdate,
    ProgramRecord,
)

load_dotenv()


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class Analyzer(Protocol):
    """
    Common interface for idea analysers.

    Both ClassifyingAnalyzer and ClusteringAnalyzer implement this protocol,
    allowing IdeaTracker to use either without branching on type.
    """

    model: str

    def analyze(self, records: list[ProgramRecord], bank: IdeaBank) -> AnalysisResult:
        """Extract and classify improvement ideas from a batch of program records."""
        ...

    def call(self, step: str, content: str | dict[str, str] = "") -> str:
        """Synchronous LLM call — used by the enrichment step in IdeaTracker."""
        ...

    async def call_async(self, step: str, content: str | dict[str, str] = "") -> str:
        """Asynchronous LLM call — used by the enrichment step in IdeaTracker."""
        ...


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _split_id(idea_ref: str) -> tuple[str, int]:
    """
    Parse ``shortId:sequence`` from classify_ext LLM output.

    If the model omits ``:sequence``, returns sequence 1 (best-effort).
    Strips surrounding square brackets if present.
    """
    raw = idea_ref.strip()
    if ":" not in raw:
        return raw.strip("[]"), 1
    left, right = raw.split(":", 1)
    return left.strip("[]"), int(right.strip("[]"))


# ---------------------------------------------------------------------------
# ClassifyingAnalyzer  (was IdeaAnalyzer)
# ---------------------------------------------------------------------------

@dataclass
class _PendingIdeas:
    """
    Scratch object tracking classification state for a single program's improvements.

    Private to ClassifyingAnalyzer — not exported.
    """
    items: list[dict[str, Any]] = field(default_factory=list)
    mapping: dict[int, str] = field(default_factory=dict)

    @classmethod
    def from_improvements(cls, improvements: list[dict[str, str]]) -> _PendingIdeas:
        items = [
            {
                "description": i["description"],
                "motivation": i.get("explanation", ""),
                "classified": False,
                "target_id": "",
                "rewrite": False,
            }
            for i in improvements
        ]
        pending = cls(items=items)
        pending.refresh_mapping()
        return pending

    def refresh_mapping(self) -> None:
        mapping: dict[int, str] = {}
        c = 1
        for item in self.items:
            if not item["classified"]:
                mapping[c] = item["description"]
                c += 1
        self.mapping = mapping

    def mark_classified(self, seq_num: int, target_id: str, rewrite: bool) -> None:
        desc = self.mapping.get(seq_num)
        if desc is None:
            logger.warning(f"ClassifyingAnalyzer: no pending idea at position {seq_num}")
            return
        for item in self.items:
            if item["description"] == desc:
                item["target_id"] = target_id
                item["classified"] = True
                item["rewrite"] = rewrite
                break

    @property
    def unclassified_count(self) -> int:
        return sum(1 for i in self.items if not i["classified"])

    def as_numbered_text(self) -> str:
        lines: list[str] = []
        c = 1
        for item in self.items:
            if not item["classified"]:
                lines.append(f"{c}) {item['description']} \n")
                c += 1
        return "".join(lines)


class ClassifyingAnalyzer:
    """
    Classifies incoming improvement ideas against an existing idea bank using an LLM.

    Processes programs sequentially. For each program, asks the LLM whether each
    incoming idea is new, an update to an existing idea, or a rewrite of one.
    The bank is read at call time via analyze(records, bank) — not stored at construction,
    so the same analyser instance can serve multiple IdeaTracker sessions.

    Args:
        model: LLM model identifier.
        base_url: Optional OpenAI-compatible API base URL.
        reasoning: Optional OpenRouter reasoning settings (e.g. {"effort": "low"}).
        retry_attempts: LLM call retries on JSON parse failure.
        description_rewriting: If True, allow the LLM to rewrite idea descriptions.
    """

    def __init__(
        self,
        model: str = "google/gemini-3-flash-preview",
        base_url: str | None = None,
        reasoning: dict[str, Any] | None = None,
        retry_attempts: int = 10,
        description_rewriting: bool = True,
    ) -> None:
        self.model = model
        self._reasoning = reasoning or {}
        self._retry_attempts = retry_attempts
        self._description_rewriting = description_rewriting
        self._llm = LLMClient(model=model, base_url=base_url)

    def call(self, step: str, content: str | dict[str, str] = "") -> str:
        """Synchronous LLM call — used by IdeaTracker enrichment step."""
        return self._llm.call(step, content, self._reasoning)

    async def call_async(self, step: str, content: str | dict[str, str] = "") -> str:
        """Asynchronous LLM call — used by IdeaTracker enrichment step."""
        return await self._llm.call_async(step, content, self._reasoning)

    def analyze(self, records: list[ProgramRecord], bank: IdeaBank) -> AnalysisResult:
        """
        Classify all program improvements against the bank.

        Returns an AnalysisResult with new ideas to add and updates to apply.
        """
        result = AnalysisResult()
        for record in tqdm(records, leave=False, desc="Classifying programs"):
            pending = _PendingIdeas.from_improvements(record.improvements)
            if not pending.items:
                continue
            self._classify_against_bank(pending, bank.classification_chunks())
            self._apply_pending_to_result(pending, record, result)
        return result

    def _classify_against_bank(
        self, pending: _PendingIdeas, chunks: list
    ) -> None:
        """Classify pending ideas against each bank chunk, updating pending in place."""
        for chunk in chunks:
            if pending.unclassified_count == 0:
                break
            unclassified_text = pending.as_numbered_text()
            prompt = f" Existing Ideas: \n {chunk.text} \n Incoming Ideas: \n {unclassified_text}"
            parsed: dict[str, list[Any]] = {"present_ideas": [], "new_ideas": [], "updated_ideas": []}
            for _ in range(self._retry_attempts):
                try:
                    raw = self._llm.call("classify_ext", prompt, self._reasoning)
                    parsed = json.loads(raw)
                    break
                except Exception as e:
                    logger.error(f"ClassifyingAnalyzer classify error: {e}")

            for ref in parsed.get("present_ideas", []):
                short_id, seq = _split_id(ref)
                full_id = self._resolve_id(short_id, chunk.short_ids)
                if full_id:
                    pending.mark_classified(seq, full_id, False)

            for item in parsed.get("updated_ideas", []):
                short_id, seq = _split_id(item["id"])
                full_id = self._resolve_id(short_id, chunk.short_ids)
                if full_id:
                    pending.mark_classified(seq, full_id, True)

            pending.refresh_mapping()

    def _resolve_id(self, short_id: str, short_ids: list[dict[str, str]]) -> str:
        """Map a short UUID prefix to a full UUID, or return '' if not found."""
        for entry in short_ids:
            if entry["short_id"] == short_id:
                return entry["id"]
        return ""

    def _apply_pending_to_result(
        self, pending: _PendingIdeas, record: ProgramRecord, result: AnalysisResult
    ) -> None:
        """Convert classified/unclassified pending items into AnalysisResult entries."""
        for item in pending.items:
            if not item["classified"]:
                result.new_ideas.append(Idea(
                    description=item["description"],
                    category=record.category if hasattr(record, "category") else "",
                    strategy=record.strategy,
                    task_description=record.task_description,
                    last_generation=record.generation,
                    programs=[record.id],
                    explanation=IdeaExplanation(entries=[item["motivation"]] if item["motivation"] else []),
                ))
            elif item["rewrite"]:
                result.updates.append(IdeaUpdate(
                    idea_id=item["target_id"],
                    programs=[record.id],
                    generation=record.generation,
                    new_description=item["description"] if self._description_rewriting else None,
                    motivation=item["motivation"] or None,
                ))
            else:
                result.updates.append(IdeaUpdate(
                    idea_id=item["target_id"],
                    programs=[record.id],
                    generation=record.generation,
                    motivation=item["motivation"] or None,
                ))


# ---------------------------------------------------------------------------
# ClusteringAnalyzer  (was IdeaAnalyzerFast)
# ---------------------------------------------------------------------------

def _extract_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from model output, allowing surrounding prose or fences."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        return json.loads(m.group())
    raise json.JSONDecodeError("No JSON object found", text, 0)


def _validate_partition(
    included: list[Any], rejected: list[Any], start: int, end: int
) -> tuple[list[int], list[int]]:
    """Validate that included + rejected form an exact partition of start..end (inclusive)."""
    if not isinstance(included, list) or not isinstance(rejected, list):
        raise ValueError("included and rejected must be lists")
    if start > end:
        raise ValueError("empty index range")
    inc = [int(x) for x in included]
    rej = [int(x) for x in rejected]
    expected = set(range(start, end + 1))
    if len(inc + rej) != len(expected) or set(inc + rej) != expected:
        raise ValueError("partition does not cover the range exactly once")
    return inc, rej


class IdeaCluster:
    """
    A mutable cluster of EmbeddedIdea instances.

    Internal working object for ClusteringAnalyzer — not exported as a data model.
    """

    def __init__(self, cluster_id: str) -> None:
        self.cluster_id = cluster_id
        self.center: list[float] = []
        self.members: list[EmbeddedIdea] = []
        self.index_to_card: dict[int, EmbeddedIdea] = {}
        self.has_changed: bool = True

    @property
    def size(self) -> int:
        return len(self.members)

    def add_member(self, card: EmbeddedIdea) -> None:
        card.cluster_id = self.cluster_id
        self.members.append(card)
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        self.index_to_card = {i + 1: c for i, c in enumerate(self.members)}

    def prune_stale(self) -> None:
        """Remove members whose cluster_id no longer matches this cluster."""
        self.members = [c for c in self.members if c.cluster_id == self.cluster_id]
        self._rebuild_index()

    def numbered_text(self) -> str:
        return "".join(f"{i+1}) {c.description} \n" for i, c in enumerate(self.members))

    def numbered_groups(self, subgroup_size: int) -> list[str]:
        if subgroup_size < 1:
            raise ValueError("subgroup_size must be >= 1")
        n = len(self.members)
        if n == 0:
            return []
        if subgroup_size >= n:
            return [self.numbered_text()]
        groups: list[str] = []
        for i in range(0, n, subgroup_size):
            chunk = self.members[i : i + subgroup_size]
            groups.append("".join(f"{i+j+1}) {c.description} \n" for j, c in enumerate(chunk)))
        return groups


class ClusteringAnalyzer:
    """
    Groups improvement ideas by semantic similarity using embeddings, DBSCAN,
    and async LLM refinement.

    Processes all program records in a single batch. Does not consult the existing
    bank — always returns new_ideas with an empty updates list. The bank parameter
    in analyze() is accepted for protocol compatibility but ignored.

    Args:
        model: LLM model for refine and representative steps.
        embeddings_model: sentence-transformers model id.
        base_url: Optional API base URL override.
        reasoning: Optional OpenRouter reasoning settings.
        batch_size: Encoding batch size.
        min_samples_for_dbscan: Below this count, skip DBSCAN and use one cluster.
        dbscan_eps: Cosine DBSCAN epsilon.
        dbscan_min_samples: DBSCAN min_samples.
        max_attempts: LLM call retries per step.
        max_rounds: Refinement loop upper bound.
        refine_subgroup_size: Max ideas per refine LLM call.
        llm_max_concurrent: Semaphore limit for async LLM calls.
    """

    def __init__(
        self,
        model: str = "google/gemini-3-flash-preview",
        embeddings_model: str = "sentence-transformers/all-mpnet-base-v2",
        base_url: str | None = None,
        reasoning: dict[str, Any] | None = None,
        batch_size: int = 32,
        min_samples_for_dbscan: int = 4,
        dbscan_eps: float = 0.25,
        dbscan_min_samples: int = 2,
        max_attempts: int = 10,
        max_rounds: int = 20,
        refine_subgroup_size: int = 20,
        llm_max_concurrent: int = 100,
    ) -> None:
        self.model = model
        self._reasoning = reasoning or {}
        self._batch_size = batch_size
        self._min_samples = min_samples_for_dbscan
        self._dbscan_eps = dbscan_eps
        self._dbscan_min_samples = dbscan_min_samples
        self._max_attempts = max_attempts
        self._max_rounds = max_rounds
        self._subgroup_size = refine_subgroup_size
        self._llm = LLMClient(model=model, base_url=base_url, max_concurrent=llm_max_concurrent)
        self._embed_model = SentenceTransformer(embeddings_model)
        self._benchmark_times: list[float] = []
        self._benchmark_clusters: list[int] = []

    def call(self, step: str, content: str | dict[str, str] = "") -> str:
        """Synchronous LLM call — used by IdeaTracker enrichment step."""
        return self._llm.call(step, content, self._reasoning)

    async def call_async(self, step: str, content: str | dict[str, str] = "") -> str:
        """Asynchronous LLM call — used by IdeaTracker enrichment step."""
        return await self._llm.call_async(step, content, self._reasoning)

    def analyze(self, records: list[ProgramRecord], bank: IdeaBank) -> AnalysisResult:
        """
        Embed, cluster, refine, and return one Idea per surviving cluster.

        bank is accepted for protocol compatibility but not used — ClusteringAnalyzer
        always produces fresh ideas without deduplicating against the existing bank.
        """
        return AnalysisResult(new_ideas=asyncio.run(self._run_async(records)))

    # ------------------------------------------------------------------
    # Async pipeline
    # ------------------------------------------------------------------

    async def _run_async(self, records: list[ProgramRecord]) -> list[Idea]:
        cards = self._flatten_to_cards(records)
        if not cards:
            return []
        t0 = time.perf_counter()
        self._embed(cards)
        clusters = self._build_clusters(cards)
        await self._refine_loop(clusters, t0)
        for c in clusters:
            c.prune_stale()
        clusters = [c for c in clusters if c.size > 0]
        tasks = [self._cluster_to_idea(c, {p.id: p for p in records}) for c in clusters]
        return list(await asyncio.gather(*tasks))

    def _flatten_to_cards(self, records: list[ProgramRecord]) -> list[EmbeddedIdea]:
        cards: list[EmbeddedIdea] = []
        for record in records:
            for imp in record.improvements:
                cards.append(EmbeddedIdea(
                    description=str(imp.get("description", "")),
                    source_program_id=record.id,
                    change_motivation=str(imp.get("explanation", "")),
                ))
        return cards

    def _embed(self, cards: list[EmbeddedIdea]) -> None:
        texts = [c.description for c in cards]
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            vecs = self._embed_model.encode(batch, convert_to_numpy=True, show_progress_bar=False)
            for i, vec in enumerate(vecs):
                cards[start + i].embedding = vec.astype(np.float64).tolist()

    def _mean_center(self, members: list[EmbeddedIdea]) -> list[float]:
        if not members:
            return []
        return np.array([m.embedding for m in members], dtype=np.float64).mean(axis=0).tolist()

    def _build_clusters(self, cards: list[EmbeddedIdea]) -> list[IdeaCluster]:
        n = len(cards)
        if n < self._min_samples:
            c = IdeaCluster(str(uuid.uuid4()))
            for card in cards:
                c.add_member(card)
            c.center = self._mean_center(c.members)
            return [c]

        mat = np.array([c.embedding for c in cards], dtype=np.float64)
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        mat = mat / np.where(norms == 0, 1.0, norms)
        labels = DBSCAN(
            eps=self._dbscan_eps, min_samples=self._dbscan_min_samples, metric="cosine"
        ).fit(mat).labels_

        clusters: list[IdeaCluster] = []
        for label in sorted(set(labels.tolist())):
            idxs = np.where(labels == label)[0]
            if label == -1:
                for i in idxs:
                    cl = IdeaCluster(str(uuid.uuid4()))
                    cl.add_member(cards[int(i)])
                    cl.center = self._mean_center(cl.members)
                    clusters.append(cl)
            else:
                cl = IdeaCluster(str(uuid.uuid4()))
                for i in idxs:
                    cl.add_member(cards[int(i)])
                cl.center = self._mean_center(cl.members)
                clusters.append(cl)
        return clusters

    async def _refine_loop(self, clusters: list[IdeaCluster], t0: float) -> None:
        self._benchmark_times.clear()
        self._benchmark_clusters.clear()
        pbar = tqdm(total=self._max_rounds, desc="Refinement rounds")
        for _ in range(self._max_rounds):
            for c in clusters:
                c.prune_stale()
            clusters[:] = [c for c in clusters if c.size > 0]
            eligible = [c for c in clusters if c.size >= 2 and c.has_changed]
            if not eligible:
                break
            pairs = list(zip(
                eligible,
                await asyncio.gather(*[self._refine_cluster(c) for c in eligible]),
                strict=True,
            ))
            changed = self._apply_refinements(clusters, pairs)
            pbar.update(1)
            pbar.set_postfix(clusters=len(clusters))
            self._benchmark_times.append(time.perf_counter() - t0)
            self._benchmark_clusters.append(len(clusters))
            if not changed:
                break
        pbar.close()

    async def _refine_cluster(
        self, cluster: IdeaCluster
    ) -> tuple[list[int], list[int]] | None:
        sg = self._subgroup_size
        groups = cluster.numbered_groups(sg)
        n = cluster.size
        if not groups:
            return None

        async def run_subgroup(gi: int, text: str) -> tuple[list[int], list[int]] | None:
            i0 = gi * sg
            start, end = i0 + 1, i0 + min(sg, n - i0)
            for _ in range(self._max_attempts):
                try:
                    raw = await self._llm.call_async("cluster_fast_refine", text, self._reasoning)
                    data = _extract_json_object(raw)
                    return _validate_partition(data.get("included", []), data.get("rejected", []), start, end)
                except (json.JSONDecodeError, ValueError, KeyError, TypeError):
                    continue
            return None

        parts = await asyncio.gather(*[run_subgroup(gi, t) for gi, t in enumerate(groups)])
        if any(p is None for p in parts):
            return None
        merged_inc: list[int] = []
        merged_rej: list[int] = []
        for p in parts:
            assert p is not None
            merged_inc.extend(p[0])
            merged_rej.extend(p[1])
        return merged_inc, merged_rej

    def _apply_refinements(
        self,
        clusters: list[IdeaCluster],
        pairs: list[tuple[IdeaCluster, tuple[list[int], list[int]] | None]],
    ) -> bool:
        changed = False
        for cluster, parsed in pairs:
            if parsed is None:
                cluster.has_changed = True
                changed = True
                continue
            inc_idx, rej_idx = parsed
            if not rej_idx:
                cluster.has_changed = False
                continue
            changed = True
            cluster.has_changed = True
            inc_set = set(inc_idx)
            rej_set = set(rej_idx)
            included_cards = [cluster.index_to_card[i] for i in sorted(inc_set)]
            rejected_cards = [cluster.index_to_card[i] for i in sorted(rej_set)]
            cluster.members = included_cards
            cluster._rebuild_index()
            for c in included_cards:
                c.cluster_id = cluster.cluster_id
            if rejected_cards:
                new_cluster = IdeaCluster(str(uuid.uuid4()))
                seen: set[str] = set()
                for c in rejected_cards:
                    if c.id not in seen:
                        seen.add(c.id)
                        new_cluster.add_member(c)
                if new_cluster.size > 0:
                    new_cluster.center = self._mean_center(new_cluster.members)
                    clusters.append(new_cluster)
        clusters[:] = [c for c in clusters if c.size > 0]
        return changed

    async def _cluster_to_idea(
        self, cluster: IdeaCluster, records_by_id: dict[str, ProgramRecord]
    ) -> Idea:
        members = cluster.members
        if not members:
            raise ValueError("empty cluster")

        if len(members) == 1:
            rep = members[0]
        else:
            rep = await self._pick_representative(cluster) or members[0]

        prog = records_by_id.get(rep.source_program_id)
        strategy = prog.strategy if prog else ""
        task_description = prog.task_description if prog else ""
        gen = prog.generation if prog else 0

        all_gens = [records_by_id[m.source_program_id].generation for m in members if m.source_program_id in records_by_id]
        last_gen = max(all_gens) if all_gens else gen

        programs = list(dict.fromkeys(m.source_program_id for m in members if m.source_program_id))
        motivations = [m.change_motivation for m in members if m.change_motivation]
        other_descriptions = [m.description for m in members if m is not rep and m.description]

        if len(members) > 1:
            desc = await self._synthesise_description(rep.description, other_descriptions, motivations)
            description = desc or rep.description
        else:
            description = rep.description

        return Idea(
            description=description,
            strategy=strategy,
            task_description=task_description,
            last_generation=last_gen,
            programs=programs,
            explanation=IdeaExplanation(entries=motivations),
        )

    async def _pick_representative(self, cluster: IdeaCluster) -> EmbeddedIdea | None:
        text = cluster.numbered_text()
        for _ in range(self._max_attempts):
            try:
                raw = await self._llm.call_async("cluster_fast_representative", text, self._reasoning)
                data = _extract_json_object(raw)
                idx = int(data["representative_index"])
                if 1 <= idx <= cluster.size:
                    return cluster.index_to_card.get(idx)
            except (json.JSONDecodeError, ValueError, KeyError, TypeError):
                continue
        return None

    async def _synthesise_description(
        self, rep_description: str, other_descriptions: list[str], motivations: list[str]
    ) -> str:
        all_desc = "".join(f"{k}) {d} \n" for k, d in enumerate(other_descriptions))
        all_motiv = "".join(f"{k}) {m} \n" for k, m in enumerate(motivations))
        prompt = {
            "<INSERT_REP>": f"- {rep_description}",
            "<INSERT_DES>": all_desc,
            "<INSERT_EXPL>": all_motiv,
        }
        for _ in range(self._max_attempts):
            try:
                return await self._llm.call_async("cluster_desc_synth", prompt, self._reasoning)
            except Exception as e:
                logger.error(f"ClusteringAnalyzer desc_synth failed: {e}")
        return ""
```

- [ ] **Step 4.4: Run split-id tests to confirm they pass**

```bash
PYTHONPATH=. /home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/memory/test_models.py::TestSplitId -v 2>&1 | tail -5
```

Expected: 3 tests PASSED.

- [ ] **Step 4.5: Run the full test suite**

```bash
PYTHONPATH=. /home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/memory/ -v 2>&1 | tail -15
```

Expected: all tests PASSED (no old code broken).

- [ ] **Step 4.6: Commit**

```bash
rtk git add gigaevo/memory/ideas_tracker/analyzers.py tests/memory/test_models.py
rtk git commit -m "$(cat <<'EOF'
refactor(ideas-tracker): add analyzers.py — Analyzer protocol + ClassifyingAnalyzer + ClusteringAnalyzer

IdeaAnalyzer → ClassifyingAnalyzer, IdeaAnalyzerFast → ClusteringAnalyzer.
Both implement the Analyzer protocol with analyze(records, bank) -> AnalysisResult.
IncomingIdeas replaced by private _PendingIdeas dataclass.
EOF
)"
```

---

## Task 5: Rewrite `ideas_tracker.py`

**Files:**
- Rewrite: `gigaevo/memory/ideas_tracker/ideas_tracker.py`

The old file is replaced entirely. The new file imports from the four new modules.
Existing tests that patch the old module paths will be updated in Task 6.

- [ ] **Step 5.1: Write the new `gigaevo/memory/ideas_tracker/ideas_tracker.py`**

```python
"""
IdeaTracker: PostRunHook that extracts, classifies, enriches, and stores
improvement ideas from a completed evolutionary run.

_SessionLog accumulates log entries in memory and writes all files to a
timestamped directory in a single flush() call at session end.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import statistics as _statistics
from datetime import datetime
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dotenv import load_dotenv
from loguru import logger

from gigaevo.evolution.engine.hooks import PostRunHook
from gigaevo.memory.ideas_tracker.analyzers import Analyzer, ClassifyingAnalyzer, ClusteringAnalyzer
from gigaevo.memory.ideas_tracker.idea_bank import IdeaBank
from gigaevo.memory.ideas_tracker.models import (
    Idea,
    IdeaExplanation,
    ProgramRecord,
    program_to_record,
)
from gigaevo.programs.program import EXCLUDE_STAGE_RESULTS, Program

if TYPE_CHECKING:
    from gigaevo.database.program_storage import ProgramStorage

load_dotenv()


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _to_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def _load_task_description(redis_prefix: str, package_path: Path) -> str:
    """Load task_description.txt from the matching problems/ directory."""
    prefix = (redis_prefix or "").replace("/", "_")
    if not prefix:
        return "No description available"
    problems_root = package_path.parents[3] / "problems"
    try:
        for root, dirs, _ in os.walk(problems_root):
            if "initial_programs" in dirs:
                leaf = Path(root)
                split = leaf.parts.index("problems") + 1
                name = "_".join(leaf.parts[split:])
                if name == prefix:
                    candidate = leaf / "task_description.txt"
                    if candidate.is_file():
                        return candidate.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return "No description available"


def _summarise_task_description(analyzer: Analyzer, task_description: str) -> str:
    """Ask the LLM for a compact summary of the task description."""
    text = str(task_description or "").strip()
    if not text:
        return "Task summary unavailable"
    try:
        raw = analyzer.call("task_description_summary", text)
        parsed = json.loads(raw)
        summary = str(parsed.get("summary", "")).strip()
        return summary or text[:240].strip()
    except Exception:
        return text[:240].strip()


def _build_usage_updates(
    programs: list[Program],
    task_summary: str,
    fitness_key: str,
) -> dict[str, dict[str, Any]]:
    """Build per-memory-card usage payloads from program fitness deltas."""
    from gigaevo.evolution.mutation.constants import MUTATION_MEMORY_SELECTED_IDS_METADATA_KEY
    from gigaevo.memory.ideas_tracker.idea_bank import _build_usage_payload, _to_float as _f

    def _as_string_list(value: Any) -> list[str]:
        import ast
        if isinstance(value, list):
            return [str(i).strip() for i in value if str(i).strip()]
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            if text[0] in "[{(":
                try:
                    return [str(i).strip() for i in json.loads(text) if str(i).strip()]
                except Exception:
                    try:
                        return [str(i).strip() for i in ast.literal_eval(text) if str(i).strip()]
                    except Exception:
                        pass
            return [text]
        return []

    fitness_by_id: dict[str, float] = {}
    for prog in programs:
        f = _f(prog.metrics.get(fitness_key))
        if f is not None:
            fitness_by_id[prog.id] = f

    usage_by_card: dict[str, dict[str, list[float]]] = {}
    for prog in programs:
        selected = _as_string_list(prog.metadata.get(MUTATION_MEMORY_SELECTED_IDS_METADATA_KEY))
        if not selected:
            continue
        child_fitness = _f(prog.metrics.get(fitness_key))
        if child_fitness is None:
            continue
        parent_fitnesses = [fitness_by_id[pid] for pid in prog.lineage.parents if pid in fitness_by_id]
        if not parent_fitnesses:
            continue
        delta = child_fitness - max(parent_fitnesses)
        for card_id in list(dict.fromkeys(selected)):
            usage_by_card.setdefault(card_id, {}).setdefault(task_summary, []).append(delta)

    return {
        card_id: _build_usage_payload(task_deltas)
        for card_id, task_deltas in usage_by_card.items()
    }


async def _enrich_ideas(
    ideas: list[Idea], analyzer: Analyzer, task_summary: str
) -> list[Idea]:
    """Enrich all ideas concurrently with keywords and explanation summaries."""

    async def _enrich_one(idea: Idea) -> Idea:
        keywords: list[str] = []
        try:
            kw_raw = await analyzer.call_async("keywords", idea.description)
            keywords = json.loads(kw_raw).get("keywords", [])
        except Exception:
            pass

        summary = ""
        entries = idea.explanation.entries
        if len(entries) == 1:
            summary = entries[0]
        elif len(entries) > 1:
            explanations_text = "\n".join(f"- {e}" for e in entries)
            try:
                sum_raw = await analyzer.call_async("usage_summary", explanations_text)
                summary = json.loads(sum_raw).get("summary", "")
            except Exception:
                pass

        return idea.model_copy(update={
            "keywords": keywords,
            "explanation": IdeaExplanation(entries=entries, summary=summary),
            "task_description_summary": task_summary,
        })

    return list(await asyncio.gather(*[_enrich_one(idea) for idea in ideas]))


def _run_write_pipeline(
    enabled: bool,
    banks_path: Path | None,
    best_ideas_path: Path | None,
    programs_path: Path | None,
    usage_updates_path: Path | None,
    memory_usage_tracking_enabled: bool,
) -> None:
    """Optionally trigger the downstream memory write pipeline."""
    if not enabled:
        return
    if banks_path is None or best_ideas_path is None:
        logger.warning("Memory write pipeline skipped: log paths unavailable.")
        return
    if not banks_path.exists():
        logger.warning(f"Memory write pipeline skipped: missing {banks_path}.")
        return

    try:
        with best_ideas_path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        has_snapshot = isinstance(payload, list) and any(
            isinstance(i, dict) and "best_ideas" in i for i in payload
        )
    except Exception:
        has_snapshot = False

    if not has_snapshot:
        logger.warning("Memory write pipeline skipped: no best_ideas snapshot.")
        return

    env_overrides = {
        "MEMORY_BANKS_PATH": str(banks_path),
        "MEMORY_BEST_IDEAS_PATH": str(best_ideas_path),
    }
    if programs_path and programs_path.exists():
        env_overrides["MEMORY_PROGRAMS_PATH"] = str(programs_path)
    if memory_usage_tracking_enabled and usage_updates_path and usage_updates_path.exists():
        env_overrides["MEMORY_USAGE_UPDATES_PATH"] = str(usage_updates_path)

    previous = {k: os.environ.get(k) for k in env_overrides}
    try:
        import importlib
        os.environ.update(env_overrides)
        mod = importlib.import_module("gigaevo.memory.write_pipeline")
        mod = importlib.reload(mod)
        snapshot = mod.main()
        if isinstance(snapshot, dict):
            stats = snapshot.get("stats", {})
            if isinstance(stats, dict):
                logger.info(
                    f"Memory write: processed={stats.get('processed',0)}, "
                    f"added={stats.get('added',0)}, updated={stats.get('updated',0)}, "
                    f"rejected={stats.get('rejected',0)}"
                )
    finally:
        for k, v in previous.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---------------------------------------------------------------------------
# _SessionLog
# ---------------------------------------------------------------------------

class _SessionLog:
    """
    Accumulates log entries in memory during a tracker run and writes all
    files to a timestamped session directory in a single flush() call.

    Replaces the per-event read-modify-write pattern of IdeasTrackerLogger.
    Files written: log.txt, banks.json, programs.json, best_ideas.json,
    memory_usage_updates.json.
    """

    def __init__(self, logs_dir: Path) -> None:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.session_dir: Path = logs_dir / ts
        self._entries: list[str] = []
        self._usage_updates: dict[str, Any] = {}

    # ------ file paths (None until flush()) ------
    @property
    def banks_file(self) -> Path:
        return self.session_dir / "banks.json"

    @property
    def programs_file(self) -> Path:
        return self.session_dir / "programs.json"

    @property
    def best_ideas_file(self) -> Path:
        return self.session_dir / "best_ideas.json"

    @property
    def usage_updates_file(self) -> Path:
        return self.session_dir / "memory_usage_updates.json"

    # ------ recording ------

    def record(self, action: str, **params: Any) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [f"[{ts}]: {action}"]
        for k, v in params.items():
            lines.append(f"  {k}: {v}")
        self._entries.append("\n".join(lines))

    def record_usage_updates(self, updates: dict[str, Any]) -> None:
        self._usage_updates = updates

    # ------ flush ------

    def flush(
        self,
        bank: IdeaBank,
        *,
        records: list[ProgramRecord],
    ) -> None:
        """Write all accumulated data to the timestamped session directory."""
        self.session_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        (self.session_dir / "log.txt").write_text(
            "\n\n".join(self._entries), encoding="utf-8"
        )

        banks_data = [{
            "active_bank": [i.model_dump() for i in bank.all_ideas()],
            "timestamp": ts,
        }]
        self.banks_file.write_text(json.dumps(banks_data, indent=2), encoding="utf-8")

        programs_data = [{
            "timestamp": ts,
            "programs": [r.model_dump() for r in records],
        }]
        self.programs_file.write_text(json.dumps(programs_data, indent=2), encoding="utf-8")

        self.usage_updates_file.write_text(
            json.dumps([{"timestamp": ts, "usage_updates": self._usage_updates}], indent=2),
            encoding="utf-8",
        )

        self._compute_and_write_statistics()

    def _compute_and_write_statistics(self) -> None:
        """Run origin analysis and inject per-idea statistics into banks.json."""
        if not self.banks_file.exists() or not self.programs_file.exists():
            return
        try:
            import pandas as pd
            from gigaevo.memory.ideas_tracker.utils.origin_analysis import compute_origin_analysis

            df_summary, df_best_ideas = compute_origin_analysis(
                banks_path=str(self.banks_file),
                programs_path=str(self.programs_file),
            )
        except RuntimeError as exc:
            if "No valid programs" in str(exc):
                return
            raise
        except Exception as exc:
            logger.warning(f"Could not compute evolutionary statistics: {exc}")
            return

        if df_summary.empty:
            return

        # Inject per-idea stats into banks.json
        stats_by_idea: dict[str, dict] = {}
        for _, row in df_summary.iterrows():
            idea_id = row["idea_id"]
            quartile = row["quartile"]
            metrics = {
                k: (v if pd.notna(v) else None)
                for k, v in row.drop(["idea_id", "quartile", "description"]).items()
            }
            stats_by_idea.setdefault(idea_id, {})[quartile] = metrics

        banks_data = json.loads(self.banks_file.read_text(encoding="utf-8"))
        for snapshot in banks_data:
            if not isinstance(snapshot, dict):
                continue
            for idea in snapshot.get("active_bank", []):
                if isinstance(idea, dict) and idea.get("id") in stats_by_idea:
                    idea["evolution_statistics"] = stats_by_idea[idea["id"]]
        self.banks_file.write_text(json.dumps(banks_data, indent=2), encoding="utf-8")

        # Write best_ideas.json
        best_ideas = [
            {k: (v if pd.notna(v) else None) for k, v in row.items()}
            for _, row in df_best_ideas.iterrows()
        ]
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.best_ideas_file.write_text(
            json.dumps([{"timestamp": ts, "best_ideas": best_ideas}], indent=2),
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# IdeaTracker
# ---------------------------------------------------------------------------

class IdeaTracker(PostRunHook):
    """
    PostRunHook that extracts, classifies, enriches, and stores improvement
    ideas from a completed evolutionary run.

    Instantiated by Hydra. Accepts a ClassifyingAnalyzer or ClusteringAnalyzer —
    both implement the Analyzer protocol, so the pipeline is identical for both.

    Args:
        analyzer: The idea analyser to use. If None, defaults to ClassifyingAnalyzer
            with its own default model — useful for the CLI entry point.
        task_description: Human-readable description of the current task. If empty,
            loaded from the matching problems/ directory using redis_prefix.
        redis_prefix: Redis key prefix (e.g. "chains/hotpotqa/static") used to
            locate the task_description.txt file when task_description is empty.
        chunk_size: Number of ideas per LLM classification batch.
        memory_write_enabled: If True, trigger the downstream memory write pipeline.
        memory_usage_tracking_enabled: If True, compute fitness deltas for memory cards.
        fitness_key: Metric key to use as fitness (default "fitness").
        logs_dir: Directory for timestamped session logs. Defaults to
            gigaevo/memory/ideas_tracker/logs/.
    """

    def __init__(
        self,
        *,
        analyzer: ClassifyingAnalyzer | ClusteringAnalyzer | None = None,
        task_description: str = "",
        redis_prefix: str = "",
        chunk_size: int = 5,
        memory_write_enabled: bool = True,
        memory_usage_tracking_enabled: bool = True,
        fitness_key: str = "fitness",
        logs_dir: str | Path | None = None,
    ) -> None:
        if analyzer is None:
            analyzer = ClassifyingAnalyzer()

        self._analyzer: ClassifyingAnalyzer | ClusteringAnalyzer = analyzer
        self._bank = IdeaBank(chunk_size=chunk_size)
        self._fitness_key = fitness_key
        self._memory_write_enabled = memory_write_enabled
        self._memory_usage_tracking_enabled = memory_usage_tracking_enabled
        self._all_records: list[ProgramRecord] = []
        self._seen_ids: set[str] = set()

        if task_description:
            self._task_description = task_description
        else:
            self._task_description = _load_task_description(
                redis_prefix, Path(__file__).resolve()
            )

        resolved_logs = (
            Path(logs_dir) if logs_dir is not None
            else Path(__file__).resolve().parent / "logs"
        )
        resolved_logs.mkdir(parents=True, exist_ok=True)
        self._log = _SessionLog(resolved_logs)

    @cached_property
    def _task_summary(self) -> str:
        """Computed once on first access; cached for the lifetime of this instance."""
        return _summarise_task_description(self._analyzer, self._task_description)

    # ------------------------------------------------------------------
    # PostRunHook interface
    # ------------------------------------------------------------------

    async def on_run_complete(self, storage: ProgramStorage) -> None:
        """Called by EvolutionEngine after the generation loop finishes."""
        programs = await storage.get_all(exclude=EXCLUDE_STAGE_RESULTS)
        if not programs:
            logger.warning("IdeaTracker: no programs in storage, skipping.")
            return
        await self._run(programs)

    # ------------------------------------------------------------------
    # CLI entry point
    # ------------------------------------------------------------------

    def run(self, programs: list[Program] | None = None) -> None:
        """CLI entry: accepts list[Program] directly."""
        if not programs:
            return
        asyncio.run(self._run(programs))

    # ------------------------------------------------------------------
    # Core pipeline
    # ------------------------------------------------------------------

    async def _run(self, programs: list[Program]) -> None:
        """Full pipeline: filter → analyse → enrich → log → write."""
        if self._memory_usage_tracking_enabled:
            usage_updates = _build_usage_updates(programs, self._task_summary, self._fitness_key)
            self._log.record_usage_updates(usage_updates)
        else:
            usage_updates = {}

        records = self._eligible_records(programs)

        result = self._analyzer.analyze(records, self._bank)
        self._bank.apply(result)

        if self._memory_usage_tracking_enabled and usage_updates:
            self._bank.apply_usage_updates(usage_updates)

        enriched = await _enrich_ideas(self._bank.all_ideas(), self._analyzer, self._task_summary)
        for idea in enriched:
            self._bank.enrich(
                idea.id,
                keywords=idea.keywords,
                summary=idea.explanation.summary,
                task_summary=self._task_summary,
            )

        self._log.record("pipeline_complete", total_ideas=len(self._bank.all_ideas()))
        self._log.flush(self._bank, records=self._all_records)

        _run_write_pipeline(
            self._memory_write_enabled,
            self._log.banks_file,
            self._log.best_ideas_file,
            self._log.programs_file,
            self._log.usage_updates_file,
            self._memory_usage_tracking_enabled,
        )

    def _eligible_records(self, programs: list[Program]) -> list[ProgramRecord]:
        """
        Filter programs and convert to ProgramRecord.

        Skips: root programs (no parents), zero/negative fitness, already-seen ids.
        """
        eligible: list[Program] = []
        for prog in programs:
            if not prog.lineage.parents:
                continue
            fitness = _to_float(prog.metrics.get(self._fitness_key))
            if fitness is None or fitness <= 0:
                continue
            if prog.id in self._seen_ids:
                continue
            eligible.append(prog)

        records = [
            program_to_record(p, self._task_description, self._task_summary, self._fitness_key)
            for p in eligible
        ]
        self._all_records.extend(records)
        self._seen_ids.update(p.id for p in eligible)
        return records
```

- [ ] **Step 5.2: Run the full existing test suite**

```bash
PYTHONPATH=. /home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/memory/test_ideas_tracker_pipeline.py -v 2>&1 | tail -20
```

Expected: some tests will fail because import paths for `program_to_record`, `programs_to_records`, `build_memory_usage_updates_from_programs`, and `IdeaTracker` constructor patches have changed. That is expected — Task 6 fixes them.

- [ ] **Step 5.3: Commit the rewrite (tests broken is OK — we fix in Task 6)**

```bash
rtk git add gigaevo/memory/ideas_tracker/ideas_tracker.py
rtk git commit -m "$(cat <<'EOF'
refactor(ideas-tracker): rewrite ideas_tracker.py — clean pipeline + _SessionLog

IdeaTracker now takes an Analyzer object directly (no string type dispatch).
_SessionLog replaces IdeasTrackerLogger with in-memory accumulation + single flush.
_enrich_ideas is one async function (replaces 4-function postprocessing.py).
_task_summary is a cached_property (replaces manual sentinel cache).
EOF
)"
```

---

## Task 6: Update existing tests

**Files:**
- Modify: `tests/memory/test_ideas_tracker_pipeline.py`

- [ ] **Step 6.1: Update `tests/memory/test_ideas_tracker_pipeline.py`**

Replace the file with the updated version below. The test logic is unchanged;
only import paths and constructor patches are updated.

```python
"""Comprehensive tests for the IdeaTracker post-run hook pipeline.

Three layers, from fastest to slowest:

1. Unit tests — records_converter, helpers, program filtering
2. OOP contract tests — PostRunHook ABC, NullPostRunHook, Hydra composability
3. Integration tests — EvolutionEngine → PostRunHook → IdeaTracker pipeline
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

from gigaevo.evolution.engine.config import EngineConfig
from gigaevo.evolution.engine.core import EvolutionEngine
from gigaevo.evolution.engine.hooks import NullPostRunHook, PostRunHook
from gigaevo.memory.ideas_tracker.models import (
    program_to_record,
    programs_to_records,
)
from gigaevo.memory.ideas_tracker.idea_bank import IdeaBank
from gigaevo.programs.program import Lineage, Program
from gigaevo.programs.program_state import ProgramState

_TEST_NAMESPACE = uuid.NAMESPACE_DNS


def _uuid(test_id: str) -> str:
    return str(uuid.uuid5(_TEST_NAMESPACE, test_id))


def _make_program(
    *,
    code: str = "def solve(): return 42",
    fitness: float = 0.75,
    fitness_key: str = "fitness",
    generation: int = 3,
    parents: list[str] | None = None,
    mutation_output: dict[str, Any] | None = None,
    memory_ids: list[str] | None = None,
    state: ProgramState = ProgramState.DONE,
    program_id: str | None = None,
) -> Program:
    metadata: dict[str, Any] = {}
    if mutation_output is not None:
        metadata["mutation_output"] = mutation_output
    if memory_ids is not None:
        metadata["memory_selected_idea_ids"] = memory_ids
    parent_list = parents or (["parent-1"] if generation > 1 else [])
    parent_uuids = [_uuid(p) if isinstance(p, str) else p for p in parent_list]
    lineage = Lineage(parents=parent_uuids, generation=max(generation, 1))
    prog = Program(code=code, state=state, metrics={fitness_key: fitness}, metadata=metadata, lineage=lineage)
    if program_id is not None:
        object.__setattr__(prog, "id", _uuid(program_id))
    return prog


def _make_root_program(*, fitness: float = 1.0) -> Program:
    return _make_program(parents=[], generation=1, fitness=fitness)


def _make_evolved_program(
    *,
    fitness: float = 5.0,
    parent_id: str = "seed-01",
    generation: int = 3,
    insights: list[str] | None = None,
    changes: list[str] | None = None,
    archetype: str = "exploitation",
) -> Program:
    mutation_output: dict[str, Any] = {"archetype": archetype}
    if insights is not None:
        mutation_output["insights_used"] = insights
    if changes is not None:
        mutation_output["changes"] = changes
    return _make_program(fitness=fitness, generation=generation, parents=[parent_id], mutation_output=mutation_output)


def _make_memory_program(*, fitness: float = 8.0, parent_id: str = "parent-a", card_ids: list[str] | None = None) -> Program:
    return _make_program(fitness=fitness, generation=5, parents=[parent_id], memory_ids=card_ids or ["idea-001", "idea-002"])


# ---------------------------------------------------------------------------
# Helper: build_memory_usage_updates_from_programs
# ---------------------------------------------------------------------------

def _build_memory_usage_updates(programs, task_summary="", fitness_key="fitness"):
    """Thin wrapper so tests don't need to import the internal helper directly."""
    from gigaevo.memory.ideas_tracker.ideas_tracker import _build_usage_updates
    return _build_usage_updates(programs, task_summary or "Task summary unavailable", fitness_key)


class TestBuildMemoryUsageFromPrograms:
    def test_empty_programs_returns_empty(self) -> None:
        assert _build_memory_usage_updates([]) == {}

    def test_programs_without_memory_ids_return_empty(self) -> None:
        progs = [_make_evolved_program() for _ in range(3)]
        assert _build_memory_usage_updates(progs) == {}

    def test_single_card_usage_computes_delta(self) -> None:
        parent = _make_program(program_id="parent-a", fitness=5.0, parents=[], generation=1)
        child = _make_memory_program(fitness=8.0, parent_id="parent-a", card_ids=["idea-1"])
        result = _build_memory_usage_updates([parent, child], "test task")
        assert "idea-1" in result
        entries = result["idea-1"]["used"]["entries"]
        assert len(entries) == 1
        assert entries[0]["used_count"] == 1
        assert entries[0]["fitness_delta_per_use"] == [3.0]
        assert entries[0]["median_delta_fitness"] == 3.0

    def test_negative_delta_included(self) -> None:
        parent = _make_program(program_id="p1", fitness=10.0, parents=[], generation=1)
        child = _make_memory_program(fitness=7.0, parent_id="p1", card_ids=["c1"])
        result = _build_memory_usage_updates([parent, child], "task")
        assert result["c1"]["used"]["entries"][0]["fitness_delta_per_use"] == [-3.0]

    def test_multiple_cards_per_program(self) -> None:
        parent = _make_program(program_id="p1", fitness=4.0, parents=[], generation=1)
        child = _make_memory_program(fitness=6.0, parent_id="p1", card_ids=["a", "b", "c"])
        result = _build_memory_usage_updates([parent, child], "t")
        assert set(result.keys()) == {"a", "b", "c"}

    def test_missing_parent_fitness_skips_program(self) -> None:
        child = _make_memory_program(fitness=8.0, parent_id="unknown-parent", card_ids=["c1"])
        assert _build_memory_usage_updates([child], "task") == {}

    def test_custom_fitness_key(self) -> None:
        parent = _make_program(program_id="p1", fitness=3.0, fitness_key="accuracy", parents=[], generation=1)
        child = _make_program(fitness=5.0, fitness_key="accuracy", generation=3, parents=["p1"], memory_ids=["c1"])
        result = _build_memory_usage_updates([parent, child], "task", "accuracy")
        assert "c1" in result

    def test_duplicate_card_ids_deduplicated(self) -> None:
        parent = _make_program(program_id="p1", fitness=1.0, parents=[], generation=1)
        child = _make_memory_program(fitness=2.0, parent_id="p1", card_ids=["dup", "dup", "dup"])
        result = _build_memory_usage_updates([parent, child], "task")
        assert result["dup"]["used"]["total"]["total_used"] == 1


# ---------------------------------------------------------------------------
# records_converter tests (now in models.py)
# ---------------------------------------------------------------------------

class TestProgramToRecord:
    def test_basic_field_mapping(self) -> None:
        prog = _make_evolved_program(fitness=7.5, generation=4, parent_id="p1", insights=["Use BFS"], changes=["Added BFS traversal"], archetype="exploration")
        record = program_to_record(prog, "Solve TSP", "TSP optimisation")
        assert record.id == prog.id
        assert record.fitness == 7.5
        assert record.generation == 4
        assert record.parents == [_uuid("p1")]
        assert record.insights == ["Use BFS"]
        assert record.strategy == "exploration"

    def test_missing_mutation_output_defaults_to_empty(self) -> None:
        prog = _make_program(mutation_output=None)
        record = program_to_record(prog, "task", "summary")
        assert record.insights == []
        assert record.strategy == ""

    def test_invalid_mutation_output_type_defaults_to_empty(self) -> None:
        prog = _make_program()
        prog.metadata["mutation_output"] = "not a dict"
        record = program_to_record(prog, "task", "summary")
        assert record.insights == []

    def test_missing_fitness_defaults_to_zero(self) -> None:
        prog = _make_program()
        prog.metrics.clear()
        record = program_to_record(prog, "task", "summary")
        assert record.fitness == 0.0

    def test_custom_fitness_key(self) -> None:
        prog = _make_program(fitness_key="accuracy")
        prog.metrics["accuracy"] = 0.95
        record = program_to_record(prog, "task", "summary", fitness_key="accuracy")
        assert record.fitness == 0.95


class TestProgramsToRecords:
    def test_empty_list(self) -> None:
        records, ids = programs_to_records([], "task", "summary")
        assert records == []
        assert ids == set()

    def test_returns_records_and_ids(self) -> None:
        progs = [_make_evolved_program(fitness=f) for f in [1.0, 2.0, 3.0]]
        records, ids = programs_to_records(progs, "task", "summary")
        assert len(records) == 3
        assert ids == {p.id for p in progs}


# ---------------------------------------------------------------------------
# PostRunHook ABC
# ---------------------------------------------------------------------------

class TestPostRunHookABC:
    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError):
            PostRunHook()

    def test_abc_defines_on_run_complete(self) -> None:
        assert hasattr(PostRunHook, "on_run_complete")

    def test_concrete_subclass_must_implement_on_run_complete(self) -> None:
        class Incomplete(PostRunHook):
            pass
        with pytest.raises(TypeError):
            Incomplete()


class TestNullPostRunHook:
    def test_instantiates_without_arguments(self) -> None:
        hook = NullPostRunHook()
        assert isinstance(hook, PostRunHook)

    @pytest.mark.asyncio
    async def test_on_run_complete_is_noop(self) -> None:
        hook = NullPostRunHook()
        storage = AsyncMock()
        await hook.on_run_complete(storage)
        storage.get_all.assert_not_called()


# ---------------------------------------------------------------------------
# IdeaTracker as PostRunHook
# ---------------------------------------------------------------------------

def _make_tracker(**kwargs):
    from gigaevo.memory.ideas_tracker.ideas_tracker import IdeaTracker
    from gigaevo.memory.ideas_tracker.analyzers import ClassifyingAnalyzer

    mock_llm_clients = (MagicMock(), MagicMock(), False)
    with patch(
        "gigaevo.memory.ideas_tracker.llm._init_clients",
        return_value=mock_llm_clients,
    ), patch(
        "gigaevo.memory.ideas_tracker.ideas_tracker._summarise_task_description",
        return_value="Test summary",
    ):
        analyzer = ClassifyingAnalyzer(model="mock-model")
        return IdeaTracker(analyzer=analyzer, task_description="Test task", **kwargs)


class TestIdeaTrackerIsPostRunHook:
    def test_is_subclass_of_post_run_hook(self) -> None:
        from gigaevo.memory.ideas_tracker.ideas_tracker import IdeaTracker
        assert issubclass(IdeaTracker, PostRunHook)

    def test_instantiates_with_analyzer(self) -> None:
        tracker = _make_tracker()
        from gigaevo.memory.ideas_tracker.ideas_tracker import IdeaTracker
        assert isinstance(tracker, PostRunHook)
        assert tracker._fitness_key == "fitness"

    def test_analyzer_types_importable(self) -> None:
        from gigaevo.memory.ideas_tracker.analyzers import ClassifyingAnalyzer, ClusteringAnalyzer
        assert ClassifyingAnalyzer is not None
        assert ClusteringAnalyzer is not None


class TestIdeaTrackerProgramFiltering:
    def test_root_programs_are_skipped(self) -> None:
        tracker = _make_tracker()
        root = _make_root_program(fitness=10.0)
        evolved = _make_evolved_program(fitness=5.0)
        result = tracker._eligible_records([root, evolved])
        assert len(result) == 1
        assert result[0].id == evolved.id

    def test_zero_fitness_programs_are_skipped(self) -> None:
        tracker = _make_tracker()
        zero = _make_evolved_program(fitness=0.0)
        positive = _make_evolved_program(fitness=1.0)
        result = tracker._eligible_records([zero, positive])
        assert len(result) == 1
        assert result[0].fitness == 1.0

    def test_negative_fitness_programs_are_skipped(self) -> None:
        tracker = _make_tracker()
        result = tracker._eligible_records([_make_evolved_program(fitness=-3.0)])
        assert result == []

    def test_duplicate_programs_are_skipped(self) -> None:
        tracker = _make_tracker()
        prog = _make_evolved_program(fitness=5.0)
        result1 = tracker._eligible_records([prog])
        assert len(result1) == 1
        result2 = tracker._eligible_records([prog])
        assert result2 == []

    def test_seen_ids_tracked_after_processing(self) -> None:
        tracker = _make_tracker()
        prog = _make_evolved_program(fitness=5.0)
        tracker._eligible_records([prog])
        assert prog.id in tracker._seen_ids

    def test_all_records_accumulates(self) -> None:
        tracker = _make_tracker()
        p1 = _make_evolved_program(fitness=1.0)
        p2 = _make_evolved_program(fitness=2.0)
        tracker._eligible_records([p1])
        tracker._eligible_records([p2])
        assert len(tracker._all_records) == 2


class TestIdeaTrackerOnRunComplete:
    def _make_tracker_with_mocked_run(self):
        tracker = _make_tracker(memory_write_enabled=False, memory_usage_tracking_enabled=False)
        tracker._run = AsyncMock()
        return tracker

    @pytest.mark.asyncio
    async def test_empty_storage_skips_pipeline(self) -> None:
        tracker = self._make_tracker_with_mocked_run()
        storage = AsyncMock()
        storage.get_all.return_value = []
        await tracker.on_run_complete(storage)
        tracker._run.assert_not_called()

    @pytest.mark.asyncio
    async def test_programs_passed_to_pipeline(self) -> None:
        tracker = self._make_tracker_with_mocked_run()
        progs = [_make_evolved_program(fitness=f) for f in [1.0, 2.0, 3.0]]
        storage = AsyncMock()
        storage.get_all.return_value = progs
        await tracker.on_run_complete(storage)
        tracker._run.assert_awaited_once_with(progs)

    @pytest.mark.asyncio
    async def test_storage_excludes_stage_results(self) -> None:
        from gigaevo.programs.program import EXCLUDE_STAGE_RESULTS
        tracker = self._make_tracker_with_mocked_run()
        storage = AsyncMock()
        storage.get_all.return_value = [_make_evolved_program()]
        await tracker.on_run_complete(storage)
        storage.get_all.assert_called_once_with(exclude=EXCLUDE_STAGE_RESULTS)


class TestIdeaTrackerLegacyRun:
    def _make_tracker_with_mocked_run(self):
        tracker = _make_tracker(memory_write_enabled=False, memory_usage_tracking_enabled=False)
        tracker._run = MagicMock()
        return tracker

    def test_none_programs_skips(self) -> None:
        tracker = self._make_tracker_with_mocked_run()
        tracker.run(None)
        tracker._run.assert_not_called()

    def test_empty_programs_skips(self) -> None:
        tracker = self._make_tracker_with_mocked_run()
        tracker.run([])
        tracker._run.assert_not_called()


# ---------------------------------------------------------------------------
# EvolutionEngine ↔ PostRunHook integration
# ---------------------------------------------------------------------------

def _make_engine(*, post_run_hook=None, max_generations=1):
    storage = AsyncMock()
    storage.count_by_status.return_value = 0
    storage.get_all_by_status.return_value = []
    storage.get_ids_by_status.return_value = []
    storage.snapshot = MagicMock()
    writer = MagicMock()
    writer.bind.return_value = writer
    metrics_tracker = AsyncMock()
    metrics_tracker.start = MagicMock()
    return EvolutionEngine(
        storage=storage,
        strategy=AsyncMock(),
        mutation_operator=AsyncMock(),
        config=EngineConfig(max_generations=max_generations),
        writer=writer,
        metrics_tracker=metrics_tracker,
        post_run_hook=post_run_hook,
    )


class TestEnginePostRunHookWiring:
    def test_none_hook_defaults_to_null(self) -> None:
        engine = _make_engine(post_run_hook=None)
        assert isinstance(engine._post_run_hook, NullPostRunHook)

    def test_custom_hook_is_stored(self) -> None:
        hook = NullPostRunHook()
        engine = _make_engine(post_run_hook=hook)
        assert engine._post_run_hook is hook

    @pytest.mark.asyncio
    async def test_hook_called_after_evolution_completes(self) -> None:
        hook = AsyncMock(spec=PostRunHook)
        engine = _make_engine(post_run_hook=hook, max_generations=1)
        await engine.run()
        hook.on_run_complete.assert_awaited_once_with(engine.storage)

    @pytest.mark.asyncio
    async def test_hook_exception_is_non_fatal(self) -> None:
        hook = AsyncMock(spec=PostRunHook)
        hook.on_run_complete.side_effect = RuntimeError("hook exploded")
        engine = _make_engine(post_run_hook=hook, max_generations=1)
        await engine.run()
        assert not engine._running


class TestHydraComposability:
    def test_none_yaml_target_is_null_hook(self) -> None:
        hook = NullPostRunHook()
        assert isinstance(hook, PostRunHook)

    def test_default_yaml_target_is_idea_tracker(self) -> None:
        from gigaevo.memory.ideas_tracker.ideas_tracker import IdeaTracker
        assert issubclass(IdeaTracker, PostRunHook)

    def test_engine_accepts_both_hook_types(self) -> None:
        engine1 = _make_engine(post_run_hook=NullPostRunHook())
        assert isinstance(engine1._post_run_hook, NullPostRunHook)
        engine2 = _make_engine(post_run_hook=AsyncMock(spec=PostRunHook))
        assert engine2._post_run_hook is not None

    def test_post_run_hook_in_engine_signature(self) -> None:
        import inspect
        sig = inspect.signature(EvolutionEngine.__init__)
        assert "post_run_hook" in sig.parameters


# ---------------------------------------------------------------------------
# Full pipeline E2E
# ---------------------------------------------------------------------------

class TestEvolutionToIdeaExtraction:
    @pytest.mark.asyncio
    async def test_hook_receives_programs_from_storage(self) -> None:
        storage = AsyncMock()
        progs = [_make_evolved_program(fitness=f) for f in [1.0, 2.0, 3.0]]
        storage.get_all.return_value = progs
        captured: list = []

        class RecordingHook(PostRunHook):
            async def on_run_complete(self, stor) -> None:
                from gigaevo.programs.program import EXCLUDE_STAGE_RESULTS
                programs = await stor.get_all(exclude=EXCLUDE_STAGE_RESULTS)
                captured.extend(programs)

        await RecordingHook().on_run_complete(storage)
        assert len(captured) == 3

    @pytest.mark.asyncio
    async def test_program_filtering_in_tracker_context(self) -> None:
        tracker = _make_tracker(memory_write_enabled=False, memory_usage_tracking_enabled=False)
        seed = _make_root_program(fitness=1.0)
        gen2_good = _make_evolved_program(fitness=5.0, parent_id=seed.id, generation=2)
        gen2_bad = _make_evolved_program(fitness=0.0, parent_id=seed.id, generation=2)
        gen3_best = _make_evolved_program(
            fitness=8.0, parent_id=gen2_good.id, generation=3,
            insights=["Use BFS for hops"], changes=["Replaced DFS with BFS"], archetype="exploitation",
        )
        records = tracker._eligible_records([seed, gen2_good, gen2_bad, gen3_best])
        assert len(records) == 2
        record_ids = {r.id for r in records}
        assert gen2_good.id in record_ids
        assert gen3_best.id in record_ids
        assert seed.id not in record_ids
        assert gen2_bad.id not in record_ids
        best = next(r for r in records if r.id == gen3_best.id)
        assert best.fitness == 8.0
        assert best.insights == ["Use BFS for hops"]
        assert best.strategy == "exploitation"

    @pytest.mark.asyncio
    async def test_memory_usage_tracked_after_evolution(self) -> None:
        seed = _make_program(program_id="seed-01", fitness=2.0, parents=[], generation=1)
        child_improved = _make_program(program_id="child-01", fitness=7.0, generation=2, parents=["seed-01"], memory_ids=["idea-1"])
        child_regressed = _make_program(program_id="child-02", fitness=1.0, generation=2, parents=["seed-01"], memory_ids=["idea-1"])
        result = _build_memory_usage_updates([seed, child_improved, child_regressed], "HoVer fact verification")
        assert "idea-1" in result
        total = result["idea-1"]["used"]["total"]
        assert total["total_used"] == 2
        deltas = result["idea-1"]["used"]["entries"][0]["fitness_delta_per_use"]
        assert sorted(deltas) == [-1.0, 5.0]
```

- [ ] **Step 6.2: Run the full test suite**

```bash
PYTHONPATH=. /home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/memory/ -v 2>&1 | tail -20
```

Expected: all tests PASSED.

- [ ] **Step 6.3: Commit**

```bash
rtk git add tests/memory/test_ideas_tracker_pipeline.py
rtk git commit -m "$(cat <<'EOF'
test(ideas-tracker): update pipeline tests for new module structure

Import paths updated to models.py and idea_bank.py.
IdeaTracker constructor now takes an Analyzer object directly.
_eligible_records replaces _get_new_programs.
EOF
)"
```

---

## Task 7: Update `cli.py`

**Files:**
- Modify: `gigaevo/memory/ideas_tracker/cli.py`

The CLI calls `IdeaTracker(logs_dir=args.logs_dir)` with no analyzer. After the refactor,
`IdeaTracker.__init__` defaults to `ClassifyingAnalyzer()` when `analyzer=None`, so the CLI
works without changes. However, `LLMClient` is imported in `cli.py` indirectly — verify it loads.

- [ ] **Step 7.1: Verify CLI imports cleanly**

```bash
PYTHONPATH=. /home/jovyan/.mlspace/envs/evo/bin/python3 -c "
from gigaevo.memory.ideas_tracker.cli import main
print('CLI import OK')
"
```

Expected: `CLI import OK`

- [ ] **Step 7.2: If import fails, check and fix `cli.py`**

The only change needed is the import inside `main()`:
```python
# line 178 of cli.py — already correct, no change needed:
from gigaevo.memory.ideas_tracker.ideas_tracker import IdeaTracker
```

No changes required if the import succeeds in Step 7.1.

- [ ] **Step 7.3: Run the full test suite one more time**

```bash
PYTHONPATH=. /home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/memory/ -v 2>&1 | tail -10
```

Expected: all tests PASSED.

---

## Task 8: Delete old files

**Files:**
- Delete: `gigaevo/memory/ideas_tracker/components/` (entire directory, prompts/ already moved)
- Delete: `gigaevo/memory/ideas_tracker/utils/helpers.py`
- Delete: `gigaevo/memory/ideas_tracker/utils/records_converter.py`
- Delete: `gigaevo/memory/ideas_tracker/utils/task_description_loader.py`
- Delete: `gigaevo/memory/ideas_tracker/utils/it_logger.py`
- Delete: `gigaevo/memory/ideas_tracker/utils/__init__.py`
- Keep: `gigaevo/memory/ideas_tracker/utils/origin_analysis.py` (still used by `_SessionLog`)

- [ ] **Step 8.1: Run the full test suite before deleting (safety check)**

```bash
PYTHONPATH=. /home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/memory/ -q 2>&1 | tail -5
```

Expected: all tests PASSED. If any fail, do not proceed with deletion.

- [ ] **Step 8.2: Delete superseded files**

```bash
cd /mnt/virtual_ai0001071-04017_SR004-nfs1/CFS-SR008/workspace/mathemage/gigaevo-core-internal

# Remove the components directory (prompts/ already moved in Task 3)
rtk git rm -r gigaevo/memory/ideas_tracker/components/

# Remove superseded utils (keep origin_analysis.py)
rtk git rm gigaevo/memory/ideas_tracker/utils/helpers.py
rtk git rm gigaevo/memory/ideas_tracker/utils/records_converter.py
rtk git rm gigaevo/memory/ideas_tracker/utils/task_description_loader.py
rtk git rm gigaevo/memory/ideas_tracker/utils/it_logger.py
rtk git rm gigaevo/memory/ideas_tracker/utils/__init__.py
```

- [ ] **Step 8.3: Run the full test suite after deletion**

```bash
PYTHONPATH=. /home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/memory/ -q 2>&1 | tail -5
```

Expected: all tests still PASSED.

- [ ] **Step 8.4: Run the full project test suite**

```bash
PYTHONPATH=. /home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/ -q --tb=short 2>&1 | tail -10
```

Expected: same pass count as before the refactor. If any tests outside `tests/memory/` fail, investigate imports referencing the deleted modules.

- [ ] **Step 8.5: Run linter**

```bash
PYTHONPATH=. /home/jovyan/.mlspace/envs/evo/bin/python3 -m ruff check gigaevo/memory/ideas_tracker/ && echo "Lint OK"
```

Fix any reported issues before committing.

- [ ] **Step 8.6: Final commit**

```bash
rtk git add -A
rtk git commit -m "$(cat <<'EOF'
refactor(ideas-tracker): delete components/ and superseded utils/

22-file module reduced to 5 source files.
components/ (analyzer.py, analyzer_f.py, data_components.py, records_manager.py,
postprocessing.py, summary.py, prompt_manager.py, memory_pipeline.py,
statistics.py, fabrics/) deleted.
utils/helpers.py, records_converter.py, task_description_loader.py, it_logger.py deleted.
utils/origin_analysis.py kept (used by _SessionLog).
EOF
)"
```

---

## Self-Review Notes

- **`_build_usage_updates` in `ideas_tracker.py`** imports `_build_usage_payload` and `_to_float` from `idea_bank.py` using a local import. This is valid but could be refactored to a top-level import — either is fine.
- **`cached_property` on `_task_summary`** requires that `IdeaTracker` instances are not shared across threads (standard Python restriction on `cached_property`). This matches existing behaviour.
- **`ClusteringAnalyzer.analyze`** calls `asyncio.run()` which will fail if called from within an already-running event loop. This mirrors the existing `IdeaAnalyzerFast` behaviour. The caller (`IdeaTracker._run`) is itself async but calls `analyze` synchronously — this is correct because `_run` is entered from `asyncio.run(self._run(programs))` in `run()` or from `await self._run(programs)` in `on_run_complete`. The nested `asyncio.run` inside `ClusteringAnalyzer.analyze` will fail in the `on_run_complete` path. **Fix**: `ClusteringAnalyzer.analyze` should use `asyncio.get_event_loop().run_until_complete()` or `IdeaTracker._run` should `await` an async version of analyze. Simplest fix: make `_run` call `await self._analyzer.analyze_async(records, bank)` for `ClusteringAnalyzer` and `self._analyzer.analyze(records, bank)` for `ClassifyingAnalyzer`. Or better: add `async def analyze_async` to both and have `_run` always await it.

**Recommended fix before Task 5 commit:** Add `async def analyze_async` to the `Analyzer` protocol and both classes:

In `analyzers.py`, add to `ClassifyingAnalyzer`:
```python
async def analyze_async(self, records: list[ProgramRecord], bank: IdeaBank) -> AnalysisResult:
    """Async wrapper — runs synchronous analyze() in a thread pool to avoid blocking."""
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, self.analyze, records, bank)
```

In `analyzers.py`, add to `ClusteringAnalyzer`:
```python
async def analyze_async(self, records: list[ProgramRecord], bank: IdeaBank) -> AnalysisResult:
    """Async implementation — runs the full embed/cluster/refine pipeline."""
    return AnalysisResult(new_ideas=await self._run_async(records))
```

In `ideas_tracker.py`, change `_run` to:
```python
result = await self._analyzer.analyze_async(records, self._bank)
```

And remove `asyncio.run(...)` from `ClusteringAnalyzer.analyze`. This makes both paths safely awaitable from `on_run_complete`.
