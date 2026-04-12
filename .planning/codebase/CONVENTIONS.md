# Code Conventions

## Code Style & Formatting
- **Formatter**: Ruff (replaces Black, isort, flake8)
- **Line length**: 88 characters
- **Target**: Python 3.12+
- **Rules**: E, F, I (imports), UP (pyupgrade)
- **Ignore**: E501 (line-too-long handled by formatter)
- **Special**: `__init__.py` allows unused imports (F401)

## Import Organization
```python
from __future__ import annotations    # Always first

import asyncio                        # stdlib
from pathlib import Path

from loguru import logger             # third-party
from pydantic import BaseModel, Field
import redis

from gigaevo.evolution.engine.core import EvolutionEngine  # internal
from gigaevo.programs.program import Program
```

- `from __future__ import annotations` at top of every file
- Stdlib, then third-party, then internal (enforced by ruff isort)
- `TYPE_CHECKING` blocks for circular import avoidance

## Type Annotations
- **Pydantic v2** for all data models (`BaseModel` + `Field`)
- **Type hints on all parameters and returns** (enforced in CI)
- **Union syntax**: Both `X | Y` (preferred) and `Optional[X]` used
- **Generic types**: `list[str]`, `dict[str, float]`, `Mapping[str, Any]`
- **Literal types**: `Literal["linear"]` for enum-like values
- **Field validation**: `@field_validator`, `@model_validator` decorators
- **ConfigDict**: `model_config = ConfigDict(extra="forbid")` on all data models

## Naming
| Entity | Style | Example |
|--------|-------|---------|
| Classes | PascalCase | `EvolutionEngine`, `ProgramStageResult` |
| Abstract bases | ABC suffix or inherit ABC | `BinningStrategy(BaseModel, abc.ABC)` |
| Strategy classes | `<Name>Strategy` / `<Name>Island` | `MapElitesMultiIsland` |
| Acceptor classes | `<Name>Acceptor` | `StateAcceptor`, `CompositeAcceptor` |
| Functions/methods | snake_case | `make_program`, `from_dict` |
| Async methods | No prefix | `async def step(self)` |
| Private | Leading underscore | `_helper_function`, `self._node_started` |
| Factory methods | `make_<type>` or `from_<source>` | `make_program()`, `from_mutation_spec()` |
| Constants | UPPER_SNAKE_CASE | `MUTATION_CONTEXT_METADATA_KEY` |

## Error Handling
- **Custom exception hierarchy** in `gigaevo/exceptions.py`:
  - Base: `GigaEvoError`
  - Categories: `ValidationError`, `StorageError`, `ProgramError`, `EvolutionError`, `SecurityError`, `LLMError`, `MemoryError`
  - Specific: `ProgramExecutionError`, `ProgramTimeoutError`, `StageExecutionError`

- **Pattern**: Catch specific exceptions, log with context:
```python
except Exception as exc:
    logger.warning(
        "[MigrationBus] Import failed for migrant {}: {}",
        program.short_id,
        exc,
    )
```

## Logging
- **Framework**: `loguru` (not stdlib logging)
- **Import**: `from loguru import logger`
- **Format**: Lazy formatting with `{}` placeholders (not f-strings):
  ```python
  logger.info("Processed {} programs in {:.1f}s", count, elapsed)
  ```
- **Contextual prefixes**: `[ComponentName]` in messages
- **Setup**: `gigaevo/utils/logger_setup.py` (colored console + file rotation)

## Async Patterns
- Heavy `async/await` throughout evolution engines, storage, DAG runners
- `asyncio.Semaphore` for backpressure (steady-state engine)
- `async with` for resource management
- `asyncio.gather` for concurrent stage execution in DAG runner

## Common Patterns

### Strategy Pattern
Abstract base classes with `ABC` + `@abstractmethod`, multiple concrete implementations.

### Acceptor/Composite
`CompositeAcceptor` chains multiple `Acceptor` instances for program filtering.

### Factory/Builder
Static methods: `from_dict()`, `from_mutation_spec()`, `create_child()`.

### Hydra Config Instantiation
```yaml
_target_: gigaevo.database.redis_program_storage.RedisProgramStorage
config:
  _target_: gigaevo.database.redis_program_storage.RedisProgramStorageConfig
```
