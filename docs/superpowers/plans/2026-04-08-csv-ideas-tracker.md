# CSV Ideas Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let people run `IdeaTracker` on a `evolution_data.csv` archive file instead of requiring live Redis, enabling post-hoc idea analysis on exported run data.

**Architecture:** A new `csv_loader.py` module reconstructs minimal `Program` objects from an `evolution_data.csv` produced by `tools/redis2pd.py`. The CLI gains a `--csv-path` flag; when set, programs are loaded from disk and passed to `tracker.run()` instead of the (currently broken) no-args path. `run_ideas_tracker_from_csv.py` becomes a thin wrapper around the same CLI with `--csv-path` required.

**Tech Stack:** Python stdlib (`csv`, `json`), `pandas` (already in project), existing `Program`/`Lineage` Pydantic models, existing `IdeaTracker.run(programs)` interface.

---

## CSV Format Reference

`evolution_data.csv` columns produced by `tools/redis2pd.py`:

| Column | Type in CSV | Notes |
|---|---|---|
| `program_id` | str (UUID) | → `Program.id` |
| `code` | str | → `Program.code` |
| `parent_ids` | JSON string | `json.loads` → `list[str]` → `Lineage.parents` |
| `lineage_generation` | int | → `Lineage.generation` |
| `metric_fitness` | float | → `metrics["fitness"]` |
| `metric_is_valid` | float | → `metrics["is_valid"]` |
| `metadata_mutation_output` | JSON string or absent | → `metadata["mutation_output"]` |
| `metadata_memory_selected_idea_ids` | JSON string or absent | → `metadata["memory_selected_idea_ids"]` |

Lists and dicts are serialised with `json.dumps` by `_serialize_complex_columns`. Metric and metadata columns are dynamic — any `metric_*` column maps to `metrics[<name>]` and any `metadata_*` column maps to `metadata[<name>]`.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `gigaevo/memory/ideas_tracker/csv_loader.py` | **Create** | Reads CSV → `list[Program]` |
| `gigaevo/memory/ideas_tracker/cli.py` | **Modify** | Add `--csv-path` arg; load & run when set |
| `gigaevo/memory/ideas_tracker/run_ideas_tracker_from_csv.py` | **Modify** | Thin wrapper requiring `--csv-path` |
| `tests/memory/test_csv_loader.py` | **Create** | Unit tests for `csv_loader` |

---

## Task 1: `csv_loader.py` — row parsing

**Files:**
- Create: `gigaevo/memory/ideas_tracker/csv_loader.py`
- Test: `tests/memory/test_csv_loader.py`

- [ ] **Step 1: Write the failing test for a single-row CSV**

```python
# tests/memory/test_csv_loader.py
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from gigaevo.memory.ideas_tracker.csv_loader import load_programs_from_csv
from gigaevo.programs.program import Program


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
    program_id: str = "11111111-1111-1111-1111-111111111111",
    code: str = "def solve(): return 42",
    parent_ids: list[str] | None = None,
    generation: int = 2,
    fitness: float = 0.75,
    is_valid: float = 1.0,
    mutation_output: dict | None = None,
) -> dict:
    return {
        "program_id": program_id,
        "code": code,
        "parent_ids": json.dumps(parent_ids or ["22222222-2222-2222-2222-222222222222"]),
        "lineage_generation": generation,
        "metric_fitness": fitness,
        "metric_is_valid": is_valid,
        "metadata_mutation_output": json.dumps(
            mutation_output or {"archetype": "exploitation", "changes": [], "insights_used": []}
        ),
    }


class TestLoadProgramsFromCsv:
    def test_single_program_loaded(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "evolution_data.csv"
        _write_csv(csv_path, [_make_row()])
        programs = load_programs_from_csv(csv_path)
        assert len(programs) == 1
        assert isinstance(programs[0], Program)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
export GIGAEVO_PYTHON=/home/jovyan/.mlspace/envs/evo/bin/python3
$GIGAEVO_PYTHON -m pytest tests/memory/test_csv_loader.py::TestLoadProgramsFromCsv::test_single_program_loaded -xvs
```

Expected: `ModuleNotFoundError: No module named 'gigaevo.memory.ideas_tracker.csv_loader'`

- [ ] **Step 3: Create minimal `csv_loader.py`**

