# IdeasTracker Refactor — Design Spec

**Date:** 2026-04-08  
**Scope:** Quality refactor of `gigaevo/memory/ideas_tracker/`. Same behaviour, simpler structure.  
**Constraint:** Existing tests in `tests/memory/test_ideas_tracker_pipeline.py` must stay green.

---

## Problem

The current module has 22 files, 7 data classes, and 3 layers of wrapping around a list of ideas.
`ideas_tracker.py` alone has 13 intra-package import statements. A new reader must trace through
`components/`, `components/fabrics/`, and `utils/` just to follow one program through the pipeline.

Root causes:
- `IdeaAnalyzer` and `IdeaAnalyzerFast` share no interface, so everything built on top branches on a string type
- `RecordListV2 → RecordBank → RecordManager` is three layers for "a list with search"
- `components/fabrics/` contains factory functions that are each 5–20 lines with no real abstraction
- `postprocessing.py` has 4 near-identical functions for one concept (sync/async split)
- `it_logger.py` does read-modify-write on JSON files for every log event
- Data classes use custom `__init__` overrides, manual `setattr` loops, and `asdict()` calls

---

## Target File Structure

```
gigaevo/memory/ideas_tracker/
  ideas_tracker.py    # IdeaTracker(PostRunHook) — pipeline orchestration only
  models.py           # All Pydantic models: Idea, ProgramRecord, IdeaUpdate, AnalysisResult, etc.
  idea_bank.py        # IdeaBank — flat idea store with classification chunking
  llm.py              # LLMClient — wraps PromptManager + OpenAI client
  analyzers.py        # Analyzer protocol + ClassifyingAnalyzer + ClusteringAnalyzer
  cli.py              # CLI entry point (unchanged)
```

**Deleted entirely:**
- `components/` directory and all contents
- `components/fabrics/` and all factory functions
- `utils/it_logger.py`, `utils/records_converter.py`, `utils/helpers.py`, `utils/task_description_loader.py`

---

## Data Models (`models.py`)

All data transfer types are Pydantic `BaseModel`. This gives:
- Validation at construction
- `.model_dump()` replacing all manual `to_dict()` / `asdict()` calls
- Clean field definitions with `Field(default_factory=...)`

```python
class IdeaExplanation(BaseModel):
    """Accumulated motivations and synthesised summary for an Idea."""
    entries: list[str] = Field(default_factory=list)
    summary: str = ""


class Idea(BaseModel):
    """
    A tracked improvement idea extracted from evolutionary programs.

    Produced by an Analyzer and stored in IdeaBank. Enriched with keywords
    and a summary after initial classification.
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

    Created by converting a raw Program object; carries only the fields
    the analyzers need (no stage results, no raw execution data).
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
    """Instruction to update an existing Idea in IdeaBank."""
    idea_id: str
    programs: list[str] = Field(default_factory=list)
    generation: int = 0
    new_description: str | None = None
    motivation: str | None = None


class AnalysisResult(BaseModel):
    """
    Output of Analyzer.analyze().

    Contains ideas to add to the bank (new_ideas) and updates to apply
    to ideas already in the bank (updates).
    """
    new_ideas: list[Idea] = Field(default_factory=list)
    updates: list[IdeaUpdate] = Field(default_factory=list)


class EmbeddedIdea(BaseModel):
    """
    An improvement extracted from a ProgramRecord with its embedding vector.

    Used internally by ClusteringAnalyzer during the embed → cluster → refine pipeline.
    """
    id: str = Field(default_factory=lambda: str(uuid4()))
    description: str
    source_program_id: str = ""
    cluster_id: str = ""
    change_motivation: str = ""
    embedding: list[float] = Field(default_factory=list)
```

`IdeaCluster` stays a plain class (mutable working object, internal to `ClusteringAnalyzer`).
`normalize_improvements` / `normalize_improvement_item` stay as module-level functions in `models.py`.

---

## Idea Bank (`idea_bank.py`)

Replaces `RecordListV2 + RecordBank + RecordManager` (three layers) with one flat class.

```python
class IdeaBank:
    """
    Stores and manages Idea objects for an IdeaTracker session.

    Provides add/get/update/enrich operations and produces chunked
    representations for LLM classification calls.
    """

    def __init__(self, chunk_size: int = 5) -> None: ...

    def add(self, idea: Idea) -> None:
        """Append a new Idea. Reassigns id if it already exists in the bank."""

    def get(self, idea_id: str) -> Idea | None:
        """Return the Idea with the given id, or None."""

    def apply(self, result: AnalysisResult) -> None:
        """Add all new_ideas and apply all updates from an AnalysisResult."""

    def update(self, update: IdeaUpdate) -> bool:
        """Apply an IdeaUpdate to an existing Idea. Returns False if not found."""

    def enrich(self, idea_id: str, *, keywords: list[str], summary: str, task_summary: str) -> bool:
        """Set keywords and summary on an existing Idea. Returns False if not found."""

    def all_ideas(self) -> list[Idea]:
        """Return all ideas in insertion order."""

    def classification_chunks(self) -> list[ClassificationChunk]:
        """
        Return ideas grouped into fixed-size chunks for LLM classification calls.

        Each chunk contains a formatted text block and a list of short-id mappings,
        matching the format expected by ClassifyingAnalyzer.
        """
```

