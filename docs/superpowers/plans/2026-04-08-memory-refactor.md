# Memory System Refactoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate duplicated utility functions, improve Pydantic patterns, remove dead code, and ensure consistency with codebase conventions across the memory system.

**Architecture:** The ideas_tracker module has scattered utility functions (_to_float, _parse_cell, _median) defined independently in csv_loader.py, idea_bank.py, and ideas_tracker.py. We consolidate into gigaevo/memory/utils.py, add proper Pydantic models for UsagePayload, and add integration tests mimicking real runs loaded from CSV.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, asyncio, csv

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `gigaevo/memory/utils.py` | Create | Canonical `to_float`, `parse_cell`, `median` utilities |
| `gigaevo/memory/ideas_tracker/models.py` | Modify | Add `UsageEntry` and `UsagePayload` Pydantic models |
| `gigaevo/memory/ideas_tracker/csv_loader.py` | Modify | Import utilities from shared module, remove duplicates |
| `gigaevo/memory/ideas_tracker/idea_bank.py` | Modify | Import utilities from shared module, use Pydantic models |
| `gigaevo/memory/ideas_tracker/ideas_tracker.py` | Modify | Import utilities from shared module, remove duplicates |
| `tests/memory/test_utils.py` | Create | Unit tests for consolidated utility functions |
| `tests/memory/test_csv_memory_integration.py` | Create | E2E integration tests for CSV→memory flow |

---

## Task 1: Consolidate utility functions into shared module

**Files:**
- Create: `gigaevo/memory/utils.py`
- Modify: `gigaevo/memory/ideas_tracker/csv_loader.py` (lines 27-35: remove _to_float, _parse_cell)
- Modify: `gigaevo/memory/ideas_tracker/idea_bank.py` (lines 27-38: remove _to_float, _median)
- Modify: `gigaevo/memory/ideas_tracker/ideas_tracker.py` (lines 50-57: remove _to_float)
- Create: `tests/memory/test_utils.py`

**Background:** `_to_float` is defined identically in 3 files (csv_loader.py:28, idea_bank.py:27, ideas_tracker.py:50). `_parse_cell` exists in csv_loader.py only but belongs in the shared module. `_median` is in idea_bank.py only. All three should live in `gigaevo/memory/utils.py`.

- [ ] **Step 1: Write failing tests**

```python
# tests/memory/test_utils.py
from __future__ import annotations

import pytest
from gigaevo.memory.utils import to_float, parse_cell, median


class TestToFloat:
    def test_valid_int(self) -> None:
        assert to_float(42) == 42.0

    def test_valid_float(self) -> None:
        assert to_float(3.14) == pytest.approx(3.14)

    def test_valid_string(self) -> None:
        assert to_float("3.14") == pytest.approx(3.14)

    def test_negative_is_valid(self) -> None:
        assert to_float(-1e5) == pytest.approx(-1e5)

    def test_zero_is_valid(self) -> None:
        assert to_float(0) == 0.0
        assert to_float("0") == 0.0

    def test_invalid_string_returns_none(self) -> None:
        assert to_float("not a number") is None

    def test_none_returns_none(self) -> None:
        assert to_float(None) is None

    def test_nan_returns_none(self) -> None:
        assert to_float(float("nan")) is None

    def test_inf_returns_none(self) -> None:
        assert to_float(float("inf")) is None
        assert to_float(float("-inf")) is None

    def test_default_returned_on_invalid(self) -> None:
        assert to_float("bad", default=0.0) == 0.0

    def test_default_returned_on_nan(self) -> None:
        assert to_float(float("nan"), default=0.0) == 0.0


class TestParseCell:
    def test_json_dict_string(self) -> None:
        result = parse_cell('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_list_string(self) -> None:
        result = parse_cell('[1, 2, 3]')
        assert result == [1, 2, 3]

    def test_plain_string_unchanged(self) -> None:
        assert parse_cell("hello") == "hello"

    def test_invalid_json_returns_original_string(self) -> None:
        s = '[not valid json{]'
        assert parse_cell(s) == s

    def test_empty_string_unchanged(self) -> None:
        assert parse_cell("") == ""

    def test_non_string_int(self) -> None:
        assert parse_cell(42) == 42

    def test_non_string_list(self) -> None:
        assert parse_cell([1, 2]) == [1, 2]

    def test_whitespace_prefix_stripped_for_detection(self) -> None:
        result = parse_cell('  {"key": 1}')
        assert result == {"key": 1}

    def test_empty_json_array(self) -> None:
        assert parse_cell("[]") == []

    def test_empty_json_object(self) -> None:
        assert parse_cell("{}") == {}


class TestMedian:
    def test_odd_length_list(self) -> None:
        assert median([1.0, 2.0, 3.0]) == 2.0

    def test_even_length_list(self) -> None:
        assert median([1.0, 2.0, 3.0, 4.0]) == pytest.approx(2.5)

    def test_single_element(self) -> None:
        assert median([5.0]) == 5.0

    def test_empty_returns_none(self) -> None:
        assert median([]) is None

    def test_unsorted_list(self) -> None:
        assert median([3.0, 1.0, 2.0]) == 2.0

    def test_negative_values(self) -> None:
        assert median([-3.0, -1.0, -2.0]) == -2.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
/home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/memory/test_utils.py -x --timeout=60 -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'gigaevo.memory.utils'`

