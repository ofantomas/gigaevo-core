# Concerns

## Technical Debt

### Watchdog Template Fragility
- **Location**: `experiments/_template/` watchdog, copied per experiment
- **Issue**: Watchdog templates assume adversarial pair labeling (`P{N}_A`/`P{N}_B`) — breaks for solo or non-standard experiments. Telegram integration and plot generation had to be manually patched for `adversarial/adversarial-vs-solo`.
- **Impact**: Every new experiment type risks watchdog failures
- **Fix needed**: Generic watchdog that reads run config from `experiment.yaml` and adapts plot/notification logic accordingly

### Memory System Complexity
- **Location**: `gigaevo/memory/`, `gigaevo/memory_platform/`
- **Issue**: Complex subsystem with ChromaDB, sentence-transformers, BM25 retrieval. 593 tests but coverage only 66%. 17 Pydantic models with `ConfigDict(extra="forbid")` after audit.
- **Resolved bugs**: Double-escaped quotes, circular imports, duplicate dedup, `load_dotenv()` side effects (PR #198)
- **Ongoing risk**: Memory subsystem interactions are subtle — changes here have cascading effects

### Heavy Dependency Footprint
- **Issue**: `chromadb`, `sentence-transformers`, `transformers`, `nltk`, `scikit-learn` are large dependencies primarily for the memory system. Adds significant install time and disk usage.
- **Impact**: Slow environment setup, large Docker images if containerized

## Known Bugs & Workarounds

### 120s Read Timeout (Fixed in hover/steady-state-v2)
- HTTP read timeout killed 96% of chain evaluations under load
- Fix: `timeout=None` for reads, keep `connect=30s`
- **Watch for regression**: Any new httpx client code must NOT set read timeouts

### CancelledError Orphans (Fixed)
- `except Exception` didn't catch `BaseException` — programs persisted but IDs lost
- Fix: `persisted_id` sentinel + `except BaseException`

### NFS Filesystem Latency
- **Impact**: Test suite runs slower on NFS than local disk. `pytest -x` (stop-on-first-failure) is essential to avoid multi-minute waits.
- **Workaround**: `-x -m "not benchmark"` flags in all test runs

## Security Concerns

### API Keys in Config
- `OPENAI_API_KEY=sk-gigaevo` stored in `experiment.yaml` `custom_env` section
- **Risk**: Low (local proxy key, not a real API key)
- **Mitigation**: `.gitignore` covers `.env` files; proxy key is non-sensitive

### HTTPS Proxy Credentials
- Proxy URL with embedded credentials: `https://623:hvtiloi3Oxdr@xy.2a2i.org:4443`
- **Location**: `.claude/settings.json` (not in git), exported as env var for watchdog
- **Risk**: Moderate — if settings.json leaks, proxy credentials are exposed
- **Mitigation**: Settings file is in `.gitignore`

### exec_runner Code Execution
- Programs are Python functions executed via subprocess
- **Risk**: Arbitrary code execution (by design — it's an evolutionary algorithm)
- **Mitigation**: Stage timeouts (`stage_timeout=3000`), DAG timeouts (`dag_timeout=7200`)

## Performance Bottlenecks

### Redis Connection Pool Exhaustion
- 150 max connections, 45s pool timeout
- Under heavy concurrent DAG execution (16 parallel), pool can saturate
- **Mitigation**: Health checks every 120s, max 5 retries with 0.5s delay

### LLM Latency Dominance
- Single mutation call: ~30-120s (model-dependent)
- Generation throughput: ~0.114 mutants/min (generational) or ~1 mutant/min (steady-state)
- **Bottleneck**: LLM inference, not framework overhead

### Collector O(N^2) → O(N+KM) (Fixed)
- Population-level stats were recomputed per program in collector
- Fixed with `_ensure_population_cache()` — 29% improvement at N=5000
- **Watch**: New collector features must use the cache, not recompute

## Fragile Areas

### Treatment Verification
- Silent fallback modes can invalidate experiments: treatment intended to be applied may silently degrade to control behavior
- `treatment-verifier` agent traces code paths, but relies on code analysis not runtime checks
- **Risk**: Experiment runs to completion producing invalid data

### Prompt Co-Evolution Sync
- Prompt evolution runs must sync with chain evolution runs via Redis
- `prompt_fetcher.prompt_prefix` must match exactly
- **Risk**: Wrong prefix → chain runs silently use default prompts instead of co-evolved ones

### Hydra CWD Sensitivity
- `launch.sh` must `cd "$PROJ"` before `nohup` commands
- Hydra resolves `problem.dir` relative to CWD
- **Risk**: Launch from wrong directory → silent config resolution failures

### Adversarial Generation Sync
- Adversarial pairs can deadlock if one population gets too far ahead (>10 gen gap)
- `MainRunSyncHook` manages sync, but extended deadlocks have been observed (Pattern 8 in PATTERNS.md)
- **Risk**: Paired runs stall indefinitely

## Missing / Gaps

### No Minimum Coverage Threshold
- `fail_under: 0` in pytest-cov config
- No enforced coverage gate in CI

### Limited Type Checking
- mypy configured but `check_untyped_defs` only
- Many modules likely have untyped functions that pass CI

### No Integration Test for Full LLM Loop
- Integration tests use mock LLM/exec runners
- No test that exercises actual LLM mutation → validation → ingestion with a real model
- **Justification**: Real LLM calls are slow and non-deterministic; testing focuses on framework behavior

### Code Quality Metric
- Baseline Quality Score: 30.31 (from test quality sprint)
- Mutation testing campaign started but incomplete