`ClassificationChunk` is a small Pydantic model:
```python
class ClassificationChunk(BaseModel):
    text: str
    short_ids: list[dict[str, str]]  # [{"id": ..., "short_id": ..., "description": ...}]
```

---

## LLM Client (`llm.py`)

`LLMClient` absorbs `PromptManager` — they were always tightly coupled (every `LLMClient`
held a `PromptManager`). `PromptManager` becomes a private implementation detail.

```python
class LLMClient:
    """
    OpenAI-compatible LLM client with prompt-file loading.

    Prompts are loaded from the `prompts/` directory adjacent to this file.
    Each step name maps to `prompts/{step}/system.txt` and `prompts/{step}/user.txt`.
    Supports synchronous and asynchronous calls with optional concurrency limiting.
    """

    def __init__(
        self,
        model: str,
        base_url: str | None = None,
        max_concurrent: int = -1,
    ) -> None: ...

    def call(self, step: str, content: str | dict[str, str] = "", reasoning: dict | None = None) -> str:
        """Synchronous chat completion for the given prompt step."""

    async def call_async(self, step: str, content: str | dict[str, str] = "", reasoning: dict | None = None) -> str:
        """Asynchronous chat completion for the given prompt step."""
```

---

## Analyzers (`analyzers.py`)

### Protocol

```python
class Analyzer(Protocol):
    """
    Common interface for idea analyzers.

    Both ClassifyingAnalyzer and ClusteringAnalyzer implement this protocol,
    allowing IdeaTracker to use either without branching.
    """
    model: str

    def analyze(self, records: list[ProgramRecord]) -> AnalysisResult:
        """Extract and classify improvement ideas from a batch of program records."""

    def call(self, step: str, content: str) -> str:
        """Synchronous LLM call — used by the enrichment step in IdeaTracker."""

    async def call_async(self, step: str, content: str) -> str:
        """Asynchronous LLM call — used by the enrichment step in IdeaTracker."""
```

### ClassifyingAnalyzer (was `IdeaAnalyzer`)

```python
class ClassifyingAnalyzer:
    """
    Classifies incoming improvement ideas against an existing idea bank using an LLM.

    Processes programs sequentially. For each program, asks the LLM whether each
    incoming idea is new, an update to an existing idea, or a rewrite of one.

    Receives the same IdeaBank instance as IdeaTracker at construction. The analyzer
    reads it for classification context; IdeaTracker writes to it via bank.apply().
    They share the instance — the analyzer never writes to the bank directly.
    """

    def __init__(
        self,
        bank: IdeaBank,
        model: str = "google/gemini-3-flash-preview",
        base_url: str | None = None,
        reasoning: dict | None = None,
        retry_attempts: int = 10,
    ) -> None: ...

    def analyze(self, records: list[ProgramRecord]) -> AnalysisResult:
        """Classify all records against the bank. Returns new ideas and updates."""
```

### ClusteringAnalyzer (was `IdeaAnalyzerFast`)

```python
class ClusteringAnalyzer:
    """
    Groups improvement ideas by semantic similarity using embeddings, DBSCAN,
    and async LLM refinement.

    Processes all records in a single batch. Does not consult the existing bank —
    always returns new_ideas with an empty updates list. Suitable when starting
    from scratch or when bank state is not needed for deduplication.
    """

    def __init__(
        self,
        model: str = "google/gemini-3-flash-preview",
        embeddings_model: str = "sentence-transformers/all-mpnet-base-v2",
        base_url: str | None = None,
        reasoning: dict | None = None,
        # ... DBSCAN / refinement knobs unchanged
    ) -> None: ...

    def analyze(self, records: list[ProgramRecord]) -> AnalysisResult:
        """Embed, cluster, refine, and return one Idea per surviving cluster."""
```

---

## Pipeline (`ideas_tracker.py`)