- [ ] **Step 3: Create gigaevo/memory/utils.py**

```python
"""Shared utility functions for the memory system.

These helpers are used across csv_loader, idea_bank, and ideas_tracker.
They live here so each module does not duplicate the definitions.
"""

from __future__ import annotations

import json
import math
import statistics
from typing import Any


def to_float(value: Any, *, default: float | None = None) -> float | None:
    """Convert value to float, returning ``default`` if conversion fails.

    Args:
        value: Anything that may be coercible to float (int, str, float).
        default: Returned when conversion fails, value is NaN, or value is
            infinite.  Defaults to ``None``.

    Returns:
        A finite float, or ``default``.
    """
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(parsed) or math.isinf(parsed):
        return default
    return parsed


def parse_cell(value: Any) -> Any:
    """JSON-decode strings that start with ``{`` or ``[``; return other values unchanged.

    Used when reading CSVs where nested structures were JSON-serialised into a
    single cell (e.g. the ``parent_ids`` column produced by ``tools/redis2pd.py``).

    Args:
        value: Any value.  Non-strings are returned as-is.

    Returns:
        Decoded JSON value when applicable, otherwise the original value.
    """
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if stripped and stripped[0] in ("{", "["):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
    return value


def median(values: list[float]) -> float | None:
    """Compute the median of a list of floats.

    Args:
        values: List of floats.  May be empty.

    Returns:
        Median as a float, or ``None`` if the list is empty.
    """
    return float(statistics.median(values)) if values else None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
/home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/memory/test_utils.py -x --timeout=60 -q
```

Expected: 21 passed

- [ ] **Step 5: Update csv_loader.py**

Replace the private helpers in `gigaevo/memory/ideas_tracker/csv_loader.py`.

**Remove** the `_parse_cell` function (lines 15-25) and `_to_float` function (lines 28-35).

**Change** the import block at the top to add:
```python
from gigaevo.memory.utils import parse_cell, to_float
```

**Change** all calls in `_row_to_program` from `_parse_cell` → `parse_cell` and `_to_float` → `to_float`.