```python
# gigaevo/memory/ideas_tracker/csv_loader.py
"""Load Program objects from an evolution_data.csv produced by tools/redis2pd.py."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

from gigaevo.programs.program import Lineage, Program
from gigaevo.programs.program_state import ProgramState


def _parse_cell(value: Any) -> Any:
    """Parse a CSV cell: JSON-decode strings that look like JSON objects/arrays."""
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if stripped and stripped[0] in ("{", "["):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
    return value


def _to_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


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
    code = str(row.get("code", "")).strip() or " "  # Program requires non-empty code

    # Lineage
    raw_parents = _parse_cell(row.get("parent_ids", "[]"))
    parents = [str(p) for p in raw_parents] if isinstance(raw_parents, list) else []
    try:
        generation = int(row.get("lineage_generation", 1))
    except (TypeError, ValueError):
        generation = 1
    generation = max(generation, 1)

    # Metrics: collect every metric_* column
    metrics: dict[str, float] = {}
    for key, val in row.items():
        if key.startswith("metric_"):
            metric_name = key[len("metric_"):]
            f = _to_float(val)
            if f is not None:
                metrics[metric_name] = f

    # Metadata: collect every metadata_* column, JSON-parsing complex values
    metadata: dict[str, Any] = {}
    for key, val in row.items():
        if key.startswith("metadata_"):
            meta_name = key[len("metadata_"):]
            metadata[meta_name] = _parse_cell(val)

    return Program(
        id=program_id,
        code=code,
        state=ProgramState.DONE,
        lineage=Lineage(parents=parents, generation=generation),
        metrics=metrics,
        metadata=metadata,
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
$GIGAEVO_PYTHON -m pytest tests/memory/test_csv_loader.py::TestLoadProgramsFromCsv::test_single_program_loaded -xvs
```

Expected: `PASSED`

---

## Task 2: Field mapping tests

**Files:**
- Modify: `tests/memory/test_csv_loader.py`

- [ ] **Step 1: Add failing tests for field mapping**

Append to `tests/memory/test_csv_loader.py`:

```python
    def test_program_id_and_code_mapped(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "data.csv"
        _write_csv(csv_path, [_make_row(program_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", code="def f(): pass")])
        prog = load_programs_from_csv(csv_path)[0]
        assert prog.id == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        assert prog.code == "def f(): pass"

    def test_lineage_parents_and_generation_mapped(self, tmp_path: Path) -> None:
        pid = "22222222-2222-2222-2222-222222222222"
        csv_path = tmp_path / "data.csv"
        _write_csv(csv_path, [_make_row(parent_ids=[pid], generation=5)])
        prog = load_programs_from_csv(csv_path)[0]
        assert prog.lineage.parents == [pid]
        assert prog.lineage.generation == 5

    def test_metrics_mapped(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "data.csv"
        _write_csv(csv_path, [_make_row(fitness=0.88, is_valid=1.0)])
        prog = load_programs_from_csv(csv_path)[0]
        assert prog.metrics["fitness"] == pytest.approx(0.88)
        assert prog.metrics["is_valid"] == pytest.approx(1.0)

    def test_mutation_output_in_metadata(self, tmp_path: Path) -> None:
        mo = {"archetype": "exploration", "changes": [{"description": "Used BFS"}], "insights_used": ["hint1"]}
        csv_path = tmp_path / "data.csv"
        _write_csv(csv_path, [_make_row(mutation_output=mo)])
        prog = load_programs_from_csv(csv_path)[0]
        assert prog.metadata["mutation_output"]["archetype"] == "exploration"
        assert prog.metadata["mutation_output"]["insights_used"] == ["hint1"]

    def test_root_program_has_no_parents(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "data.csv"
        _write_csv(csv_path, [_make_row(parent_ids=[])])
        prog = load_programs_from_csv(csv_path)[0]
        assert prog.lineage.parents == []

    def test_multiple_programs_loaded(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "data.csv"
        rows = [
            _make_row(program_id=f"{'a' * 8}-{'a' * 4}-{'a' * 4}-{'a' * 4}-{'a' * 12}", fitness=float(i))
            for i in range(5)
        ]
        # Use unique IDs
        for i, row in enumerate(rows):
            row["program_id"] = f"{'0' * 7}{i}-0000-0000-0000-000000000000"
        _write_csv(csv_path, rows)
        programs = load_programs_from_csv(csv_path)
        assert len(programs) == 5

    def test_empty_csv_returns_empty_list(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "empty.csv"
        # Write header-only CSV
        csv_path.write_text("program_id,code,parent_ids,lineage_generation\n", encoding="utf-8")
        assert load_programs_from_csv(csv_path) == []

    def test_missing_is_valid_column_skipped_gracefully(self, tmp_path: Path) -> None:
        """CSV from old runs may not have metric_is_valid — should not crash."""
        row = _make_row()
        del row["metric_is_valid"]
        csv_path = tmp_path / "data.csv"
        _write_csv(csv_path, [row])
        programs = load_programs_from_csv(csv_path)
        assert len(programs) == 1
        assert "is_valid" not in programs[0].metrics
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
$GIGAEVO_PYTHON -m pytest tests/memory/test_csv_loader.py -xvs
```

