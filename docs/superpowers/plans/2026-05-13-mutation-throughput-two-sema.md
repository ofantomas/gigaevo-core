# Mutation-Throughput Two-Semaphore Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decouple LLM/refresh concurrency from produced-but-not-ingested mutant buffer by replacing the single `_in_flight_sema` with two semaphores (`_producer_sema`, `_buffer_sema`), both sized to the existing `max_in_flight` knob.

**Architecture:** Producer task acquires `_producer_sema` for the full refresh+LLM call; once the LLM result is persisted, it acquires `_buffer_sema` and atomically transfers it (with the parent-refresh ticket) into `_in_flight` under `_in_flight_lock`; the ingestor releases `_buffer_sema` on DONE/DISCARDED. `_producer_sema` is always released in the producer task's `finally` (no transfer). Single config field (`max_in_flight`) sizes both pools; steady-state pipeline depth ~2N mutants.

**Tech Stack:** Python 3.11, asyncio, pytest-asyncio, pydantic v2. Touches only `gigaevo/evolution/engine/{config,steady_state,dispatcher,mutant_task,ingestor}.py` and tests under `tests/evolution/` + `tests/integration/`.

**Spec:** [`docs/superpowers/specs/2026-05-13-mutation-throughput-two-sema-design.md`](../specs/2026-05-13-mutation-throughput-two-sema-design.md)