The complete file after changes:
```python
"""Load Program objects from an evolution_data.csv produced by tools/redis2pd.py."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from gigaevo.memory.utils import parse_cell, to_float
from gigaevo.programs.program import Lineage, Program
from gigaevo.programs.program_state import ProgramState


def load_programs_from_csv(path: str | Path) -> list[Program]:
    """Read a CSV produced by redis2pd and return Program objects.

    Only columns needed by IdeaTracker are reconstructed:
    program_id, code, parent_ids, lineage_generation, metric_*, metadata_*.
    """
    path = Path(path)
    programs: list[Program] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            programs.append(_row_to_program(row))
    return programs


def _row_to_program(row: dict[str, Any]) -> Program:
    program_id = str(row.get("program_id", "")).strip()
    code = str(row.get("code", "")).strip() or " "

    raw_parents = parse_cell(row.get("parent_ids", "[]"))
    parents = [str(p) for p in raw_parents] if isinstance(raw_parents, list) else []
    try:
        generation = max(int(row.get("lineage_generation", 1)), 1)
    except (TypeError, ValueError):
        generation = 1

    metrics: dict[str, float] = {}
    for key, val in row.items():
        if key.startswith("metric_"):
            f = to_float(val)
            if f is not None:
                metrics[key[len("metric_"):]] = f

    metadata: dict[str, Any] = {}
    for key, val in row.items():
        if key.startswith("metadata_"):
            metadata[key[len("metadata_"):]] = parse_cell(val)

    return Program(
        id=program_id,
        code=code,
        state=ProgramState.DONE,
        lineage=Lineage(parents=parents, generation=generation),
        metrics=metrics,
        metadata=metadata,
    )
```

- [ ] **Step 6: Update idea_bank.py**

Replace the private helpers in `gigaevo/memory/ideas_tracker/idea_bank.py`.

**Remove** `_to_float` (lines 27-34) and `_median` (lines 37-38).

**Change** import block at the top to add:
```python
from gigaevo.memory.utils import median, to_float
```

**Change** all calls:
- `_to_float(...)` → `to_float(...)`
- `_median(...)` → `median(...)`

- [ ] **Step 7: Update ideas_tracker.py**

Remove private `_to_float` definition (lines 50-57) from `gigaevo/memory/ideas_tracker/ideas_tracker.py`.

**Change** import block to add:
```python
from gigaevo.memory.utils import to_float
```

**Remove** the inline import in `_build_usage_updates`:
```python
# DELETE this line:
from gigaevo.memory.ideas_tracker.idea_bank import _to_float as _f
```

**Change** all `_f(...)` calls in `_build_usage_updates` → `to_float(...)`.

- [ ] **Step 8: Also remove inline imports inside _build_usage_updates**

The current function has inline imports at lines 101-105. Move them to the top of the file:
```python
# At top of file (with other imports):
from gigaevo.evolution.mutation.constants import MUTATION_MEMORY_SELECTED_IDS_METADATA_KEY
from gigaevo.memory.ideas_tracker.idea_bank import _build_usage_payload
```

- [ ] **Step 9: Run all memory tests**

```bash
ruff check gigaevo/memory/ && ruff format --check gigaevo/memory/ && /home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/memory/ -x --timeout=120 -q
```

Expected: Lint clean, all tests pass

- [ ] **Step 10: Commit**