```python
class IdeaTracker(PostRunHook):
    """
    PostRunHook that extracts, classifies, enriches, and stores improvement ideas
    from a completed evolutionary run.

    Instantiated via Hydra. Accepts either a ClassifyingAnalyzer or ClusteringAnalyzer —
    both implement the Analyzer protocol, so the pipeline is identical for both.
    """

    def __init__(
        self,
        *,
        analyzer: ClassifyingAnalyzer | ClusteringAnalyzer,
        task_description: str = "",
        chunk_size: int = 5,
        memory_write_enabled: bool = True,
        memory_usage_tracking_enabled: bool = True,
        fitness_key: str = "fitness",
        logs_dir: str | Path | None = None,
    ) -> None: ...

    async def on_run_complete(self, storage: ProgramStorage) -> None:
        """Called by EvolutionEngine after the generation loop finishes."""
        programs = await storage.get_all(exclude=EXCLUDE_STAGE_RESULTS)
        if not programs:
            return
        await self._run(programs)

    async def _run(self, programs: list[Program]) -> None:
        records = self._eligible_records(programs)
        if self._memory_usage_tracking_enabled:
            usage_updates = _build_usage_updates(programs, self._task_summary, self._fitness_key)
        result = self._analyzer.analyze(records)
        self._bank.apply(result)
        if self._memory_usage_tracking_enabled:
            _apply_usage_updates(self._bank, usage_updates)
        await _enrich_ideas(self._bank.all_ideas(), self._analyzer, self._task_summary)
        self._log.flush(self._bank, programs=self._all_records)
        _run_write_pipeline(self._memory_write_enabled, self._log)
```

Key changes vs current:
- No `if analyzer_pipeline_type == "default"` branch — one code path
- `_enrich_ideas` is always async (no sync/async union type)
- `_SessionLog` (private class in this file) accumulates entries in memory; `flush()` writes all JSON files at the end in one pass — no read-modify-write per event
- `_task_summary` computed lazily via `@cached_property` (no `""` sentinel cache)
- Analyzer injected directly (no string + factory indirection)

### `_SessionLog` (private)

```python
class _SessionLog:
    """
    Accumulates log entries in memory during a run and writes all files on flush().

    Replaces the per-event read-modify-write pattern of IdeasTrackerLogger.
    Files written: log.txt, banks.json, programs.json, best_ideas.json,
    memory_usage_updates.json.
    """

    def flush(self, bank: IdeaBank, *, programs: list[ProgramRecord]) -> None:
        """Write all accumulated entries to the timestamped session directory."""
```

---

## What Does NOT Change

The following logic is preserved exactly — only its location/wrapping changes:

- `normalize_improvements` / `normalize_improvement_item` — stay in `models.py`
- `build_memory_usage_updates_from_programs` — stays as module-level function, moves to `ideas_tracker.py`
- `merge_usage_payloads` / `build_usage_payload_from_task_deltas` — move to `idea_bank.py`
- `compute_origin_analysis` — stays in `utils/origin_analysis.py` (only caller is `statistics.py`, which folds into `_SessionLog.flush`)
- All LLM prompt files in `components/prompts/` — moved to `prompts/` at the package root (same directory as `llm.py`). `_PromptLoader` uses `Path(__file__).resolve().parent / "prompts"`.
- All DBSCAN / embedding / refinement logic in `ClusteringAnalyzer` — unchanged
- All `ClassifyingAnalyzer` classification logic — unchanged
- `PostRunHook` ABC, `NullPostRunHook` — unchanged

---

## Naming Summary

| Old | New | File |
|-----|-----|------|
| `RecordCardExtended` | `Idea` | `models.py` |
| `RecordCardEmbedding` | `EmbeddedIdea` | `models.py` |
| `IdeaExplanation` (dict) | `IdeaExplanation` (Pydantic) | `models.py` |
| `IncomingIdeas` | internal scratch (not exported) | `analyzers.py` |
| `RecordListV2 + RecordBank + RecordManager` | `IdeaBank` | `idea_bank.py` |
| `IdeaAnalyzer` | `ClassifyingAnalyzer` | `analyzers.py` |
| `IdeaAnalyzerFast` | `ClusteringAnalyzer` | `analyzers.py` |
| `IdeasTrackerLogger` | `_SessionLog` | `ideas_tracker.py` |
| `LLMClient` | `LLMClient` | `llm.py` |
| `PromptManager` | private `_PromptLoader` | `llm.py` |
| `create_analyzer` / `create_postprocessing` | deleted | — |
| `_extract_ideas_v2` | `_classify_against_bank` | `analyzers.py` |
| `ideas_groups_texts` | `classification_chunks` | `idea_bank.py` |
| `ClusterCard` | `IdeaCluster` (plain class) | `analyzers.py` |
| `process_ideas` stub on Fast | deleted | — |
| `enrich_ideas` / `enrich_ideas_async` / `enrich_idea_async_` | `_enrich_ideas` (one async fn) | `ideas_tracker.py` |

---

## Test Impact

Existing tests (`tests/memory/test_ideas_tracker_pipeline.py`) test:
- `program_to_record` / `programs_to_records` → move to `models.py`, keep same signature
- `build_memory_usage_updates_from_programs` → stays as module-level fn, import path changes
- `IdeaTracker` as `PostRunHook` → constructor signature changes (takes `analyzer` object, not string)
- `IdeaTracker._get_new_programs` → renamed `_eligible_records`, same filtering logic

All existing tests need import-path updates. Constructor tests need a mock analyzer injected.
No test logic changes — same assertions, same factories.
