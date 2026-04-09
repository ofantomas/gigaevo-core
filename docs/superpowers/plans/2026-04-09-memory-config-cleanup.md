# Memory Config Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove dead helper functions from `runtime_config.py`, refactor `config.py` to use OmegaConf structured schemas (matching the pattern established in `write_pipeline_config.py`), and simplify `memory_read_example.py`.

**Architecture:** `gigaevo/memory/config.py` is the last file that still uses the old `load_settings` + `deep_get` + `to_str` helpers from `runtime_config.py`. After migrating it to OmegaConf structured schemas (same as `write_pipeline_config.py`), the helpers become dead code and can be deleted along with their tests. The `memory_read_example.py` example also uses the old pattern and will be rewritten to use `load_config()`.

**Tech Stack:** Python 3.11+, OmegaConf 2.3+, Pydantic v2, pytest, ruff

---

## File Map

| File | Change |
|---|---|
| `gigaevo/memory/config.py` | Rewrite: OmegaConf schemas, remove `try/except ImportError` |
| `gigaevo/memory/runtime_config.py` | Strip dead code: remove `to_bool`, `to_int`, `to_str`, `to_list`, `deep_get`, `load_settings` |
| `gigaevo/memory/examples/memory_read_example.py` | Rewrite: use `load_config()` from `write_pipeline_config.py` |
| `tests/memory/test_runtime_config.py` | Delete test classes for removed functions |

---

## Context

The previous session refactored `write_pipeline_config.py` to use OmegaConf structured schemas (commit `cd77282f`). The pattern is: define `@dataclass` section schemas, call `_merge_section(file_cfg, "key", SchemaClass)` to load+coerce YAML, expose a `PipelineConfig` dataclass from `load_config()`.

`gigaevo/memory/config.py` was NOT yet migrated. It still uses:
```python
try:
    from .runtime_config import deep_get, load_settings, to_str
except ImportError:  # script-style fallback
    from runtime_config import deep_get, load_settings, to_str

_SETTINGS = load_settings()  # side effect at import time

OPENROUTER_MODEL_NAME = os.getenv("OPENROUTER_MODEL_NAME", to_str(...))
AMEM_EMBEDDING_MODEL_NAME = to_str(deep_get(_SETTINGS, "models.amem_embedding_model_name"), default="all-MiniLM-L6-v2")
```

After this plan, `runtime_config.py` contains only:
- `resolve_settings_path()`  — used by `write_pipeline_config.py` and `config.py`
- `resolve_local_path()`     — used by `write_pipeline_config.py`

---

## Task 1: Refactor `gigaevo/memory/config.py` to OmegaConf

**Files:**
- Modify: `gigaevo/memory/config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/memory/test_config_load.py
"""Tests for gigaevo.memory.config module-level constants."""

from __future__ import annotations

import importlib
import sys

import pytest


def _reload_config(monkeypatch, extra_env: dict | None = None):
    """Reload config module with clean env."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL_NAME", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("BASE_URL", raising=False)
    for k, v in (extra_env or {}).items():
        monkeypatch.setenv(k, v)
    if "gigaevo.memory.config" in sys.modules:
        del sys.modules["gigaevo.memory.config"]
    return importlib.import_module("gigaevo.memory.config")


class TestConfigConstants:
    def test_string_constants_are_strings(self, monkeypatch):
        cfg = _reload_config(monkeypatch)
        assert isinstance(cfg.OPENROUTER_MODEL_NAME, str)
        assert isinstance(cfg.AMEM_EMBEDDING_MODEL_NAME, str)
        assert isinstance(cfg.GAM_DENSE_RETRIEVER_MODEL_NAME, str)

    def test_openai_api_key_none_when_not_set(self, monkeypatch):
        cfg = _reload_config(monkeypatch)
        assert cfg.OPENAI_API_KEY is None

    def test_openai_api_key_from_env(self, monkeypatch):
        cfg = _reload_config(monkeypatch, {"OPENAI_API_KEY": "sk-test"})
        assert cfg.OPENAI_API_KEY == "sk-test"

    def test_openai_api_key_from_openrouter_env_fallback(self, monkeypatch):
        cfg = _reload_config(monkeypatch, {"OPENROUTER_API_KEY": "sk-or-test"})
        assert cfg.OPENAI_API_KEY == "sk-or-test"

    def test_openrouter_reasoning_is_dict(self, monkeypatch):
        cfg = _reload_config(monkeypatch)
        assert isinstance(cfg.OPENROUTER_REASONING, dict)

    def test_amem_embedding_model_name_has_default(self, monkeypatch):
        cfg = _reload_config(monkeypatch)
        assert cfg.AMEM_EMBEDDING_MODEL_NAME  # non-empty string

    def test_no_load_settings_imported(self):
        """config.py must NOT import from runtime_config except resolve_settings_path."""
        import ast
        import pathlib
        src = pathlib.Path("gigaevo/memory/config.py").read_text()
        tree = ast.parse(src)
        forbidden = {"deep_get", "load_settings", "to_str", "to_bool", "to_int", "to_list"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and "runtime_config" in node.module:
                names = {alias.name for alias in node.names}
                assert not names & forbidden, f"Forbidden import: {names & forbidden}"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
$GIGAEVO_PYTHON -m pytest tests/memory/test_config_load.py -x -q --tb=short 2>&1 | tail -20
```
Expected: FAIL (some tests fail because `config.py` still uses old imports)