```bash
git add gigaevo/memory/utils.py gigaevo/memory/ideas_tracker/csv_loader.py gigaevo/memory/ideas_tracker/idea_bank.py gigaevo/memory/ideas_tracker/ideas_tracker.py tests/memory/test_utils.py
git commit -m "refactor(memory): consolidate _to_float/_parse_cell/_median into shared module

- Create gigaevo/memory/utils.py with to_float(), parse_cell(), median()
- Remove duplicate private helpers from csv_loader, idea_bank, ideas_tracker
- Move inline imports in _build_usage_updates to module top-level
- Add 21 unit tests for shared utilities
- DRY: eliminates 3 identical _to_float definitions

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: Add Pydantic models for UsagePayload structure

**Files:**
- Modify: `gigaevo/memory/ideas_tracker/models.py`
- Modify: `gigaevo/memory/ideas_tracker/idea_bank.py`
- Modify: `tests/memory/test_data_components.py` (add new test class)

**Background:** `_build_usage_payload` in idea_bank.py returns a raw `dict[str, Any]`. The structure is
`{"used": {"entries": [...], "total": {"total_used": N, "median_delta_fitness": F}}}`.
This should be typed Pydantic models to match the rest of the codebase (all models in models.py use BaseModel).
Check the existing `Idea`, `IdeaExplanation`, `ProgramRecord` in models.py for the pattern to follow.

- [ ] **Step 1: Read models.py to understand existing pattern**

```bash
/home/jovyan/.mlspace/envs/evo/bin/python3 -c "
from gigaevo.memory.ideas_tracker.models import Idea, IdeaExplanation, ProgramRecord
print('Idea fields:', list(Idea.model_fields.keys()))
print('IdeaExplanation fields:', list(IdeaExplanation.model_fields.keys()))
"
```

- [ ] **Step 2: Write failing tests in test_data_components.py**

Add the following class to `tests/memory/test_data_components.py`:

```python
class TestUsageModels:
    def test_usage_entry_fields(self) -> None:
        from gigaevo.memory.ideas_tracker.models import UsageEntry
        entry = UsageEntry(
            task_description_summary="Multi-hop QA",
            used_count=3,
            fitness_delta_per_use=[0.05, 0.02, -0.01],
            median_delta_fitness=0.02,
        )
        assert entry.task_description_summary == "Multi-hop QA"
        assert entry.used_count == 3
        assert entry.fitness_delta_per_use == [0.05, 0.02, -0.01]
        assert entry.median_delta_fitness == pytest.approx(0.02)

    def test_usage_entry_none_median(self) -> None:
        from gigaevo.memory.ideas_tracker.models import UsageEntry
        entry = UsageEntry(
            task_description_summary="Task",
            used_count=0,
            fitness_delta_per_use=[],
            median_delta_fitness=None,
        )
        assert entry.median_delta_fitness is None

    def test_usage_payload_model(self) -> None:
        from gigaevo.memory.ideas_tracker.models import UsageEntry, UsagePayload
        payload = UsagePayload(
            entries=[
                UsageEntry(
                    task_description_summary="Task A",
                    used_count=2,
                    fitness_delta_per_use=[0.1, 0.2],
                    median_delta_fitness=0.15,
                )
            ],
            total_used=2,
            median_delta_fitness=0.15,
        )
        assert len(payload.entries) == 1
        assert payload.total_used == 2
        assert payload.median_delta_fitness == pytest.approx(0.15)

    def test_usage_payload_defaults(self) -> None:
        from gigaevo.memory.ideas_tracker.models import UsagePayload
        payload = UsagePayload()
        assert payload.entries == []
        assert payload.total_used == 0
        assert payload.median_delta_fitness is None

    def test_usage_payload_serialization_roundtrip(self) -> None:
        from gigaevo.memory.ideas_tracker.models import UsageEntry, UsagePayload
        payload = UsagePayload(
            entries=[
                UsageEntry(
                    task_description_summary="task",
                    used_count=1,
                    fitness_delta_per_use=[0.5],
                    median_delta_fitness=0.5,
                )
            ],
            total_used=1,
            median_delta_fitness=0.5,
        )
        data = payload.model_dump()
        restored = UsagePayload.model_validate(data)
        assert restored.total_used == 1
        assert restored.entries[0].task_description_summary == "task"
