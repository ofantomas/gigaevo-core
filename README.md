# GigaEvo

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

Evolutionary algorithm framework that uses Large Language Models to automatically
improve programs through iterative mutation and selection (MAP-Elites). Programs
are Python functions; fitness is task performance. The framework is task-agnostic
and supports single runs, multi-island evolution, and prompt co-evolution.

## Demo

![Demo](./docs/demos/demo-opt.gif)

## Getting Started

- **[Quick Start](docs/QUICKSTART.md)** — Get running in 5 minutes
- **[Architecture Guide](docs/ARCHITECTURE.md)** — System design overview

## Documentation

| Guide | Description |
|-------|-------------|
| [Adversarial Co-Evolution](docs/adversarial_coevolution.md) | Two-population co-evolution guide (generator/discriminator pattern) |
| [DAG System](docs/DAG_SYSTEM.md) | Execution engine: stages, dependencies, caching |
| [Evolution Strategies](docs/EVOLUTION_STRATEGIES.md) | MAP-Elites, multi-island, migration |
| [Memory System](docs/memory.md) | How memory-augmented mutation works (writers, readers, providers, ideas tracker) |
| [Optuna Optimization](docs/OPTUNA_OPTIMIZATION.md) | LLM-driven hyperparameter sweeps for evolved programs |
| [Prompt Co-Evolution](docs/COEVOLUTION.md) | Co-evolve mutation prompts alongside programs |
| [Tools](tools/README.md) | Analysis, debugging, and problem scaffolding utilities |
| [Usage Guide](docs/USAGE.md) | Detailed usage and Hydra configuration |
| [Contributing](docs/CONTRIBUTING.md) | Guidelines for contributors |
| [Changelog](CHANGELOG.md) | Version history |

## Quick Start

### 1. Install

**Requirements:** Python 3.11+, Redis

GigaEvo ships with a minimal core and opt-in **extras** so installs stay fast
on firewalled/slow networks. Pick the install level that matches your use:

| Use case | Command |
|---|---|
| **Minimal** — engine + numpy exemplar problems + LLM mutation + core CLI (`status`, `top`, `trajectory`, `logs`, `flush`, `checkpoint`, `inspect`, `launch`, `watchdog`, `export`) | `pip install -e .` |
| **Common** — also runs chain/NLP problems (HoVer, HotpotQA, IFBench, gsm8k, …) + `gigaevo plot` / `gigaevo events` / `gigaevo profiler` | `pip install -e ".[chains,plotting]"` |
| **Full** — everything user-facing (chains, optimization, plotting, tracking, local-LLM runtime, memory platform) | `pip install -e ".[all]"` |
| **Developer** — full + linters, type-checkers, pytest, dag_builder dev API | `pip install -e ".[all,dev,test]"` |

À la carte mapping of features to extras:

| Feature / module | Required extras |
|---|---|
| `gigaevo plot`, `gigaevo events`, `gigaevo profiler` | `[plotting]` |
| Chain/prompt problems: HoVer, HotpotQA, IFBench, gsm8k, musique, papillon, pupa | `[chains]` |
| Optuna / CMA optimization stages | `[optimization]` |
| Alphaevolve / hexagon_improver / santa2025 problems (JAX, sympy, shapely) | `[optimization]` |
| W&B / TensorBoard tracker backends | `[tracking]` |
| sudoku local-runtime solver (torch + vllm) | `[local-llm]` |
| GAM memory **platform** backend (`use_api=True`) — local backend needs nothing | `[memory-platform]` |
| `tools/dag_builder` web API | `[dev]` (uvicorn) |

Install Redis if not already available:

```bash
# Ubuntu/Debian
sudo apt-get install redis-server

# macOS
brew install redis

# Or run via Docker
docker run -d -p 6379:6379 redis:7-alpine
```

### 2. Configure LLM Access

Create a `.env` file with your API key:

```bash
OPENAI_API_KEY=sk-or-v1-your-api-key-here

# Optional: Langfuse tracing
LANGFUSE_PUBLIC_KEY=<key>
LANGFUSE_SECRET_KEY=<key>
LANGFUSE_HOST=https://cloud.langfuse.com
```

### 3. Start Redis

```bash
redis-server
```

### 4. Run Evolution

```bash
python run.py problem.name=heilbron
```

Evolution starts immediately. Logs are saved to `outputs/`.

### 5. Launch a managed experiment (`gigaevo launch`)

`python run.py` is the low-level launcher. For tracked runs use the
**experiment-manifest** workflow of the `gigaevo` CLI (registered by
`pip install -e .`): it adds preflight validation, Redis-DB claiming, `nohup`
exec, and a watchdog. A worked, end-to-end example manifest ships at
[`experiments/sella/full_sella_baseline_evolution/experiment.yaml`](experiments/sella/full_sella_baseline_evolution/experiment.yaml).

