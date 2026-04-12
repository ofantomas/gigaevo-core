# Directory Structure

## Top-Level Layout

```
gigaevo-core-internal/
├── gigaevo/                    # Core framework
│   ├── adversarial/            # Adversarial co-evolution components
│   ├── cli/                    # CLI entry points
│   ├── config/                 # Hydra structured configs
│   ├── database/               # Redis storage layer
│   ├── entrypoint/             # Application entry point wiring
│   ├── evolution/              # Evolution engines and strategies
│   │   ├── bus/                # Multi-island migration bus
│   │   ├── engine/             # Core engine + steady-state variant
│   │   ├── mutation/           # LLM-based mutation operators
│   │   ├── scheduling/         # Run scheduling
│   │   ├── storage/            # Evolution-specific storage
│   │   └── strategies/         # MAP-Elites, binning, acceptors
│   ├── infra/                  # Infrastructure (LLM clients, chat)
│   ├── llm/                    # LLM wrappers and structured output
│   ├── memory/                 # Agentic memory system
│   ├── memory_platform/        # Memory platform integration
│   ├── problems/               # Problem interface definitions
│   ├── programs/               # Program model, stages, metrics
│   │   ├── dag/                # DAG construction helpers
│   │   ├── metrics/            # Metrics tracking and context
│   │   └── stages/             # Pipeline stage implementations
│   ├── prompts/                # Default mutation/insights prompts
│   │   └── coevolution/        # Prompt co-evolution stages
│   ├── runner/                 # DAG runner (execution engine)
│   └── utils/                  # Shared utilities, logging
├── config/                     # Hydra config directory
│   ├── pipeline/               # 17 pipeline variants (standard, adversarial, etc.)
│   ├── prompt_fetcher/         # Prompt fetcher configs (fixed, coevolved)
│   ├── evolution/              # Engine configs (generational, steady_state)
│   └── *.yaml                  # Top-level config defaults
├── problems/                   # Problem definitions (one dir per task)
│   ├── heilbron/               # Heilbronn triangle (solo)
│   ├── heilbron_adversarial/   # Heilbronn adversarial (pop_a, pop_b)
│   ├── heilbron_solo/          # Heilbronn solo MAP-Elites
│   ├── chains/hotpotqa/        # HotpotQA multi-hop QA variants
│   ├── chains/hover/           # HoVer fact verification variants
│   ├── prompt_evolution/       # Generic prompt meta-optimization
│   ├── prompt_evolution_hover/ # HoVer prompt meta-optimization
│   └── ...                     # 20+ problem variants
├── experiments/                # Research experiment lifecycle
│   ├── INDEX.md                # Cross-experiment ledger
│   ├── PATTERNS.md             # Cross-cutting research patterns
│   ├── IDEAS.yaml              # Ranked experiment proposals
│   ├── infrastructure.yaml     # Server inventory
│   ├── _template/              # Phase templates (01-05)
│   ├── adversarial/            # Adversarial task experiments
│   │   ├── CONTEXT.md          # Task knowledge
│   │   └── */                  # Individual experiments
│   ├── hotpotqa/               # HotpotQA experiments
│   ├── hover/                  # HoVer experiments
│   └── heilbron/               # Heilbronn experiments
├── tools/                      # General-purpose tools
│   ├── experiment/             # Experiment lifecycle automation
│   ├── dag_builder/            # Visual DAG builder (React+FastAPI)
│   ├── wizard/                 # Problem scaffolding
│   ├── status.py               # Live run monitoring
│   ├── trajectory.py           # Fitness trajectory tables
│   ├── top_programs.py         # Top programs inspector
│   ├── comparison.py           # Multi-run fitness plots
│   ├── flush.py                # Safe Redis flush
│   └── ...                     # 20+ tools
├── tests/                      # Test suite (~4800 tests)
│   ├── conftest.py             # Shared fixtures
│   ├── benchmarks/             # Performance tests
│   ├── integration/            # E2E tests
│   ├── database/               # Redis storage tests
│   ├── evolution/              # Engine tests
│   ├── stages/                 # Stage tests
│   └── ...                     # 19 test subdirectories
├── docs/                       # Documentation
│   └── protocol/               # Experimental protocol
├── .claude/                    # Claude Code configuration
│   ├── skills/                 # Experiment lifecycle skills
│   ├── agents/                 # Specialized AI agents
│   └── settings.json           # Hooks, permissions
├── run.py                      # Main entry point
├── pyproject.toml              # Package config, deps, tools
└── CLAUDE.md                   # Project instructions
```

## Key Locations

| What | Path |
|------|------|
| Entry point | `run.py` |
| Core framework | `gigaevo/` |
| Evolution engine | `gigaevo/evolution/engine/core.py` |
| Steady-state engine | `gigaevo/evolution/engine/steady_state.py` |
| Program model | `gigaevo/programs/program.py` |
| Stage base class | `gigaevo/programs/stages/` |
| DAG runner | `gigaevo/runner/dag_runner.py` |
| Redis storage | `gigaevo/database/redis_program_storage.py` |
| Metrics tracker | `gigaevo/programs/metrics/` |
| Exception hierarchy | `gigaevo/exceptions.py` |
| Hydra configs | `config/` |
| Pipeline definitions | `config/pipeline/*.yaml` |
| Problem definitions | `problems/<name>/validate.py` |
| Experiment manifests | `experiments/<task>/<name>/experiment.yaml` |
| Tool index | `tools/README.md` |

## Naming Conventions

| Entity | Convention | Example |
|--------|-----------|---------|
| Modules | `snake_case.py` | `redis_program_storage.py` |
| Test files | `test_<module>.py` | `test_redis_storage.py` |
| Classes | `PascalCase` | `EvolutionEngine`, `MapElitesMultiIsland` |
| Functions | `snake_case` | `make_program`, `from_dict` |
| Constants | `UPPER_SNAKE_CASE` | `GENESIS_GENERATION`, `VALIDITY_KEY` |
| Configs | `snake_case.yaml` | `adversarial_coevo.yaml` |
| Experiment dirs | `<task>/<kebab-case-name>` | `hover/prompt-coevolution` |
| Branches | `exp/<task>/<name>` | `exp/adversarial/adversarial-vs-solo` |
| Problem dirs | `snake_case` or `chains/<task>/<variant>` | `heilbron_solo`, `chains/hotpotqa/static` |
