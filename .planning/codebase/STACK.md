# Technology Stack

## Primary Language
- **Python 3.12+** (`requires-python = ">=3.12"`)
- Runtime: `/home/jovyan/.mlspace/envs/evo/bin/python3` (conda env `evo`)

## Package Management
- **setuptools** build backend (`pyproject.toml`)
- No lockfile — dependencies specified with minimum versions
- Version: `1.28.0`

## Core Frameworks
| Framework | Version | Purpose |
|-----------|---------|---------|
| `hydra-core` | >=1.3.0 | Configuration management, CLI overrides, config composition |
| `pydantic` | >=2.0.0 | Data models, validation, serialization (BaseModel throughout) |
| `redis` | >=4.5.0 | Primary data store (programs, metrics, run state) |
| `loguru` | >=0.7.0 | Structured logging with rotation |
| `openai` | >=1.0.0 | LLM API client (OpenAI-compatible endpoints) |
| `litellm` | >=1.16.11 | LLM proxy and model routing |
| `httpx` | >=0.27.0 | HTTP client for LLM calls |

## ML/Science Stack
| Library | Purpose |
|---------|---------|
| `numpy` >=2.0.0 | Numerical computation |
| `scipy` | Statistical analysis (Welch t-test in experiment analysis) |
| `pandas` | Data export and analysis (`redis2pd.py`) |
| `scikit-learn` >=1.3.2 | Clustering, ML utilities |
| `networkx` | Graph structures (DAG pipeline) |

## Memory/Retrieval Stack
| Library | Purpose |
|---------|---------|
| `chromadb` >=0.4.22 | Vector store for memory system |
| `sentence-transformers` >=2.2.2 | Embedding generation |
| `rank-bm25` >=0.2.2 | Sparse retrieval |
| `nltk` >=3.8.1 | NLP utilities |
| `transformers` >=4.36.2 | Model tokenizers |

## Utilities
| Library | Purpose |
|---------|---------|
| `orjson` | Fast JSON serialization |
| `diffpatch` | Code diff generation for mutations |
| `psutil` >=5.9.0 | Process monitoring (PID checks) |
| `PyYAML` >=6.0 | YAML parsing for experiment manifests |
| `tqdm` >=4.65.0 | Progress bars |

## Dev Dependencies
| Tool | Purpose |
|------|---------|
| `pytest` >=8.0 | Test framework |
| `pytest-asyncio` >=0.23 | Async test support |
| `pytest-cov` >=5.0 | Coverage reporting |
| `pytest-timeout` >=2.4 | Test timeout enforcement |
| `ruff` | Linting + formatting (replaces Black, isort, flake8) |
| `fakeredis[lua]` >=2.19.0 | Redis mock for tests |
| `matplotlib` | Plotting (fitness curves, comparisons) |

## Configuration System
- **Hydra** with YAML configs in `config/`
- Entry point: `python run.py problem.name=<name> [overrides]`
- Config preview: `python run.py [overrides] --cfg job`
- Pipeline configs: `config/pipeline/` (17 pipeline variants)
- Prompt fetcher configs: `config/prompt_fetcher/` (fixed, coevolved)
- Structured configs via Hydra `_target_` instantiation

## Build & Tooling
- **Ruff** for linting and formatting (line length 88, Python 3.12 target)
- **GitHub Actions** CI (`build.yml`): lint + test on Ubuntu
- **GitNexus** for code intelligence (24942 symbols, 66235 relationships)
- **Claude Code** skills and agents for experiment lifecycle automation
- **RTK** (Rust Token Killer) for token-optimized git operations

## Infrastructure
- Runs on NVIDIA GPU servers (Linux 5.15.0-1044-nvidia)
- NFS-mounted workspace
- Redis 16 DBs (0-15) on localhost:6379
- LiteLLM proxy at INTERNAL_IP:4000 for model routing