**A. Per-machine setup (coordinator).**

```bash
pip install -e .                              # registers the `gigaevo` CLI + entry points
gigaevo --help                                # NB: global flags (-e/-r/...) go BEFORE the subcommand
redis-server                                  # one Redis serves program storage AND the validation queue
echo "OPENAI_API_KEY=sk-or-v1-..." > .env     # OpenRouter key (LANGFUSE_* keys here auto-enable tracing)
export GIGAEVO_PYTHON=$(which python)          # REQUIRED: launch.sh + the GIGAEVO_PYTHON gate use this;
                                               # the built-in default is a stale path and will fail.
```

**B. Problem + seeds.** A problem dir holds `metrics.yaml`, `task_description.txt`,
`initial_programs/`, and a `validate(optimizer, …)` entry. You can point at an
external checkout with `problem.dir=…`, **but the preflight seed-check always
looks at `problems/<problem_name>/initial_programs/`** — so symlink it:

```bash
ln -sfn /abs/path/to/problem_checkout problems/<problem_name>
```

> **`validate()` must return a pure-numeric metrics dict** (`dict[str, float]`).
> The validator stage rejects strings/bools (e.g. an `invalid_reason` string) —
> keep diagnostics out of the returned dict.

**C. Distributed validation workers** — only for problems whose `validate()`
farms work to a Redis-backed pool (e.g. the Sella optimizer). The pool's queue
is the coordinator Redis **db0** (the `RemoteOptimizationClient` default), so the
GigaEvo run must store programs in a **different** DB (see `runs[].db` below).
On each worker host run a babysat pool (`JAX_ENABLE_X64=1` is required for xTB);
for the Sella problem use the helper in the problem repo:

```bash
# opt_problem/scripts/deploy_validate_workers.sh [branch] [coordinator] [num_workers]
scripts/deploy_validate_workers.sh full-sella-baseline-evolution a002dc-0002 48
# (equivalently, the raw pool — coordinator Redis reached via an SSH-config alias:)
JAX_ENABLE_X64=1 scripts/babysit_validate.sh <coordinator-alias> 6379 6380 48 \
    xtb 1.0 true logs_validate "$(which python)" 1 10 1200 64
```

**D. Author the manifest** at `experiments/<task>/<name>/experiment.yaml`
(`schema_version: 2`). Key fields the preflight gates care about:

```yaml
schema_version: 2
contract:
  identity: { name: sella/full_sella_baseline_evolution, task: sella, branch: full-sella-baseline-evolution }
  problem:
    name: full_sella_baseline_evolution
    has_test_set: true
    fitness_type: continuous
    metric_name: fitness
    test_set_path: /abs/path/molecules/test_XTB.json
    test_set_sha256: <sha256sum of the test set>   # required when has_test_set: true
  config:
    problem_name: full_sella_baseline_evolution
    pipeline: intra_extra_memory          # "new standard": intra+extra memory + live refresh hook
    llm_model: google/gemini-3.5-flash
    shared_overrides:
      mutation_mode: diff                 # SEARCH/REPLACE diff mutation
      num_parents: 1
      algorithm: single_island            # 1D island, fitness as the axis
      max_concurrent_dags: 5
      max_code_length: 200000             # raise above the 30000 default for large seeds
      problem.dir: /abs/path/to/problem_checkout
  runs:
    - label: A1
      db: 1                               # program storage — MUST differ from the xTB queue (db0)
      prefix: fsbe
      pipeline: intra_extra_memory
      problem_name: full_sella_baseline_evolution
      condition: diff_baseline
      model_name: google/gemini-3.5-flash
      mutation_url: https://openrouter.ai/api/v1   # else the generator emits llm_base_url=None
  servers: [ https://openrouter.ai/api/v1 ]
  max_generations: 1000000                # drives `max_mutants`; large == effectively open-ended
  baseline: { reference: sella, metric: mean_rel_steps }
lifecycle:
  status: implemented                     # set after a green smoke test (see E)
  smoke_test: { completed: true, db: 1, generations: 3 }
  treatment_verification: { completed: true }   # single-condition run -> N/A, but the gate needs true
control_plane:
  notifications:
    telegram: { enabled: false }          # enable only where api.telegram.org is reachable + creds set
    pr: { enabled: false }
```

**E. Smoke test → implemented → launch.** `gigaevo launch` enforces CRITICAL
gates: status `implemented`, `GIGAEVO_PYTHON` set/executable, LLM endpoint +
model-id reachable (`/v1/models`), **Redis run-DB empty + claimable**, seed
programs exist, test-set SHA matches, smoke test completed, treatment
verification completed, resolved config matches pins. A quick smoke run first:

```bash
EXP=sella/full_sella_baseline_evolution

# Smoke: a few mutants on a scratch DB; confirms seed scores + diff mutation + workers.
python run.py problem.name=full_sella_baseline_evolution problem.dir=/abs/checkout \
  pipeline=intra_extra_memory mutation_mode=diff algorithm=single_island num_parents=1 \
  model_name=google/gemini-3.5-flash llm_base_url=https://openrouter.ai/api/v1 \
  max_code_length=200000 redis.db=1 max_mutants=3

gigaevo -e "$EXP" launch --dry-run       # preflight only (claims the run DB); fix any CRITICALs
gigaevo -e "$EXP" launch                 # preflight → claim DB → nohup exec → spawn watchdog
```

Monitor: `gigaevo -e "$EXP" status` / `top` / `trajectory` / `logs` (+ Langfuse UI).
Stop the open-ended run by killing the recorded run + watchdog PIDs.

## How It Works

1. **Load initial programs** from `problems/<name>/initial_programs/`
2. **Mutate programs** using LLMs (GPT, Claude, Gemini, Qwen, etc.)
3. **Evaluate fitness** by running each program's `entrypoint()` + `validate()`
4. **Select solutions** using MAP-Elites across a behavior space
5. **Repeat** continuously (steady-state) until a `stopper` (e.g. `max_mutants`,
   wall-clock, fitness-plateau) fires

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Problem   │────▶│  Evolution  │────▶│     LLM     │
│  (programs, │     │   Engine    │     │  (mutation)  │
│   metrics)  │     │ (MAP-Elites)│     └──────┬──────┘
└─────────────┘     └──────┬──────┘            │
                           │                   ▼
                    ┌──────┴──────┐     ┌─────────────┐
                    │   Storage   │◀────│  Evaluator   │
                    │   (Redis)   │     │ (DAG Runner) │
                    └─────────────┘     └─────────────┘
```

## Customization

### Experiment Presets

```bash
# Migration bus: parallel runs share rejected programs via Redis stream
python run.py experiment=migration_bus problem.name=heilbron redis.db=0
python run.py experiment=migration_bus problem.name=heilbron redis.db=1

# Multi-island evolution (fitness + simplicity islands)
python run.py experiment=multi_island_complexity problem.name=heilbron

# Multi-LLM exploration (diverse mutation models)
python run.py experiment=multi_llm_exploration problem.name=heilbron

# Prompt co-evolution (evolve mutation prompts alongside programs)
python run.py experiment=prompt_coevolution problem.name=heilbron \
    redis.db=4 prompt_fetcher.prompt_redis_db=6
```

### Common Overrides

```bash
# Cap total mutants (steady-state stopper budget)
python run.py problem.name=heilbron max_mutants=10

# Use different Redis database
python run.py problem.name=heilbron redis.db=5

# Change LLM model
python run.py problem.name=heilbron model_name=anthropic/claude-3.5-sonnet

# Pick a different stopper (wall-clock, fitness-plateau, ...)
python run.py problem.name=heilbron stopper=wall_clock

# Preview config without running
python run.py problem.name=heilbron --cfg job
```

### Prompt Co-Evolution

Co-evolve the mutation prompts alongside your programs. A paired prompt run
evolves the system prompt used by the mutation LLM, selecting for prompts that
produce better mutations:

```bash
# Main run — uses co-evolved prompts from DB 6
python run.py problem.name=my_task pipeline=my_pipeline \
    prompt_fetcher=coevolved prompt_fetcher.prompt_redis_db=6 redis.db=4

# Prompt run — evolves mutation prompts, reads outcomes from DB 4
python run.py problem.name=prompt_evolution pipeline=prompt_evolution \
    redis.db=6 main_redis_db=4 main_redis_prefix=my_task