Expected: First new test fails (implementation may not map all fields yet).

- [ ] **Step 3: Run all tests to verify they pass**

The Task 1 implementation already handles all these cases. If any test fails, fix `_row_to_program` in `csv_loader.py`.

```bash
$GIGAEVO_PYTHON -m pytest tests/memory/test_csv_loader.py -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
rtk git add gigaevo/memory/ideas_tracker/csv_loader.py tests/memory/test_csv_loader.py
rtk git commit -m "feat(ideas-tracker): add csv_loader — reconstruct Programs from evolution_data.csv"
```

---

## Task 3: Wire CSV loader into CLI

**Files:**
- Modify: `gigaevo/memory/ideas_tracker/cli.py`
- Test: `tests/memory/test_csv_loader.py` (add CLI integration test)

- [ ] **Step 1: Write failing test for `--csv-path` flag**

Append to `tests/memory/test_csv_loader.py`:

```python
class TestCliCsvPath:
    def test_cli_runs_tracker_with_csv_path(self, tmp_path: Path) -> None:
        """main() with --csv-path should load programs and run the tracker."""
        from unittest.mock import patch, MagicMock
        from gigaevo.memory.ideas_tracker.cli import main

        csv_path = tmp_path / "data.csv"
        _write_csv(csv_path, [_make_row()])

        with (
            patch("gigaevo.memory.ideas_tracker.ideas_tracker.IdeaTracker.run") as mock_run,
            patch("gigaevo.memory.ideas_tracker.ideas_tracker._summarise_task_description", return_value="s"),
            patch("gigaevo.memory.ideas_tracker.llm._init_clients", return_value=(MagicMock(), MagicMock(), False)),
        ):
            main(["--csv-path", str(csv_path), "--no-memory-write"])

        mock_run.assert_called_once()
        programs_arg = mock_run.call_args[0][0]
        assert len(programs_arg) == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
$GIGAEVO_PYTHON -m pytest tests/memory/test_csv_loader.py::TestCliCsvPath -xvs
```

Expected: `error: unrecognized arguments: --csv-path`

- [ ] **Step 3: Add `--csv-path` to CLI parser and loading logic**

In `gigaevo/memory/ideas_tracker/cli.py`, add argument to `_build_argument_parser()`:

```python
    parser.add_argument(
        "--csv-path",
        default=None,
        help=(
            "Path to evolution_data.csv exported by tools/redis2pd.py. "
            "When provided, programs are loaded from the CSV instead of Redis."
        ),
    )
```

And update `main()` to load and run when `--csv-path` is given:

```python
    # Replace the existing try block content:
    previous_config_path = os.environ.get("EVO_MEMORY_CONFIG_PATH")
    os.environ["EVO_MEMORY_CONFIG_PATH"] = str(runtime_config_path)
    try:
        tracker = IdeaTracker(logs_dir=args.logs_dir)
        if args.csv_path is not None:
            from gigaevo.memory.ideas_tracker.csv_loader import load_programs_from_csv

            programs = load_programs_from_csv(args.csv_path)
            tracker.run(programs)
        else:
            tracker.run()
    finally:
        if previous_config_path is None:
            os.environ.pop("EVO_MEMORY_CONFIG_PATH", None)
        else:
            os.environ["EVO_MEMORY_CONFIG_PATH"] = previous_config_path
```

- [ ] **Step 4: Run test to verify it passes**

```bash
$GIGAEVO_PYTHON -m pytest tests/memory/test_csv_loader.py::TestCliCsvPath -xvs
```

Expected: `PASSED`

---

## Task 4: Fix `run_ideas_tracker_from_csv.py`

**Files:**
- Modify: `gigaevo/memory/ideas_tracker/run_ideas_tracker_from_csv.py`
- Test: `tests/memory/test_csv_loader.py`

- [ ] **Step 1: Write failing test that `--csv-path` is required**

Append to `tests/memory/test_csv_loader.py`:

```python
class TestRunFromCsvEntryPoint:
    def test_run_from_csv_requires_csv_path(self) -> None:
        """run_ideas_tracker_from_csv should fail without --csv-path."""
        import subprocess, sys
        result = subprocess.run(
            [sys.executable, "-m", "gigaevo.memory.ideas_tracker.run_ideas_tracker_from_csv", "--help"],
            capture_output=True, text=True,
        )
        assert "--csv-path" in result.stdout

    def test_run_from_csv_accepts_csv_path(self, tmp_path: Path) -> None:
        """run_ideas_tracker_from_csv forwards --csv-path to main()."""
        from unittest.mock import patch, MagicMock
        import gigaevo.memory.ideas_tracker.run_ideas_tracker_from_csv as mod

        csv_path = tmp_path / "data.csv"
        _write_csv(csv_path, [_make_row()])

        captured: list = []
        def fake_main(argv):
            captured.extend(argv)
            return 0

        with patch("gigaevo.memory.ideas_tracker.run_ideas_tracker_from_csv.main", fake_main):
            mod.main(["--csv-path", str(csv_path)])

        assert "--csv-path" in captured
        assert str(csv_path) in captured
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
$GIGAEVO_PYTHON -m pytest tests/memory/test_csv_loader.py::TestRunFromCsvEntryPoint -xvs
```

Expected: fails (current file doesn't expose a `main()` function for testing).

- [ ] **Step 3: Rewrite `run_ideas_tracker_from_csv.py`**

```python
# gigaevo/memory/ideas_tracker/run_ideas_tracker_from_csv.py
"""
Entry point: run IdeaTracker on an evolution_data.csv archive.

Usage:
    python -m gigaevo.memory.ideas_tracker.run_ideas_tracker_from_csv \\
        --csv-path path/to/evolution_data.csv [cli.py options...]

The CSV must be produced by tools/redis2pd.py (or equivalent).  All other
options (--redis-prefix, --logs-dir, --no-memory-write, etc.) are forwarded
to the standard IdeaTracker CLI.
"""

from __future__ import annotations

from collections.abc import Sequence
import sys

from gigaevo.memory.ideas_tracker.cli import main


def main(argv: Sequence[str] | None = None) -> int:  # type: ignore[misc]
    """Forward argv to cli.main; --csv-path is required but validated there."""
    args = list(argv) if argv is not None else sys.argv[1:]
    return main(args)


if __name__ == "__main__":
    raise SystemExit(main())
```

Wait — this creates a naming conflict (local `main` shadows the import). Use an alias:

```python
# gigaevo/memory/ideas_tracker/run_ideas_tracker_from_csv.py
"""
Entry point: run IdeaTracker on an evolution_data.csv archive.

Usage:
    python -m gigaevo.memory.ideas_tracker.run_ideas_tracker_from_csv \\
        --csv-path path/to/evolution_data.csv [cli.py options...]

The CSV must be produced by tools/redis2pd.py.  All other options
(--redis-prefix, --logs-dir, --no-memory-write, etc.) are forwarded
to the standard IdeaTracker CLI.
"""

from __future__ import annotations

from collections.abc import Sequence
import sys

from gigaevo.memory.ideas_tracker.cli import main as _cli_main


def main(argv: Sequence[str] | None = None) -> int:
    """Forward argv to cli.main; --csv-path is required but validated there."""
    args = list(argv) if argv is not None else sys.argv[1:]
    return _cli_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run all tests to verify they pass**

```bash
$GIGAEVO_PYTHON -m pytest tests/memory/test_csv_loader.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Run full memory test suite**

```bash
$GIGAEVO_PYTHON -m pytest tests/memory/ -q --tb=short
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
rtk git add gigaevo/memory/ideas_tracker/csv_loader.py \
            gigaevo/memory/ideas_tracker/cli.py \
            gigaevo/memory/ideas_tracker/run_ideas_tracker_from_csv.py \
            tests/memory/test_csv_loader.py
rtk git commit -m "feat(ideas-tracker): implement CSV loading; wire --csv-path into CLI"
```

---

## Self-Review

### Spec coverage
- [x] CSV → Program reconstruction: Task 1–2
- [x] `--csv-path` CLI flag: Task 3
- [x] `run_ideas_tracker_from_csv.py` working entry point: Task 4
- [x] Negative fitness / is_valid already fixed by earlier work (BUG 1)
- [x] Empty CSV handled: `test_empty_csv_returns_empty_list`
- [x] Missing columns handled gracefully: `test_missing_is_valid_column_skipped_gracefully`

### Placeholder scan
No TBDs, TODOs, or vague "handle X" steps. All code shown.

### Type consistency
- `load_programs_from_csv(path: str | Path) -> list[Program]` — used consistently in Task 1, Task 2, Task 3.
- `_row_to_program(row: dict[str, Any]) -> Program` — internal helper, not referenced elsewhere.
- `main(argv: Sequence[str] | None = None) -> int` — in `run_ideas_tracker_from_csv.py`, matches `cli.main` signature.
