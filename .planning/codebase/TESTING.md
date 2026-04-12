# Testing

## Framework & Config
- **Framework**: pytest >= 8.0
- **Async**: pytest-asyncio >= 0.23
- **Coverage**: pytest-cov >= 5.0 (branch coverage enabled)
- **Timeout**: pytest-timeout >= 2.4 (60s per test in CI)
- **Mocking**: unittest.mock (AsyncMock, MagicMock, patch)
- **Redis mock**: fakeredis[lua] >= 2.19.0

## Test Suite Stats
- **~4800 tests** across 19 subdirectories
- **CI command**: `python -m pytest -m "not benchmark" --timeout=60 --cov=gigaevo tests/`
- **Run locally**: Always use `/run-tests` skill (never pytest directly)

## Directory Structure
```
tests/
├── conftest.py                     # Shared fixtures (NullWriter, mock stages, make_program)
├── adversarial_pipeline/           # Adversarial co-evolution tests
├── benchmarks/                     # Performance tests (@pytest.mark.benchmark)
│   └── conftest.py                 # Benchmark fixtures (archive_size, make_heavy_program)
├── concurrency/                    # Deadlock prevention tests
├── config/                         # Config helpers and resolver tests
├── dag/                            # DAG automata and edge case tests
├── database/                       # Redis storage CRUD, batch ops, state manager
├── entrypoint/                     # Entry point wiring tests
├── evolution/                      # Engine, bandit, steady-state tests
├── fakes/                          # Fake implementations for testing
├── infra/                          # Infrastructure tests
├── integration/                    # Full E2E tests (mini_run, memory evolution)
├── llm/                            # LLM wrapper tests
├── memory/                         # Memory system tests (593 tests, 26%->66% coverage)
├── problems/                       # Problem-specific tests
├── prompts/                        # Prompt template tests
├── stages/                         # Pipeline stage tests
├── test_tools/                     # Tool tests
├── trackers/                       # Metrics tracker tests
├── utils/                          # Utility tests
└── test_*.py                       # Root-level: program, metrics, stage registry
```

## Test Patterns

### Unit Tests (pytest classes)
```python
class TestProgramUUIDCoercion:
    def test_uuid_object_is_coerced_to_string(self) -> None:
        uid = uuid.uuid4()
        prog = Program(code="def f(): pass", id=uid)
        assert prog.id == str(uid)
```

### Async Tests
```python
@pytest.mark.asyncio
async def test_add_and_get(self, fakeredis_storage, make_program):
    prog = make_program()
    await fakeredis_storage.add(prog)
    fetched = await fakeredis_storage.get(prog.id)
    assert fetched.id == prog.id
```

### Integration Tests
- `tests/integration/test_mini_run.py` — full E2E with real `EvolutionEngine`
- Uses real DAG runner, real MAP-Elites, mock LLM + exec runners
- Deterministic mutation operator for reproducibility
- Completes in <5 seconds with fakeredis

### Category Organization
```python
# ===================================================================
# Category A: Basic CRUD
# ===================================================================
class TestBasicCRUD:
    async def test_add_and_get(self, fakeredis_storage, make_program): ...

# ===================================================================
# Category B: Batch Operations
# ===================================================================
class TestBatchOperations:
    async def test_mget_returns_all(self, fakeredis_storage, make_program): ...
```

## Fixtures

### Factory Fixtures
```python
@pytest.fixture
def make_program():
    def _make(code="def solve(): return 42", ...) -> Program:
        p = Program(code=code, state=state, atomic_counter=999_999_999)
        if metrics: p.add_metrics(metrics)
        return p
    return _make
```

### Redis Fixtures
```python
@pytest.fixture
async def fakeredis_storage():
    server = fakeredis.FakeServer()
    storage = RedisProgramStorage(config)
    storage._conn._redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    yield storage
    await storage.close()
```

### Autouse Cleanup
```python
@pytest.fixture(autouse=True)
async def _clear_exec_runner_pool():
    default_exec_runner_pool.cache_clear()
    yield
    await pool.shutdown()
```

### Mock Stages (in conftest.py)
- `FastStage`, `ChainedStage`, `FailingStage`, `SlowStage`, `TimeoutStage`
- `OptionalInputStage`, `VoidStage`, `SideEffectStage`
- All inherit from `Stage` with proper `InputsModel`/`OutputModel`

## Coverage
- **Source**: `gigaevo/` directory only
- **Branch coverage**: Enabled
- **Exclude patterns**: `pragma: no cover`, `if TYPE_CHECKING:`, `raise NotImplementedError`, `@abstractmethod`
- **Reports**: term-missing, XML (coverage.xml), HTML (htmlcov/)
- **Fail under**: 0 (no minimum threshold enforced)

## CI/CD
- **Workflow**: `.github/workflows/build.yml`
- **Lint job**: `ruff check . && ruff format --check .`
- **Test job**: pytest with coverage on Python 3.12, Ubuntu latest
- **Markers**: `@pytest.mark.benchmark` (excluded from CI), `@pytest.mark.asyncio`
- **Coverage artifact**: `coverage.xml` uploaded
