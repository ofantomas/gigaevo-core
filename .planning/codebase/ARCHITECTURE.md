# Architecture

## Pattern
**Pipeline-driven evolutionary computation** with MAP-Elites selection strategy.

Programs (Python functions) are evolved through LLM-guided mutation. Each program flows through a DAG pipeline of stages (mutation, evaluation, formatting). A MAP-Elites archive maintains diverse elite solutions. Redis serves as the persistent state layer.

## Layers

```
                  ┌─────────────────────┐
                  │   Entry Point       │  run.py (Hydra CLI)
                  └──────────┬──────────┘
                             │
                  ┌──────────▼──────────┐
                  │  Evolution Engine   │  gigaevo/evolution/engine/
                  │  (core.py,          │  Generational or SteadyState loop
                  │   steady_state.py)  │  Selects parents, triggers mutation
                  └──────────┬──────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
    ┌─────────▼────┐ ┌──────▼──────┐ ┌─────▼─────────┐
    │  Mutation     │ │  DAG Runner │ │  Strategies   │
    │  Operator     │ │  (pipeline) │ │  (MAP-Elites) │
    │  (LLM call)  │ │             │ │               │
    └──────────────┘ └──────┬──────┘ └───────────────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
    ┌─────────▼───┐ ┌──────▼──────┐ ┌────▼──────────┐
    │  Stages     │ │  Collector  │ │  Validator    │
    │  (pipeline  │ │  (formatter)│ │  (problem-    │
    │   stages)   │ │             │ │   specific)   │
    └─────────────┘ └─────────────┘ └───────────────┘
                            │
                  ┌─────────▼──────────┐
                  │  Redis Storage     │  gigaevo/database/
                  │  (programs, state, │  Programs, metrics, archive
                  │   metrics, archive)│
                  └────────────────────┘
```

## Key Abstractions

### Evolution Engine (`gigaevo/evolution/engine/`)
- `EvolutionEngine` (core.py): Generational loop — selects parents, runs mutations in batches, ingests results per generation
- `SteadyStateEvolutionEngine` (steady_state.py): Continuous mutation with asyncio semaphore backpressure
- `BusedEvolutionEngine` (bus/engine.py): Multi-island migration variant
- All engines use `step()` async method for one generation/epoch

### DAG Runner (`gigaevo/runner/dag_runner.py`)
- Executes a directed acyclic graph of stages per program
- Stages declared via Hydra pipeline YAML configs
- Supports caching (`NO_CACHE` stages re-evaluate each run)
- Concurrency: `dag_concurrency=16` parallel DAGs

### Stages (`gigaevo/programs/stages/`)
- Base class: `Stage` with `InputsModel`, `OutputModel`, `compute()` async method
- Key stages: `MutationStage`, `CallValidatorFunction`, `CollectorStage`, `FormatterStage`
- Adversarial stages: `FetchOpponentResultsStage`, `MainRunSyncHook`
- Each stage receives a `Program` and returns typed output

### MAP-Elites Strategy (`gigaevo/evolution/strategies/`)
- `MapElitesMultiIsland`: Multi-island archive with binning strategies
- Acceptor chain: `CompositeAcceptor` filters programs for archive insertion
- Binning: linear bins over behavior dimensions (e.g., fitness resolution)

### Program Model (`gigaevo/programs/program.py`)
- Pydantic BaseModel: `id`, `code`, `state`, `metrics`, `generation`, `parent_id`
- States: PENDING, RUNNING, DONE, ERROR
- Metrics: attached via `add_metrics()`

### Mutation (`gigaevo/evolution/mutation/`)
- LLM-based: sends parent code + context to LLM, gets mutated code back
- Modes: `rewrite` (full rewrite), `diff` (diff-patch)
- Metadata keys: `MutationSpec.META_MODEL`, `META_OUTPUT`, `META_PROMPT_ID`

## Data Flow

1. **Selection**: Engine selects parent(s) from MAP-Elites archive
2. **Mutation**: LLM generates mutated program code
3. **Pipeline**: DAG runner executes stage pipeline on new program:
   - Formatter stage prepares context (failure examples, insights)
   - Validator stage runs problem-specific `validate.py`
   - Collector stage computes metrics and population stats
4. **Ingestion**: Engine ingests result — if valid + competitive, inserted into archive
5. **Persistence**: All data written to Redis (programs, metrics history, run state)

## Extension Points

### Adding a new problem
1. Create `problems/<name>/` with `validate.py`, `metrics.yaml`, `task_description.txt`, `initial_programs/`
2. Reference as `problem.name=<name>` in Hydra config

### Adding a new pipeline
1. Create `config/pipeline/<name>.yaml` defining stage DAG
2. Reference as `pipeline=<name>` in Hydra config

### Adding a new evolution engine
1. Subclass `EvolutionEngine` in `gigaevo/evolution/engine/`
2. Create `config/evolution/<name>.yaml`
3. Reference as `evolution=<name>` in Hydra config