```

See [Prompt Co-Evolution Guide](docs/COEVOLUTION.md) for the full architecture,
launch instructions, and monitoring.

## Configuration

GigaEvo uses [Hydra](https://hydra.cc/) for modular configuration. All config
files are in `config/`:

| Directory | Purpose | Key files |
|-----------|---------|-----------|
| `experiment/` | Complete experiment templates | `base.yaml`, `full_featured.yaml`, `migration_bus.yaml`, `multi_island_complexity.yaml`, `multi_llm_exploration.yaml`, `prompt_coevolution.yaml`, `steady_state_adversarial.yaml` |
| `algorithm/` | Evolution algorithms | `single_island.yaml`, `single_island_2d.yaml`, `multi_island.yaml`, `topology_3d.yaml` |
| `llm/` | LLM setups | `single.yaml`, `heterogeneous.yaml`, `heterogeneous_bandit.yaml`, `openrouter_bandit.yaml`, `openrouter_ensemble.yaml` |
| `pipeline/` | DAG execution pipelines | `auto.yaml` (default), `standard.yaml`, `with_context.yaml`, `custom.yaml`, `prompt_evolution.yaml` |
| `prompt_fetcher/` | Prompt sourcing | `fixed.yaml`, `coevolved.yaml` |
| `stopper/` | Stopping criteria | `max_mutants.yaml` (default), `wall_clock.yaml`, `fitness_plateau.yaml` |
| `constants/` | Tunable parameters | `evolution.yaml`, `llm.yaml`, `islands.yaml`, `pipeline.yaml`, `runner.yaml`, `endpoints.yaml`, `redis.yaml`, `logging.yaml` |
| `loader/` | Program loading | `directory.yaml`, `redis_selection.yaml` |
| `logging/` | Backends | `tensorboard.yaml`, `wandb.yaml` |

Override any setting via command line:
```bash
python run.py experiment=full_featured max_mutants=50 temperature=0.8
```

## Creating a Problem

1. Create a directory under `problems/`:
   ```
   problems/my_problem/
   ├── validate.py           # Fitness evaluation
   ├── metrics.yaml          # Metric specifications
   ├── task_description.txt  # Problem description for the LLM
   └── initial_programs/     # Seed programs
       ├── strategy1.py      # Must define entrypoint()
       └── strategy2.py
   ```

2. Run:
   ```bash
   python run.py problem.name=my_problem
   ```

Or use the wizard: `python -m tools.wizard config.yaml`

See `problems/heilbron/` for a complete example.

## Output

Results are saved to `outputs/YYYY-MM-DD/HH-MM-SS/`:
- **Logs**: `evolution_*.log`
- **Programs**: Stored in Redis (export with `gigaevo export csv`)
- **Metrics**: TensorBoard / W&B (if configured)

## CLI Tools (`gigaevo`)

Installed via `pip install -e .`. Global flags: `-e/--experiment`, `-r/--run`, `-f/--format`.

| Command | Purpose |
|---------|---------|
| `gigaevo -e EXP status` | Live monitoring: gen, metrics, PIDs, watchdog |
| `gigaevo -r RUN trajectory` | Gen-by-gen fitness trajectory |
| `gigaevo -r RUN top` | Inspect best programs by fitness |
| `gigaevo -e EXP plot comparison -o DIR` | Multi-run fitness curve plots |
| `gigaevo -e EXP plot arms-race -o DIR` | Dual-panel adversarial arms-race plot |
| `gigaevo -e EXP profiler` | Profile runner logs into text summary + HTML dashboard |
| `gigaevo -e EXP manifest gate <status>` | Hard-gate on experiment status (preregistered/implemented/running/complete) |
| `gigaevo -r RUN export csv -o FILE` | Export evolution data to CSV |
| `gigaevo flush --db N --confirm` | Safely flush Redis DBs (kills workers first) |
| `gigaevo -e EXP launch` / `watchdog` | Launch + supervise an experiment |
| `tools/experiment/archive_run.sh` | Archive run data before flush |
| `tools/dag_builder/` | Visual DAG pipeline designer |
| `tools/wizard/` | Interactive problem scaffolding |

See [tools/README.md](tools/README.md) for full CLI reference and Redis key schema.

## Testing

```bash
# Full test suite (uses fakeredis, no Redis server needed)
python -m pytest

# Specific area
python -m pytest tests/stages/
python -m pytest tests/evolution/

# With coverage
python -m pytest --cov=gigaevo --cov-report=term-missing

# Linting
ruff check . && ruff format --check .
```

## Troubleshooting

**Redis database not empty:**
```bash
# Flush (kills exec_runner workers first):
gigaevo flush --db 0 --confirm

# Or use a different DB:
python run.py redis.db=1
```

**LLM connection issues:**
```bash
# Verify API key
echo $OPENAI_API_KEY

# Test OpenRouter
curl -H "Authorization: Bearer $OPENAI_API_KEY" https://openrouter.ai/api/v1/models
```

## License

MIT License — see [LICENSE](LICENSE).

## Citation

```bibtex
@misc{khrulkov2025gigaevoopensourceoptimization,
      title={GigaEvo: An Open Source Optimization Framework Powered By LLMs And Evolution Algorithms},
      author={Valentin Khrulkov and Andrey Galichin and Denis Bashkirov and Dmitry Vinichenko and Oleg Travkin and Roman Alferov and Andrey Kuznetsov and Ivan Oseledets},
      year={2025},
      eprint={2511.17592},
      archivePrefix={arXiv},
      primaryClass={cs.NE},
      url={https://arxiv.org/abs/2511.17592},
}
```