```

- [ ] **Step 3: Run test to verify it fails**

```bash
/home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/memory/test_data_components.py::TestUsageModels -x --timeout=60 -q
```

Expected: FAIL with `ImportError: cannot import name 'UsageEntry'`

- [ ] **Step 4: Add UsageEntry and UsagePayload to models.py**

Open `gigaevo/memory/ideas_tracker/models.py`. After the imports, before `ProgramRecord`, add:

```python
class UsageEntry(BaseModel):
    """Single per-task entry in a memory card's usage payload."""

    task_description_summary: str
    """Human-readable task summary this entry belongs to."""

    used_count: int
    """Number of times this card was used in this task."""

    fitness_delta_per_use: list[float] = Field(default_factory=list)
    """Fitness deltas for each use: child_fitness - max(parent_fitness)."""

    median_delta_fitness: float | None = None
    """Median fitness delta across all uses for this task."""


class UsagePayload(BaseModel):
    """Aggregated usage statistics for a single memory card."""

    entries: list[UsageEntry] = Field(default_factory=list)
    """Per-task usage entries, sorted by task_description_summary."""

    total_used: int = 0
    """Total use count across all tasks."""

    median_delta_fitness: float | None = None
    """Median fitness delta across all uses and all tasks."""
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
/home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/memory/test_data_components.py::TestUsageModels -x --timeout=60 -q
```

Expected: 5 passed

- [ ] **Step 6: Update _build_usage_payload in idea_bank.py to use the Pydantic models**

Replace the return value of `_build_usage_payload`:

```python
from gigaevo.memory.ideas_tracker.models import (
    AnalysisResult,
    ClassificationChunk,
    Idea,
    IdeaExplanation,
    IdeaUpdate,
    UsageEntry,
    UsagePayload,
)


def _build_usage_payload(task_to_deltas: dict[str, list[float]]) -> dict[str, Any]:
    """Build per-memory-card usage payload from per-task fitness deltas."""
    entries: list[UsageEntry] = []
    total_deltas: list[float] = []

    for task_summary in sorted(task_to_deltas):
        deltas = [
            d for raw in task_to_deltas[task_summary]
            if (d := to_float(raw)) is not None
        ]
        if not deltas:
            continue
        entries.append(
            UsageEntry(
                task_description_summary=task_summary,
                used_count=len(deltas),
                fitness_delta_per_use=deltas,
                median_delta_fitness=median(deltas),
            )
        )
        total_deltas.extend(deltas)

    payload = UsagePayload(
        entries=entries,
        total_used=len(total_deltas),
        median_delta_fitness=median(total_deltas),
    )
    # Return as {"used": {...}} for backward compat with existing callers
    return {"used": payload.model_dump()}
```

- [ ] **Step 7: Run all memory tests**

```bash
ruff check gigaevo/memory/ideas_tracker/ && /home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/memory/ -x --timeout=120 -q
```

Expected: All pass

- [ ] **Step 8: Commit**

```bash
git add gigaevo/memory/ideas_tracker/models.py gigaevo/memory/ideas_tracker/idea_bank.py tests/memory/test_data_components.py
git commit -m "refactor(memory): add UsageEntry/UsagePayload Pydantic models

- Add UsageEntry: per-task fitness delta aggregation (typed)
- Add UsagePayload: full card usage stats with serialisation roundtrip
- Use models in _build_usage_payload, maintain backward-compat dict shape
- Add 5 tests covering construction, defaults, serialization roundtrip
- Consistent with Idea/IdeaExplanation/ProgramRecord pattern in models.py

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: Add integration tests for CSV → IdeaTracker flow

**Files:**
- Create: `tests/memory/test_csv_memory_integration.py`

**Background:** We now have a complete CSV loading path (redis_loader.py, csv_loader.py, cli.py). We need E2E tests that simulate: (1) export run data to CSV, (2) load programs from CSV, (3) run IdeaTracker on them, (4) verify log output. This is the most common user flow for post-hoc analysis.

- [ ] **Step 1: Write integration tests**