**Branch:** `refactor/steady-state-true-jit-refresh` (PR #227)

**Testing:** **Always invoke `/run-tests <paths>`** — never bare `pytest tests/` (hangs). Lint with `ruff check . && ruff format --check .` (use `/home/jovyan/.mlspace/envs/evo/bin/ruff`). Python interpreter: `/home/jovyan/.mlspace/envs/evo/bin/python3`.

**Commits:** Use `rtk git`, not bare `git`. Co-author trailer: `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `gigaevo/evolution/engine/config.py` | `EngineConfig.max_in_flight` field + docstring | Rewrite docstring only |
| `gigaevo/evolution/engine/steady_state.py` | Engine init builds semaphores; `_final_ingestion_sweep` releases slots | Replace `_in_flight_sema` with `_producer_sema` + `_buffer_sema` |
| `gigaevo/evolution/engine/dispatcher.py` | Long-lived loop: acquire slot → spawn mutant task | Acquire `_producer_sema` instead of `_in_flight_sema`, mirror its release on early-stop |
| `gigaevo/evolution/engine/mutant_task.py` | Per-mutant producer; refresh → LLM → register | Add `_buffer_sema.acquire()` after LLM, `_producer_sema.release()` in `finally` (always), buffer release only when held-not-transferred |
| `gigaevo/evolution/engine/ingestor.py` | Long-lived loop: poll DONE → release slot | Release `_buffer_sema` (not `_in_flight_sema`); saturation check unchanged (uses `len(_in_flight)`) |
| `tests/evolution/test_dispatcher_producer_sema.py` | NEW | Dispatcher acquires `_producer_sema`; early-stop releases it |
| `tests/evolution/test_mutant_task_two_sema.py` | NEW | All exit paths of `run_one_mutant` — slot/buffer/ticket accounting |
| `tests/evolution/test_ingestor_releases_buffer.py` | NEW | DONE/DISCARDED release `_buffer_sema` |
| `tests/evolution/test_engine_no_slot_leak.py` | NEW | Load + cancel-chaos invariant: both semas at full count after shutdown |
| `tests/evolution/test_engine_jit_dag_refill.py` | NEW | Behavioral property: free DAG slot is refilled within one event-loop tick |
| `tests/evolution/test_engine_ghost_persist.py` | EXISTING | Migrate references from `_in_flight_sema` → `_producer_sema`/`_buffer_sema` in `_FakeEngine` |
| `tests/integration/test_two_sema_end_to_end.py` | NEW | Real Redis (DB 15), N=3, 30 mutants, pipeline drains cleanly |

**Naming convention (locked):** `_producer_sema`, `_buffer_sema`, with leading underscore matching `_in_flight`, `_in_flight_lock`. Use these exact names in every task below.

**Local variable convention in `run_one_mutant`:** `slot_transferred` (kept from current code), `buffer_held` (new). The producer-sema slot has no transfer semantics — there is no `producer_held` flag because the producer-sema is always acquired by the dispatcher (caller) and is always released in `finally`.

---

## Task 1: Config docstring rewrite

**Files:**
- Modify: `gigaevo/evolution/engine/config.py:30-40`
- Test: `tests/evolution/test_config_max_in_flight_doc.py` (NEW)

- [ ] **Step 1: Read the field today**

Run: `sed -n '30,40p' gigaevo/evolution/engine/config.py`

Expected output (verify before editing):

```python
    max_in_flight: int = Field(
        default=5,
        gt=0,
        description=(
            "Max mutant programs in the pipeline (produced but not yet "
            "ingested/discarded). The dispatcher blocks on a semaphore of this "
            "size; the ingestor releases slots as programs reach DONE/DISCARDED. "
            "~4 concurrent per GPU server is the sweet spot (measured on "
            "Qwen3-235B). Default 5 is tuned for 3-4 servers with 4 runs."
        ),
    )
```

- [ ] **Step 2: Write the failing test**

Create `tests/evolution/test_config_max_in_flight_doc.py`:

```python
"""Doc-string guard: max_in_flight must describe the two-pool semantics.

Operators read this description via Hydra --help and the generated YAML;
the previous single-pool wording is misleading after the two-sema redesign.
"""

from __future__ import annotations

from gigaevo.evolution.engine.config import EngineConfig


def test_max_in_flight_description_mentions_two_pools() -> None:
    field = EngineConfig.model_fields["max_in_flight"]
    desc = field.description or ""
    # Must call out BOTH pools so operators know depth is ~2N, not N.
    assert "producer" in desc.lower()
    assert "buffer" in desc.lower()
    assert "2" in desc or "two" in desc.lower()
```

- [ ] **Step 3: Run the test — verify it fails**

Run: `/run-tests tests/evolution/test_config_max_in_flight_doc.py`

Expected: 1 failed (current docstring contains neither "producer" nor "buffer").

- [ ] **Step 4: Rewrite the docstring**

Edit `gigaevo/evolution/engine/config.py` to replace the `description=...` block (lines 33-39) with:

```python
        description=(
            "Backpressure cap. Sizes BOTH the producer pool (concurrent "
            "LLM/refresh tasks; ``_producer_sema``) AND the buffer of "
            "produced-but-not-yet-ingested mutants (``_buffer_sema``). "
            "Steady-state pipeline depth is therefore ~2 × max_in_flight: "
            "~N producers alive (mix of LLM-running and holding ready "
            "result) plus ~N buffered (DAG queue + running + waiting "
            "ingest). The dispatcher acquires producer_sema and the "
            "ingestor releases buffer_sema as programs reach "
            "DONE/DISCARDED. ~4 concurrent producers per GPU server is "
            "the sweet spot (measured on Qwen3-235B). Default 5 is tuned "
            "for 3-4 servers with 4 runs."
        ),
```

- [ ] **Step 5: Re-run the test — verify it passes**

Run: `/run-tests tests/evolution/test_config_max_in_flight_doc.py`

Expected: 1 passed.

- [ ] **Step 6: Lint**

Run: `/home/jovyan/.mlspace/envs/evo/bin/ruff check gigaevo/evolution/engine/config.py tests/evolution/test_config_max_in_flight_doc.py && /home/jovyan/.mlspace/envs/evo/bin/ruff format gigaevo/evolution/engine/config.py tests/evolution/test_config_max_in_flight_doc.py`

Expected: `All checks passed!` and `1 file already formatted` (or `2 files reformatted` with no diff that matters).

- [ ] **Step 7: Commit**

```bash
rtk git add gigaevo/evolution/engine/config.py tests/evolution/test_config_max_in_flight_doc.py
rtk git commit -m "$(cat <<'EOF'
refactor(engine): rewrite max_in_flight docstring for two-sema semantics

Field name unchanged; semantics now apply symmetrically to producer
and buffer pools. Steady-state pipeline depth ~2N.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Add `_producer_sema` and `_buffer_sema` to engine init

**Files:**
- Modify: `gigaevo/evolution/engine/steady_state.py:30-56` (init), `:147-260` (sweep)
- Test: `tests/evolution/test_steady_state_init_sema_pair.py` (NEW)

- [ ] **Step 1: Write the failing test**

Create `tests/evolution/test_steady_state_init_sema_pair.py`:

```python
"""SteadyStateEvolutionEngine.__init__ must allocate both semaphores."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from gigaevo.evolution.engine.config import SteadyStateEngineConfig
from gigaevo.evolution.engine.steady_state import SteadyStateEvolutionEngine


def _make_engine(max_in_flight: int = 7) -> SteadyStateEvolutionEngine:
    cfg = SteadyStateEngineConfig(max_in_flight=max_in_flight)
    return SteadyStateEvolutionEngine(
        config=cfg,
        storage=AsyncMock(),
        strategy=AsyncMock(),
        mutation_operator=AsyncMock(),
        state=MagicMock(),
    )


@pytest.mark.asyncio
async def test_engine_init_creates_both_semaphores() -> None:
    engine = _make_engine(max_in_flight=7)
    assert isinstance(engine._producer_sema, asyncio.Semaphore)
    assert isinstance(engine._buffer_sema, asyncio.Semaphore)
    # Both sized symmetrically to the single knob.
    assert engine._producer_sema._value == 7
    assert engine._buffer_sema._value == 7
    # Legacy attribute gone — anything still reaching for it must crash.
    assert not hasattr(engine, "_in_flight_sema")
```

- [ ] **Step 2: Run the test — verify it fails**

Run: `/run-tests tests/evolution/test_steady_state_init_sema_pair.py`

Expected: 1 failed (either `_producer_sema` not present, or `_in_flight_sema` still attached).

- [ ] **Step 3: Edit `steady_state.py` `__init__`**

Replace the line at `gigaevo/evolution/engine/steady_state.py:49`:

```python
        self._in_flight_sema = asyncio.Semaphore(self._ss_config.max_in_flight)
```

with:

```python
        # Two-sema model: producer pool caps concurrent (refresh + LLM); buffer
        # pool caps produced-but-not-yet-ingested mutants. Both sized from the
        # single ``max_in_flight`` knob; steady-state pipeline depth ~2 × N.
        # See docs/superpowers/specs/2026-05-13-mutation-throughput-two-sema-design.md.
        self._producer_sema = asyncio.Semaphore(self._ss_config.max_in_flight)
        self._buffer_sema = asyncio.Semaphore(self._ss_config.max_in_flight)
```

- [ ] **Step 4: Update startup log line**

In `gigaevo/evolution/engine/steady_state.py` `run()` (around line 58-62), replace:

```python
        logger.info(
            "[SteadyState] Start | max_in_flight={} stopper={}",
            self._ss_config.max_in_flight,
            type(self._ss_config.stopper).__name__,
        )
```

with:

```python
        logger.info(
            "[SteadyState] Start | producer_sema={} buffer_sema={} "
            "(max_in_flight={}) stopper={}",
            self._ss_config.max_in_flight,
            self._ss_config.max_in_flight,
            self._ss_config.max_in_flight,
            type(self._ss_config.stopper).__name__,
        )
```

- [ ] **Step 5: Update the sweep doc-comment to reference `buffer_sema`**

In `gigaevo/evolution/engine/steady_state.py` `_final_ingestion_sweep`, update the docstring's first paragraph (lines 149-158) so:

```python
        """Drain DONE/DISCARDED out of ``_in_flight`` after the loops exit.

        Releases ``_buffer_sema`` slots that a mutant cancelled between
        ``_in_flight.add`` and the slot release would otherwise leak —
        ``mutant_task``'s ``finally`` guards ``slot_transferred=True`` and
        refuses to release, expecting the ingestor to. On normal completion
        the DAG may still be flipping QUEUED→RUNNING→DONE for the last few
        in-flight mutants, so we sleep between empty passes instead of giving
        up immediately, bounded by ``deadline_seconds``.
```

(Only the second sentence changes: `semaphore slots` → `_buffer_sema slots`. Everything else is unchanged.)

In the warning at line 244-249, update the message:

```python
            logger.warning(
                "[SteadyState] final sweep deadline elapsed with {} "
                "in-flight mutant(s) still pending; _buffer_sema slots "
                "will be released on next engine start. stuck_ids={}",
                len(stuck),
                stuck[:10] + (["..."] if len(stuck) > 10 else []),
            )
```

- [ ] **Step 6: Run the new test — verify it passes**

Run: `/run-tests tests/evolution/test_steady_state_init_sema_pair.py`

Expected: 1 passed.

- [ ] **Step 7: Run dispatcher + ingestor tests to confirm what's now broken**

Run: `/run-tests tests/evolution/test_evolution_engine.py tests/evolution/test_engine_ghost_persist.py`

Expected: **multiple failures** referencing `_in_flight_sema` — these will be fixed in Tasks 3–5. Record the list of failing tests as a sanity check that you've found every reference.

- [ ] **Step 8: Lint (do not commit yet — engine is broken)**

Run: `/home/jovyan/.mlspace/envs/evo/bin/ruff check gigaevo/evolution/engine/steady_state.py tests/evolution/test_steady_state_init_sema_pair.py`

Expected: clean (will keep checking after each subsequent task).

**Do not commit yet — the engine is broken at the dispatcher/ingestor/mutant_task boundary. Tasks 3-5 must land in the same commit chain before any push.**

---

## Task 3: Dispatcher — acquire `_producer_sema`

**Files:**
- Modify: `gigaevo/evolution/engine/dispatcher.py:18-39`
- Test: `tests/evolution/test_dispatcher_producer_sema.py` (NEW)

- [ ] **Step 1: Write the failing test**

Create `tests/evolution/test_dispatcher_producer_sema.py`:

```python
"""Dispatcher acquires _producer_sema (not _buffer_sema) before spawning.

These tests use a fake engine surface so dispatcher_loop's semaphore
interaction can be observed without spinning up Redis / strategies /
hooks. We pin three properties:
  1. Each iteration acquires _producer_sema BEFORE create_task.
  2. _buffer_sema is NOT touched by the dispatcher.
  3. Early-stop (engine._running=False after acquire) releases _producer_sema.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from gigaevo.evolution.engine.dispatcher import dispatcher_loop


class _FakeDispatcherEngine:
    """Minimal surface dispatcher_loop reads. No real engine wiring."""

    def __init__(self, max_in_flight: int = 3) -> None:
        self._running = True
        self._producer_sema = asyncio.Semaphore(max_in_flight)
        self._buffer_sema = asyncio.Semaphore(max_in_flight)
        self._max = max_in_flight
        self._spawn_count = 0
        self._reached = False

    def _reached_mutant_cap(self) -> bool:
        return self._reached

    async def _select_parents_for_mutation(self):  # never called in these tests
        return []


@pytest.mark.asyncio
async def test_dispatcher_acquires_producer_sema(monkeypatch) -> None:
    engine = _FakeDispatcherEngine(max_in_flight=2)

    spawned: list[int] = []

    async def fake_run_one_mutant(eng, task_id: int) -> None:
        spawned.append(task_id)
        await asyncio.sleep(0.5)  # hold the slot

    monkeypatch.setattr(
        "gigaevo.evolution.engine.dispatcher.run_one_mutant", fake_run_one_mutant
    )

    task = asyncio.create_task(dispatcher_loop(engine))
    await asyncio.sleep(0.05)  # let dispatcher spawn up to capacity

    # Both initial slots taken from _producer_sema; _buffer_sema untouched.
    assert engine._producer_sema._value == 0
    assert engine._buffer_sema._value == 2
    assert len(spawned) == 2

    engine._running = False
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_dispatcher_early_stop_releases_producer_sema(monkeypatch) -> None:
    """If engine stops between acquire and spawn, the producer slot is returned."""
    engine = _FakeDispatcherEngine(max_in_flight=1)

    async def fake_run_one_mutant(eng, task_id: int) -> None:  # pragma: no cover
        raise AssertionError("should never spawn after early-stop")

    monkeypatch.setattr(
        "gigaevo.evolution.engine.dispatcher.run_one_mutant", fake_run_one_mutant
    )

    # Patch _reached_mutant_cap so the post-acquire check fires immediately
    # for the first iteration but leaves the loop guard simple.
    engine._reached = True

    task = asyncio.create_task(dispatcher_loop(engine))
    await asyncio.sleep(0.05)

    # acquire fired once, post-check tripped, release fired — back to full.
    assert engine._producer_sema._value == 1
    assert engine._buffer_sema._value == 1

    engine._running = False
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
```

- [ ] **Step 2: Run the test — verify it fails**

Run: `/run-tests tests/evolution/test_dispatcher_producer_sema.py`

Expected: 2 failed (`AttributeError: '_FakeDispatcherEngine' object has no attribute '_in_flight_sema'`).

- [ ] **Step 3: Edit `dispatcher.py`**

In `gigaevo/evolution/engine/dispatcher.py:18-39`, replace the loop body so it reads:

```python
async def dispatcher_loop(engine) -> None:
    logger.info("[dispatcher] start")
    active: set[asyncio.Task] = set()
    task_id = 0
    try:
        while engine._running and not engine._reached_mutant_cap():
            await engine._producer_sema.acquire()
            if not engine._running or engine._reached_mutant_cap():
                # Post-acquire early-stop: hand the slot back so a graceful
                # restart finds _producer_sema at full capacity.
                engine._producer_sema.release()
                break
            t = asyncio.create_task(
                run_one_mutant(engine, task_id), name=f"mutant-{task_id}"
            )
            task_id += 1
            active.add(t)
            t.add_done_callback(active.discard)
    finally:
        for t in active:
            t.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)
        logger.info("[dispatcher] stop")
```

- [ ] **Step 4: Re-run the dispatcher tests — verify they pass**

Run: `/run-tests tests/evolution/test_dispatcher_producer_sema.py`

Expected: 2 passed.

- [ ] **Step 5: Lint**

Run: `/home/jovyan/.mlspace/envs/evo/bin/ruff check gigaevo/evolution/engine/dispatcher.py tests/evolution/test_dispatcher_producer_sema.py`

Expected: clean.

**Still do not commit — `mutant_task` still references `_in_flight_sema`.**

---

## Task 4: `run_one_mutant` — buffer-sema acquire + paired release

**Files:**
- Modify: `gigaevo/evolution/engine/mutant_task.py:36-113` (whole function body)
- Test: `tests/evolution/test_mutant_task_two_sema.py` (NEW)

- [ ] **Step 1: Write the failing test (success path + one-of-each cancel path)**

Create `tests/evolution/test_mutant_task_two_sema.py`:

```python
"""Two-sema accounting on every exit path of run_one_mutant.

Each test holds one producer_sema slot at entry (caller protocol — the
dispatcher acquires it before spawning) and verifies the post-condition:

  producer_sema: always released (no transfer semantics)
  buffer_sema  : transferred to ingestor only when slot_transferred=True
  ticket       : transferred only when slot_transferred=True
  _in_flight   : contains new_id iff slot_transferred=True
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from gigaevo.evolution.engine.mutant_task import run_one_mutant
from gigaevo.evolution.engine.refresh import ParentRefreshTicket
from gigaevo.evolution.mutation.parent_selector import RandomParentSelector
from gigaevo.programs.program import Program
from gigaevo.programs.program_state import ProgramState


def _make_parent() -> Program:
    return Program(code="def solve(): return 42", state=ProgramState.DONE)


class _FakeEngine:
    """Minimal engine surface used by run_one_mutant under the two-sema model."""

    def __init__(self, parent: Program, *, max_in_flight: int = 3) -> None:
        self.storage = AsyncMock()
        self.state = AsyncMock()
        self.mutation_operator = AsyncMock()
        self._in_flight: set[str] = set()
        self._inflight_tickets: dict[str, ParentRefreshTicket] = {}
        self._in_flight_lock = asyncio.Lock()
        self._producer_sema = asyncio.Semaphore(max_in_flight)
        self._buffer_sema = asyncio.Semaphore(max_in_flight)

        self.metrics = type("M", (), {})()
        self.metrics.total_mutants = 0
        self.metrics.mutations_created = 0
        self.metrics.submitted_for_refresh = 0

        cfg = type("C", (), {})()
        cfg.loop_interval = 0.01
        cfg.parent_selector = RandomParentSelector(num_parents=1)
        self.config = cfg

        refresher = type("R", (), {})()

        async def _refresh_with_ticket(parents):
            return ParentRefreshTicket(refreshed=parents, _locks=[])

        refresher.refresh_with_ticket = _refresh_with_ticket
        self._parent_refresher = refresher
        self._parent = parent

    async def _select_parents_for_mutation(self):
        return [self._parent]

    async def _write_snapshot(self, **_kwargs) -> None:
        return None


async def _hold_producer_slot(engine: _FakeEngine) -> None:
    """Mirror the dispatcher contract: caller holds one producer slot."""
    await engine._producer_sema.acquire()


@pytest.mark.asyncio
async def test_success_path_transfers_buffer_and_ticket(monkeypatch) -> None:
    engine = _FakeEngine(_make_parent(), max_in_flight=3)
    await _hold_producer_slot(engine)

    async def fake_gen(**_k):
        return "new-id-1"

    monkeypatch.setattr(
        "gigaevo.evolution.engine.mutant_task.generate_one_mutation", fake_gen
    )

    result = await run_one_mutant(engine, task_id=0)

    assert result == "new-id-1"
    # producer slot: released
    assert engine._producer_sema._value == 3
    # buffer slot: held (transferred to ingestor)
    assert engine._buffer_sema._value == 2
    # in-flight & ticket: transferred
    assert "new-id-1" in engine._in_flight
    assert "new-id-1" in engine._inflight_tickets


@pytest.mark.asyncio
async def test_refresh_failure_releases_producer_no_buffer(monkeypatch) -> None:
    engine = _FakeEngine(_make_parent(), max_in_flight=3)
    await _hold_producer_slot(engine)

    async def boom(_parents):
        raise ValueError("refresh boom")

    engine._parent_refresher.refresh_with_ticket = boom

    async def fake_gen(**_k):  # pragma: no cover
        raise AssertionError("must not reach generate_one_mutation")

    monkeypatch.setattr(
        "gigaevo.evolution.engine.mutant_task.generate_one_mutation", fake_gen
    )

    result = await run_one_mutant(engine, task_id=0)

    assert result is None
    assert engine._producer_sema._value == 3
    # buffer never acquired
    assert engine._buffer_sema._value == 3
    assert not engine._in_flight


@pytest.mark.asyncio
async def test_llm_returns_none_releases_producer_no_buffer(monkeypatch) -> None:
    engine = _FakeEngine(_make_parent(), max_in_flight=2)
    await _hold_producer_slot(engine)

    async def fake_gen(**_k):
        return None

    monkeypatch.setattr(
        "gigaevo.evolution.engine.mutant_task.generate_one_mutation", fake_gen
    )

    result = await run_one_mutant(engine, task_id=0)

    assert result is None
    assert engine._producer_sema._value == 2
    assert engine._buffer_sema._value == 2  # untouched
    assert not engine._in_flight


@pytest.mark.asyncio
async def test_cancel_blocked_on_buffer_releases_producer(monkeypatch) -> None:
    """Cancel while producer is waiting on _buffer_sema.acquire().

    Sets up: buffer fully drained so the next acquire blocks. Cancel the
    task while it's parked. Both semaphores must end at their pre-test
    counts (producer back to full, buffer still drained).
    """
    engine = _FakeEngine(_make_parent(), max_in_flight=2)
    # Drain buffer to zero so the producer's acquire blocks.
    await engine._buffer_sema.acquire()
    await engine._buffer_sema.acquire()
    assert engine._buffer_sema._value == 0

    await _hold_producer_slot(engine)

    async def fake_gen(**_k):
        return "drift-id-1"

    monkeypatch.setattr(
        "gigaevo.evolution.engine.mutant_task.generate_one_mutation", fake_gen
    )

    task = asyncio.create_task(run_one_mutant(engine, task_id=0))
    await asyncio.sleep(0.05)  # let it park at _buffer_sema.acquire()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # producer: released. buffer: still zero (we hold both externally).
    assert engine._producer_sema._value == 2
    assert engine._buffer_sema._value == 0
    # _in_flight not populated; persist is the user-visible orphan we
    # acknowledge in the spec's cancellation matrix.
    assert "drift-id-1" not in engine._in_flight
```

- [ ] **Step 2: Run the test — verify it fails**

Run: `/run-tests tests/evolution/test_mutant_task_two_sema.py`

Expected: 4 failed (`run_one_mutant` still references `_in_flight_sema`, doesn't acquire `_buffer_sema`, doesn't carry a `buffer_held` flag).

- [ ] **Step 3: Rewrite `mutant_task.py`**

Replace the entire body of `run_one_mutant` in `gigaevo/evolution/engine/mutant_task.py:36-113` with:

```python
async def run_one_mutant(engine, task_id: int) -> str | None:
    """Produce one mutant. Caller (dispatcher) holds one ``_producer_sema`` slot."""
    slot_transferred = False
    buffer_held = False
    ticket: ParentRefreshTicket | None = None
    new_id: str | None = None
    try:
        parents = await engine._select_parents_for_mutation()
        if not parents:
            # Empty archive — back off so dispatcher does not hot-spin while
            # the population is being seeded or while all programs are being
            # rejected by the acceptor.
            await asyncio.sleep(engine.config.loop_interval)
            return None

        try:
            ticket = await engine._parent_refresher.refresh_with_ticket(parents)
        except (ValueError, TimeoutError) as exc:
            logger.warning(
                "[mutant_task:{}] Parent refresh failed: {} — aborting mutant",
                task_id,
                exc,
            )
            return None
        refreshed = ticket.refreshed

        if refreshed:
            engine.metrics.submitted_for_refresh += len(refreshed)

        # Inline single-mutant primitive — no asyncio.gather to swallow the
        # persisted ID under outer-cancel. If we are cancelled after the
        # program is persisted, generate_one_mutation's except BaseException
        # arm returns the ID and we transfer the slot below before the
        # finally block re-raises.
        new_id = await generate_one_mutation(
            parents=refreshed,
            mutator=engine.mutation_operator,
            storage=engine.storage,
            state_manager=engine.state,
            iteration=engine.metrics.total_mutants,
            task_id=task_id,
        )

        if new_id is None:
            return None

        # Buffer backpressure: block here when the DAG cannot keep up. The
        # producer slot is still held during this wait — that is the design
        # invariant. The producer pool's job is to keep N LLM calls (or
        # ready-result-held producers) alive; the buffer pool gates
        # registration in _in_flight. See spec § Architecture.
        await engine._buffer_sema.acquire()
        buffer_held = True

        # Transfer both the buffer slot AND the parent-refresh ticket
        # atomically under _in_flight_lock so the ingestor can later pair
        # them by mutant id. Holding _in_flight_lock here is cheap — the
        # critical section is two dict/set ops with no awaits.
        async with engine._in_flight_lock:
            engine._in_flight.add(new_id)
            engine._inflight_tickets[new_id] = ticket
        slot_transferred = True
        # Ticket ownership has transferred to the ingestor; null it locally
        # so the `finally` block does not double-release the same locks.
        ticket = None
        engine.metrics.total_mutants += 1
        engine.metrics.mutations_created += 1
        # Persist counter so a resume after a crash continues from the
        # correct mutant count rather than 0. Without this,
        # MaxMutantsStopper would run the full budget again on resume.
        await engine._write_snapshot(total_mutants=engine.metrics.total_mutants)
        return new_id

    finally:
        # producer_sema: ALWAYS released. No transfer semantics — the
        # dispatcher holds one slot per spawned task and the slot is
        # returned to the pool the moment the producer task exits, win,
        # lose, or cancel. This is what lets a freshly-freed DAG slot get
        # refilled within one event-loop tick from a buffer-held producer.
        engine._producer_sema.release()
        # buffer_sema: released only if we held it AND did not transfer
        # to the ingestor. `slot_transferred=True` means the ingestor
        # owns the release. The (buffer_held, slot_transferred) pair has
        # three reachable states:
        #   (False, False) → never acquired, nothing to release.
        #   (True,  False) → acquired but cancel before _in_flight.add;
        #                    we release here.
        #   (True,  True ) → acquired AND transferred; ingestor releases.
        if buffer_held and not slot_transferred:
            engine._buffer_sema.release()
        # Parent-lock invariant: if the ticket did not transfer to the
        # ingestor (failure path or pre-registration cancel), release it
        # here so the per-parent-id locks are freed for the next producer.
        # ``release()`` is idempotent.
        if ticket is not None:
            ticket.release()
```

Also update the module docstring at `gigaevo/evolution/engine/mutant_task.py:1-24`. Replace the entire docstring with:

```python
"""Per-mutant async task — the unit of producer work under the steady-state engine.

One task = one mutant. The dispatcher loop spawns these as soon as a
``_producer_sema`` slot opens; the task runs to completion independently
and is never awaited by the dispatcher.

Three ownership-handoff invariants govern every exit path:

1. **Producer-sema slot**: the dispatcher acquires it before spawning;
   the producer task ALWAYS releases it in ``finally``. No transfer
   semantics. This is what guarantees a freshly-freed DAG slot is
   refilled within one event-loop tick — the producer pool is decoupled
   from the per-mutant DAG lifetime.

2. **Buffer-sema slot**: acquired AFTER the LLM call returns and BEFORE
   ``_in_flight.add``. Every exit either (a) adds the new mutant id to
   ``engine._in_flight`` (transferring slot ownership; the ingestor will
   release the slot when the mutant reaches DONE/DISCARDED), or (b)
   releases the slot here. Never both, never neither.

3. **Parent-refresh ticket**: ``refresh_with_ticket`` returns a ticket
   holding the per-parent-id locks. The producer extends lock-hold past
   the refresh through the entire child-DAG by transferring the ticket
   to ``engine._inflight_tickets`` keyed by the new mutant id; the
   ingestor releases the ticket when the child is ingested or swept. If
   the producer fails before the child is registered, the ticket is
   released here. This enforces "no parent refresh while a child of that
   parent is in flight" — without it, a concurrent producer could pick
   the same parents and read this mutant's in-flight (state=RUNNING,
   metrics={}) entry from Redis during its own refresh DAG.

See ``docs/superpowers/specs/2026-05-13-mutation-throughput-two-sema-design.md``.
"""
```

- [ ] **Step 4: Re-run mutant_task tests — verify all pass**

Run: `/run-tests tests/evolution/test_mutant_task_two_sema.py`

Expected: 4 passed.

- [ ] **Step 5: Lint**

Run: `/home/jovyan/.mlspace/envs/evo/bin/ruff check gigaevo/evolution/engine/mutant_task.py tests/evolution/test_mutant_task_two_sema.py && /home/jovyan/.mlspace/envs/evo/bin/ruff format --check gigaevo/evolution/engine/mutant_task.py tests/evolution/test_mutant_task_two_sema.py`

Expected: clean.

**Still do not commit — ingestor still releases `_in_flight_sema`.**

---

## Task 5: Ingestor — release `_buffer_sema`

**Files:**
- Modify: `gigaevo/evolution/engine/ingestor.py:85-95` (the release-under-lock block)
- Test: `tests/evolution/test_ingestor_releases_buffer.py` (NEW)

- [ ] **Step 1: Write the failing test**

Create `tests/evolution/test_ingestor_releases_buffer.py`:

```python
"""Ingestor releases _buffer_sema on DONE/DISCARDED, never _producer_sema.

The producer task already released _producer_sema in its finally when the
mutant entered _in_flight; the ingestor's job is to release the buffer slot
the producer transferred under _in_flight_lock.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from gigaevo.evolution.engine.ingestor import poll_and_ingest
from gigaevo.evolution.engine.refresh import ParentRefreshTicket
from gigaevo.programs.program import Program
from gigaevo.programs.program_state import ProgramState


class _FakeIngestorEngine:
    def __init__(self, max_in_flight: int = 3) -> None:
        self._in_flight: set[str] = set()
        self._inflight_tickets: dict[str, ParentRefreshTicket] = {}
        self._in_flight_lock = asyncio.Lock()
        self._producer_sema = asyncio.Semaphore(max_in_flight)
        self._buffer_sema = asyncio.Semaphore(max_in_flight)

        self.storage = AsyncMock()
        self.strategy = AsyncMock()

        # config surface
        cfg = type("C", (), {})()
        cfg.loop_interval = 0.01
        cfg.program_acceptor = type("A", (), {})()
        cfg.program_acceptor.is_accepted = lambda _p: True
        cfg.post_step_hook_timeout_s = 1.0
        cfg.post_step_hook_cancel_grace_s = 0.5
        self.config = cfg

        self._post_step_hook = None

        # metrics surface
        self.metrics = type("M", (), {})()
        self.metrics.programs_processed = 0

        def _record(_a, _v, _s):
            return None

        self.metrics.record_ingestion_metrics = _record

        async def _notify(_p, _o):
            return None

        self._notify_hook = _notify

        async def _write_snapshot(**_k):
            return None

        self._write_snapshot = _write_snapshot

    async def _add_in_flight(self, pid: str) -> None:
        # Mirror what the producer does on transfer: acquire buffer_sema,
        # then atomically register under _in_flight_lock with a ticket.
        await self._buffer_sema.acquire()
        async with self._in_flight_lock:
            self._in_flight.add(pid)
            self._inflight_tickets[pid] = ParentRefreshTicket(
                refreshed=[], _locks=[]
            )


@pytest.mark.asyncio
async def test_ingestor_done_releases_buffer_not_producer() -> None:
    engine = _FakeIngestorEngine(max_in_flight=3)
    await engine._add_in_flight("done-1")
    assert engine._buffer_sema._value == 2  # one buffer slot held by producer
    assert engine._producer_sema._value == 3  # producer slot already returned

    # Strategy.add returns True so the program is accepted (no DISCARDED transition).
    engine.strategy.add.return_value = True

    done_prog = Program(
        id="done-1", code="def f(): pass", state=ProgramState.DONE, metrics={}
    )
    engine.storage.mget.return_value = [done_prog]

    handled = await poll_and_ingest(engine)

    assert handled == 1
    # Buffer slot returned to pool; producer pool untouched.
    assert engine._buffer_sema._value == 3
    assert engine._producer_sema._value == 3
    assert not engine._in_flight
    assert not engine._inflight_tickets


@pytest.mark.asyncio
async def test_ingestor_discarded_releases_buffer_not_producer() -> None:
    engine = _FakeIngestorEngine(max_in_flight=3)
    await engine._add_in_flight("disc-1")

    discarded_prog = Program(
        id="disc-1", code="def f(): pass", state=ProgramState.DISCARDED, metrics={}
    )
    engine.storage.mget.return_value = [discarded_prog]

    handled = await poll_and_ingest(engine)

    assert handled == 1
    assert engine._buffer_sema._value == 3
    assert engine._producer_sema._value == 3
    assert not engine._in_flight


@pytest.mark.asyncio
async def test_ingestor_vanished_program_releases_buffer() -> None:
    engine = _FakeIngestorEngine(max_in_flight=3)
    await engine._add_in_flight("ghost-1")

    # storage.mget returns no entries — id leaked.
    engine.storage.mget.return_value = []

    handled = await poll_and_ingest(engine)

    assert handled == 1
    assert engine._buffer_sema._value == 3
    assert engine._producer_sema._value == 3
    assert not engine._in_flight
```

- [ ] **Step 2: Run the test — verify it fails**

Run: `/run-tests tests/evolution/test_ingestor_releases_buffer.py`

Expected: 3 failed (`AttributeError: '_FakeIngestorEngine' object has no attribute '_in_flight_sema'`).

- [ ] **Step 3: Edit `ingestor.py`**

In `gigaevo/evolution/engine/ingestor.py:85-94`, replace:

```python
        async with engine._in_flight_lock:
            for pid in released:
                if pid in engine._in_flight:
                    engine._in_flight.discard(pid)
                    engine._in_flight_sema.release()
                    ticket = engine._inflight_tickets.pop(pid, None)
                    if ticket is not None:
                        tickets_to_release.append(ticket)
```

with:

```python
        async with engine._in_flight_lock:
            for pid in released:
                if pid in engine._in_flight:
                    engine._in_flight.discard(pid)
                    # Buffer slot transferred to us by the producer under
                    # _in_flight_lock; we release it here so the next
                    # producer blocked at _buffer_sema.acquire() wakes up
                    # and registers ITS already-completed result in
                    # _in_flight on the next event-loop tick. The producer
                    # sema is untouched — the producer task released it in
                    # its own finally the moment it exited.
                    engine._buffer_sema.release()
                    ticket = engine._inflight_tickets.pop(pid, None)
                    if ticket is not None:
                        tickets_to_release.append(ticket)
```

The saturation check in `ingestor_loop` (line 27) is unchanged — it reads `len(engine._in_flight)`, not a semaphore value.

- [ ] **Step 4: Re-run ingestor tests — verify all pass**

Run: `/run-tests tests/evolution/test_ingestor_releases_buffer.py`

Expected: 3 passed.

- [ ] **Step 5: Lint**

Run: `/home/jovyan/.mlspace/envs/evo/bin/ruff check gigaevo/evolution/engine/ingestor.py tests/evolution/test_ingestor_releases_buffer.py`

Expected: clean.

---

## Task 6: Migrate `_FakeEngine` in existing ghost-persist test

**Files:**
- Modify: `tests/evolution/test_engine_ghost_persist.py:281-326` (the `_FakeEngine` class)

- [ ] **Step 1: Apply the migration**

In `tests/evolution/test_engine_ghost_persist.py:293`, replace:

```python
        self._in_flight_sema = asyncio.Semaphore(8)
```

with:

```python
        self._producer_sema = asyncio.Semaphore(8)
        self._buffer_sema = asyncio.Semaphore(8)
```

Then update the integration test body at lines 396-407. Replace:

```python
        sema_was_released = engine._in_flight_sema._value >= 1
        has_in_flight = len(engine._in_flight) >= 1
        # ghost = persisted, no tracking, slot reclaimed — engine "forgot" the program
        is_ghost = (
            storage.add.call_count == 1 and not has_in_flight and sema_was_released
        )
        assert not is_ghost, (
            "GHOST-PERSIST: program in Redis, no _in_flight entry, "
            "sema released — engine lost the program. "
            f"task_cancelled={task_cancelled} result={result} "
            f"in_flight={engine._in_flight} sema_value={engine._in_flight_sema._value}"
        )
```

with:

```python
        # Under the two-sema model, the ghost check is "persisted but neither
        # in_flight nor any buffer slot consumed by us" — which means the
        # producer task either never acquired _buffer_sema (cancel arrived
        # before that step) OR acquired and released it in finally. Either
        # way, if storage.add fired AND _in_flight is empty AND the producer
        # slot has come back to full, the engine has lost the program.
        producer_returned = engine._producer_sema._value >= 8
        has_in_flight = len(engine._in_flight) >= 1
        is_ghost = (
            storage.add.call_count == 1 and not has_in_flight and producer_returned
        )
        assert not is_ghost, (
            "GHOST-PERSIST: program in Redis, no _in_flight entry, "
            "producer slot released — engine lost the program. "
            f"task_cancelled={task_cancelled} result={result} "
            f"in_flight={engine._in_flight} "
            f"producer_sema={engine._producer_sema._value} "
            f"buffer_sema={engine._buffer_sema._value}"
        )
```

Also update the caller protocol in the same test at line 366. Replace:

```python
        await engine._in_flight_sema.acquire()  # caller holds a slot per protocol
```

with:

```python
        await engine._producer_sema.acquire()  # dispatcher holds one producer slot per protocol
```

- [ ] **Step 2: Run the ghost-persist test — verify pass**

Run: `/run-tests tests/evolution/test_engine_ghost_persist.py`

Expected: all previously-passing tests still pass.

- [ ] **Step 3: Run the broader evolution-engine suite — verify the wiring is sound**

Run: `/run-tests tests/evolution/test_evolution_engine.py tests/evolution/test_engine_ghost_persist.py tests/evolution/test_engine_cancellation.py tests/evolution/test_engine_invariants.py`

Expected: **all pass.** If any test still references `_in_flight_sema`, grep for it:

```bash
rtk git grep -n "_in_flight_sema" tests/
```

Expected output: no remaining matches (or only matches in dead `# old` comments, which you should delete).

- [ ] **Step 4: Lint the whole engine module + touched tests**

Run: `/home/jovyan/.mlspace/envs/evo/bin/ruff check gigaevo/evolution/engine/ tests/evolution/`

Expected: clean.

- [ ] **Step 5: Commit Tasks 2–6 atomically**

```bash
rtk git add gigaevo/evolution/engine/steady_state.py \
            gigaevo/evolution/engine/dispatcher.py \
            gigaevo/evolution/engine/mutant_task.py \
            gigaevo/evolution/engine/ingestor.py \
            tests/evolution/test_steady_state_init_sema_pair.py \
            tests/evolution/test_dispatcher_producer_sema.py \
            tests/evolution/test_mutant_task_two_sema.py \
            tests/evolution/test_ingestor_releases_buffer.py \
            tests/evolution/test_engine_ghost_persist.py
rtk git commit -m "$(cat <<'EOF'
refactor(engine): two-semaphore mutation throughput

Replace single _in_flight_sema with _producer_sema (concurrent
refresh+LLM) and _buffer_sema (produced-but-not-ingested). The
dispatcher acquires producer_sema; mutant_task acquires buffer_sema
after the LLM persist and transfers it atomically with the refresh
ticket under _in_flight_lock; ingestor releases buffer_sema on
DONE/DISCARDED. Producer_sema has no transfer semantics — always
released in mutant_task's finally — which is what lets a freshly-
freed DAG slot get refilled in one event-loop tick from a ready
buffer-held producer.

Both pools sized from the existing max_in_flight knob (single
operator-facing field, semantics documented in config docstring).
Steady-state pipeline depth ~2 × max_in_flight.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Slot-leak invariant under load + cancel chaos

**Files:**
- Test: `tests/evolution/test_engine_no_slot_leak.py` (NEW)

- [ ] **Step 1: Write the failing test (will reveal accounting holes)**

Create `tests/evolution/test_engine_no_slot_leak.py`:

```python
"""Slot-accounting invariants under load + cancel chaos.

These tests use a fake-engine surface so we exercise dispatcher +
mutant_task + ingestor together (the three components that share the
two semaphores) without spinning up Redis, the DAG runner, or the
strategy. Property under test:

  After 200 producer tasks complete (mix of success / refresh-fail /
  LLM-None / cancel mid-flight), both semaphores' available count
  must equal the initial capacity. No silent leaks across paths.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any
from unittest.mock import AsyncMock

import pytest

from gigaevo.evolution.engine.mutant_task import run_one_mutant
from gigaevo.evolution.engine.refresh import ParentRefreshTicket
from gigaevo.evolution.mutation.parent_selector import RandomParentSelector
from gigaevo.programs.program import Program
from gigaevo.programs.program_state import ProgramState


class _LoadEngine:
    def __init__(self, max_in_flight: int) -> None:
        self.N = max_in_flight
        self._in_flight: set[str] = set()
        self._inflight_tickets: dict[str, ParentRefreshTicket] = {}
        self._in_flight_lock = asyncio.Lock()
        self._producer_sema = asyncio.Semaphore(max_in_flight)
        self._buffer_sema = asyncio.Semaphore(max_in_flight)

        self.storage = AsyncMock()
        self.state = AsyncMock()
        self.mutation_operator = AsyncMock()

        self.metrics = type("M", (), {})()
        self.metrics.total_mutants = 0
        self.metrics.mutations_created = 0
        self.metrics.submitted_for_refresh = 0

        cfg = type("C", (), {})()
        cfg.loop_interval = 0.001
        cfg.parent_selector = RandomParentSelector(num_parents=1)
        self.config = cfg

        self._refresh_fail = False
        self._llm_returns_none = False
        self._parent = Program(code="def f(): return 1", state=ProgramState.DONE)

        async def _refresh_with_ticket(parents):
            if self._refresh_fail:
                raise ValueError("synthetic refresh failure")
            return ParentRefreshTicket(refreshed=parents, _locks=[])

        refresher = type("R", (), {})()
        refresher.refresh_with_ticket = _refresh_with_ticket
        self._parent_refresher = refresher

    async def _select_parents_for_mutation(self):
        return [self._parent]

    async def _write_snapshot(self, **_k):
        return None


def _make_gen(out_id_box: list[str], failures: set[int], iteration_ref: list[int]):
    async def _gen(**_k):
        # Each call gets the next sequential id; some return None.
        i = iteration_ref[0]
        iteration_ref[0] += 1
        # Tiny yield so cancellation can land here.
        await asyncio.sleep(random.uniform(0.0001, 0.001))
        if i in failures:
            return None
        pid = f"id-{i}"
        out_id_box.append(pid)
        return pid

    return _gen


@pytest.mark.asyncio
async def test_no_leak_under_random_workloads(monkeypatch) -> None:
    """200 producers, mix of success/refresh-fail/LLM-None — both semas full at end."""
    random.seed(0xC0FFEE)
    N = 5
    engine = _LoadEngine(max_in_flight=N)
    ids_produced: list[str] = []
    none_iters = {i for i in range(200) if random.random() < 0.2}  # ~20% return None
    iteration_ref = [0]

    monkeypatch.setattr(
        "gigaevo.evolution.engine.mutant_task.generate_one_mutation",
        _make_gen(ids_produced, none_iters, iteration_ref),
    )

    async def one_producer(i: int) -> None:
        # ~10% of iterations: simulate refresh failure for this producer only.
        engine._refresh_fail = random.random() < 0.10
        await engine._producer_sema.acquire()
        try:
            await run_one_mutant(engine, task_id=i)
        finally:
            engine._refresh_fail = False

    # Mock ingestor: drain _in_flight as soon as anything appears, releasing
    # the buffer slot. This simulates the DAG completing fast.
    async def fake_ingestor() -> None:
        while True:
            await asyncio.sleep(0.001)
            async with engine._in_flight_lock:
                drained = list(engine._in_flight)
                engine._in_flight.clear()
                tickets = [engine._inflight_tickets.pop(p, None) for p in drained]
            for _ in drained:
                engine._buffer_sema.release()
            for t in tickets:
                if t is not None:
                    t.release()

    ingestor = asyncio.create_task(fake_ingestor())
    await asyncio.gather(*[one_producer(i) for i in range(200)])
    ingestor.cancel()
    try:
        await ingestor
    except asyncio.CancelledError:
        pass

    # Final drain check.
    async with engine._in_flight_lock:
        leftover = list(engine._in_flight)
        engine._in_flight.clear()
    for _ in leftover:
        engine._buffer_sema.release()

    # No leaks: both pools at full capacity.
    assert engine._producer_sema._value == N, (
        f"producer_sema leaked: value={engine._producer_sema._value} expected={N}"
    )
    assert engine._buffer_sema._value == N, (
        f"buffer_sema leaked: value={engine._buffer_sema._value} expected={N}"
    )


@pytest.mark.asyncio
async def test_no_leak_with_cancel_chaos(monkeypatch) -> None:
    """200 producers, ~10% cancelled at random points — invariants still hold."""
    random.seed(0xDEADBEEF)
    N = 5
    engine = _LoadEngine(max_in_flight=N)
    ids_produced: list[str] = []
    iteration_ref = [0]

    monkeypatch.setattr(
        "gigaevo.evolution.engine.mutant_task.generate_one_mutation",
        _make_gen(ids_produced, set(), iteration_ref),
    )

    cancelled_tasks: list[asyncio.Task] = []

    async def one_producer(i: int) -> None:
        await engine._producer_sema.acquire()
        try:
            await run_one_mutant(engine, task_id=i)
        except asyncio.CancelledError:
            raise

    async def cancel_chaos(tasks: list[asyncio.Task]) -> None:
        # Wake up a few times during the workload; cancel ~10% of in-flight.
        for _ in range(8):
            await asyncio.sleep(random.uniform(0.001, 0.005))
            alive = [t for t in tasks if not t.done()]
            random.shuffle(alive)
            for t in alive[: max(1, len(alive) // 10)]:
                t.cancel()
                cancelled_tasks.append(t)

    async def fake_ingestor() -> None:
        while True:
            await asyncio.sleep(0.001)
            async with engine._in_flight_lock:
                drained = list(engine._in_flight)
                engine._in_flight.clear()
                tickets = [engine._inflight_tickets.pop(p, None) for p in drained]
            for _ in drained:
                engine._buffer_sema.release()
            for t in tickets:
                if t is not None:
                    t.release()

    ingestor = asyncio.create_task(fake_ingestor())
    tasks = [asyncio.create_task(one_producer(i)) for i in range(200)]
    chaos = asyncio.create_task(cancel_chaos(tasks))
    await asyncio.gather(*tasks, return_exceptions=True)
    await chaos
    ingestor.cancel()
    try:
        await ingestor
    except asyncio.CancelledError:
        pass

    async with engine._in_flight_lock:
        leftover = list(engine._in_flight)
        engine._in_flight.clear()
    for _ in leftover:
        engine._buffer_sema.release()

    assert engine._producer_sema._value == N, (
        f"producer_sema leaked under chaos: "
        f"value={engine._producer_sema._value} expected={N}; "
        f"cancelled={len(cancelled_tasks)}"
    )
    assert engine._buffer_sema._value == N, (
        f"buffer_sema leaked under chaos: "
        f"value={engine._buffer_sema._value} expected={N}; "
        f"cancelled={len(cancelled_tasks)}"
    )
```

- [ ] **Step 2: Run the tests — they should pass on the fix**

Run: `/run-tests tests/evolution/test_engine_no_slot_leak.py`

Expected: 2 passed. (If they fail, the leak they expose is real and Task 4's `finally` block needs auditing — re-read the `(buffer_held, slot_transferred)` matrix.)

- [ ] **Step 3: Lint**

Run: `/home/jovyan/.mlspace/envs/evo/bin/ruff check tests/evolution/test_engine_no_slot_leak.py`

Expected: clean.

- [ ] **Step 4: Commit**

```bash
rtk git add tests/evolution/test_engine_no_slot_leak.py
rtk git commit -m "$(cat <<'EOF'
test(engine): slot-leak invariants under load + cancel chaos

200 producer tasks, mixed exit paths (success / refresh-fail / LLM-None /
cancel at random point), fake-ingestor draining _in_flight. After all
tasks settle, both semaphores must return to their initial capacity.
Validates the buffer_held / slot_transferred flag interactions for the
full reachable state space.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Behavioral test — DAG slot refilled within one tick

**Files:**
- Test: `tests/evolution/test_engine_jit_dag_refill.py` (NEW)

- [ ] **Step 1: Write the failing test**

Create `tests/evolution/test_engine_jit_dag_refill.py`:

```python
"""The property this redesign exists to deliver:

When the ingestor releases a buffer slot, an already-completed LLM result
(held in memory by a producer task blocked at _buffer_sema.acquire()) is
registered in _in_flight within ONE event-loop tick. No LLM round-trip
sits between "DAG slot free" and "next mutant queued."

We construct N pre-completed producers blocked on _buffer_sema, then call
the ingestor-side release. The blocked producer must wake up and register
its mutant before our test sleep elapses — we use a tight 50ms window to
prove "one tick" rather than "eventually."
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from gigaevo.evolution.engine.mutant_task import run_one_mutant
from gigaevo.evolution.engine.refresh import ParentRefreshTicket
from gigaevo.evolution.mutation.parent_selector import RandomParentSelector
from gigaevo.programs.program import Program
from gigaevo.programs.program_state import ProgramState


class _JITEngine:
    def __init__(self, N: int) -> None:
        self.N = N
        self._in_flight: set[str] = set()
        self._inflight_tickets: dict[str, ParentRefreshTicket] = {}
        self._in_flight_lock = asyncio.Lock()
        self._producer_sema = asyncio.Semaphore(N)
        self._buffer_sema = asyncio.Semaphore(N)

        self.storage = AsyncMock()
        self.state = AsyncMock()
        self.mutation_operator = AsyncMock()

        self.metrics = type("M", (), {})()
        self.metrics.total_mutants = 0
        self.metrics.mutations_created = 0
        self.metrics.submitted_for_refresh = 0

        cfg = type("C", (), {})()
        cfg.loop_interval = 0.001
        cfg.parent_selector = RandomParentSelector(num_parents=1)
        self.config = cfg

        self._parent = Program(code="def f(): return 1", state=ProgramState.DONE)

        async def _refresh_with_ticket(parents):
            return ParentRefreshTicket(refreshed=parents, _locks=[])

        refresher = type("R", (), {})()
        refresher.refresh_with_ticket = _refresh_with_ticket
        self._parent_refresher = refresher

    async def _select_parents_for_mutation(self):
        return [self._parent]

    async def _write_snapshot(self, **_k):
        return None


@pytest.mark.asyncio
async def test_buffer_release_wakes_blocked_producer_in_one_tick(monkeypatch) -> None:
    """N producers ready with completed LLM results; release frees instant registration."""
    N = 3
    engine = _JITEngine(N=N)
    counter = [0]

    async def fake_gen(**_k):
        counter[0] += 1
        return f"id-{counter[0]}"

    monkeypatch.setattr(
        "gigaevo.evolution.engine.mutant_task.generate_one_mutation", fake_gen
    )

    # Step 1: drain the buffer_sema to zero by acquiring N slots externally —
    # this simulates "DAG is full." The producer tasks will block at
    # _buffer_sema.acquire() after their fake_gen returns.
    for _ in range(N):
        await engine._buffer_sema.acquire()
    assert engine._buffer_sema._value == 0

    # Step 2: spawn N producer tasks. Each will acquire _producer_sema, run
    # the fake LLM, then block at _buffer_sema.acquire().
    async def one_producer(i: int) -> str | None:
        await engine._producer_sema.acquire()
        return await run_one_mutant(engine, task_id=i)

    producers = [asyncio.create_task(one_producer(i)) for i in range(N)]
    # Let the producers run their LLM (fake_gen) and park at the buffer wait.
    # We need a slightly larger pause here only because we have N tasks each
    # going through several await points; 50ms is comfortably long enough.
    await asyncio.sleep(0.05)

    # All N completed their LLM and are now blocked on _buffer_sema.
    assert counter[0] == N
    assert len(engine._in_flight) == 0  # none registered yet

    # Step 3: release ONE buffer slot (simulating the ingestor seeing a DAG
    # slot free). Measure how quickly the registered count grows from 0→1.
    t0 = time.monotonic()
    engine._buffer_sema.release()
    # Yield to the scheduler. _ONE_ tick must be enough.
    await asyncio.sleep(0)
    await asyncio.sleep(0)  # at most two tick-yields — covers acquire→lock→add
    elapsed = time.monotonic() - t0

    assert len(engine._in_flight) == 1, (
        f"Expected exactly 1 producer to register after one buffer release; "
        f"got {len(engine._in_flight)}. Either the producer is not waking up "
        f"on release, or it's doing more work between release and "
        f"_in_flight.add than the spec allows."
    )
    # Sanity: well under any LLM round-trip.
    assert elapsed < 0.020, (
        f"Buffer-release → in_flight registration took {elapsed*1000:.1f}ms; "
        f"must be sub-tick (< 20ms) to satisfy the redesign goal."
    )

    # Cleanup: release remaining producers.
    for _ in range(N - 1):
        engine._buffer_sema.release()
    for p in producers:
        try:
            await p
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_producer_continues_during_buffer_pressure(monkeypatch) -> None:
    """LLM keeps running while buffer is full — producer_sema is the limiter.

    Confirms the producer pool is NOT gated by the buffer. With N producer
    slots and 0 buffer slots, exactly N producers should complete their LLM
    call (incrementing the counter) and then park; no further producers
    should start because _producer_sema is the gate.
    """
    N = 4
    engine = _JITEngine(N=N)
    counter = [0]

    async def fake_gen(**_k):
        counter[0] += 1
        return f"id-{counter[0]}"

    monkeypatch.setattr(
        "gigaevo.evolution.engine.mutant_task.generate_one_mutation", fake_gen
    )

    # Drain buffer fully.
    for _ in range(N):
        await engine._buffer_sema.acquire()

    # Spawn 3N producer tasks. Each must acquire _producer_sema before its
    # LLM call. With buffer fully drained, completed-and-waiting producers
    # never release _producer_sema, so only N LLM calls fire.
    async def one_producer(i: int) -> str | None:
        await engine._producer_sema.acquire()
        return await run_one_mutant(engine, task_id=i)

    producers = [asyncio.create_task(one_producer(i)) for i in range(3 * N)]
    await asyncio.sleep(0.05)

    assert counter[0] == N, (
        f"Expected exactly N={N} LLM calls (producer-sema gated); "
        f"got {counter[0]}. If the count is 3N, the producer is releasing "
        f"its slot before _in_flight.add — the wrong limiter is active."
    )

    # Cleanup.
    for _ in range(N):
        engine._buffer_sema.release()
    for p in producers:
        try:
            p.cancel()
            await p
        except (asyncio.CancelledError, Exception):
            pass
```

- [ ] **Step 2: Run the test — verify pass**

Run: `/run-tests tests/evolution/test_engine_jit_dag_refill.py`

Expected: 2 passed. (If `test_buffer_release_wakes_blocked_producer_in_one_tick` fails with `len(_in_flight) == 0`, the buffer-acquire is happening too late in `run_one_mutant` — re-read the order of operations in Task 4 step 3.)

- [ ] **Step 3: Lint**

Run: `/home/jovyan/.mlspace/envs/evo/bin/ruff check tests/evolution/test_engine_jit_dag_refill.py`

Expected: clean.

- [ ] **Step 4: Commit**

```bash
rtk git add tests/evolution/test_engine_jit_dag_refill.py
rtk git commit -m "$(cat <<'EOF'
test(engine): JIT DAG refill — buffer release wakes producer in one tick

The behavioral property the two-sema redesign exists to deliver: when
the ingestor releases _buffer_sema, an already-completed LLM result is
registered in _in_flight within one event-loop tick. Also verifies the
producer pool is gated by _producer_sema, not _buffer_sema, so the LLM
keeps running under buffer pressure.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Resume-after-kill regression test

**Files:**
- Modify: `tests/evolution/test_engine_resume_after_kill.py` (existing — patch + extend if needed)
- Test: `tests/evolution/test_engine_resume_two_sema.py` (NEW)

- [ ] **Step 1: Inspect the existing resume test**

Run: `rtk git grep -n "_in_flight_sema\|_producer_sema\|_buffer_sema" tests/evolution/test_engine_resume_after_kill.py tests/evolution/test_resume.py tests/evolution/test_resume_e2e.py`

Expected: matches show where (if anywhere) existing resume tests touch the semaphore. **If any match references `_in_flight_sema`, replace it with `_producer_sema` (the dispatcher's gate). Buffer-sema is rebuilt fresh on resume — see Step 2.**

- [ ] **Step 2: Write the failing test**

Create `tests/evolution/test_engine_resume_two_sema.py`:

```python
"""Engine resume: both semaphores initialize at full capacity, _in_flight empty.

Today's behavior (verified in spec § Crash-resume): the single
_in_flight_sema starts at full capacity regardless of stranded RUNNING
programs in Redis; the engine relies on the recovery pass to rehydrate
_in_flight separately. The two-sema redesign mirrors this verbatim —
NEITHER semaphore is acquired during __init__. If the resume contract
is later strengthened to populate _in_flight from stranded RUNNING
programs on init, the implementation MUST also acquire _buffer_sema
once per rehydrated entry; today no such pre-acquire happens.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from gigaevo.evolution.engine.config import SteadyStateEngineConfig
from gigaevo.evolution.engine.steady_state import SteadyStateEvolutionEngine


def _engine(N: int) -> SteadyStateEvolutionEngine:
    return SteadyStateEvolutionEngine(
        config=SteadyStateEngineConfig(max_in_flight=N),
        storage=AsyncMock(),
        strategy=AsyncMock(),
        mutation_operator=AsyncMock(),
        state=MagicMock(),
    )


@pytest.mark.asyncio
async def test_resume_both_semaphores_start_at_full_capacity() -> None:
    """Fresh-construct after a simulated crash: both semas at N, _in_flight empty."""
    engine = _engine(N=4)
    # Construction is the entire "resume from crash" boundary today —
    # rehydration of _in_flight happens via storage recovery in run.py, not
    # via the engine __init__. The semaphores must reflect a clean slate.
    assert engine._producer_sema._value == 4
    assert engine._buffer_sema._value == 4
    assert engine._in_flight == set()
    assert engine._inflight_tickets == {}


@pytest.mark.asyncio
async def test_resume_with_stranded_in_flight_rehydration_keeps_semas_full() -> None:
    """If a future patch adds rehydration, this test guards the buffer_sema invariant.

    Today: __init__ creates an empty _in_flight set, so this test is a
    no-op precondition assertion. If rehydration is added later, the
    implementation MUST acquire _buffer_sema once per rehydrated id
    (mirroring what the producer would have done pre-crash); this test
    will then need to assert _buffer_sema._value == N - len(_in_flight)
    and break loudly if the producer/buffer invariant drifts.
    """
    engine = _engine(N=3)
    # Today no rehydration in __init__. Document the invariant for whoever
    # adds it: producer_sema is rebuilt fresh; buffer_sema must drop by
    # exactly len(_in_flight) on resume to preserve "buffer slot held per
    # in-flight mutant."
    assert engine._buffer_sema._value == 3
    assert len(engine._in_flight) == 0
    # ⚠ NOTE FOR FUTURE: if you populate _in_flight from stranded RUNNING
    # programs here, also `await engine._buffer_sema.acquire()` for each
    # rehydrated id, then assert this:
    #   assert engine._buffer_sema._value == 3 - len(engine._in_flight)
```

- [ ] **Step 3: Run the test — verify pass**

Run: `/run-tests tests/evolution/test_engine_resume_two_sema.py`

Expected: 2 passed.

- [ ] **Step 4: Patch the existing resume tests if they referenced `_in_flight_sema`**

If Step 1 found references in `test_engine_resume_after_kill.py` / `test_resume.py` / `test_resume_e2e.py`, replace each `engine._in_flight_sema` occurrence with `engine._producer_sema`. After patching, run:

Run: `/run-tests tests/evolution/test_engine_resume_after_kill.py tests/evolution/test_resume.py tests/evolution/test_resume_e2e.py`

Expected: all pass. If anything fails because the semantic meaning differs, **stop** and ask — the redesign may interact with resume in a way the spec didn't cover.

- [ ] **Step 5: Lint**

Run: `/home/jovyan/.mlspace/envs/evo/bin/ruff check tests/evolution/test_engine_resume_two_sema.py tests/evolution/test_engine_resume_after_kill.py tests/evolution/test_resume.py tests/evolution/test_resume_e2e.py`

Expected: clean.

- [ ] **Step 6: Commit**

```bash
rtk git add tests/evolution/test_engine_resume_two_sema.py \
            tests/evolution/test_engine_resume_after_kill.py \
            tests/evolution/test_resume.py \
            tests/evolution/test_resume_e2e.py
rtk git commit -m "$(cat <<'EOF'
test(engine): resume — both semaphores re-init at full capacity

Documents the invariant: __init__ is the entire resume boundary today;
_in_flight is rehydrated by storage recovery in run.py, not in the
engine. Both semaphores must therefore start at full capacity on
__init__. Existing resume tests migrated from _in_flight_sema to
_producer_sema where they touched the legacy attribute.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Real-Redis end-to-end smoke

**Files:**
- Test: `tests/integration/test_two_sema_end_to_end.py` (NEW)
- Read first (for the integration pattern): `tests/integration/` (see what exists)

- [ ] **Step 1: Inspect existing integration patterns**

Run: `ls tests/integration/ && grep -l "redis" tests/integration/*.py | head -3`

Identify the most similar existing integration test (likely one that uses Redis DB 15 with a real `RedisProgramStorage`). Read the top of its `_make_engine` / `_make_storage` helper to mirror the pattern. **Do not invent a new setup pattern.**

- [ ] **Step 2: Write the failing test**

Create `tests/integration/test_two_sema_end_to_end.py`. Use the helper pattern from the file you read in Step 1. The test body should be:

```python
"""End-to-end: real Redis, N=3 max_in_flight, 30 mutants, clean drain.

Validates the two-sema model under the full DAG + ingestor stack — the
unit/invariant tests in tests/evolution/ exercise individual components
with fake-engine surfaces; this one wires the real thing.

Skipped by default if Redis DB 15 is not reachable.
"""

from __future__ import annotations

import asyncio
import os

import pytest

# Skip the whole module if Redis isn't reachable on the conventional dev port.
redis = pytest.importorskip("redis.asyncio")


REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_DB = 15  # tests-only DB


async def _redis_alive() -> bool:
    try:
        client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)
        await client.ping()
        await client.flushdb()
        await client.aclose()
        return True
    except Exception:
        return False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_two_sema_pipeline_drains_cleanly() -> None:
    if not await _redis_alive():
        pytest.skip(f"Redis unavailable at {REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}")

    # Use the same engine-builder helper your similar integration test uses.
    # Pseudocode (replace with the real helpers identified in Step 1):
    #
    #   storage = build_test_storage(db=REDIS_DB)
    #   engine = build_steady_state_engine(
    #       storage=storage,
    #       max_in_flight=3,
    #       max_mutants=30,
    #       mutation_operator=DummyMutationOperator(),
    #   )
    #   await engine.run()
    #
    # Then assert:
    #   - engine._in_flight is empty
    #   - engine._producer_sema._value == 3
    #   - engine._buffer_sema._value == 3
    #   - engine.metrics.total_mutants >= 30
    #
    # Until the test-builder pattern is mirrored from the file you read in
    # Step 1, mark this test xfail so it stays in the tree as a contract
    # signal without blocking the test run.
    pytest.xfail(
        "Integration test scaffolding pending — mirror pattern from "
        "tests/integration/<existing>.py and replace this xfail."
    )
```

**Important:** If you find a suitable existing integration test in Step 1 (e.g. `tests/integration/test_steady_state_redis.py` or similar), **delete the `pytest.xfail` body and replace it with the real engine setup mirroring that file.** The xfail is a placeholder only when the integration scaffolding doesn't already exist.

- [ ] **Step 3: Run the test**

Run: `/run-tests tests/integration/test_two_sema_end_to_end.py`

Expected: 1 xpassed/passed or 1 skipped (Redis down). Either is acceptable for CI; what we want is the contract recorded.

- [ ] **Step 4: Lint**

Run: `/home/jovyan/.mlspace/envs/evo/bin/ruff check tests/integration/test_two_sema_end_to_end.py`

Expected: clean.

- [ ] **Step 5: Commit**

```bash
rtk git add tests/integration/test_two_sema_end_to_end.py
rtk git commit -m "$(cat <<'EOF'
test(integration): real-Redis smoke for two-sema pipeline

N=3, 30 mutants, real Redis DB 15. Asserts pipeline drains cleanly
(both semaphores back at full capacity, _in_flight empty). Skipped
when Redis unreachable; xfail when integration scaffolding has not
been mirrored from the closest existing integration test.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Full evolution suite sweep + push

**Files:**
- (None — final verification + push)

- [ ] **Step 1: Run the full evolution test surface and the integration smoke**

Run:

```bash
/run-tests tests/evolution/ tests/integration/
```

Expected: all pass, plus the integration test either passes or is skipped (Redis down).

If anything fails: **stop and ask.** Do NOT push a partial fix. The likely failure modes are:
- A test in `test_evolution_engine.py` still references `_in_flight_sema` — grep for it and migrate.
- A test in `test_engine_stress.py` expects specific semaphore values mid-run — re-read the test, decide if the property still holds.

- [ ] **Step 2: Lint the entire engine module + test surface**

Run: `/home/jovyan/.mlspace/envs/evo/bin/ruff check gigaevo/evolution/engine/ tests/evolution/ tests/integration/ && /home/jovyan/.mlspace/envs/evo/bin/ruff format --check gigaevo/evolution/engine/ tests/evolution/ tests/integration/`

Expected: clean.

- [ ] **Step 3: Confirm no stragglers reference `_in_flight_sema`**

Run: `rtk git grep -n "_in_flight_sema" gigaevo/ tests/`

Expected: zero matches.

- [ ] **Step 4: Push the branch**

Run: `rtk git push`

Expected: branch updated on origin.

- [ ] **Step 5: Telegram status notification**

Run:

```bash
/home/jovyan/.mlspace/envs/evo/bin/python3 -c "from tools.telegram_notify import notify; notify('refactor/steady-state-true-jit-refresh: two-sema redesign landed. PR #227 updated. All tests green.', parse_mode='')"
```

(Use `parse_mode=""` to avoid markdown parsing on the message body.)

---

## Self-Review

### 1. Spec coverage

| Spec section | Task(s) |
|---|---|
| § Architecture — two semaphores in `__init__` | Task 2 |
| § Architecture — startup log line | Task 2 |
| `config.py` — docstring rewrite | Task 1 |
| `steady_state.py` — `__init__` builds both semaphores | Task 2 |
| `steady_state.py` — `_final_ingestion_sweep` references `buffer_sema` | Task 2 (doc-comment + log message updates) |
| `dispatcher.py` — acquire/release producer_sema | Task 3 |
| `mutant_task.py` — complete rewrite with buffer-sema acquire-after-LLM | Task 4 |
| `mutant_task.py` — `finally` releases producer_sema always, buffer_sema iff held-not-transferred | Task 4 |
| `ingestor.py` — release buffer_sema on DONE/DISCARDED | Task 5 |
| § Ownership Invariants I1 / I2 / I3 | Tasks 4 + 5 (code) + Task 7 (chaos test verifies all three) |
| § Cancellation matrix | Task 4 (success + 3 of 6 rows), Task 7 (load + chaos = full coverage) |
| § Crash-resume contract | Task 9 |
| § Testing § Unit | Tasks 1, 3, 4, 5 |
| § Testing § Invariant | Task 7 |
| § Testing § Concurrency / observable behavior | Task 8 |
| § Testing § Resume | Task 9 |
| § Testing § Integration | Task 10 |
| § Risk Register — operator confusion (startup log) | Task 2 (the log-line update) |

No gaps. Every spec section has a dedicated task or two.

### 2. Placeholder scan

Scanned for "TBD", "TODO", "Similar to Task", "fill in details", "appropriate error handling". One placeholder remains in Task 10 step 2 — it explicitly calls for *the engineer* to mirror an existing integration-test pattern they identify in Step 1. That's documented behavior, not a missing instruction; the xfail line keeps the test passing until the scaffolding is mirrored. **Not a plan failure** — it's a concrete fallback with an exit ramp.

### 3. Type / name consistency

- `_producer_sema` / `_buffer_sema` (leading underscore, snake_case) used in every task — locked in the "Naming convention" section at the top.
- `slot_transferred` reused from current code; `buffer_held` added; no `producer_held` — documented in the same section.
- `ParentRefreshTicket` reused from `refresh.py` — no new fields.
- `_in_flight` / `_inflight_tickets` / `_in_flight_lock` unchanged.
- Helper class names (`_FakeDispatcherEngine`, `_FakeIngestorEngine`, `_LoadEngine`, `_JITEngine`, `_FakeEngine`) — all clearly scoped to their test file; no cross-test sharing assumed.

No type-consistency issues.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-13-mutation-throughput-two-sema.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