- [ ] **Step 3: Rewrite `gigaevo/memory/config.py`**

Replace the entire file with:

```python
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from omegaconf import OmegaConf

from gigaevo.memory.runtime_config import resolve_settings_path

# Load repo-root .env. override=False: .env sets defaults, not overrides.
load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env", override=False)


@dataclass
class _HuggingFaceSchema:
    etag_timeout: str = "60"
    download_timeout: str = "300"


@dataclass
class _ModelsSchema:
    openrouter_model_name: str = "openai/gpt-4.1-mini"
    amem_embedding_model_name: str = "all-MiniLM-L6-v2"
    gam_dense_retriever_model_name: str = "BAAI/bge-m3"
    openai_base_url: str = ""
    llm_base_url: str = ""


def _normalize_env(value: str | None) -> str | None:
    """Strip quotes and whitespace; return None for blank values."""
    if not value:
        return None
    stripped = value.strip().strip('"').strip("'")
    return stripped or None


def _merge_section(cfg: Any, dotted_key: str, schema_cls: type) -> dict[str, Any]:
    raw = OmegaConf.select(cfg, dotted_key) or {}
    merged = OmegaConf.merge(OmegaConf.structured(schema_cls), raw)
    return OmegaConf.to_container(merged, resolve=True)  # type: ignore[return-value]


def _configure_huggingface_env(hf: dict[str, Any]) -> None:
    if not os.getenv("HF_HUB_ETAG_TIMEOUT"):
        os.environ["HF_HUB_ETAG_TIMEOUT"] = str(hf["etag_timeout"])
    if not os.getenv("HF_HUB_DOWNLOAD_TIMEOUT"):
        os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = str(hf["download_timeout"])


def _load() -> tuple[dict[str, Any], dict[str, Any]]:
    cfg = OmegaConf.load(resolve_settings_path())
    hf = _merge_section(cfg, "downloads.huggingface", _HuggingFaceSchema)
    _configure_huggingface_env(hf)
    models: dict[str, Any] = _merge_section(cfg, "models", _ModelsSchema)
    reasoning_raw = OmegaConf.select(cfg, "reasoning")
    reasoning: dict[str, Any] = (
        OmegaConf.to_container(reasoning_raw, resolve=True)  # type: ignore[assignment]
        if reasoning_raw is not None
        else {}
    )
    return models, reasoning if isinstance(reasoning, dict) else {}


_models, _reasoning = _load()

OPENAI_API_KEY = _normalize_env(
    os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY")
)
OPENROUTER_API_KEY = _normalize_env(
    os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
)
OPENROUTER_MODEL_NAME: str = (
    os.getenv("OPENROUTER_MODEL_NAME") or str(_models["openrouter_model_name"])
)
LLM_BASE_URL = _normalize_env(
    os.getenv("OPENAI_BASE_URL")
    or os.getenv("LLM_BASE_URL")
    or os.getenv("BASE_URL")
    or str(_models["openai_base_url"] or "")
    or str(_models["llm_base_url"] or "")
)
OPENROUTER_REASONING: dict[str, object] = _reasoning
AMEM_EMBEDDING_MODEL_NAME: str = str(_models["amem_embedding_model_name"])
GAM_DENSE_RETRIEVER_MODEL_NAME: str = str(_models["gam_dense_retriever_model_name"])
```