```python
# tests/memory/test_csv_memory_integration.py
"""Integration tests: CSV → load_programs_from_csv → IdeaTracker.run()."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gigaevo.memory.ideas_tracker.csv_loader import load_programs_from_csv
from gigaevo.memory.ideas_tracker.ideas_tracker import IdeaTracker
from gigaevo.programs.program_state import ProgramState


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _make_row(
    *,
    program_id: str = "prog-001",
    code: str = "def solve(): return 42",
    parent_ids: list[str] | None = None,
    generation: int = 2,
    fitness: float = 0.75,
    is_valid: float = 1.0,
    mutation_output: dict | None = None,
    memory_ids: list[str] | None = None,
) -> dict:
    mo = mutation_output or {"archetype": "exploitation", "changes": [], "insights_used": []}
    row: dict = {
        "program_id": program_id,
        "code": code,
        "parent_ids": json.dumps(["seed-001"] if parent_ids is None else parent_ids),
        "lineage_generation": str(generation),
        "metric_fitness": str(fitness),
        "metric_is_valid": str(is_valid),
        "metadata_mutation_output": json.dumps(mo),
    }
    if memory_ids is not None:
        row["metadata_memory_selected_idea_ids"] = json.dumps(memory_ids)
    return row


_LLM_PATCH = patch(
    "gigaevo.memory.ideas_tracker.llm._init_clients",
    return_value=(MagicMock(), MagicMock(), False),
)
_TASK_PATCH = patch(
    "gigaevo.memory.ideas_tracker.ideas_tracker._summarise_task_description",
    return_value="test task summary",
)


def _make_tracker(tmp_path: Path, **kwargs) -> IdeaTracker:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return IdeaTracker(
        logs_dir=logs_dir,
        memory_write_enabled=False,
        memory_usage_tracking_enabled=False,
        **kwargs,
    )


class TestCsvToIdeaTrackerFlow:
    def test_evolved_programs_produce_log_files(self, tmp_path: Path) -> None:
        """Full flow: CSV → load → tracker.run() → log files created."""
        csv_path = tmp_path / "evolution_data.csv"
        _write_csv(csv_path, [
            _make_row(program_id="prog-001", parent_ids=[], generation=1),  # root, skipped
            _make_row(program_id="prog-002", fitness=0.8),                  # eligible
            _make_row(program_id="prog-003", fitness=0.9),                  # eligible
        ])

        programs = load_programs_from_csv(csv_path)
        assert len(programs) == 3

        tracker = _make_tracker(tmp_path)
        with _LLM_PATCH, _TASK_PATCH:
            tracker.run(programs)

        session_dirs = list((tmp_path / "logs").glob("*/"))
        assert len(session_dirs) == 1
        session = session_dirs[0]
        assert (session / "log.txt").exists()
        assert (session / "banks.json").exists()
        assert (session / "programs.json").exists()

    def test_root_programs_are_excluded_from_analysis(self, tmp_path: Path) -> None:
        """Programs with no parents must not reach _eligible_records."""
        csv_path = tmp_path / "data.csv"
        _write_csv(csv_path, [
            _make_row(program_id="root", parent_ids=[], generation=1),
        ])
        programs = load_programs_from_csv(csv_path)
        tracker = _make_tracker(tmp_path)
        with _LLM_PATCH, _TASK_PATCH:
            tracker.run(programs)

        # Eligible records = 0 (root only)
        assert tracker._all_records == []

    def test_invalid_programs_excluded(self, tmp_path: Path) -> None:
        """Programs with is_valid=0.0 must not be processed."""
        csv_path = tmp_path / "data.csv"
        _write_csv(csv_path, [
            _make_row(program_id="bad", is_valid=0.0, fitness=-1e5),
        ])
        programs = load_programs_from_csv(csv_path)
        tracker = _make_tracker(tmp_path)
        with _LLM_PATCH, _TASK_PATCH:
            tracker.run(programs)
        assert tracker._all_records == []

    def test_negative_fitness_programs_are_valid(self, tmp_path: Path) -> None:
        """Negative fitness is valid (sentinel -1e5 only invalid if is_valid=0)."""
        csv_path = tmp_path / "data.csv"
        _write_csv(csv_path, [
            _make_row(program_id="p1", fitness=-0.5, is_valid=1.0),
        ])
        programs = load_programs_from_csv(csv_path)
        tracker = _make_tracker(tmp_path)
        with _LLM_PATCH, _TASK_PATCH:
            tracker.run(programs)
        # The program has a parent (default row), is_valid=1.0 → eligible
        assert len(tracker._all_records) == 1

    def test_program_state_is_done_after_csv_load(self, tmp_path: Path) -> None:
        """All CSV-loaded programs must have ProgramState.DONE."""
        csv_path = tmp_path / "data.csv"
        _write_csv(csv_path, [_make_row()])
        programs = load_programs_from_csv(csv_path)
        assert all(p.state == ProgramState.DONE for p in programs)

    def test_duplicate_programs_not_double_counted(self, tmp_path: Path) -> None:
        """Same program_id appearing twice should be processed once."""
        csv_path = tmp_path / "data.csv"
        _write_csv(csv_path, [
            _make_row(program_id="dup-001"),
            _make_row(program_id="dup-001"),  # duplicate
        ])
        programs = load_programs_from_csv(csv_path)
        tracker = _make_tracker(tmp_path)
        with _LLM_PATCH, _TASK_PATCH:
            tracker.run(programs)
        # Dedup by seen_ids
        assert len(tracker._all_records) == 1

    def test_programs_file_contains_records(self, tmp_path: Path) -> None:
        """programs.json should contain the eligible program records."""
        csv_path = tmp_path / "data.csv"
        _write_csv(csv_path, [_make_row(program_id="p1", fitness=0.88)])
        programs = load_programs_from_csv(csv_path)
        tracker = _make_tracker(tmp_path)
        with _LLM_PATCH, _TASK_PATCH:
            tracker.run(programs)

        session = list((tmp_path / "logs").glob("*/"))[0]
        import json as _json
        data = _json.loads((session / "programs.json").read_text())
        # programs.json is a list of snapshots: [{"timestamp": ..., "programs": [...]}]
        assert isinstance(data, list) and len(data) == 1
        records = data[0]["programs"]
        assert len(records) == 1
        assert records[0]["program_id"] == "p1"
```

