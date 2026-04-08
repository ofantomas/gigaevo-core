# Origin Analysis Refactor — Design Spec

**Date:** 2026-04-08
**Branch:** `refactor/origin-analysis-submodules` (from `main`)
**File under refactor:** `gigaevo/memory/ideas_tracker/utils/origin_analysis.py`

---

## Goal

Split the 1,302-line monolithic `origin_analysis.py` into a focused submodule package. Each submodule has one responsibility, an explicit typed interface, and is independently testable. The public API is renamed from `compute_origin_analysis` to `analyse` and the call site in `statistics.py` is updated. No behavioural change.

---

## Motivation

- `compute_origin_analysis()` is 586 lines — too large to hold in context, too coarse to extend
- Zero dedicated tests make it risky to modify
- Adding a new metric requires reading the whole function to find the right insertion point
- After refactor: add a new metric by writing one function in `events.py` or `aggregation.py`, test it in isolation, and call it from `pipeline.py`

---

## New Package Structure

```
gigaevo/memory/ideas_tracker/utils/origin_analysis/   ← replaces origin_analysis.py
├── __init__.py       re-exports analyse() only
├── types.py          shared dataclasses: IntroEvent, DescMetrics, ProgramGraph,
│                     QuartileConfig, LookupIndices, SiblingIndices, AnalysisResult
├── loader.py         load_ideas, load_programs, build_parents, build_children,
│                     invert_idea_to_programs, compute_roots_memoized
├── statistics.py     robust_median, robust_quantile, mad, percentile_rank,
│                     elite_threshold_by_top_k, nanmedian, nanquantile,
│                     nanrate_bool, nancount
├── quartiles.py      generation_quantile_bounds, generation_range_bounds,
│                     generation_to_quartile
├── siblings.py       build_sibling_groups, build_sibling_groups_allgens
├── events.py         compute_intro_events, pick_best_parent, mean_parent_fitness,
│                     compute_descendant_metrics
├── aggregation.py    aggregate_idea_rows, filter_best_ideas
└── pipeline.py       analyse() — ~100-line orchestrator
```

Old `gigaevo/memory/ideas_tracker/utils/origin_analysis.py` is deleted.

---

## Public API

### Before
```python
# gigaevo/memory/ideas_tracker/components/statistics.py
from gigaevo.memory.ideas_tracker.utils.origin_analysis import compute_origin_analysis

df_out, df_best = compute_origin_analysis(
    banks_path=..., programs_path=..., elite_pct=0.1, max_desc_k=5, ...
)
```

### After
```python
from gigaevo.memory.ideas_tracker.utils.origin_analysis import analyse

result = analyse(
    banks_path=..., programs_path=..., elite_pct=0.1, max_desc_k=5, ...
)
# result.summary_df, result.best_ideas_df
```

`__init__.py` exports only `analyse` and `AnalysisResult`. All internal symbols stay private to their modules.

---

## Typed Contracts (`types.py`)

```python
@dataclass
class ProgramGraph:
    valid_pids: set[str]
    parents: dict[str, list[str]]
    children: dict[str, list[str]]
    generations: dict[str, int]
    fitness: dict[str, float]
    roots: dict[str, set[str]]          # memoized root ancestry

@dataclass
class QuartileConfig:
    b1: float
    b2: float
    b3: float
    elite_pids: set[str]
    elite_threshold: float

@dataclass
class LookupIndices:
    prog_to_ideas: dict[str, list[str]]
    gen_to_sorted_fits: dict[int, list[float]]

@dataclass
class SiblingIndices:
    by_gen_bucket: dict[tuple, list[str]]   # (parent_key, gen_bucket) → [child_ids]
    all_gens: dict[str, list[str]]          # parent_key → [child_ids]

@dataclass
class AnalysisResult:
    summary_df: pd.DataFrame       # 5 rows per idea (Q1–Q4 + ALL), ~40 columns
    best_ideas_df: pd.DataFrame    # filtered subset, one row per idea
```

