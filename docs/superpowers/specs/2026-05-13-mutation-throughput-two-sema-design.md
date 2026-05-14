# Mutation-Throughput Two-Semaphore Redesign

**Author:** evovalya25 / Claude collaboration · **Date:** 2026-05-13
**Branch:** `refactor/steady-state-true-jit-refresh` (PR #227)
**Related:** [`2026-05-12-steady-state-engine-audit-and-redesign.md`](2026-05-12-steady-state-engine-audit-and-redesign.md)

## Problem

The steady-state engine today gates the entire mutant pipeline on a single semaphore (`_in_flight_sema`, sized `max_in_flight`). One slot covers the whole journey of one mutant: **parent-refresh → LLM mutation → child-DAG eval → ingest**. When the slot frees (ingestor sees the child DONE), the dispatcher's `acquire()` resumes and spawns the next producer task — which then has to do its own refresh and LLM call before another mutant enters DAG eval.

Observed effect on `run_A2_G.log`: ~30 % of pipeline depth is at any moment in LLM/refresh phases, so DAG capacity sees only ~2/3 of `max_in_flight` in concurrent work, and a freshly-freed DAG slot waits a full LLM round-trip (~30 s) before being refilled. The user's complaint, verbatim:

> as soon as we have free dag slot — create a mutant.

The redesign decouples LLM generation from DAG dispatch so a free DAG slot is filled **instantly** from an already-produced ready mutant, while the LLM pool keeps generating into a buffer up to a backpressure cap.

## Goals

1. A free DAG slot is filled within one event-loop tick from an already-completed LLM result — no LLM round-trip stands between "DAG slot free" and "next mutant queued."
2. The LLM pipeline produces continuously while DAG drains; it only blocks when the buffer is full.
3. Single operator-facing knob (`max_in_flight`, semantics updated). No new configuration cognitive load.
4. Preserve every correctness invariant from today's design: slot-ownership balance, parent-refresh ticket lifetime, cancellation safety, crash-resume rehydration.

## Non-goals

- Splitting parent refresh into its own pipeline stage. Refresh stays inside the producer task, ahead of the LLM call, because the LLM mutation needs fresh parent metrics.
- Dynamic auto-tuning of semaphore sizes based on observed bottleneck. The operator picks `N`; the system uses it symmetrically for both pools.
- Reworking the DAG runner's own concurrency. Parent-refresh DAGs and child-mutant DAGs continue to share the DAG runner gated by its existing concurrency limit.
- Migration tooling for old config files. The field name `max_in_flight` is preserved (semantics updated); old configs continue to load.

## Architecture

Two semaphores, both sized to the same `max_in_flight = N`:

- **`producer_sema = Semaphore(N)`** — caps concurrent (refresh + LLM) tasks. Acquired by the dispatcher before spawning a producer task; released by the producer task once it has persisted the mutant and registered it for ingest (or in `finally` on any failure).
- **`buffer_sema = Semaphore(N)`** — caps "produced but not yet ingested" mutants. Acquired by the producer task **after** the LLM call returns and **before** it registers the mutant in `_in_flight`. Released by the ingestor when the mutant reaches DONE/DISCARDED.

```
dispatcher
  └─ producer_sema.acquire() ──► spawn producer task
                                    │
producer task                        │
  1. select parents                  │
  2. refresh parents (DAG)           │  producer_sema HELD
  3. LLM mutation (Redis-persisted)  │
  4. buffer_sema.acquire()  ◄────────┘  ← blocks here if buffer full
  5. _in_flight.add(new_id); _inflight_tickets[new_id] = ticket   (under _in_flight_lock)
  6. release producer_sema          ──► dispatcher spawns next
                                          producer task immediately

ingestor (on DONE/DISCARDED)
  discard from _in_flight, release buffer_sema   ──► oldest blocked producer
                                                      wakes up, registers
```

**Why this solves the goal:** when a DAG slot frees and the ingestor releases `buffer_sema`, an already-completed LLM result (held in memory by some producer task blocked at step 4) is registered in `_in_flight` within the next event-loop tick. No LLM round-trip stands between DAG-slot-free and DAG-slot-refilled. Meanwhile, every other producer keeps the LLM busy: either still running its mutation, or holding its ready result, blocked on buffer.

**Steady state with `N = 10`:**
- ~10 producer tasks alive (mix of "running LLM" and "holding ready result").
- ~10 buffer slots held (mutants in Redis QUEUED/RUNNING + waiting ingest).
- Total pipeline depth = ~20 mutants in some phase.
- DAG runner always sees work; LLM always runs unless DAG falls fully behind.

## File-Level Changes

All changes contained to `gigaevo/evolution/engine/`:

### `config.py`
- Keep field name `max_in_flight: int`. Rewrite docstring to describe the two-pool semantics:
  > Backpressure cap. Both the producer pool (concurrent LLM/refresh tasks) and the buffer of produced-but-not-yet-ingested mutants are sized to this value. Steady-state pipeline depth ~ 2 × max_in_flight.
- No new field. Old YAML configs continue to load with the new semantics.

### `steady_state.py`
- `__init__` builds two semaphores from the single config value:
  ```python
  self._producer_sema = asyncio.Semaphore(self._ss_config.max_in_flight)
  self._buffer_sema = asyncio.Semaphore(self._ss_config.max_in_flight)
  ```
- Remove `self._in_flight_sema`. `_in_flight` set, `_inflight_tickets` dict, and `_in_flight_lock` keep their roles.
- `_final_ingestion_sweep` releases `buffer_sema` (not `_in_flight_sema`) when draining stranded `_in_flight` entries.

### `dispatcher.py`
- Acquire `engine._producer_sema` (not `_in_flight_sema`).
- Early-stop check (`engine._reached_mutant_cap()` between acquire and spawn) releases `engine._producer_sema`.

### `mutant_task.py` (concentrated rewrite)
```python
async def run_one_mutant(engine, task_id):
    slot_transferred = False
    buffer_held = False
    ticket = None
    new_id = None
    try:
        parents = await engine._select_parents_for_mutation()
        if not parents:
            await asyncio.sleep(engine.config.loop_interval)
            return None

        try:
            ticket = await engine._parent_refresher.refresh_with_ticket(parents)
        except (ValueError, TimeoutError) as exc:
            logger.warning("[mutant_task:{}] Parent refresh failed: {}", task_id, exc)
            return None
        refreshed = ticket.refreshed
        if refreshed:
            engine.metrics.submitted_for_refresh += len(refreshed)

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

        # ─── buffer backpressure ─────────────────────────────────
        await engine._buffer_sema.acquire()
        buffer_held = True
        # ─────────────────────────────────────────────────────────

        async with engine._in_flight_lock:
            engine._in_flight.add(new_id)
            engine._inflight_tickets[new_id] = ticket
        slot_transferred = True
        ticket = None
        engine.metrics.total_mutants += 1
        engine.metrics.mutations_created += 1
        await engine._write_snapshot(total_mutants=engine.metrics.total_mutants)
        return new_id

    finally:
        # producer_sema: always released (no transfer semantics).
        engine._producer_sema.release()
        # buffer_sema: released only if held AND not transferred to ingestor.
        if buffer_held and not slot_transferred:
            engine._buffer_sema.release()
        # ticket: released if not transferred under the lock.
        if ticket is not None:
            ticket.release()
```

### `ingestor.py`
- `poll_and_ingest` releases `engine._buffer_sema` (not `_in_flight_sema`) for handled and leaked IDs.
- Saturation check inside `ingestor_loop` uses `len(engine._in_flight) >= engine._ss_config.max_in_flight`.

## Ownership Invariants

**(I1) `producer_sema` slot — owned by producer task, always released in `finally`.** No transfer semantics. The dispatcher acquires and immediately hands off to the producer task, whose `finally` is the sole release site.

**(I2) `buffer_sema` slot — transfer semantics identical to today's `_in_flight_sema`.**
- Acquired by producer after the LLM call.
- Transferred to the ingestor atomically with `_in_flight.add` under `_in_flight_lock` (and the `slot_transferred = True` flag).
- Released by ingestor on DONE/DISCARDED.
- Released by producer's `finally` only when `buffer_held and not slot_transferred` — the same guarded form used today.

**(I3) Parent-refresh ticket — unchanged.** Transferred atomically with `_in_flight.add` under the lock; released by ingestor at the same moment as buffer_sema; released by producer's `finally` if not transferred.

### Cancellation matrix

| Cancel point | producer_sema | buffer_sema | ticket | persisted in Redis |
|---|---|---|---|---|
| Before refresh | released (finally) | not acquired | not created | none |
| During refresh | released (finally) | not acquired | released (finally) | none |
| During LLM | released (finally) | not acquired | released (finally) | none |
| Blocked at `buffer_sema.acquire()` | released (finally) | not acquired | released (finally) | **orphan** |
| Between acquire and `_in_flight.add` | released (finally) | released (finally) | released (finally) | **orphan** |
| After `_in_flight.add` | released (finally) | held → released by ingestor | held → released by ingestor | tracked, will ingest |

The two "orphan" rows are symmetric to a race that **already exists today** (cancel between `generate_one_mutation` persisting and `_in_flight.add` registering). The new design does not introduce new orphan paths; it only relocates the existing window.

### Final ingestion sweep

`_final_ingestion_sweep` is unchanged structurally; it drains `_in_flight` post-shutdown and now releases `buffer_sema` per drained entry. Producer-side bounding is by dispatcher cancel + each producer task's `finally`.

### Crash-resume

Both semaphores are constructed fresh in `__init__` at their full capacity. Whatever the current code does to reconcile `_in_flight_sema` with rehydrated stranded programs on resume (today: nothing — the semaphore starts at full capacity and `_in_flight` starts empty regardless of stranded programs in Redis) is mirrored verbatim for `buffer_sema`. If the resume contract is later strengthened to rehydrate `_in_flight` from stranded RUNNING programs, the implementation must also acquire `buffer_sema` once per rehydrated entry; this is called out for the plan-writer but is not a behavior change relative to today.

## Testing Strategy

Paranoia-grade per project convention. Five layers:

### Unit tests (per file, deterministic, fast)

In `tests/evolution/`:
- `test_dispatcher_producer_sema.py` — dispatcher acquires `producer_sema` (not `buffer_sema`); early-stop releases `producer_sema`.
- `test_mutant_task_two_sema.py` — every exit path of `run_one_mutant` audited via a parametrized fixture:
  - success → producer released, buffer transferred, ticket transferred
  - exception during refresh → producer released, buffer never acquired, ticket released
  - exception during LLM → producer released, buffer never acquired, ticket released
  - cancel blocked at `buffer_sema.acquire()` → producer released, buffer not held, ticket released
  - cancel between acquire and `_in_flight.add` → producer released, **buffer released**, ticket released
  - cancel after `_in_flight.add` → producer released, buffer **held** (ingestor will release), ticket transferred
- `test_ingestor_releases_buffer.py` — DONE/DISCARDED handling releases `buffer_sema`, not `producer_sema`.

### Invariant tests (slot accounting under load)

- `test_engine_no_slot_leak.py` — run 200 mutants with `N = 5`, randomize per-task latencies, after shutdown assert both semaphores' available count == `N` (no leak across paths).
- `test_engine_cancel_chaos.py` — same load, but randomly cancel ~10 % of producer tasks at each checkpoint; final accounting must still balance.

### Concurrency / observable-behavior tests (the property the redesign exists to deliver)

- `test_producer_continues_during_dag_drain.py` — gate the DAG runner to drain slowly; verify producers continue generating into the buffer up to `N`, then block on `buffer_sema` (not on DAG completion).
- `test_dag_pulls_instantly_when_slot_frees.py` — pre-fill buffer with `N` ready mutants; free one DAG slot; assert next mutant enters DAG within one event-loop tick (no LLM round-trip wall time).

### Resume / shutdown

- `test_engine_resume_two_sema.py` — crash mid-run after `K < N` mutants registered, restart engine, assert `_in_flight` rehydrates from stranded programs and both semaphores re-initialize at correct counts (producer at full `N`, buffer at `N − len(_in_flight)`).
- Update existing `test_engine_ghost_persist.py` for the new sema names.

### Integration (real Redis)

- One end-to-end test in `tests/integration/` that runs `N = 3`, 30 mutants, real Redis DB (test DB 15), verifies pipeline drains cleanly and `_in_flight` is empty on stop.

All run via `/run-tests tests/evolution/` plus the integration test path. No full-suite hangs; no bare pytest.

## Risk Register

| Risk | Mitigation |
|---|---|
| Producer holds `buffer_sema` waiting indefinitely (e.g. ingestor wedged) | `buffer_sema.acquire()` has no timeout, matching today's `_in_flight_sema`. Ingestor wedge is already a class-1 fault; `_await_idle` ghost-check sweep continues to apply. |
| Buffer-acquire cancellation leaks the persisted (orphan) mutant in Redis | Symmetric to today's existing race; not a regression. Future work could add an ingestor-side scavenger for orphan DONE programs; out of scope here. |
| Parent-refresh DAGs starve child-mutant DAGs under buffer-full pressure | Unchanged from today. The DAG runner's own concurrency continues to gate both. |
| Operator confusion: `max_in_flight = 10` now means up to 20 in-flight mutants | Docstring rewrite in `config.py` makes the two-pool semantics explicit. Logged at engine startup: `[SteadyState] Start | producer_sema=N buffer_sema=N`. |

## Out of Scope

- Splitting refresh into its own pipeline stage.
- Per-pool independent sizing (two-knob config). Could be added later if asymmetric tuning becomes important.
- Replacing the DAG runner's concurrency limit.
- Telemetry on buffer occupancy. (Easy follow-up if profiling shows it useful.)