- [ ] **Step 2: Run tests**

```bash
/home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/memory/test_csv_memory_integration.py -x --timeout=180 -q
```

Expected: All 7 tests pass

- [ ] **Step 3: Commit**

```bash
git add tests/memory/test_csv_memory_integration.py
git commit -m "test(memory): add CSV→IdeaTracker integration tests

- test_evolved_programs_produce_log_files: full E2E flow check
- test_root_programs_are_excluded_from_analysis: filter correctness
- test_invalid_programs_excluded: is_valid=0 must be skipped
- test_negative_fitness_programs_are_valid: BUG from refactor was here
- test_program_state_is_done: CSV loader contract
- test_duplicate_programs_not_double_counted: seen_ids dedup
- test_programs_file_contains_records: log output shape

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: Move inline imports in _build_usage_updates to module top-level

**Files:**
- Modify: `gigaevo/memory/ideas_tracker/ideas_tracker.py`

**Background:** `_build_usage_updates` (ideas_tracker.py:95) contains inline imports at lines 101-108:
```python
from gigaevo.evolution.mutation.constants import MUTATION_MEMORY_SELECTED_IDS_METADATA_KEY
from gigaevo.memory.ideas_tracker.idea_bank import _build_usage_payload
from gigaevo.memory.ideas_tracker.idea_bank import _to_float as _f
import ast
```
Also `_as_string_list` has `import ast` inside it. Per project style, all imports must be at the top of the file. The `_as_string_list` nested function with its inner `import ast` is also unnecessarily complex.

- [ ] **Step 1: Write tests to verify current behaviour**

```bash
/home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/memory/test_ideas_tracker_pipeline.py -x --timeout=120 -q
```

Expected: All pass (baseline)

- [ ] **Step 2: Refactor ideas_tracker.py**

**Move** these to the top-level imports block (after existing imports, before `load_dotenv()`):
```python
import ast