- [ ] **Step 4: Run lint**

```bash
ruff check gigaevo/memory/config.py && ruff format gigaevo/memory/config.py
```
Expected: no errors

- [ ] **Step 5: Run tests**

```bash
$GIGAEVO_PYTHON -m pytest tests/memory/test_config_load.py -x -q --tb=short 2>&1 | tail -20
```
Expected: all PASS

- [ ] **Step 6: Run broader memory tests to check nothing broke**

```bash
$GIGAEVO_PYTHON -m pytest tests/memory/ -x -m "not benchmark" --tb=short -q -p no:warnings 2>&1 | tail -15
```
Expected: no new failures

- [ ] **Step 7: Commit**

```bash
rtk git add gigaevo/memory/config.py tests/memory/test_config_load.py
rtk git commit -m "refactor(memory): migrate config.py to OmegaConf, remove legacy deep_get/load_settings"
```

---

## Task 2: Strip dead helpers from `runtime_config.py`

**Files:**
- Modify: `gigaevo/memory/runtime_config.py`
- Modify: `tests/memory/test_runtime_config.py`

After Task 1, `load_settings`, `deep_get`, `to_str`, `to_bool`, `to_int`, `to_list` are no longer called by any production code. Their only remaining callers are tests and the `examples/memory_read_example.py` script (handled in Task 3).

- [ ] **Step 1: Write a sentinel test verifying the helpers are gone**

Add to `tests/memory/test_runtime_config.py`, at the top of the file after imports:

```python
def test_dead_helpers_removed():
    """Ensure deprecated helpers are no longer exported from runtime_config."""
    import gigaevo.memory.runtime_config as rc
    for dead in ("to_bool", "to_int", "to_str", "to_list", "deep_get", "load_settings"):
        assert not hasattr(rc, dead), f"{dead!r} should have been deleted"
```

- [ ] **Step 2: Verify test fails**

```bash
$GIGAEVO_PYTHON -m pytest tests/memory/test_runtime_config.py::test_dead_helpers_removed -x -q --tb=short 2>&1 | tail -10
```
Expected: FAIL — `to_bool` still present

- [ ] **Step 3: Replace `gigaevo/memory/runtime_config.py` with stripped version**

Replace the entire file content with:

```python
"""Runtime config path helpers for the memory module.

Provides only path resolution utilities.  All type-coercion helpers
(``to_bool``, ``to_int``, ``to_str``, ``to_list``, ``deep_get``,
``load_settings``) were removed; config loading uses OmegaConf directly.
"""

from __future__ import annotations

import os
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent


def resolve_settings_path(settings_path: str | Path | None = None) -> Path:
    """Return the settings YAML path.

    Priority: explicit argument → EVO_MEMORY_CONFIG_PATH env var →
    EVO_MEMORY_SETTINGS_PATH env var → default memory_backend.yaml.
    """
    if settings_path is not None:
        return Path(settings_path)
    env_primary = os.getenv("EVO_MEMORY_CONFIG_PATH")
    if env_primary:
        return Path(env_primary)
    env_fallback = os.getenv("EVO_MEMORY_SETTINGS_PATH")
    if env_fallback:
        return Path(env_fallback)
    return _THIS_DIR.parents[2] / "config" / "memory_backend.yaml"


def resolve_local_path(
    base: Path,
    raw: str | None,
    default_relative: str,
) -> Path:
    """Resolve *raw* relative to *base*.

    If *raw* is empty or None, returns ``base / default_relative``.
    Absolute paths are returned as-is.
    """
    if not raw:
        return base / default_relative
    p = Path(raw)
    if p.is_absolute():
        return p
    return base / p
```

- [ ] **Step 4: Remove dead test classes from `tests/memory/test_runtime_config.py`**

Delete the following test classes entirely (they test functions that no longer exist):
- `TestDeepGet`
- `TestToBool`
- `TestToInt`
- `TestToList`
- `TestToStr`
- `TestLoadSettings`

And remove the corresponding import names (`deep_get`, `load_settings`, `to_bool`, `to_int`, `to_list`, `to_str`) from the `from gigaevo.memory.runtime_config import (...)` block at the top.

The file should become:

```python
"""Tests for gigaevo.memory.runtime_config path-resolution utilities."""

from pathlib import Path

import pytest

from gigaevo.memory.runtime_config import (
    resolve_local_path,
    resolve_settings_path,
)


def test_dead_helpers_removed():
    """Ensure deprecated helpers are no longer exported from runtime_config."""
    import gigaevo.memory.runtime_config as rc
    for dead in ("to_bool", "to_int", "to_str", "to_list", "deep_get", "load_settings"):
        assert not hasattr(rc, dead), f"{dead!r} should have been deleted"


# ===========================================================================
# resolve_settings_path
# ===========================================================================


class TestResolveSettingsPath:
    def test_explicit_path(self):
        p = resolve_settings_path("/some/path.yaml")
        assert p == Path("/some/path.yaml")

    def test_env_var_override(self, monkeypatch):
        monkeypatch.setenv("EVO_MEMORY_CONFIG_PATH", "/from/env.yaml")
        p = resolve_settings_path()
        assert p == Path("/from/env.yaml")

    def test_fallback_env_var(self, monkeypatch):
        monkeypatch.delenv("EVO_MEMORY_CONFIG_PATH", raising=False)
        monkeypatch.setenv("EVO_MEMORY_SETTINGS_PATH", "/fallback.yaml")
        p = resolve_settings_path()
        assert p == Path("/fallback.yaml")


# ===========================================================================
# resolve_local_path
# ===========================================================================


class TestResolveLocalPath:
    def test_absolute_path_returned(self):
        p = resolve_local_path(Path("/base"), "/abs/path", "default")
        assert p == Path("/abs/path")

    def test_relative_resolved_against_base(self):
        p = resolve_local_path(Path("/base"), "rel/path", "default")
        assert p == Path("/base/rel/path")

    def test_none_uses_default(self):
        p = resolve_local_path(Path("/base"), None, "default/dir")
        assert p == Path("/base/default/dir")

    def test_empty_string_uses_default(self):
        p = resolve_local_path(Path("/base"), "", "default/dir")
        assert p == Path("/base/default/dir")
```

- [ ] **Step 5: Run lint**

```bash
ruff check gigaevo/memory/runtime_config.py tests/memory/test_runtime_config.py
ruff format gigaevo/memory/runtime_config.py tests/memory/test_runtime_config.py
```

- [ ] **Step 6: Run tests**

```bash
$GIGAEVO_PYTHON -m pytest tests/memory/test_runtime_config.py tests/memory/test_config_load.py -x -q --tb=short 2>&1 | tail -15
```
Expected: all PASS

- [ ] **Step 7: Run broader memory suite**

```bash
$GIGAEVO_PYTHON -m pytest tests/memory/ -x -m "not benchmark" --tb=short -q -p no:warnings 2>&1 | tail -15
```
Expected: no new failures

- [ ] **Step 8: Commit**

```bash
rtk git add gigaevo/memory/runtime_config.py tests/memory/test_runtime_config.py
rtk git commit -m "refactor(memory): strip dead helpers from runtime_config (to_bool, deep_get etc.)"
```

---

## Task 3: Simplify `memory_read_example.py`

**Files:**
- Modify: `gigaevo/memory/examples/memory_read_example.py`

The example script still uses the old `try/except ImportError` pattern with 8 dead helper imports. Replace with `load_config()`.

- [ ] **Step 1: Verify lint failure on the example (it will fail once runtime_config helpers are gone)**

```bash
$GIGAEVO_PYTHON -c "import gigaevo.memory.examples.memory_read_example" 2>&1 | head -5
```
Expected: ImportError or AttributeError — functions no longer exist

- [ ] **Step 2: Replace `gigaevo/memory/examples/memory_read_example.py`**

Replace the entire file with:

```python
"""Example: search the memory backend using the same query format as MemorySelectorAgent.

Run with:
    PYTHONPATH=. $GIGAEVO_PYTHON gigaevo/memory/examples/memory_read_example.py
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

from gigaevo.memory.shared_memory.memory import AmemGamMemory
from gigaevo.memory.shared_memory.memory_config import ApiConfig, GamConfig, MemoryConfig
from gigaevo.memory.write_pipeline_config import load_config

load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env", override=True)

_cfg = load_config()

MEMORY_DIR = _cfg.memory_dir
MEMORY_API_URL = str(_cfg.memory_api_url)
NAMESPACE = _cfg.namespace
USE_API = _cfg.use_api
CHANNEL = _cfg.channel
ENABLE_BM25 = _cfg.enable_bm25
ALLOWED_GAM_TOOLS = list(_cfg.allowed_gam_tools)
GAM_PIPELINE_MODE = _cfg.gam_pipeline_mode or "default"
GAM_TOP_K_BY_TOOL = dict(_cfg.gam_top_k_by_tool)


def _build_memory_selector_style_request() -> str:
    """Example request payload aligned with gigaevo/prompts/memory_selector/user.txt."""
    return """MUTATION INPUTS

TASK DESCRIPTION:
Place 11 distinct points inside a unit-area equilateral triangle to maximize the minimum triangle area (Heilbronn 11-point target >= 0.0365).

AVAILABLE METRICS:
- fitness: min_triangle_area (higher is better)
- valid_points_rate
- boundary_violation_count
- near_collinearity_count

MUTATION MODE:
guided_innovation

PARENTS (same parent code + mutation context given to mutation agent):
=== Parent 1 ===
```python
def entrypoint():
    # baseline: optimize with smooth min objective
    ...
```
Parent context:
- Last fitness: 0.0349
- Weakness: frequent near-collinear triplets
- Prior change: switched to L-BFGS-B with moderate smoothing

=== Parent 2 ===
```python
def entrypoint():
    # baseline variant: basin hopping + SLSQP constraints
    ...
```
Parent context:
- Last fitness: 0.0352
- Weakness: unstable local convergence at final stage
- Prior change: higher exploration noise

"""


def main() -> None:
    api_config = (
        ApiConfig(
            base_url=MEMORY_API_URL or "http://localhost:8000",
            namespace=NAMESPACE or "default",
            channel=CHANNEL or "latest",
        )
        if USE_API
        else None
    )
    mem_config = MemoryConfig(
        checkpoint_path=MEMORY_DIR,
        api=api_config,
        gam=GamConfig(
            enable_bm25=ENABLE_BM25,
            allowed_tools=ALLOWED_GAM_TOOLS or [],
            top_k_by_tool=GAM_TOP_K_BY_TOOL or {},
            pipeline_mode=GAM_PIPELINE_MODE,
        ),
    )
    memory = AmemGamMemory(config=mem_config)

    print("\n==============================")
    print("API Memory Demo: Search")
    print("==============================\n")
    print(f"Config file: {_cfg.settings_path}")
    print(f"Using API: {USE_API}")

    query = _build_memory_selector_style_request()

    print(">>> MEMORY SELECTOR STYLE INPUT:\n")
    print(query)
    print()
    try:
        result = memory.search(query)
    except RuntimeError as exc:
        print(f"Search failed: {exc}")
        return
    print("Result:\n")
    print(result)
    print("\nDone.\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run lint**

```bash
ruff check gigaevo/memory/examples/memory_read_example.py && ruff format gigaevo/memory/examples/memory_read_example.py
```

- [ ] **Step 4: Verify example imports cleanly**

```bash
$GIGAEVO_PYTHON -c "import gigaevo.memory.examples.memory_read_example; print('OK')" 2>&1
```
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
rtk git add gigaevo/memory/examples/memory_read_example.py
rtk git commit -m "refactor(memory): simplify memory_read_example.py to use load_config()"
```

---

## Task 4: Final verification

**Files:** none changed

- [ ] **Step 1: Run full memory test suite + integration**

```bash
$GIGAEVO_PYTHON -m pytest tests/memory/ tests/integration/ -x -m "not benchmark" --tb=short -q -p no:warnings 2>&1 | tee /tmp/pytest_results.txt; echo "EXIT:$?"
grep -E "passed|failed|error" /tmp/pytest_results.txt | tail -3
```
Expected: all pass, EXIT:0

- [ ] **Step 2: Run lint on all changed files**

```bash
ruff check gigaevo/memory/config.py gigaevo/memory/runtime_config.py gigaevo/memory/examples/memory_read_example.py tests/memory/test_runtime_config.py tests/memory/test_config_load.py
```
Expected: no errors

- [ ] **Step 3: Verify no remaining imports of dead helpers**

```bash
grep -rn "from gigaevo.memory.runtime_config import" gigaevo/ tests/ | grep -v "resolve_local_path\|resolve_settings_path" | grep -v "test_runtime_config"
```
Expected: no output (only `resolve_*` functions remain in use)