`IntroEvent` and `DescMetrics` move from `origin_analysis.py` into `types.py` unchanged.

---

## Module Responsibilities

### `loader.py`
Reads JSON files, builds the program graph, computes memoized root ancestry.
- **In:** `banks_path: Path`, `programs_path: Path`
- **Out:** `tuple[dict, dict, ProgramGraph]` — (idea_origins, idea_descriptions, graph)

### `statistics.py`
Pure mathematical helpers. No I/O, no pandas, no domain knowledge.
- All functions are stateless and have no side effects.
- Existing functions moved verbatim; no behaviour change.

### `quartiles.py`
Computes generation quartile boundaries and elite threshold from a `ProgramGraph`.
- **In:** `ProgramGraph`, `quartile_mode: str`, `elite_pct: float`
- **Out:** `QuartileConfig`

### `siblings.py`
Groups sibling programs (programs sharing a parent) by generation bucket and across all generations.
- **In:** `ProgramGraph`, `QuartileConfig`
- **Out:** `SiblingIndices`

### `events.py`
Detects intro events (where an idea first appears in a child but not its parents) and computes per-event descendant metrics.
- **In:** `idea_origins: dict`, `ProgramGraph`, `QuartileConfig`, `LookupIndices`
- **Out:** `list[IntroEvent]`, `dict[str, DescMetrics]`

### `aggregation.py`
Aggregates event-level rows into per-idea summary DataFrames and filters to best ideas.
- **In:** `list[IntroEvent]`, per-event metrics dicts, `SiblingIndices`, `LookupIndices`
- **Out:** `AnalysisResult`

### `pipeline.py`
Calls each module in sequence. No logic of its own — only orchestration.
```python
def analyse(banks_path, programs_path, *, elite_pct=0.1, max_desc_k=5,
            quartile_mode="quantile", **kwargs) -> AnalysisResult:
    idea_origins, idea_descriptions, graph = load(banks_path, programs_path)
    quartile_cfg = compute_quartiles(graph, quartile_mode, elite_pct)
    lookup = build_lookup_indices(graph, idea_origins)
    sibling_idx = build_sibling_indices(graph, quartile_cfg)
    events, desc_metrics = detect_events(idea_origins, graph, quartile_cfg, lookup)
    return aggregate(events, desc_metrics, sibling_idx, lookup, idea_descriptions)
```

---

## Testing Strategy

**New test file:** `tests/memory/ideas_tracker/test_origin_analysis.py`

All tests use small synthetic in-memory fixtures (5–10 programs, 3–5 ideas). No JSON files on disk.

| Test class | What it covers |
|---|---|
| `TestLoader` | load from fixture dict → correct `ProgramGraph` fields |
| `TestStatistics` | `robust_median`, `mad`, `percentile_rank`, `nanquantile` with known inputs |
| `TestQuartiles` | known fitness list → correct Q1/Q2/Q3 boundaries; elite threshold |
| `TestSiblings` | 4-program graph → correct sibling groupings per gen and all-gens |
| `TestEvents` | 3-program chain with known idea origins → correct `IntroEvent` detected |
| `TestAggregation` | pre-built event rows → correct summary DataFrame shape and values |
| `TestPipeline` | end-to-end smoke test with synthetic fixture → `AnalysisResult` has expected columns |

Existing behaviour of `compute_origin_analysis` is the regression oracle: the end-to-end smoke test asserts `result.summary_df` columns and row count match a known-good run on the synthetic fixture.

---

## What Does NOT Change

- All function logic moved verbatim — no algorithmic changes
- `statistics.py` in `ideas_tracker/components/` updates its import to `from ... import analyse` — one line change
- CLI entry point (`main()`) moves to `pipeline.py` — same interface
- No config, no Hydra, no Redis

---

## Out of Scope

- Algorithmic improvements to any metric
- Changing the output DataFrame schema
- Refactoring `statistics.py` in `ideas_tracker/components/` beyond the import update
- The other three refactor targets (data_components, memory_platform, steady_state)