from gigaevo.evolution.mutation.constants import MUTATION_MEMORY_SELECTED_IDS_METADATA_KEY
from gigaevo.memory.ideas_tracker.idea_bank import _build_usage_payload
```

**Remove** the `_as_string_list` nested function and replace with a module-level helper.
**Remove** all inline imports from `_build_usage_updates`.

The refactored helpers and function:
```python
def _as_string_list(value: Any) -> list[str]:
    """Parse a JSON string or list into a list of non-empty strings."""
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


def _build_usage_updates(
    programs: list[Program],
    task_summary: str,
    fitness_key: str,
) -> dict[str, dict[str, Any]]:
    """Build per-memory-card usage payloads from program fitness deltas."""
    fitness_by_id: dict[str, float] = {}
    for prog in programs:
        is_valid = to_float(prog.metrics.get(VALIDITY_KEY))
        if is_valid is None or is_valid <= 0:
            continue
        f = to_float(prog.metrics.get(fitness_key))
        if f is not None:
            fitness_by_id[prog.id] = f

    usage_by_card: dict[str, dict[str, list[float]]] = {}
    for prog in programs:
        is_valid = to_float(prog.metrics.get(VALIDITY_KEY))
        if is_valid is None or is_valid <= 0:
            continue
        selected = _as_string_list(
            prog.metadata.get(MUTATION_MEMORY_SELECTED_IDS_METADATA_KEY)
        )
        if not selected:
            continue
        child_fitness = to_float(prog.metrics.get(fitness_key))
        if child_fitness is None:
            continue
        parent_fitnesses = [
            fitness_by_id[pid] for pid in prog.lineage.parents if pid in fitness_by_id
        ]
        if not parent_fitnesses:
            continue
        delta = child_fitness - max(parent_fitnesses)
        for card_id in list(dict.fromkeys(selected)):
            usage_by_card.setdefault(card_id, {}).setdefault(task_summary, []).append(delta)

    return {
        card_id: _build_usage_payload(task_deltas)
        for card_id, task_deltas in usage_by_card.items()
    }
```

- [ ] **Step 3: Run tests to verify nothing broke**

```bash
ruff check gigaevo/memory/ideas_tracker/ideas_tracker.py && /home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/memory/ -x --timeout=120 -q
```

Expected: Lint clean, all tests pass

- [ ] **Step 4: Commit**

```bash
git add gigaevo/memory/ideas_tracker/ideas_tracker.py
git commit -m "refactor(memory): move all inline imports to module top-level

- Move MUTATION_MEMORY_SELECTED_IDS_METADATA_KEY, _build_usage_payload,
  ast imports out of _build_usage_updates function body
- Extract _as_string_list to module-level helper (was nested in a function)
- Per project style: never use imports inside code, always on top
- No logic changes — behaviour identical

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 5: Final validation

- [ ] **Step 1: Run full memory test suite**

```bash
ruff check . && ruff format --check . && /home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/memory/ -x --timeout=180 -q
```

Expected: Lint clean, all tests pass (target: 50+ tests)

- [ ] **Step 2: Check for any remaining inline imports**

```bash
rg "^\s+from gigaevo\|^\s+import " gigaevo/memory/ideas_tracker/ --type py
```

Expected: Only hits inside `_as_string_list`-style try/except would be a concern — verify none

- [ ] **Step 3: Verify no duplicate _to_float definitions**

```bash
rg "def _to_float" gigaevo/memory/
```

Expected: 0 matches (all replaced by `to_float` from `gigaevo.memory.utils`)

- [ ] **Step 4: Final commit if any cleanup needed**

```bash
git add -A
git commit -m "chore(memory): final cleanup after consolidation refactor

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```
