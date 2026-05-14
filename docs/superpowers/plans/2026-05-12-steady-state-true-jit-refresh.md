# Steady-state engine — true JIT-refresh refactor

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the epoch-driven steady-state engine with a true continuous async stream of mutation tasks that refresh only their selected parents on the spot, governed by a single `total_mutants` counter and a `max_in_flight` semaphore.

**Architecture:** A long-lived **dispatcher** coroutine acquires `max_in_flight` slots and spawns **per-mutant tasks** (`pick parents → JIT-refresh those parents → produce mutant → register in `in_flight``). A long-lived **ingestor** coroutine polls in-flight programs in batch and accept/rejects each as it reaches DONE. The 935-LOC `steady_state.py` is split into `engine.py`, `dispatcher.py`, `mutant_task.py`, `ingestor.py`, `refresh.py`. The generational `EvolutionEngine.step()` and its `run()` loop are deleted; `EvolutionEngine` shrinks to an abstract base of shared concerns (snapshot, metrics, idle wait, stop context, hooks). `MaxGenerationsStopper` becomes `MaxMutantsStopper` with a deprecated alias for one release. `EngineSnapshot.refresh_pass` and the multi-pass / bucketed refresh code path are removed (the cross-program tracker race they closed is structurally eliminated by sequential per-producer parent refresh).

**Tech Stack:** Python 3.11+, asyncio, Pydantic, Redis (`fakeredis` for unit tests), Hydra configs, pytest. Branch: `refactor/steady-state-true-jit-refresh` (head: `cb134230`).

**Spec:** `docs/superpowers/specs/2026-05-12-steady-state-engine-audit-and-redesign.md`.

**Conventions:**
- Always use `rtk git` instead of `git`.
- Always run tests via the `/run-tests` skill, never `pytest tests/`.
- Python env: `/home/jovyan/.mlspace/envs/evo/bin/python3`.
- Linting: `/home/jovyan/.mlspace/envs/evo/bin/ruff check . && /home/jovyan/.mlspace/envs/evo/bin/ruff format --check .` from repo root.
- Lint must pass after every commit. Run `ruff format` (without `--check`) to autofix style; fix lint errors manually before committing.
- Use force-add for files under `docs/superpowers/` (the directory is `.gitignore`'d but tracked-by-exception).
- After every commit: send a one-line Telegram notification via `tools.telegram_notify.notify("<msg>")` to mark the milestone.

**Out of scope (deferred to follow-ups):**
- Renaming `SteadyStateEvolutionEngine → EvolutionEngine`.
- `gigaevo/programs/stages/optimization/cma.py` (uses its own `max_generations`; unrelated).
- Watchdog/alerts/manifest `max_generations` contract field (display-only budget, not an engine counter).
- Cross-experiment integration smoke tests beyond `tests/evolution/test_steady_state.py`.

---

## File Structure

### Files to create
| Path | Responsibility | Approx LOC |
|---|---|---|
| `gigaevo/evolution/engine/refresh.py` | `_refresh_parents(parents)` helper + per-parent lock registry. The only post-seed DONE→QUEUED path. | ~120 |
| `gigaevo/evolution/engine/mutant_task.py` | `run_one_mutant(engine)` async function: select parents → refresh → mutate → register-or-release. One task per mutant, runs to completion independently. | ~120 |
| `gigaevo/evolution/engine/dispatcher.py` | `dispatcher_loop(engine)`: while running, `acquire()` semaphore, `create_task(run_one_mutant)`, loop. Spawn-and-forget. | ~80 |
| `gigaevo/evolution/engine/ingestor.py` | `ingestor_loop(engine)` + `_poll_and_ingest`, `_ingest_batch`, accept/reject/notify. | ~200 |
| `tests/evolution/test_refresh_parents.py` | Unit tests for `_refresh_parents` (single parent, multi-parent, concurrent-overlap, failure). | n/a |
| `tests/evolution/test_dispatcher.py` | Unit tests for dispatcher (semaphore backpressure, spawn-and-forget, shutdown). | n/a |
| `tests/evolution/test_mutant_task.py` | Unit tests for per-mutant task (success/None/error/cancel). | n/a |
| `tests/evolution/test_ingestor.py` | Unit tests for ingestor poll/ingest path. | n/a |
| `tests/evolution/test_jit_refresh_e2e.py` | End-to-end: select-parent → JIT-refresh → produce-mutant → ingest without an epoch barrier. | n/a |
| `config/stopper/max_mutants.yaml` | Hydra group entry for `MaxMutantsStopper`. | n/a |

### Files to modify
| Path | Change |
|---|---|
| `gigaevo/evolution/engine/snapshot.py` | Remove `refresh_pass` field. Rename `total_generations` → `total_mutants`. |
| `gigaevo/evolution/engine/metrics.py` | Rename `total_generations` → `total_mutants`. |
| `gigaevo/evolution/engine/stopper.py` | Rename `StopContext.total_generations` → `total_mutants`. Rename `MaxGenerationsStopper` → `MaxMutantsStopper` (constructor `max_mutants`). **Delete** the old class; no alias (semantic shift would silently change run length ~8×). Wire `best_fitness` via `_metrics_tracker.get_best_fitness()` in `_build_stop_context` (fixes the `FitnessPlateauStopper` dead-code TODO). |
| `gigaevo/evolution/engine/config.py` | Drop `refresh_passes`, `refresh_order`, `epoch_trigger_count` property. Move `SteadyStateEngineConfig` knobs (`max_in_flight`) up into a single `EngineConfig`; remove `SteadyStateEngineConfig` subclass entirely. Update `generation_timeout` deprecation note. |
| `gigaevo/evolution/engine/__init__.py` | Drop `SteadyStateEngineConfig` export. Add `MaxMutantsStopper`. **Remove** `MaxGenerationsStopper` from exports — class is deleted. |
| `gigaevo/evolution/engine/core.py` | Strip generational `step()` and generational `run()` loop. Keep `EvolutionEngine` as abstract-ish base with shared helpers: `_await_idle`, `_select_elites_for_mutation`, `_notify_hook`, `_build_stop_context`, `_write_snapshot`, `_load_snapshot_on_resume`, `restore_state`, `_has_active_dags`, `start`, `stop`, `pause`, `resume`. Move construction (in-flight set, semaphore, parent-lock registry) here. |
| `gigaevo/evolution/engine/steady_state.py` | Reduce to a thin shim that wires `dispatcher_loop` + `ingestor_loop` from the new modules into `run()`. ~150 LOC. Delete: `_mutation_gate`, `_draining`, `_processed_since_epoch`, `_epoch_mutants`, `_epoch_eligible_since`, `_EPOCH_WATERMARK_FALLBACK_S`, `_should_trigger_epoch`, `_epoch_refresh`, `_drain_in_flight`, `_drain_scoped`, `_cached_elites`, `_elite_cache_lock`, `_get_cached_elites`, `_produce_one_mutant` (moved to `mutant_task.py`), `_poll_and_ingest`, `_ingest_batch` (moved to `ingestor.py`), `_refresh_archive_programs` overrides (`fifo` + `generation_bucketed` + multi-pass). |
| `gigaevo/adversarial/shared_benchmark_lineage.py` | Remove `compute_hash` override (snapshot no longer has `refresh_pass`); inherit base `LineageStage.compute_hash`. Update docstring. |
| `gigaevo/prompts/coevolution/sync.py` | `MainRunSyncHook._get_min_gen`: read `snap.programs_processed` instead of `snap.total_generations` (rename method to `_get_min_processed`, update internal `_last_main_*` field; log strings updated). |
| `gigaevo/monitoring/redis_queries.py` | `get_generation` → return `snap.programs_processed` (snapshot has no `total_generations`); rename to `get_programs_processed`. Update `collect_snapshot` to populate `RunSnapshot.generation` from `programs_processed`. |
| `gigaevo/programs/stages/collector.py` | Set `best_fitness_in_iteration`, `worst_fitness_in_iteration`, `average_fitness_in_iteration`, `valid_rate_in_iteration` to `None` unconditionally (cohort semantics collapse under per-mutant `iteration`). Add a one-line module comment explaining the new semantics. |
| `config/evolution/default.yaml` | Replace `_target_: gigaevo.evolution.engine.EvolutionEngine` with `SteadyStateEvolutionEngine`. Replace `EngineConfig` with `EngineConfig` (now unified; still that class name). Add `max_in_flight: ${max_in_flight}`. Default `evolution=default` now means steady-state. |
| `config/evolution/steady_state.yaml` | Drop `refresh_order` and `refresh_passes` keys. Keep file as a thin alias of `default` for one release (deprecated). |
| `config/stopper/max_generations.yaml` | **Delete** (renamed). |
| `config/stopper/max_generations_or_fitness_plateau.yaml` | **Delete** — replaced by new `max_mutants_or_fitness_plateau.yaml`. |
| `config/stopper/max_mutants.yaml` (new) | `_target_: MaxMutantsStopper`, key on `max_mutants: ${max_mutants}`. |
| `config/stopper/max_mutants_or_fitness_plateau.yaml` (new) | Composite of `MaxMutantsStopper` + `FitnessPlateauStopper`. |
| `config/config.yaml` | Default stopper: `stopper: max_mutants` (was `max_generations`). |
| `config/constants/evolution.yaml` | Replace `max_generations: 100` with `max_mutants: 800` (preserves prior ~800-mutant effective run length). Delete `max_mutations_per_generation: 8` (no longer meaningful — epoch concept is gone). |
| `config/evolution/steady_state.yaml`, `config/evolution/default.yaml` | Drop `max_mutations_per_generation` line. |
| `tests/evolution/test_engine_metrics.py` | Rename references `total_generations` → `total_mutants`. |
| `tests/evolution/test_engine_snapshot.py` | Drop `refresh_pass` assertions; rename `total_generations` → `total_mutants`. |
| `tests/evolution/test_resume.py` | Rename `total_generations` → `total_mutants`; update `MaxGenerationsStopper` to `MaxMutantsStopper`. |
| `tests/evolution/test_resume_e2e.py` | Same renames as `test_resume.py`. |
| `tests/evolution/test_evolution_engine.py` | Rewrite generational `step()` tests to drive the steady-state loop end-to-end (or mark and replace with `tests/evolution/test_jit_refresh_e2e.py`). Rename counter references. |
| `tests/evolution/test_steady_state.py` | Remove tests of `_epoch_refresh`, `_drain_*`, `_mutation_gate`, `_cached_elites`, `_should_trigger_epoch`, bucketed/multi-pass refresh. Replace with JIT-refresh tests. |
| `tests/evolution/test_steady_state_benchmark.py` | Update counter references and drop epoch-specific assertions. |
| `tests/evolution/test_steady_state_determinism.py` | Same as above. |
| `tests/evolution/test_snapshot_refresh_pass.py` | Delete (refresh_pass mechanism is gone). |
| `tests/evolution/test_stopper.py` | Add `MaxMutantsStopper` tests. Delete or replace any `MaxGenerationsStopper` tests (the class is gone). Add a negative test asserting `MaxGenerationsStopper` no longer exists in the module. |
| `tests/evolution/test_generation_boundary_emit.py` | Drop (generational `step()` is gone; no emission site). |
| `tests/evolution/test_evolution_metrics_pipeline.py` | Rename counter references. |
| `tests/memory/test_ideas_tracker_pipeline.py` | Replace `MaxGenerationsStopper(max_generations=N)` with `MaxMutantsStopper(max_mutants=N)` at every call site. Assertions guard on `post_run_hook` ran ≥1, not on counter value — so the numeric shift is harmless here. |
| `tests/monitoring/test_redis_queries.py` | Rename `write_engine_snapshot_sync(..., total_generations=5)` → `total_mutants=5`. |
| `tests/adversarial_pipeline/test_lineage_cache_invalidation.py` | Delete (refresh_pass cache-key mechanism is gone). |
| `tests/adversarial_pipeline/test_shared_benchmark_lineage.py` | Delete the three `refresh_pass`-keyed cache-invalidation tests (named in the test body); keep the rest. |
| `tests/adversarial_pipeline/test_two_pass_mutation_context.py` | Delete (multi-pass refresh is gone). |
| `tests/adversarial_pipeline/test_steady_state_adversarial_e2e.py` | Update counter references; remove epoch-refresh assertions. |
| `gigaevo/monitoring/events.py` | Keep `GenerationBoundary` class for back-compat (no subscriber depends on emission; `log_audit.py` only counts it). Delete `_emit_event(GenerationBoundary(...))` call sites with `core.py:283`. |

---

## Task list

> Each task is its own commit. Mark every step with `[x]` as it completes. The phases are ordered so the tree compiles and tests pass at every commit boundary (renames first, behavioural changes after, deletions last).

---

### Task 1: Pin baseline test status

**Files:** none (verification only)

- [ ] **Step 1.1: Confirm branch and head**

Run:
```bash
rtk git rev-parse --abbrev-ref HEAD
rtk git log --oneline -2
```

Expected: branch `refactor/steady-state-true-jit-refresh`, head `cb134230`.

- [ ] **Step 1.2: Pin engine baseline**

Run `/run-tests tests/evolution/test_engine_metrics.py tests/evolution/test_engine_snapshot.py tests/evolution/test_stopper.py tests/evolution/test_resume.py`. Record pass/fail counts so later regressions are attributable.

Expected: all currently pass on `cb134230`. Note any unexpected failures and stop — investigate before proceeding.

- [ ] **Step 1.3: Pin adversarial baseline**

Run `/run-tests tests/adversarial_pipeline/test_lineage_cache_invalidation.py tests/adversarial_pipeline/test_shared_benchmark_lineage.py tests/adversarial_pipeline/test_two_pass_mutation_context.py`. Record pass/fail counts.

- [ ] **Step 1.4: Pin ruff baseline**

Run `/home/jovyan/.mlspace/envs/evo/bin/ruff check . && /home/jovyan/.mlspace/envs/evo/bin/ruff format --check .` from repo root.

Expected: clean. If not clean, stop — fix pre-existing lint before refactoring.

(No commit for this task — it's a verification gate.)

---

### Task 2: Rename `EngineMetrics.total_generations` → `total_mutants`

**Files:**
- Modify: `gigaevo/evolution/engine/metrics.py:9-11`
- Modify: `tests/evolution/test_engine_metrics.py` (all references)

- [ ] **Step 2.1: Write the failing test**

Add to `tests/evolution/test_engine_metrics.py`:

```python
def test_total_mutants_replaces_total_generations():
    """Engine progress counter is named total_mutants, not total_generations."""
    m = EngineMetrics()
    assert m.total_mutants == 0
    assert not hasattr(m, "total_generations")
```

- [ ] **Step 2.2: Run test to verify it fails**

Run `/run-tests tests/evolution/test_engine_metrics.py::test_total_mutants_replaces_total_generations`.

Expected: FAIL (attribute does not exist).

- [ ] **Step 2.3: Implement the rename**

In `gigaevo/evolution/engine/metrics.py:9-11`, replace:

```python
    total_generations: int = Field(
        default=0, description="Total number of generations run"
    )
```

with:

```python
    total_mutants: int = Field(
        default=0,
        description=(
            "Total number of mutants produced (incremented once per "
            "successful generate_mutations call, before DAG evaluation). "
            "Monotone, single source of truth for engine progress."
        ),
    )
```

- [ ] **Step 2.4: Update all callers in `tests/evolution/test_engine_metrics.py`**

Replace every occurrence of `total_generations` with `total_mutants` in that test file. Keep the assertion at line 138 (`m.total_generations += 1`) — rename it to `m.total_mutants += 1`.

- [ ] **Step 2.5: Run all engine-metrics tests**

Run `/run-tests tests/evolution/test_engine_metrics.py -v`.

Expected: all pass.

- [ ] **Step 2.6: Commit**

```bash
rtk git add gigaevo/evolution/engine/metrics.py tests/evolution/test_engine_metrics.py
rtk git commit -m "refactor(engine): rename EngineMetrics.total_generations → total_mutants

Single counter for engine progress. See spec §3.5."
```

Then send a Telegram notification:
```bash
/home/jovyan/.mlspace/envs/evo/bin/python3 -c "from tools.telegram_notify import notify; notify('engine refactor: Task 2 — total_mutants rename committed')"
```

---

### Task 3: Rename `EngineSnapshot.total_generations` → `total_mutants` and drop `refresh_pass`

**Files:**
- Modify: `gigaevo/evolution/engine/snapshot.py:29-36`
- Modify: `tests/evolution/test_engine_snapshot.py`

- [ ] **Step 3.1: Write the failing test**

Replace the body of `tests/evolution/test_engine_snapshot.py::test_default_snapshot_fields_are_zero_or_none` with:

```python
def test_default_snapshot_fields_are_zero_or_none():
    snap = EngineSnapshot()
    assert snap.total_mutants == 0
    assert snap.programs_processed == 0
    assert snap.completion_reason is None
    assert snap.version == 0
    assert not hasattr(snap, "total_generations")
    assert not hasattr(snap, "refresh_pass")
```

- [ ] **Step 3.2: Run to verify FAIL**

Run `/run-tests tests/evolution/test_engine_snapshot.py::test_default_snapshot_fields_are_zero_or_none`.

Expected: FAIL (`total_mutants` not present; `total_generations` still present).

- [ ] **Step 3.3: Implement the snapshot change**

In `gigaevo/evolution/engine/snapshot.py:29-36`, replace the class body:

```python
class EngineSnapshot(BaseModel):
    total_mutants: int = 0
    programs_processed: int = 0
    completion_reason: str | None = None
    version: int = 0

    model_config = ConfigDict(frozen=True, extra="forbid")
```

(Removed `total_generations` and `refresh_pass` fields.)

- [ ] **Step 3.4: Update the rest of `test_engine_snapshot.py`**

In `tests/evolution/test_engine_snapshot.py`:
- `test_load_engine_snapshot_round_trips_json`: replace `total_generations=7, refresh_pass=2` with `total_mutants=7`. Drop the `refresh_pass` assertion.
- `test_write_snapshot_merges_updates_and_bumps_version`: replace `total_generations` with `total_mutants`. Replace `await engine_with_storage._write_snapshot(refresh_pass=1)` with `await engine_with_storage._write_snapshot(programs_processed=42)`; assert `programs_processed == 42` and `total_mutants == 3` is preserved.
- `test_write_snapshot_persists_to_redis`: replace `total_generations=7` with `total_mutants=7`.
- `test_write_snapshot_with_no_updates_still_bumps_version`: replace `total_generations == 0` with `total_mutants == 0`. Drop the `refresh_pass == 0` line.
- `test_load_snapshot_on_resume_hydrates_from_redis`: replace `total_generations=5` with `total_mutants=5`.

- [ ] **Step 3.5: Run snapshot tests**

Run `/run-tests tests/evolution/test_engine_snapshot.py -v`.

Expected: all pass.

- [ ] **Step 3.6: Commit**

```bash
rtk git add gigaevo/evolution/engine/snapshot.py tests/evolution/test_engine_snapshot.py
rtk git commit -m "refactor(engine): rename EngineSnapshot.total_generations → total_mutants, drop refresh_pass

JIT-refresh has no global refresh-pass concept. See spec §3.3, §3.5."
```

Then `notify('engine refactor: Task 3 — snapshot rename + refresh_pass drop committed')`.

---

### Task 4: Drop `compute_hash` override on `SharedBenchmarkFilteredLineageStage`

**Files:**
- Modify: `gigaevo/adversarial/shared_benchmark_lineage.py:86-99, 70-83` (docstring)
- Delete: `tests/adversarial_pipeline/test_lineage_cache_invalidation.py`
- Modify: `tests/adversarial_pipeline/test_shared_benchmark_lineage.py` (drop the three refresh-pass tests)

- [ ] **Step 4.1: Write the failing test**

Append to `tests/adversarial_pipeline/test_shared_benchmark_lineage.py`:

```python
def test_compute_hash_inherits_base_after_refresh_pass_removal():
    """SharedBenchmarkFilteredLineageStage no longer suffixes refresh_pass."""
    from gigaevo.adversarial.shared_benchmark_lineage import (
        SharedBenchmarkFilteredLineageStage,
    )
    from gigaevo.programs.stages.insights_lineage import LineageStage

    assert (
        SharedBenchmarkFilteredLineageStage.compute_hash.__qualname__.startswith(
            "LineageStage."
        )
        or "compute_hash" not in SharedBenchmarkFilteredLineageStage.__dict__
    )
```

- [ ] **Step 4.2: Run to verify FAIL**

Run `/run-tests tests/adversarial_pipeline/test_shared_benchmark_lineage.py::test_compute_hash_inherits_base_after_refresh_pass_removal`.

Expected: FAIL (subclass still overrides `compute_hash`).

- [ ] **Step 4.3: Implement the change**

In `gigaevo/adversarial/shared_benchmark_lineage.py`:

1. Delete the entire `@classmethod compute_hash` method (lines 86–99).
2. Remove the `from gigaevo.evolution.engine.snapshot import get_current_snapshot` import (line 49).
3. Rewrite the "Cache invariant" docstring section (lines 70–84) to:

```
    Cache invariant
    ---------------
    Inherits ``compute_hash`` from :class:`LineageStage`. Cross-program
    tracker freshness is provided by the engine's JIT parent-refresh
    contract: a child's LineageStage runs only after every selected parent
    has finished its DGTrackerStage write, eliminating the cross-program
    race that the prior ``refresh_pass`` cache-key suffix existed to
    paper over.
```

- [ ] **Step 4.4: Delete the now-irrelevant test files**

```bash
rtk git rm tests/adversarial_pipeline/test_lineage_cache_invalidation.py
rtk git rm tests/adversarial_pipeline/test_two_pass_mutation_context.py
```

- [ ] **Step 4.5: Remove `refresh_pass`-suffix tests from `test_shared_benchmark_lineage.py`**

Delete the three test functions in `tests/adversarial_pipeline/test_shared_benchmark_lineage.py` whose bodies reference `set_current_snapshot(EngineSnapshot(refresh_pass=...))` or `_refresh_pass_token` (search the file for `refresh_pass` and remove each containing `def test_*` function in full). Also remove the unused `set_current_snapshot` / `EngineSnapshot` imports if they become orphaned.

- [ ] **Step 4.6: Run the affected tests**

Run `/run-tests tests/adversarial_pipeline/test_shared_benchmark_lineage.py -v`.

Expected: all remaining tests pass, including the new `test_compute_hash_inherits_base_after_refresh_pass_removal`.

- [ ] **Step 4.7: Commit**

```bash
rtk git add gigaevo/adversarial/shared_benchmark_lineage.py tests/adversarial_pipeline/
rtk git commit -m "refactor(adversarial): drop refresh_pass cache-key suffix on SharedBenchmarkFilteredLineageStage

Cross-program tracker race is structurally eliminated by per-producer JIT
parent refresh. See spec §3.3 + §6.2."
```

Then `notify('engine refactor: Task 4 — refresh_pass cache-key dropped')`.

---

### Task 5: Migrate `MainRunSyncHook` to `programs_processed`

**Files:**
- Modify: `gigaevo/prompts/coevolution/sync.py:22-127`

- [ ] **Step 5.1: Write the failing test**

Create `tests/prompts/test_coevolution_sync.py` (or extend existing test if present):

```python
from __future__ import annotations

import json

import pytest
from redis import asyncio as aioredis

from gigaevo.evolution.engine.snapshot import ENGINE_SNAPSHOT_KEY, EngineSnapshot
from gigaevo.prompts.coevolution.sync import MainRunSyncHook


@pytest.mark.asyncio
async def test_main_run_sync_hook_reads_programs_processed(fakeredis_url_factory):
    """Hook polls programs_processed (not total_mutants, not the removed total_generations)."""
    redis_url = fakeredis_url_factory(db=5)
    # Seed two snapshots with different programs_processed values
    r = aioredis.from_url(redis_url, decode_responses=True)
    payload = EngineSnapshot(total_mutants=999, programs_processed=12).model_dump_json()
    await r.hset("main:run_state", ENGINE_SNAPSHOT_KEY, payload)
    await r.close()

    hook = MainRunSyncHook(
        host="localhost", port=6379, db=5, prefix="main", timeout=1.0
    )
    hook._last_main_progress = 0  # new attribute name
    min_seen = await hook._get_min_progress()
    assert min_seen == 12
```

(If a `fakeredis_url_factory` fixture is not available, use `fakeredis.aioredis.FakeRedis` directly.)

- [ ] **Step 5.2: Run to verify FAIL**

Run `/run-tests tests/prompts/test_coevolution_sync.py::test_main_run_sync_hook_reads_programs_processed`.

Expected: FAIL (`_get_min_progress` and `_last_main_progress` do not exist; existing method reads `total_generations`).

- [ ] **Step 5.3: Implement the change**

In `gigaevo/prompts/coevolution/sync.py`:

1. Rename `self._last_main_gen` → `self._last_main_progress` (init to `-1`).
2. Rename method `_get_min_gen` → `_get_min_progress`.
3. Inside the renamed method, replace `gens.append(snap.total_generations)` with `gens.append(snap.programs_processed)`.
4. Update every log string referring to "gen" / "generation" in the file to "progress" / "programs_processed" for consistency (`"Main runs advanced to gen {} ..."` → `"Main runs advanced to programs_processed={} ..."`, etc.).
5. Update the `__call__` body to use the renamed identifiers.
6. Update the module docstring (top of file) to reflect "blocks until main run(s) advance by at least one *processed program*" instead of "by at least one generation".

- [ ] **Step 5.4: Run tests**

Run `/run-tests tests/prompts/test_coevolution_sync.py -v` plus any neighbouring tests under `tests/prompts/`.

Expected: pass.

- [ ] **Step 5.5: Commit**

```bash
rtk git add gigaevo/prompts/coevolution/sync.py tests/prompts/test_coevolution_sync.py
rtk git commit -m "refactor(prompts): MainRunSyncHook polls programs_processed not total_generations

Engine snapshot no longer has total_generations; programs_processed is the
correct cross-run progress key (already used by ProgressBasedSyncHook)."
```

Then `notify('engine refactor: Task 5 — prompt sync hook migrated to programs_processed')`.

---

### Task 6: Migrate `monitoring/redis_queries.py` reader

**Files:**
- Modify: `gigaevo/monitoring/redis_queries.py:118-129, 250-310`
- Modify: `tests/monitoring/test_redis_queries.py:202`

- [ ] **Step 6.1: Write the failing test**

In `tests/monitoring/test_redis_queries.py`, add:

```python
def test_get_programs_processed_reads_snapshot_field(fakeredis):
    """get_programs_processed returns snap.programs_processed (replaces get_generation)."""
    from gigaevo.monitoring.redis_queries import get_programs_processed
    from gigaevo.evolution.engine.snapshot import EngineSnapshot

    payload = EngineSnapshot(total_mutants=42, programs_processed=17).model_dump_json()
    fakeredis.hset(f"{PREFIX}:run_state", "engine:snapshot", payload)

    assert get_programs_processed(fakeredis, PREFIX) == 17
```

(`PREFIX` and `fakeredis` are existing test fixtures — check the file's top for their definitions.)

- [ ] **Step 6.2: Run to verify FAIL**

Run `/run-tests tests/monitoring/test_redis_queries.py::test_get_programs_processed_reads_snapshot_field`.

Expected: FAIL (`get_programs_processed` does not exist).

- [ ] **Step 6.3: Implement the change**

In `gigaevo/monitoring/redis_queries.py`:

1. Replace `get_generation` (lines 118-129) with:

```python
def get_programs_processed(r: redis_lib.Redis, prefix: str) -> int | None:
    """Get the engine's programs_processed counter from the snapshot.

    This is the CANONICAL source of run progress. Returns ``None`` when the
    snapshot is absent or its JSON is corrupt — callers downstream
    distinguish "no data yet" from "zero processed".
    """
    snap = _read_engine_snapshot(r, prefix)
    if snap is None:
        return None
    return snap.programs_processed
```

2. In `collect_snapshot` (lines 250-310), replace:

```python
        gen = snap.total_generations if snap is not None else None
```

with:

```python
        gen = snap.programs_processed if snap is not None else None
```

(Keep the local name `gen` and the `RunSnapshot.generation=` keyword on line 294 — the field is still named `generation` for display compatibility but is now populated from `programs_processed`. Add a comment above the assignment: `# RunSnapshot.generation is populated from programs_processed under JIT engine`.)

3. Update test fixture `tests/monitoring/test_redis_queries.py:202` to use `total_mutants=5` and add `programs_processed=5` so `collect_snapshot` test still has a non-None generation field.

- [ ] **Step 6.4: Update any local helper `write_engine_snapshot_sync`**

In `tests/monitoring/test_redis_queries.py`, find the helper that writes the snapshot fixture (search for `write_engine_snapshot_sync`). Update its signature: replace the `total_generations=` parameter with `total_mutants=` and add `programs_processed=`. Update all call sites in the file.

- [ ] **Step 6.5: Run tests**

Run `/run-tests tests/monitoring/test_redis_queries.py -v`.

Expected: pass.

- [ ] **Step 6.6: Commit**

```bash
rtk git add gigaevo/monitoring/redis_queries.py tests/monitoring/test_redis_queries.py
rtk git commit -m "refactor(monitoring): redis_queries.get_programs_processed replaces get_generation

Engine snapshot field renamed; RunSnapshot.generation is now populated from
programs_processed for display compatibility."
```

Then `notify('engine refactor: Task 6 — monitoring redis_queries migrated')`.

---

### Task 7: Replace `MaxGenerationsStopper` with `MaxMutantsStopper` (hard rename, no alias)

**Files:**
- Modify: `gigaevo/evolution/engine/stopper.py`
- Modify: `gigaevo/evolution/engine/__init__.py:8-16`
- Modify: `tests/evolution/test_stopper.py`
- Modify: `gigaevo/utils/metrics_tracker.py` (add `get_best_fitness()` if missing)

**Why no alias** (user decision, 2026-05-12): the old `MaxGenerationsStopper(max_generations=N)` counted **epochs** in steady-state today, where one epoch produces `max_mutations_per_generation` (=8 default) mutants. The new `MaxMutantsStopper(max_mutants=N)` counts **individual mutants**. Same name, ~8× different run length — a silent footgun. Better to fail loudly at config load time and force every caller to choose its new budget explicitly.

- [ ] **Step 7.1: Write the failing test**

In `tests/evolution/test_stopper.py`, add:

```python
def test_max_mutants_stopper_fires_at_threshold():
    from gigaevo.evolution.engine.stopper import (
        MaxMutantsStopper,
        StopContext,
    )

    stopper = MaxMutantsStopper(max_mutants=10)
    assert not stopper.should_stop(StopContext(total_mutants=9)).stop
    decision = stopper.should_stop(StopContext(total_mutants=10))
    assert decision.stop is True
    assert "max_mutants=10" in decision.reason


def test_max_generations_stopper_is_gone():
    """MaxGenerationsStopper is intentionally deleted — semantic shift forced explicit migration."""
    import gigaevo.evolution.engine.stopper as stopper_mod
    assert not hasattr(stopper_mod, "MaxGenerationsStopper")
```

- [ ] **Step 7.2: Run to verify FAIL**

Run `/run-tests tests/evolution/test_stopper.py::test_max_mutants_stopper_fires_at_threshold`.

Expected: FAIL (`MaxMutantsStopper` doesn't exist; `StopContext.total_mutants` doesn't exist).

- [ ] **Step 7.3: Implement the change**

In `gigaevo/evolution/engine/stopper.py`:

1. Rename `StopContext.total_generations` → `total_mutants` (line 15).
2. Rename `MaxGenerationsStopper` → `MaxMutantsStopper`. Its constructor takes `max_mutants`, attribute `self.max_mutants`. `should_stop` reads `ctx.total_mutants` and the reason string becomes `f"Reached max_mutants={self.max_mutants}"`.
3. **Delete** the old `MaxGenerationsStopper` class entirely. Do NOT add a back-compat alias — the semantic shift makes silent reuse dangerous.
4. Wire `best_fitness` into `StopContext` in `EvolutionEngine._build_stop_context` (line 702-712 of `core.py`) by calling a new method on `_metrics_tracker` — if such a method does not exist, add `MetricsTracker.get_best_fitness() -> float | None` in `gigaevo/utils/metrics_tracker.py` returning the best frontier value for the primary metric (or `None` if unknown). The change is small and unblocks `FitnessPlateauStopper` (spec §6.3). If wiring proves invasive (>30 LOC), defer to a follow-up task and just leave a TODO.
5. Update `FitnessPlateauStopper`'s TODO comment (line 59-63) to either point at the new wiring or note it remains pending.

- [ ] **Step 7.4: Update `__init__.py` exports**

In `gigaevo/evolution/engine/__init__.py`, replace `MaxGenerationsStopper` with `MaxMutantsStopper` in the import list. Remove the old name from `__all__` if present.

- [ ] **Step 7.5: Run tests**

Run `/run-tests tests/evolution/test_stopper.py -v`.

Expected: new tests pass. Any old test that imported `MaxGenerationsStopper` should be updated to `MaxMutantsStopper` (or deleted if redundant) in the same commit — this is part of Task 8's propagation.

- [ ] **Step 7.6: Commit**

(Folded into the Task 2+3+7+8 merged commit — see Task 8.)

Then `notify('engine refactor: Task 7 — MaxMutantsStopper replaces MaxGenerationsStopper, no alias')`.

---

### Task 8: Propagate `total_mutants` rename through `core.py` and `steady_state.py`

**Files:**
- Modify: `gigaevo/evolution/engine/core.py` (lines using `self.metrics.total_generations`, `self._snapshot.total_generations`, `self._run_start_gen`, `_build_stop_context`)
- Modify: `gigaevo/evolution/engine/steady_state.py` (same)
- Modify: `tests/evolution/test_resume.py`, `tests/evolution/test_resume_e2e.py`, `tests/evolution/test_evolution_engine.py`

- [ ] **Step 8.1: Write the failing test**

Pick `tests/evolution/test_resume.py` and add at top of `TestRestore` (or equivalent class):

```python
async def test_restores_total_mutants(self, fakeredis_storage) -> None:
    snap = EngineSnapshot(total_mutants=17)
    await fakeredis_storage.save_run_state(
        ENGINE_SNAPSHOT_KEY, snap.model_dump_json()
    )
    engine = _make_engine(fakeredis_storage)
    assert engine.metrics.total_mutants == 0
    await engine.restore_state()
    assert engine.metrics.total_mutants == 17
```

- [ ] **Step 8.2: Run to verify FAIL**

Run `/run-tests tests/evolution/test_resume.py::TestRestore::test_restores_total_mutants`.

Expected: FAIL.

- [ ] **Step 8.3: Implement the rename in `core.py`**

Replace every occurrence of `self.metrics.total_generations` with `self.metrics.total_mutants` and every `self._snapshot.total_generations` with `self._snapshot.total_mutants`. The grep map: `core.py:180, 220, 281, 283, 289, 337, 387, 397, 407, 437, 447, 462, 474, 496, 579, 601, 609, 688-694, 709`.

In `core.py:281-283`:

```python
        self.metrics.total_mutants += 1   # NOTE: will be deleted with step() in Task 11
        try:
            _emit_event(GenerationBoundary(gen=self.metrics.total_mutants))
```

In `core.py:407`, the `iteration=self.metrics.total_generations` argument to `generate_mutations` stays semantically the same (it's the per-mutant index source for `Program.iteration`) but the variable is now `self.metrics.total_mutants`. Change accordingly.

In `core.py:702-712`, rebuild `StopContext`:

```python
        return StopContext(
            total_mutants=self.metrics.total_mutants,
            elapsed_seconds=elapsed,
            best_fitness=self._metrics_tracker.get_best_fitness(),
            programs_processed=self.metrics.programs_processed,
        )
```

In `core.py:687-696` (`restore_state`):

```python
        self.metrics.total_mutants = self._snapshot.total_mutants
        self.metrics.programs_processed = self._snapshot.programs_processed
        logger.info(
            "[EvolutionEngine] Restored total_mutants={} programs_processed={}",
            self._snapshot.total_mutants,
            self._snapshot.programs_processed,
        )
```

Rename `self._run_start_gen` → `self._run_start_mutants` (lines 84, 180, 1 line in `steady_state.py`). Update log strings to print `mutants=` instead of `gen=`.

- [ ] **Step 8.4: Implement the rename in `steady_state.py`**

Same rename pass. Lines: `steady_state.py:103, 107, 281, 523, 600, 601, 846, 874, 896, 912, 921`. In particular:

- Line 281: `iteration=self.metrics.total_mutants`.
- Line 600-601: replace the increment + `_write_snapshot(total_generations=...)` with `total_mutants=...`.

(Most of these lines belong to code that Task 11 deletes; the rename is interim — that's fine as long as the tree compiles and tests pass at this commit.)

- [ ] **Step 8.5: Rename in tests**

In `tests/evolution/test_resume.py`, `tests/evolution/test_resume_e2e.py`, `tests/evolution/test_evolution_engine.py`, `tests/evolution/test_evolution_engine_complex.py`, `tests/evolution/test_evolution_metrics_pipeline.py`, `tests/evolution/test_ingest_mutation_ids.py`:

Replace every `total_generations` with `total_mutants`. Replace every `MaxGenerationsStopper(N)` with `MaxMutantsStopper(N)` (the alias still works, but switching here exercises the new name).

- [ ] **Step 8.6: Run tests**

Run `/run-tests tests/evolution/test_resume.py tests/evolution/test_evolution_engine.py -v`.

Expected: all rename-affected tests pass. The new `test_restores_total_mutants` passes. The previous `test_restores_total_generations` was already replaced by this rename.

- [ ] **Step 8.7: Commit**

```bash
rtk git add gigaevo/evolution/engine/core.py gigaevo/evolution/engine/steady_state.py tests/evolution/
rtk git commit -m "refactor(engine): propagate total_mutants rename through core + steady_state + tests

Mechanical rename; no behaviour change. Wired best_fitness into StopContext."
```

Then `notify('engine refactor: Task 8 — total_mutants rename propagated')`.

---

### Task 9: Add `_refresh_parents` helper (`gigaevo/evolution/engine/refresh.py`)

**Files:**
- Create: `gigaevo/evolution/engine/refresh.py`
- Create: `tests/evolution/test_refresh_parents.py`

- [ ] **Step 9.1: Write the failing test (single-parent happy path)**

Create `tests/evolution/test_refresh_parents.py`:

```python
from __future__ import annotations

import asyncio

import pytest

from gigaevo.evolution.engine.refresh import ParentRefresher
from gigaevo.evolution.engine.state_for_refresh_test import build_test_refresher
from gigaevo.programs.program import Program
from gigaevo.programs.program_state import ProgramState


@pytest.mark.asyncio
async def test_refresh_single_parent_round_trip(fakeredis_storage):
    """A single DONE parent is flipped to QUEUED and re-awaited to DONE."""
    refresher, parent, fake_dag = build_test_refresher(fakeredis_storage)

    refreshed = await refresher.refresh([parent])

    assert len(refreshed) == 1
    assert refreshed[0].id == parent.id
    assert refreshed[0].state == ProgramState.DONE
    assert fake_dag.evaluations == 1, "Parent must be re-evaluated exactly once"


@pytest.mark.asyncio
async def test_refresh_two_parents_batch(fakeredis_storage):
    """Two parents are flipped together and awaited as a batch."""
    refresher, p1, fake_dag = build_test_refresher(fakeredis_storage)
    p2 = await fake_dag.add_program("p2")

    refreshed = await refresher.refresh([p1, p2])

    refreshed_ids = {p.id for p in refreshed}
    assert refreshed_ids == {p1.id, p2.id}
    assert fake_dag.evaluations == 2


@pytest.mark.asyncio
async def test_refresh_overlapping_parents_serialised(fakeredis_storage):
    """Two concurrent refresh() calls sharing one parent do not double-flip it."""
    refresher, p1, fake_dag = build_test_refresher(fakeredis_storage)
    p2 = await fake_dag.add_program("p2")
    p3 = await fake_dag.add_program("p3")

    # Call A refreshes {p1, p2}; Call B refreshes {p1, p3} concurrently.
    a, b = await asyncio.gather(refresher.refresh([p1, p2]), refresher.refresh([p1, p3]))

    a_ids = {p.id for p in a}
    b_ids = {p.id for p in b}
    assert p1.id in a_ids and p1.id in b_ids
    # p1 was flipped exactly once across the two concurrent callers
    assert fake_dag.flip_count_for(p1.id) == 1


@pytest.mark.asyncio
async def test_refresh_discarded_parent_raises(fakeredis_storage):
    """A DISCARDED parent passed in raises rather than flipping it."""
    refresher, parent, fake_dag = build_test_refresher(fakeredis_storage)
    await fake_dag.discard(parent.id)

    with pytest.raises(ValueError, match="DISCARDED"):
        await refresher.refresh([parent])
```

Create the test helper `gigaevo/evolution/engine/state_for_refresh_test.py` (a `tests/`-only fixture builder is fine; if you prefer, put it in `tests/evolution/_fake_dag.py` and import locally). It exposes:
- `build_test_refresher(fakeredis_storage) -> tuple[ParentRefresher, Program, FakeDag]`
- `FakeDag.add_program(name) -> Program`
- `FakeDag.discard(pid) -> None`
- `FakeDag.evaluations: int`
- `FakeDag.flip_count_for(pid) -> int`

The fake DAG implements: when a program transitions to QUEUED, schedule an async task that flips it back to DONE after one event-loop tick, incrementing `evaluations` and `flip_count_for[pid]`.

- [ ] **Step 9.2: Run to verify FAIL**

Run `/run-tests tests/evolution/test_refresh_parents.py -v`.

Expected: FAIL (module `gigaevo.evolution.engine.refresh` does not exist).

- [ ] **Step 9.3: Implement `ParentRefresher`**

Create `gigaevo/evolution/engine/refresh.py`:

```python
"""JIT parent refresh — the only post-seed DONE→QUEUED path under the
steady-state engine.

A producer task selects parents from the archive, then asks the
:class:`ParentRefresher` to:

1. Flip every selected parent from DONE → QUEUED (in one batch transition,
   so no producer sees a half-flipped parent bundle).
2. Wait until every flipped parent is DONE again (re-evaluated by the
   DAG runner).
3. Return the freshly-evaluated :class:`Program` objects.

Concurrent producers that happen to select overlapping parents are
serialised on a per-parent-id :class:`asyncio.Lock` so a parent is never
double-flipped.

Failure semantics: if any parent ends up DISCARDED or vanishes during the
refresh wait, the helper raises :class:`ValueError`; the caller aborts
that mutant (releases its in-flight slot) rather than fall back to stale
state.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable

from loguru import logger

from gigaevo.database.program_storage import ProgramStorage
from gigaevo.programs.program import EXCLUDE_STAGE_RESULTS, Program
from gigaevo.programs.program_state import ProgramState


_REFRESH_POLL_S = 0.25  # tighter than engine loop_interval — refresh is on the critical path


class ParentRefresher:
    """Per-parent-id locked DONE→QUEUED→DONE refresh helper."""

    def __init__(
        self,
        *,
        storage: ProgramStorage,
        poll_interval: float = _REFRESH_POLL_S,
        timeout_seconds: float | None = None,
    ) -> None:
        self._storage = storage
        self._poll_interval = poll_interval
        self._timeout_seconds = timeout_seconds
        self._locks: dict[str, asyncio.Lock] = {}
        self._registry_lock = asyncio.Lock()

    async def refresh(self, parents: list[Program]) -> list[Program]:
        if not parents:
            return []
        # Acquire locks in deterministic order (sorted by id) to avoid deadlock
        # under overlapping concurrent calls.
        ordered = sorted(parents, key=lambda p: p.id)
        locks = [await self._get_lock(p.id) for p in ordered]
        async with _acquire_all(locks):
            return await self._do_refresh(ordered)

    async def _get_lock(self, pid: str) -> asyncio.Lock:
        async with self._registry_lock:
            lock = self._locks.get(pid)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[pid] = lock
            return lock

    async def _do_refresh(self, parents: list[Program]) -> list[Program]:
        # 1. Validate input: any DISCARDED parent should never have been selected.
        for p in parents:
            if p.state == ProgramState.DISCARDED:
                raise ValueError(
                    f"ParentRefresher: parent {p.short_id} is DISCARDED; refusing to flip"
                )

        # 2. Flip DONE→QUEUED in one batch. Idempotent for non-DONE parents.
        done_ids = [p.id for p in parents if p.state == ProgramState.DONE]
        if done_ids:
            await self._storage.batch_transition_by_ids(
                done_ids,
                ProgramState.DONE.value,
                ProgramState.QUEUED.value,
            )

        # 3. Wait until every parent is DONE again.
        return await self._await_done([p.id for p in parents])

    async def _await_done(self, pids: list[str]) -> list[Program]:
        deadline = (
            time.monotonic() + self._timeout_seconds
            if self._timeout_seconds is not None
            else None
        )
        while True:
            programs = await self._storage.mget(pids, exclude=EXCLUDE_STAGE_RESULTS)
            done: list[Program] = []
            still_active = 0
            missing: list[str] = []

            found_ids = {p.id for p in programs if p is not None}
            for pid in pids:
                if pid not in found_ids:
                    missing.append(pid)

            for p in programs:
                if p is None:
                    continue
                if p.state == ProgramState.DONE:
                    done.append(p)
                elif p.state in (ProgramState.QUEUED, ProgramState.RUNNING):
                    still_active += 1
                elif p.state == ProgramState.DISCARDED:
                    raise ValueError(
                        f"ParentRefresher: parent {p.short_id} became DISCARDED during refresh"
                    )

            if missing:
                raise ValueError(
                    f"ParentRefresher: {len(missing)} parents vanished during refresh"
                )

            if still_active == 0 and len(done) == len(pids):
                return done

            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError(
                    f"ParentRefresher: timed out waiting for {still_active} parents"
                )

            await asyncio.sleep(self._poll_interval)


async def _acquire_all(locks: Iterable[asyncio.Lock]):
    """Async context manager that acquires all locks in order and releases on exit."""
    locks = list(locks)
    acquired: list[asyncio.Lock] = []
    try:
        for lk in locks:
            await lk.acquire()
            acquired.append(lk)
        yield None
    finally:
        for lk in reversed(acquired):
            lk.release()


# Convert _acquire_all to a real async context manager
import contextlib  # noqa: E402  (kept at bottom to make the file self-contained)

_acquire_all = contextlib.asynccontextmanager(_acquire_all)  # type: ignore[assignment]


__all__ = ["ParentRefresher"]
```

(Note: the helper file uses `contextlib.asynccontextmanager` to expose `_acquire_all` as an async-with-friendly object. If the linter complains about the bottom-of-file import, hoist it to the top during step 9.5.)

- [ ] **Step 9.4: Implement the test fake DAG**

Create `tests/evolution/_fake_dag.py`:

```python
"""Test-only fake DAG runner: any program flipped to QUEUED is automatically
flipped back to DONE on the next loop iteration. Used to exercise the
:class:`ParentRefresher` without spinning up the real DagRunner.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from gigaevo.evolution.engine.refresh import ParentRefresher
from gigaevo.programs.program import Program
from gigaevo.programs.program_state import ProgramState


class FakeDag:
    def __init__(self, storage):
        self.storage = storage
        self.evaluations = 0
        self._flip_count: dict[str, int] = defaultdict(int)
        self._task: asyncio.Task | None = None

    async def add_program(self, name: str) -> Program:
        prog = Program.minimal(code=f"def {name}(): pass", name=name)
        prog.state = ProgramState.DONE
        await self.storage.add(prog)
        return prog

    async def discard(self, pid: str) -> None:
        await self.storage.batch_transition_by_ids(
            [pid], ProgramState.DONE.value, ProgramState.DISCARDED.value
        )

    def flip_count_for(self, pid: str) -> int:
        return self._flip_count[pid]

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while True:
            queued_ids = await self.storage.get_ids_by_status(
                ProgramState.QUEUED.value
            )
            if queued_ids:
                await self.storage.batch_transition_by_ids(
                    queued_ids,
                    ProgramState.QUEUED.value,
                    ProgramState.DONE.value,
                )
                for pid in queued_ids:
                    self._flip_count[pid] += 1
                    self.evaluations += 1
            await asyncio.sleep(0.01)


def build_test_refresher(storage):
    """Wire a ParentRefresher with a FakeDag against the given storage. Returns (refresher, seed_program, fake_dag)."""
    fake_dag = FakeDag(storage)
    fake_dag.start()

    async def _seed():
        return await fake_dag.add_program("p1")

    seed = asyncio.get_event_loop().run_until_complete(_seed())
    refresher = ParentRefresher(storage=storage)
    return refresher, seed, fake_dag
```

(`Program.minimal()` is a placeholder — use whatever existing factory the tests already use; check `tests/evolution/conftest.py` or `tests/conftest.py` for an existing program factory and use it directly.)

- [ ] **Step 9.5: Run lint, fix the bottom-of-file import**

Run `/home/jovyan/.mlspace/envs/evo/bin/ruff check gigaevo/evolution/engine/refresh.py`.

If `ruff` complains about the late `import contextlib`, hoist it to the top of `refresh.py` and convert `_acquire_all` into a single `@contextlib.asynccontextmanager`-decorated function (one definition, no reassignment).

- [ ] **Step 9.6: Run the refresh-helper tests**

Run `/run-tests tests/evolution/test_refresh_parents.py -v`.

Expected: all four tests pass.

- [ ] **Step 9.7: Commit**

```bash
rtk git add gigaevo/evolution/engine/refresh.py tests/evolution/test_refresh_parents.py tests/evolution/_fake_dag.py
rtk git commit -m "feat(engine): add ParentRefresher — JIT DONE→QUEUED→DONE for selected parents

Per-parent-id locks serialise overlapping concurrent refreshers. All-or-nothing
batch: a DISCARDED or vanished parent aborts the refresh rather than fall back
to stale state. See spec §3.4."
```

Then `notify('engine refactor: Task 9 — ParentRefresher landed')`.

---

### Task 10: Add per-mutant task function (`mutant_task.py`)

**Files:**
- Create: `gigaevo/evolution/engine/mutant_task.py`
- Create: `tests/evolution/test_mutant_task.py`

- [ ] **Step 10.1: Write the failing tests**

Create `tests/evolution/test_mutant_task.py`:

```python
from __future__ import annotations

import pytest

from gigaevo.evolution.engine.mutant_task import run_one_mutant


@pytest.mark.asyncio
async def test_run_one_mutant_happy_path(steady_state_engine_with_fake_dag):
    """run_one_mutant picks parents → refreshes → mutates → registers in_flight."""
    engine = steady_state_engine_with_fake_dag
    await engine._in_flight_sema.acquire()  # caller (dispatcher) holds the slot

    result = await run_one_mutant(engine, task_id=0)

    assert result is not None  # returned the new mutant id
    assert result in engine._in_flight
    assert engine.metrics.total_mutants == 1


@pytest.mark.asyncio
async def test_run_one_mutant_no_elites_releases_slot(steady_state_engine_no_elites):
    """When no elites are available, the slot is released and total_mutants does not advance."""
    engine = steady_state_engine_no_elites
    await engine._in_flight_sema.acquire()

    result = await run_one_mutant(engine, task_id=0)

    assert result is None
    assert engine._in_flight_sema._value == engine._ss_config.max_in_flight  # slot released
    assert engine.metrics.total_mutants == 0


@pytest.mark.asyncio
async def test_run_one_mutant_mutation_returns_none_releases_slot(
    steady_state_engine_mutator_returns_none,
):
    engine = steady_state_engine_mutator_returns_none
    await engine._in_flight_sema.acquire()

    result = await run_one_mutant(engine, task_id=0)

    assert result is None
    assert engine._in_flight_sema._value == engine._ss_config.max_in_flight


@pytest.mark.asyncio
async def test_run_one_mutant_refresh_failure_releases_slot(
    steady_state_engine_refresh_raises,
):
    engine = steady_state_engine_refresh_raises
    await engine._in_flight_sema.acquire()

    result = await run_one_mutant(engine, task_id=0)

    assert result is None
    assert engine._in_flight_sema._value == engine._ss_config.max_in_flight
```

(The four fixtures `steady_state_engine_*` should live in `tests/evolution/conftest.py`. If `conftest.py` exists, extend it; otherwise create the file. The fixtures wrap the engine constructor with the test FakeDag + stubbed strategy/mutator.)

- [ ] **Step 10.2: Run to verify FAIL**

Run `/run-tests tests/evolution/test_mutant_task.py -v`.

Expected: FAIL (module does not exist).

- [ ] **Step 10.3: Implement `run_one_mutant`**

Create `gigaevo/evolution/engine/mutant_task.py`:

```python
"""Per-mutant async task — the unit of producer work under the steady-state
JIT-refresh engine.

One task = one mutant. The dispatcher loop spawns these as soon as a
semaphore slot opens; the task runs to completion independently and is
never awaited by the dispatcher.

Invariant: every exit path either (a) adds the new mutant id to
``engine._in_flight`` (transferring slot ownership; the ingestor will
release the slot when the mutant reaches DONE/DISCARDED), or (b) releases
the slot. Never both, never neither.
"""

from __future__ import annotations

from loguru import logger

from gigaevo.evolution.engine.mutation import generate_mutations
from gigaevo.evolution.engine.refresh import ParentRefresher
from gigaevo.programs.program import Program


async def run_one_mutant(engine, task_id: int) -> str | None:
    """Produce one mutant. Assumes one ``engine._in_flight_sema`` slot is held by the caller."""
    try:
        elites = await engine._select_elites_for_mutation()
        if not elites:
            engine._in_flight_sema.release()
            return None

        parents = _pick_parents(engine, elites)
        if not parents:
            engine._in_flight_sema.release()
            return None

        try:
            refreshed = await engine._parent_refresher.refresh(parents)
        except (ValueError, TimeoutError) as exc:
            logger.warning(
                "[mutant_task:{}] Parent refresh failed: {} — aborting mutant",
                task_id,
                exc,
            )
            engine._in_flight_sema.release()
            return None

        mutation_ids = await generate_mutations(
            refreshed,
            mutator=engine.mutation_operator,
            storage=engine.storage,
            state_manager=engine.state,
            parent_selector=engine.config.parent_selector,
            limit=1,
            iteration=engine.metrics.total_mutants,
        )

        if not mutation_ids:
            engine._in_flight_sema.release()
            return None

        if len(mutation_ids) > 1:
            logger.warning(
                "[mutant_task:{}] generate_mutations(limit=1) returned {} ids; tracking first",
                task_id,
                len(mutation_ids),
            )
            mutation_ids = mutation_ids[:1]

        new_id = mutation_ids[0]
        async with engine._in_flight_lock:
            engine._in_flight.add(new_id)
        engine.metrics.total_mutants += 1
        engine.metrics.record_mutation_metrics(1, 0)
        return new_id

    except BaseException:
        # Slot release on any unexpected failure — including CancelledError —
        # before the program reaches in_flight. If we already registered it,
        # the ingestor owns the slot release path.
        engine._in_flight_sema.release()
        raise


def _pick_parents(engine, elites: list[Program]) -> list[Program]:
    """Run the configured ParentSelector once to pick one parent bundle."""
    iterator = engine.config.parent_selector.create_parent_iterator(elites)
    try:
        return next(iter(iterator))
    except StopIteration:
        return []


__all__ = ["run_one_mutant"]
```

- [ ] **Step 10.4: Run tests**

Run `/run-tests tests/evolution/test_mutant_task.py -v`.

Expected: all four pass.

- [ ] **Step 10.5: Commit**

```bash
rtk git add gigaevo/evolution/engine/mutant_task.py tests/evolution/test_mutant_task.py tests/evolution/conftest.py
rtk git commit -m "feat(engine): add run_one_mutant — per-mutant producer task

Slot-ownership invariant: every exit either registers the new mutant in
_in_flight (slot transferred to ingestor) or releases the slot. See spec §3.2."
```

Then `notify('engine refactor: Task 10 — run_one_mutant landed')`.

---

### Task 11: Add dispatcher loop (`dispatcher.py`)

**Files:**
- Create: `gigaevo/evolution/engine/dispatcher.py`
- Create: `tests/evolution/test_dispatcher.py`

- [ ] **Step 11.1: Write the failing tests**

Create `tests/evolution/test_dispatcher.py`:

```python
from __future__ import annotations

import asyncio

import pytest

from gigaevo.evolution.engine.dispatcher import dispatcher_loop


@pytest.mark.asyncio
async def test_dispatcher_spawns_until_backpressure(steady_state_engine_with_fake_dag):
    """Dispatcher spawns until max_in_flight tasks are concurrent, then blocks on acquire()."""
    engine = steady_state_engine_with_fake_dag
    engine._ss_config = engine._ss_config.model_copy(update={"max_in_flight": 2})
    engine._in_flight_sema = asyncio.Semaphore(2)

    task = asyncio.create_task(dispatcher_loop(engine))
    # Let the loop spawn a few mutant tasks
    await asyncio.sleep(0.2)

    assert engine.metrics.total_mutants <= 2 + len(engine._in_flight)  # spawned at most slot+inflight
    engine._running = False
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_dispatcher_stops_when_stopper_fires(steady_state_engine_stopper_fires_at_one):
    """Dispatcher stops spawning once stopper.should_stop is True."""
    engine = steady_state_engine_stopper_fires_at_one
    task = asyncio.create_task(dispatcher_loop(engine))
    await asyncio.wait_for(task, timeout=2.0)
    # Stopper threshold was 1 → at most one mutant spawned
    assert engine.metrics.total_mutants <= 1
```

- [ ] **Step 11.2: Run to verify FAIL**

Run `/run-tests tests/evolution/test_dispatcher.py -v`.

Expected: FAIL.

- [ ] **Step 11.3: Implement `dispatcher_loop`**

Create `gigaevo/evolution/engine/dispatcher.py`:

```python
"""Long-lived dispatcher loop for the steady-state engine.

Pattern: `while running: acquire semaphore slot; create_task(run_one_mutant);
loop`. The dispatcher never awaits the per-mutant task it spawned — that is
what makes the engine a continuous stream rather than a sequential producer.
Backpressure is enforced by the semaphore alone.
"""

from __future__ import annotations

import asyncio

from loguru import logger

from gigaevo.evolution.engine.mutant_task import run_one_mutant


async def dispatcher_loop(engine) -> None:
    logger.info("[dispatcher] start")
    active: set[asyncio.Task] = set()
    task_id = 0
    try:
        while engine._running and not engine._reached_generation_cap():
            await engine._in_flight_sema.acquire()
            if not engine._running or engine._reached_generation_cap():
                engine._in_flight_sema.release()
                break
            t = asyncio.create_task(
                run_one_mutant(engine, task_id), name=f"mutant-{task_id}"
            )
            task_id += 1
            active.add(t)
            t.add_done_callback(active.discard)
    except asyncio.CancelledError:
        raise
    finally:
        for t in active:
            t.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)
        logger.info("[dispatcher] stop")


__all__ = ["dispatcher_loop"]
```

- [ ] **Step 11.4: Run tests**

Run `/run-tests tests/evolution/test_dispatcher.py -v`.

Expected: pass.

- [ ] **Step 11.5: Commit**

```bash
rtk git add gigaevo/evolution/engine/dispatcher.py tests/evolution/test_dispatcher.py
rtk git commit -m "feat(engine): add dispatcher_loop — spawn-and-forget per-mutant tasks

Continuous stream model: semaphore is the sole backpressure mechanism;
the dispatcher never awaits the mutant tasks it spawns. See spec §3.2."
```

Then `notify('engine refactor: Task 11 — dispatcher_loop landed')`.

---

### Task 12: Add ingestor loop (`ingestor.py`)

**Files:**
- Create: `gigaevo/evolution/engine/ingestor.py`
- Create: `tests/evolution/test_ingestor.py`

- [ ] **Step 12.1: Write the failing tests**

Create `tests/evolution/test_ingestor.py`:

```python
from __future__ import annotations

import asyncio

import pytest

from gigaevo.evolution.engine.ingestor import ingestor_loop, poll_and_ingest


@pytest.mark.asyncio
async def test_poll_and_ingest_promotes_done_mutants(steady_state_engine_with_one_done_mutant):
    """A DONE mutant in _in_flight is ingested and its slot released."""
    engine = steady_state_engine_with_one_done_mutant
    before = engine._in_flight_sema._value
    handled = await poll_and_ingest(engine)
    assert handled == 1
    assert engine._in_flight_sema._value == before + 1
    assert engine.metrics.programs_processed >= 1


@pytest.mark.asyncio
async def test_poll_and_ingest_sweeps_vanished_in_flight(steady_state_engine_with_ghost_in_flight):
    """An in-flight id whose program vanished from Redis is swept and slot released."""
    engine = steady_state_engine_with_ghost_in_flight
    before = engine._in_flight_sema._value
    handled = await poll_and_ingest(engine)
    assert handled == 1
    assert engine._in_flight_sema._value == before + 1


@pytest.mark.asyncio
async def test_ingestor_loop_exits_when_running_false(steady_state_engine_empty):
    engine = steady_state_engine_empty
    task = asyncio.create_task(ingestor_loop(engine))
    await asyncio.sleep(0.1)
    engine._running = False
    await asyncio.wait_for(task, timeout=2.0)
```

- [ ] **Step 12.2: Run to verify FAIL**

Run `/run-tests tests/evolution/test_ingestor.py -v`.

Expected: FAIL.

- [ ] **Step 12.3: Implement the ingestor**

Create `gigaevo/evolution/engine/ingestor.py`:

```python
"""Long-lived ingestion loop for the steady-state engine.

Polls in-flight programs in batch, ingests DONE ones (accept→archive |
reject→DISCARDED), sweeps vanished/DISCARDED ones, and releases the
semaphore slot they each owned.
"""

from __future__ import annotations

import asyncio

from loguru import logger

from gigaevo.llm.bandit import MutationOutcome
from gigaevo.programs.program import EXCLUDE_STAGE_RESULTS
from gigaevo.programs.program_state import ProgramState


async def ingestor_loop(engine) -> None:
    logger.info("[ingestor] start")
    try:
        while engine._running:
            ingested = await poll_and_ingest(engine)
            interval = (
                engine.config.loop_interval * 0.25
                if (ingested or len(engine._in_flight) >= engine._ss_config.max_in_flight)
                else engine.config.loop_interval
            )
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        raise
    finally:
        logger.info("[ingestor] stop")


async def poll_and_ingest(engine) -> int:
    async with engine._in_flight_lock:
        if not engine._in_flight:
            return 0
        candidates = list(engine._in_flight)

    programs = await engine.storage.mget(candidates, exclude=EXCLUDE_STAGE_RESULTS)
    found_ids = {p.id for p in programs if p is not None}

    done_ids: list[str] = []
    leaked_ids: list[str] = []
    for prog in programs:
        if prog is None:
            continue
        if prog.state == ProgramState.DONE:
            done_ids.append(prog.id)
        elif prog.state == ProgramState.DISCARDED:
            leaked_ids.append(prog.id)
    for pid in candidates:
        if pid not in found_ids:
            leaked_ids.append(pid)

    handled_ids: list[str] = []
    if done_ids:
        _, handled_ids = await _ingest_batch(engine, done_ids)

    released = set(handled_ids) | set(leaked_ids)
    if released:
        async with engine._in_flight_lock:
            for pid in released:
                if pid in engine._in_flight:
                    engine._in_flight.discard(pid)
                    engine._in_flight_sema.release()

    # Persist programs_processed to Redis so external sync hooks see progress immediately.
    if handled_ids or leaked_ids:
        await engine._write_snapshot(programs_processed=engine.metrics.programs_processed)

    return len(handled_ids) + len(leaked_ids)


async def _ingest_batch(engine, program_ids: list[str]) -> tuple[int, list[str]]:
    if not program_ids:
        return 0, []

    completed = await engine.storage.mget(program_ids, exclude=EXCLUDE_STAGE_RESULTS)
    completed = [p for p in completed if p.state == ProgramState.DONE]
    if not completed:
        return 0, []

    added = 0
    rej_valid = 0
    rej_strategy = 0
    reject_ids: list[str] = []

    for prog in completed:
        try:
            if not engine.config.program_acceptor.is_accepted(prog):
                logger.info(
                    "[ingestor] {} REJECTED by acceptor (metrics={})",
                    prog.short_id,
                    prog.metrics,
                )
                await engine._notify_hook(prog, MutationOutcome.REJECTED_ACCEPTOR)
                reject_ids.append(prog.id)
                rej_valid += 1
            elif await engine.strategy.add(prog):
                added += 1
                await engine._notify_hook(prog, MutationOutcome.ACCEPTED)
            else:
                await engine._notify_hook(prog, MutationOutcome.REJECTED_STRATEGY)
                reject_ids.append(prog.id)
                rej_strategy += 1
        except Exception as exc:
            logger.error("[ingestor] {} ingestion failed: {}", prog.short_id, exc)
            reject_ids.append(prog.id)

    if reject_ids:
        for prog in completed:
            if prog.id in set(reject_ids):
                prog.state = ProgramState.DISCARDED
        try:
            await engine.storage.batch_transition_by_ids(
                reject_ids,
                ProgramState.DONE.value,
                ProgramState.DISCARDED.value,
            )
        except Exception as exc:
            logger.error(
                "[ingestor] batch discard failed for {} programs: {}",
                len(reject_ids),
                exc,
            )

    engine.metrics.programs_processed += len(completed)
    engine.metrics.record_ingestion_metrics(added, rej_valid, rej_strategy)
    return added, [p.id for p in completed]


__all__ = ["ingestor_loop", "poll_and_ingest"]
```

- [ ] **Step 12.4: Run tests**

Run `/run-tests tests/evolution/test_ingestor.py -v`.

Expected: pass.

- [ ] **Step 12.5: Commit**

```bash
rtk git add gigaevo/evolution/engine/ingestor.py tests/evolution/test_ingestor.py
rtk git commit -m "feat(engine): add ingestor_loop + poll_and_ingest

Single long-lived ingestion coroutine; multiplexes the 'reached DONE'
observation across all in-flight mutants via batch mget. See spec §3.2."
```

Then `notify('engine refactor: Task 12 — ingestor_loop landed')`.

---

### Task 13: Wire new modules into `SteadyStateEvolutionEngine`; delete epoch code

**Files:**
- Modify: `gigaevo/evolution/engine/steady_state.py` (drastic shrink)
- Modify: `gigaevo/evolution/engine/config.py` (drop `refresh_passes`, `refresh_order`, `epoch_trigger_count`)
- Modify: `gigaevo/evolution/engine/__init__.py` (drop `SteadyStateEngineConfig` export? Decision: keep `SteadyStateEngineConfig` class name as alias of the unified config to avoid Hydra `_target_` churn. Implementation below makes it a `class SteadyStateEngineConfig(EngineConfig): pass` — no extra fields.)
- Modify: `tests/evolution/test_steady_state.py` (remove epoch tests; rewrite as JIT tests)

- [ ] **Step 13.1: Write the failing test (JIT replaces epoch refresh)**

Create `tests/evolution/test_jit_refresh_e2e.py`:

```python
"""End-to-end: select-parent → JIT-refresh that parent → produce mutant → ingest.
No epoch barrier, no global archive refresh. The mutant's parent counter
shows it was re-evaluated exactly once during its own producer task.
"""

from __future__ import annotations

import asyncio

import pytest

from gigaevo.evolution.engine.steady_state import SteadyStateEvolutionEngine


@pytest.mark.asyncio
async def test_jit_refresh_e2e_no_epoch_barrier(steady_state_e2e_factory):
    """One mutation cycle: parent is JIT-refreshed exactly once; no global flip happens."""
    engine, fake_dag = steady_state_e2e_factory(max_in_flight=1, stopper_after_mutants=1)
    parent_id = fake_dag.seed_id

    engine.start()
    await asyncio.wait_for(engine.task, timeout=10.0)

    assert engine.metrics.total_mutants == 1
    # Parent was re-evaluated exactly once (its producer task) — not on every "epoch"
    assert fake_dag.flip_count_for(parent_id) == 1
    # No archive-wide refresh ever fired (counter remains zero)
    assert engine.metrics.submitted_for_refresh == 0
```

- [ ] **Step 13.2: Run to verify FAIL**

Run `/run-tests tests/evolution/test_jit_refresh_e2e.py -v`.

Expected: FAIL (engine still uses epoch_refresh path; `submitted_for_refresh > 0`).

- [ ] **Step 13.3: Replace `steady_state.py`**

Rewrite `gigaevo/evolution/engine/steady_state.py` to the minimal form:

```python
"""SteadyStateEvolutionEngine — true continuous async stream.

Composes :func:`dispatcher_loop` and :func:`ingestor_loop`. No epoch
barrier, no global archive refresh; archive programs are re-evaluated
only when they are themselves selected as parents
(:class:`ParentRefresher`).

See ``docs/superpowers/specs/2026-05-12-steady-state-engine-audit-and-redesign.md``.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import cast

from loguru import logger

from gigaevo.evolution.engine.config import SteadyStateEngineConfig
from gigaevo.evolution.engine.core import EvolutionEngine
from gigaevo.evolution.engine.dispatcher import dispatcher_loop
from gigaevo.evolution.engine.ingestor import ingestor_loop, poll_and_ingest
from gigaevo.evolution.engine.refresh import ParentRefresher


class SteadyStateEvolutionEngine(EvolutionEngine):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        cfg = cast(SteadyStateEngineConfig, self.config)
        if not isinstance(cfg, SteadyStateEngineConfig):
            raise TypeError(
                f"SteadyStateEvolutionEngine requires SteadyStateEngineConfig, "
                f"got {type(self.config).__name__}"
            )
        self._ss_config: SteadyStateEngineConfig = cfg

        self._in_flight: set[str] = set()
        self._in_flight_sema = asyncio.Semaphore(self._ss_config.max_in_flight)
        self._in_flight_lock = asyncio.Lock()

        self._parent_refresher = ParentRefresher(storage=self.storage)

        self._dispatcher_task: asyncio.Task | None = None
        self._ingestor_task: asyncio.Task | None = None

    async def step(self) -> None:
        raise NotImplementedError(
            "SteadyStateEvolutionEngine uses run() directly. "
            "step() is not meaningful in steady-state mode."
        )

    async def run(self) -> None:
        logger.info(
            "[SteadyState] Start | max_in_flight={} stopper={}",
            self._ss_config.max_in_flight,
            type(self._ss_config.stopper).__name__,
        )
        self._running = True
        self._run_start_time = time.monotonic()
        self._run_start_mutants = self.metrics.total_mutants

        await self._write_snapshot(
            total_mutants=self.metrics.total_mutants,
            programs_processed=self.metrics.programs_processed,
        )

        try:
            # Phase 0: drain initial seed population (already QUEUED by loader)
            await self._await_idle()
            await self._ingest_seed_programs()
            self.storage.snapshot.bump(incremental=True)
            await self._write_snapshot(programs_processed=self.metrics.programs_processed)

            if self._pre_step_hook:
                await self._pre_step_hook()

            self._dispatcher_task = asyncio.create_task(
                dispatcher_loop(self), name="ss-dispatcher"
            )
            self._ingestor_task = asyncio.create_task(
                ingestor_loop(self), name="ss-ingestor"
            )

            done, pending = await asyncio.wait(
                [self._dispatcher_task, self._ingestor_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await t

            loop_exc = None
            for t in done:
                if not t.cancelled():
                    exc = t.exception()
                    if exc and not isinstance(exc, asyncio.CancelledError):
                        logger.error("[SteadyState] Loop failed: {}", exc)
                        loop_exc = exc

            # Final ingestion sweep to capture any stragglers.
            if self._in_flight:
                while self._in_flight:
                    handled = await poll_and_ingest(self)
                    if handled == 0:
                        await asyncio.sleep(self.config.loop_interval)

            if loop_exc is not None:
                raise loop_exc

        except asyncio.CancelledError:
            logger.debug("[SteadyState] run() cancelled")
            raise
        finally:
            self._running = False
            try:
                await self._post_run_hook.on_run_complete(self.storage)
            except Exception as exc:
                logger.error("[SteadyState] post-run hook failed: {}", exc)
            logger.info("[SteadyState] Stopped")

    async def _ingest_seed_programs(self) -> None:
        """Seed-population ingestion path. Delegates to the base ingestion
        method since seed programs are not yet in ``_in_flight``."""
        await self._ingest_completed_programs(mutation_ids=None)
```

(Lines deleted: all of `_mutation_loop`, `_produce_one_mutant`, `_get_cached_elites`, `_create_single_mutant`, `_ingestion_loop`, `_poll_and_ingest`, `_ingest_batch`, `_should_trigger_epoch`, `_epoch_refresh`, `_drain_in_flight`, `_drain_scoped`, `_refresh_archive_programs`, `_refresh_archive_programs_one_pass`. The class shrinks from 935 LOC to ~130 LOC.)

- [ ] **Step 13.4: Update `config.py`**

In `gigaevo/evolution/engine/config.py`:

1. Delete the `refresh_passes` Field (lines 76-109).
2. Delete the `refresh_order` Field (lines 111-137).
3. Delete the `epoch_trigger_count` property (lines 139-142).
4. Add `max_in_flight: int = Field(default=5, gt=0, description="...")` to `EngineConfig` (the parent class) so the unified config carries it. Keep `SteadyStateEngineConfig` as `class SteadyStateEngineConfig(EngineConfig): pass` for Hydra `_target_` back-compat.
5. Update the `EngineConfig` and `SteadyStateEngineConfig` docstrings: remove "epoch refresh" terminology; describe JIT model.

- [ ] **Step 13.5: Delete obsolete tests, rewrite remaining ones**

In `tests/evolution/test_steady_state.py`:
- Delete every test whose name or body references `_epoch_refresh`, `_drain_*`, `_mutation_gate`, `_cached_elites`, `_should_trigger_epoch`, `refresh_passes`, `refresh_order`, `_processed_since_epoch`, `_epoch_mutants`, or the bucketed/multi-pass refresh path.
- Keep tests that exercise: backpressure semaphore, leaked-in-flight sweep, programs_processed accounting, restore-from-snapshot.
- Rename `self.metrics.total_generations` → `self.metrics.total_mutants` in remaining tests.

In `tests/evolution/test_steady_state_benchmark.py` and `tests/evolution/test_steady_state_determinism.py`:
- Same renames + epoch-test removals.

In `tests/evolution/test_evolution_engine.py`:
- The generational `step()`-driven tests are now driving deprecated code (Task 14 will delete it). For this commit, mark them with `@pytest.mark.skip(reason="generational step() removed in Task 14")` rather than delete — Task 14 deletes them.

In `tests/evolution/test_generation_boundary_emit.py`:
- Mark every test with `@pytest.mark.skip(reason="GenerationBoundary emission removed with step()")`.

- [ ] **Step 13.6: Run the affected tests**

Run `/run-tests tests/evolution/test_jit_refresh_e2e.py tests/evolution/test_steady_state.py -v`.

Expected: new e2e test passes; surviving steady-state tests pass; deleted tests are gone; skipped tests are skipped.

- [ ] **Step 13.7: Run full engine suite for regression**

Run `/run-tests tests/evolution/ -v`.

Expected: only skipped tests are skipped; everything else passes. If something fails that isn't yet skipped, triage and either skip-with-reason or fix.

- [ ] **Step 13.8: Commit**

```bash
rtk git add gigaevo/evolution/engine/steady_state.py gigaevo/evolution/engine/config.py tests/evolution/
rtk git commit -m "refactor(engine): SteadyStateEvolutionEngine composes dispatcher + ingestor + ParentRefresher

Drops 800+ LOC of epoch machinery (_mutation_gate, _draining, _processed_since_epoch,
_epoch_refresh, _drain_in_flight, _drain_scoped, _cached_elites, _should_trigger_epoch,
multi-pass + bucketed _refresh_archive_programs). Adds JIT parent refresh as the
only post-seed DONE→QUEUED path. See spec §3."
```

Then `notify('engine refactor: Task 13 — epoch code deleted, JIT engine live')`.

---

### Task 14: Delete generational `EvolutionEngine.step()` and `run()` loop

**Files:**
- Modify: `gigaevo/evolution/engine/core.py` (delete `step`, generational `run`, `_create_mutants`, `_ingest_completed_programs` if its only caller was `step()`, `_refresh_archive_programs`, `GenerationBoundary` emit)
- Modify: `gigaevo/monitoring/events.py` — keep `GenerationBoundary` class (back-compat) but no longer imported by `core.py`
- Modify: `config/evolution/default.yaml` (target steady-state)
- Modify: `tests/evolution/test_evolution_engine.py` (delete generational tests; keep helper/idle tests)
- Delete: `tests/evolution/test_generation_boundary_emit.py`

- [ ] **Step 14.1: Confirm no production caller remains**

Run:
```bash
rtk grep -rn "EvolutionEngine\b" gigaevo/ config/ run.py 2>/dev/null | grep -v "SteadyState\|steady_state\|^Binary\|test_"
```

Expected: every match is either a class definition, a comment, or `config/evolution/default.yaml:36`. No production code instantiates `EvolutionEngine` directly anymore.

If any non-test instantiation exists, stop and migrate it first (Task 14b — add a sub-task here).

- [ ] **Step 14.2: Write the failing test**

In `tests/evolution/test_evolution_engine.py`, add at top of file:

```python
def test_step_method_is_gone():
    """Generational step() is removed. SteadyStateEvolutionEngine raises NotImplementedError;
    base EvolutionEngine simply does not define it."""
    from gigaevo.evolution.engine.core import EvolutionEngine
    assert not hasattr(EvolutionEngine, "step"), (
        "EvolutionEngine.step() is removed; steady-state engine is the only engine."
    )
```

- [ ] **Step 14.3: Run to verify FAIL**

Run `/run-tests tests/evolution/test_evolution_engine.py::test_step_method_is_gone`.

Expected: FAIL (`EvolutionEngine.step` still exists).

- [ ] **Step 14.4: Delete generational code in `core.py`**

In `gigaevo/evolution/engine/core.py`:

1. Delete `step()` (lines 218-322).
2. Delete the generational body inside `run()` (lines 167-216) — replace `run()` with `NotImplementedError` so subclasses must implement, mirroring `step()`:

```python
async def run(self) -> None:
    raise NotImplementedError(
        "EvolutionEngine.run() is abstract — subclasses provide the loop. "
        "Use SteadyStateEvolutionEngine."
    )
```

3. Delete `_create_mutants` (lines 393-411). Its only caller was `step()`.
4. Delete `_refresh_archive_programs` (lines 585-613). Its only caller was `step()`.
5. Keep `_ingest_completed_programs` (lines 413-583) — `SteadyStateEvolutionEngine._ingest_seed_programs` still calls it for the initial population.
6. Delete the `from gigaevo.monitoring.events import GenerationBoundary` and `from gigaevo.monitoring.emit import emit as _emit_event` imports.
7. Delete the `_reached_generation_cap` method's docstring comment about "generation" if it remains; keep the method (steady-state engine calls it).
8. Remove `_stagnant_gens` / `_prev_archive_size` if their only writer was `step()` — check; the steady-state engine also bumped these in `_epoch_refresh` (now deleted), so they have no remaining writer. Delete them.

- [ ] **Step 14.5: Replace `config/evolution/default.yaml`**

In `config/evolution/default.yaml`, replace lines 19-26:

```yaml
engine_config:
  _target_: gigaevo.evolution.engine.SteadyStateEngineConfig
  loop_interval: ${loop_interval}
  max_elites_per_generation: ${max_elites_per_generation}
  max_mutations_per_generation: ${max_mutations_per_generation}
  program_acceptor: ${program_acceptor}
  parent_selector: ${parent_selector}
  stopper: ${stopper}
  max_in_flight: ${max_in_flight}
```

And lines 35-46:

```yaml
evolution_engine:
  _target_: gigaevo.evolution.engine.SteadyStateEvolutionEngine
  storage: ${ref:redis_storage}
  strategy: ${evolution_strategy}
  mutation_operator: ${mutation_operator}
  config: ${engine_config}
  writer: ${writer}
  metrics_tracker: ${metrics_tracker}
  pre_step_hook: ${pre_step_hook}
  post_run_hook: ${ideas_tracker}
  post_step_hook: ${post_step_hook}
```

Also add to `config/constants/evolution.yaml`:

```yaml
max_in_flight: 8
```

(If `max_in_flight` is already defined elsewhere, skip this addition.)

- [ ] **Step 14.6: Drop generational tests**

In `tests/evolution/test_evolution_engine.py`:
- Delete every test whose body calls `engine.step()` or asserts behaviour of `_create_mutants` / `_refresh_archive_programs`.
- Keep tests of `_await_idle`, `_has_active_dags`, `_notify_hook`, `_build_stop_context`, `restore_state`, `_write_snapshot`.

```bash
rtk git rm tests/evolution/test_generation_boundary_emit.py
```

- [ ] **Step 14.7: Run tests**

Run `/run-tests tests/evolution/ -v`.

Expected: `test_step_method_is_gone` passes; all other engine tests pass.

- [ ] **Step 14.8: Run config dry-runs**

Verify both engine configs parse cleanly:

```bash
/home/jovyan/.mlspace/envs/evo/bin/python3 run.py problem.name=hover --cfg job 2>&1 | head -50
/home/jovyan/.mlspace/envs/evo/bin/python3 run.py problem.name=hover evolution=steady_state --cfg job 2>&1 | head -50
```

Expected: both resolve to `_target_: gigaevo.evolution.engine.SteadyStateEvolutionEngine`. If `evolution=steady_state` raises a missing-key error after Task 13's config trim, update `config/evolution/steady_state.yaml` to be a thin re-defaults alias of `default`.

- [ ] **Step 14.9: Commit**

```bash
rtk git add gigaevo/evolution/engine/core.py config/evolution/default.yaml config/constants/evolution.yaml tests/evolution/
rtk git commit -m "refactor(engine): delete generational EvolutionEngine.step() / run() loop

evolution=default now wires SteadyStateEvolutionEngine. EvolutionEngine
becomes an abstract base of shared helpers (snapshot, metrics, idle wait,
hooks, stop context). See spec §3.6."
```

Then `notify('engine refactor: Task 14 — generational engine removed; steady-state is the default')`.

---

### Task 15: Drop `*_in_iteration` cohort aggregates from `collector.py`

**Files:**
- Modify: `gigaevo/programs/stages/collector.py:171-182, 514-524, 565-568`

- [ ] **Step 15.1: Write the failing test**

In an existing collector test (e.g. `tests/programs/stages/test_collector.py` — locate via `rtk grep -rln "EvolutionaryStatistics" tests/`), add:

```python
def test_in_iteration_aggregates_are_none():
    """Under JIT engine, every mutant has its own iteration; cohort fields are None."""
    stats = build_evolutionary_statistics(...)  # use the existing test fixture pattern
    assert stats.best_fitness_in_iteration is None
    assert stats.worst_fitness_in_iteration is None
    assert stats.average_fitness_in_iteration is None
    assert stats.valid_rate_in_iteration is None
```

(If no test file under `tests/programs/stages/` exists for collector, the new test can be a smoke test stubbed against an in-memory archive — see existing collector usage in `tests/evolution/test_evolution_metrics_pipeline.py` for patterns.)

- [ ] **Step 15.2: Run to verify FAIL**

Run the new test. Expected: FAIL (current code populates the fields from the per-iteration cohort).

- [ ] **Step 15.3: Implement the change**

In `gigaevo/programs/stages/collector.py:514-524`, replace the iteration-cohort computation with hard-coded `None`s:

```python
        # Iteration cohort aggregates are vestigial under the JIT-refresh engine
        # (each mutant has a unique iteration value; cohorts collapse to one
        # program). Keep the field for schema stability; populate with None.
        iter_best, iter_worst, iter_avg, iter_valid_rate = None, None, None, None
```

(Delete the `if iteration is not None: iter_programs = [p for p in programs if p.iteration == iteration] ... _compute_fitness_stats_all_metrics(...)` block in full.)

- [ ] **Step 15.4: Run tests**

Run `/run-tests tests/programs/ tests/evolution/test_evolution_metrics_pipeline.py -v`.

Expected: new test passes; pipeline tests pass (the `iter_*` fields are still on the schema, just `None`).

- [ ] **Step 15.5: Commit**

```bash
rtk git add gigaevo/programs/stages/collector.py tests/
rtk git commit -m "refactor(collector): set *_in_iteration aggregates to None under JIT engine

Each mutant has a unique iteration (= total_mutants_at_production), so cohort
aggregates collapse to single-program windows. Schema field retained for
plot/exporter compatibility; consumers needing windowed aggregates should
compute them at plot time. See spec §3.5 + §6.5."
```

Then `notify('engine refactor: Task 15 — iteration cohort aggregates cleared')`.

---

### Task 16: Migrate stopper Hydra configs

**Files:**
- Create: `config/stopper/max_mutants.yaml`
- Create: `config/stopper/max_mutants_or_fitness_plateau.yaml`
- Delete: `config/stopper/max_generations.yaml`
- Delete: `config/stopper/max_generations_or_fitness_plateau.yaml`
- Modify: `config/config.yaml`
- Modify: `config/constants/evolution.yaml` (rename `max_generations: 100` → `max_mutants: 800`; delete `max_mutations_per_generation`)
- Modify: `config/evolution/steady_state.yaml`, `config/evolution/default.yaml`

- [ ] **Step 16.1: Write the failing test**

Create `tests/config/test_stopper_configs.py` (or extend existing config-resolution test if present):

```python
def test_max_mutants_stopper_config_resolves():
    from hydra import compose, initialize_config_dir
    from hydra.utils import instantiate

    with initialize_config_dir(config_dir=str(REPO / "config"), version_base=None):
        cfg = compose(config_name="config", overrides=["stopper=max_mutants", "max_generations=42"])
    stopper = instantiate(cfg.stopper)
    from gigaevo.evolution.engine.stopper import MaxMutantsStopper
    assert isinstance(stopper, MaxMutantsStopper)
    assert stopper.max_mutants == 42
```

- [ ] **Step 16.2: Run to verify FAIL**

Expected: FAIL (`config/stopper/max_mutants.yaml` does not exist).

- [ ] **Step 16.3: Implement the configs (hard rename)**

Per user decision (Option A, 2026-05-12), this is a clean break — no back-compat alias.

**Add the new top-level constant.** In `config/constants/evolution.yaml`:

1. Delete the line `max_generations: 100`.
2. Delete the line `max_mutations_per_generation: 8` (no longer meaningful; epoch concept is gone).
3. Add a new line `max_mutants: 800` (preserves current ~800-mutant run length: old 100 epochs × 8 mutants/epoch).

**Create the new stopper config.** `config/stopper/max_mutants.yaml`:

```yaml
_target_: gigaevo.evolution.engine.stopper.MaxMutantsStopper
max_mutants: ${max_mutants}
```

**Delete the old stopper configs.** Remove:
- `config/stopper/max_generations.yaml`
- `config/stopper/max_generations_or_fitness_plateau.yaml`

**Add the replacement combined stopper config.** `config/stopper/max_mutants_or_fitness_plateau.yaml`:

```yaml
_target_: gigaevo.evolution.engine.stopper.CompositeStopper
stoppers:
  - _target_: gigaevo.evolution.engine.stopper.MaxMutantsStopper
    max_mutants: ${max_mutants}
  - _target_: gigaevo.evolution.engine.stopper.FitnessPlateauStopper
    patience: ${fitness_plateau_patience}
    min_delta: ${fitness_plateau_min_delta}
```

**Update `config/config.yaml`.** Change `- stopper: max_generations` → `- stopper: max_mutants`.

**Update `config/evolution/steady_state.yaml` and `config/evolution/default.yaml`.** Drop the line `max_mutations_per_generation: ${max_mutations_per_generation}` (the engine no longer reads it).

- [ ] **Step 16.4: Run config tests**

Run `/run-tests tests/config/test_stopper_configs.py tests/experiment/test_launch_generator.py -v`.

Expected: pass after they're updated to reference `max_mutants`/`MaxMutantsStopper` instead of `max_generations`/`MaxGenerationsStopper`.

**Loud failure intentional.** Any old experiment manifest or override that still references `max_generations` or `MaxGenerationsStopper` will fail at Hydra-compose time with a missing-key/missing-target error. That's the desired safety: a silent ~8× run-length change would be much worse.

- [ ] **Step 16.5: Commit**

```bash
rtk git add config/stopper/ tests/config/ config/config.yaml config/constants/evolution.yaml config/evolution/steady_state.yaml config/evolution/default.yaml
rtk git rm config/stopper/max_generations.yaml config/stopper/max_generations_or_fitness_plateau.yaml
rtk git commit -m "config(stopper): hard rename max_generations → max_mutants (semantic shift, no alias)

Under the new JIT engine, one mutant = one count unit (was: one epoch =
~8 mutants). To avoid silent 8x run-length change, deleted the alias and
forced explicit migration. New default max_mutants=800 preserves the
prior ~800-mutant effective run length."
```

Then `notify('engine refactor: Task 16 — stopper configs hard-renamed to max_mutants')`.

---

### Task 17: Stop emitting `GenerationBoundary`; keep class for log-audit back-compat

**Files:**
- Modify: `gigaevo/monitoring/events.py` (no change needed beyond docstring)
- (already done in Task 14: deleted the only emit site)

- [ ] **Step 17.1: Verify the emit site is gone**

Run:
```bash
rtk grep -rn "_emit_event(GenerationBoundary\|GenerationBoundary(" gigaevo/ 2>/dev/null
```

Expected: only class-definition line in `gigaevo/monitoring/events.py:73`. No emit call.

- [ ] **Step 17.2: Update the docstring**

In `gigaevo/monitoring/events.py`, update the `GenerationBoundary` class docstring (line 73-78) to:

```python
class GenerationBoundary(BaseEvent):
    """Vestigial event class — preserved for log-audit backwards compatibility.

    Under the JIT-refresh engine the notion of a "generation boundary" no
    longer exists, so this event is no longer emitted. The class is kept
    so historical run logs that contain GENERATION_BOUNDARY entries still
    deserialise cleanly during ``gigaevo experiment log-audit`` runs.
    """

    event: ClassVar[str] = "GENERATION_BOUNDARY"
    description: ClassVar[str] = "Vestigial: not emitted under JIT engine."
    health_question: ClassVar[str] = "(no longer asked)"

    gen: int
```

- [ ] **Step 17.3: Verify log_audit still works**

The conditional check at `gigaevo/experiment/log_audit.py:147-155` (`if saw_generation_boundary: ...`) will simply never enter the "missing-by-gen" branch — same as today, since no canonical event has `expected_after_gen > 0`. No test change needed.

- [ ] **Step 17.4: Commit**

```bash
rtk git add gigaevo/monitoring/events.py
rtk git commit -m "docs(events): mark GenerationBoundary vestigial; no longer emitted

JIT engine has no generation boundary. Class kept so historical log lines
still parse during gigaevo experiment log-audit."
```

Then `notify('engine refactor: Task 17 — GenerationBoundary marked vestigial')`.

---

### Task 18: Update `ideas_tracker` test fixture and other indirect callers

**Files:**
- Modify: `tests/memory/test_ideas_tracker_pipeline.py:21, 537`

- [ ] **Step 18.1: Update import + stopper**

In `tests/memory/test_ideas_tracker_pipeline.py`:

1. Replace `from gigaevo.evolution.engine.stopper import MaxGenerationsStopper` with `from gigaevo.evolution.engine.stopper import MaxMutantsStopper`.
2. Replace `MaxGenerationsStopper(max_generations=...)` with `MaxMutantsStopper(max_mutants=...)` at every call site.
3. Update the helper signature `_make_engine(*, post_run_hook=None, max_generations=1)` → `_make_engine(*, post_run_hook=None, max_mutants=1)` and call sites at lines 557, 565. Rename the local variable consistently — no aliases remain.

- [ ] **Step 18.2: Run the test**

Run `/run-tests tests/memory/test_ideas_tracker_pipeline.py -v`.

Expected: pass.

- [ ] **Step 18.3: Commit**

```bash
rtk git add tests/memory/test_ideas_tracker_pipeline.py
rtk git commit -m "test(memory): migrate ideas_tracker_pipeline to MaxMutantsStopper"
```

Then `notify('engine refactor: Task 18 — ideas_tracker test migrated')`.

---

### Task 19: Full test sweep + ruff

**Files:** none (verification)

- [ ] **Step 19.1: Run full evolution + adversarial + monitoring test trees**

Run in three parallel `/run-tests` invocations:

```
/run-tests tests/evolution/
/run-tests tests/adversarial_pipeline/
/run-tests tests/monitoring/
```

Plus:

```
/run-tests tests/experiment/
/run-tests tests/prompts/
/run-tests tests/memory/
```

Expected: all pass (including ones marked `@pytest.mark.skip` from Task 13 — those are now permanently obsolete and should be deleted in this task).

- [ ] **Step 19.2: Delete the `@pytest.mark.skip` placeholders left in Task 13**

Search:
```bash
rtk grep -rn "@pytest.mark.skip(reason=\"generational step() removed" tests/
rtk grep -rn "@pytest.mark.skip(reason=\"GenerationBoundary emission removed" tests/
```

Delete the marked test functions (they are obsolete with the generational engine removal).

- [ ] **Step 19.3: Run ruff**

Run:
```bash
/home/jovyan/.mlspace/envs/evo/bin/ruff format .
/home/jovyan/.mlspace/envs/evo/bin/ruff check . --fix
/home/jovyan/.mlspace/envs/evo/bin/ruff check .
/home/jovyan/.mlspace/envs/evo/bin/ruff format --check .
```

Expected: clean (no unfixable errors, no format diffs).

- [ ] **Step 19.4: Re-run full test sweep after autofixes**

Run all the test commands from Step 19.1 again. Expected: pass.

- [ ] **Step 19.5: Commit**

```bash
rtk git add -A
rtk git commit -m "test+lint: drop placeholder skips; pass full sweep on JIT engine"
```

Then `notify('engine refactor: Task 19 — full sweep green')`.

---

### Task 20: Smoke test on a real experiment config

**Files:** none (verification)

- [ ] **Step 20.1: Pick a small steady-state config**

Use `experiments/heilbron/d-tanh-no-lineage` (recent, known-good fitness trajectory; small enough to dry-run a few iterations) or any other small experiment under `experiments/`.

- [ ] **Step 20.2: Dry-run resolve**

Run:
```bash
EXP=heilbron/d-tanh-no-lineage
gigaevo -e "$EXP" launch --dry-run 2>&1 | tail -30
```

Expected: launch script resolves cleanly; the dry-run shows `_target_: gigaevo.evolution.engine.SteadyStateEvolutionEngine` in the resolved config dump.

- [ ] **Step 20.3: Smoke run**

Pick the smallest treatment arm. Set `max_generations=5` (which now means 5 mutants under the alias) and a tight wall_clock cap. Launch into a scratch Redis DB (use a free DB index via `gigaevo flush --db N --confirm` to reset first if needed):

```bash
# Use whichever launch idiom the experiment supports; if launch.sh is interactive,
# manually issue the python run.py command for one arm with overrides.
```

Expected:
- Engine starts; `[SteadyState] Start | max_in_flight=...` logs.
- A few mutants are produced; `programs_processed` advances.
- No `KeyError`, `AttributeError`, or "generation"-related warnings.
- Telegram notification of completion fires.

- [ ] **Step 20.4: Inspect the produced programs**

Run:
```bash
gigaevo redis-cli --db N "HGETALL run:engine:snapshot"
```

Expected: snapshot JSON contains `"total_mutants": <n>`, `"programs_processed": <m>`, no `total_generations` or `refresh_pass` keys.

- [ ] **Step 20.5: Flush the scratch DB**

```bash
gigaevo flush --db N --confirm
```

- [ ] **Step 20.6: Write the smoke-test results to the experiment scratchpad**

Append a short note to `docs/superpowers/specs/2026-05-12-steady-state-engine-audit-and-redesign.md` under a new `## 9. Smoke-test results` heading, including: experiment name, args, total_mutants reached, programs_processed reached, wall time, any anomalies.

- [ ] **Step 20.7: Commit**

```bash
rtk git add -f docs/superpowers/specs/2026-05-12-steady-state-engine-audit-and-redesign.md
rtk git commit -m "docs(specs): add smoke-test results for JIT engine refactor

Verifies §8 success criterion #5."
```

Then `notify('engine refactor: Task 20 — smoke test passed')`.

---

### Task 19A: Concurrency stress + simulation (load × async patterns)

**Files:**
- Create: `tests/evolution/test_engine_stress.py`

Adds parameterised simulation tests that vary `max_in_flight`, mutant count, per-mutant duration distribution (constant, exponential, heavy-tail), and parent-overlap rate. Each combination asserts the same invariants:

- No semaphore slot leak (`sema._value == max_in_flight` at end).
- `_in_flight` set is empty.
- `total_mutants` == number of mutants the dispatcher spawned.
- `programs_processed` == `accepted + rejected` (no orphans).
- `ParentRefresher` flipped each parent at most once per mutant that used it.
- Counters monotonically non-decreasing across snapshots written during the run.

**Steps:**
- [ ] **19A.1** Write `tests/evolution/test_engine_stress.py` with `pytest.mark.parametrize` over `(max_in_flight ∈ {1, 4, 16}, n_mutants ∈ {50, 200}, duration_dist ∈ ['const', 'expo', 'heavy_tail'], overlap_rate ∈ [0.0, 0.5])`. Each test drives the dispatcher + ingestor + ParentRefresher against the `FakeDag` with a configurable per-program duration.
- [ ] **19A.2** Run `/run-tests tests/evolution/test_engine_stress.py -v`. Expected: all combinations pass.
- [ ] **19A.3** Commit `test(engine): concurrency stress + simulation suite (load × async patterns)` + notify.

---

### Task 19B: Cancellation + resume-after-kill invariants

**Files:**
- Create: `tests/evolution/test_engine_cancellation.py`
- Create: `tests/evolution/test_engine_resume_after_kill.py`

Verifies:
1. Cancelling the dispatcher mid-run leaves the engine in a recoverable state: every spawned mutant task settles (success, None, or CancelledError), `_in_flight` reconciles, semaphore is fully released, counters unchanged after the cancel arrived.
2. Killing the process between mutants (simulated by tearing down the engine then constructing a new one against the same Redis state) hydrates from `EngineSnapshot` correctly: `total_mutants` and `programs_processed` resume, `_in_flight` is rebuilt by sweeping QUEUED/RUNNING program ids, and the next mutant produced has `iteration = total_mutants_at_resume`.

**Steps:**
- [ ] **19B.1** Write the cancellation test: spawn N=10 mutants, cancel after producing 3, assert invariants.
- [ ] **19B.2** Write the resume-after-kill test: run engine to total_mutants=5, drop the engine instance, build a new one bound to the same fakeredis storage, run for 5 more mutants, assert total_mutants==10 at end.
- [ ] **19B.3** Run `/run-tests tests/evolution/test_engine_cancellation.py tests/evolution/test_engine_resume_after_kill.py -v`.
- [ ] **19B.4** Commit `test(engine): cancellation + resume-after-kill invariants` + notify.

---

### Task 19C: Real-Redis integration smoke (not fakeredis)

**Files:**
- Create: `tests/integration/test_engine_real_redis.py` (or extend existing integration suite)

Uses a real `redis-server` subprocess (or `pytest-redis` if available) on a free port + scratch DB. Drives a 50-mutant run end-to-end through the steady-state engine with `max_in_flight=8`. Asserts: no fakeredis-only behaviour (`bitcount`, `pipeline` corner cases, `eval` Lua scripts that fakeredis stubs differently from real Redis); snapshot persists across an in-test process restart.

**Steps:**
- [ ] **19C.1** Locate the project's real-Redis fixture (search `tests/integration/conftest.py` for `redis_server` or `real_redis`); reuse if present, otherwise spawn one via `subprocess.Popen(["redis-server", "--port", "0", "--save", ""])` and capture the port from stderr.
- [ ] **19C.2** Write the 50-mutant smoke test.
- [ ] **19C.3** Run via `/run-tests tests/integration/test_engine_real_redis.py -v`.
- [ ] **19C.4** Commit `test(engine): real-Redis integration smoke` + notify.

---

### Task 19D: ParentRefresher failure-mode resilience

**Files:**
- Extend: `tests/evolution/test_refresh_parents.py`

Adds tests for:
- DAG runner crashes mid-refresh (parent never transitions to DONE within timeout).
- Parent flipped to DISCARDED by another path during refresh → `ParentRefresher` raises `ValueError`, caller releases slot.
- Parent vanishes from storage mid-refresh → raises `ValueError`.
- Overlapping concurrent refresh on the same parent set serialises correctly under arbitrary lock-acquire ordering (sorted by id, deterministic).
- Timeout fires when configured; no timeout when not configured (default).

**Steps:**
- [ ] **19D.1** Add the four failure-mode tests to `tests/evolution/test_refresh_parents.py`.
- [ ] **19D.2** Run `/run-tests tests/evolution/test_refresh_parents.py -v`.
- [ ] **19D.3** Commit `test(engine): ParentRefresher failure-mode resilience` + notify.

---

### Task 19E: Chaos-hacker adversarial review

**Files:** none (code review only — followups may add fixes)

Invoke the [[chaos-hacker]] subagent on the four new modules + the rewritten `steady_state.py`:

```
Agent({
  subagent_type: "chaos-hacker",
  description: "Adversarial review of JIT engine modules",
  prompt: "Review gigaevo/evolution/engine/{refresh,mutant_task,dispatcher,ingestor,steady_state}.py for: slot accounting bugs in run_one_mutant (every exit path must release-or-transfer exactly one semaphore slot), lock-ordering deadlocks in ParentRefresher under overlapping concurrent calls, BaseException vs Exception coverage gaps, partial-failure paths where mutation IDs are persisted but never added to _in_flight, race between ingestor poll_and_ingest and dispatcher in_flight_lock acquisition, infinite-wait paths if poll_interval is misconfigured, snapshot ordering bugs around programs_processed write timing. Report findings ranked by severity."
})
```

**Steps:**
- [ ] **19E.1** Invoke chaos-hacker subagent per the prompt above.
- [ ] **19E.2** For each CRITICAL or HIGH finding, open a tracking note in `docs/superpowers/plans/` and either patch in this PR or file a follow-up issue. MEDIUM/LOW: triage and document decision.
- [ ] **19E.3** Commit any patches as a fixup commit referencing chaos-hacker findings.

---

### Task 19F: Counter-monotonicity invariant test

**Files:**
- Create: `tests/evolution/test_counter_monotonicity.py`

Drives a 100-mutant run while a background coroutine snapshots `total_mutants` and `programs_processed` from Redis every 50ms; asserts both sequences are monotonically non-decreasing. Also asserts the final values agree with the in-process `EngineMetrics`.

**Steps:**
- [ ] **19F.1** Write the test.
- [ ] **19F.2** Run `/run-tests tests/evolution/test_counter_monotonicity.py -v`.
- [ ] **19F.3** Commit `test(engine): counter monotonicity invariants` + notify.

---

### Task 21: Open PR

**Files:** none (PR creation)

- [ ] **Step 21.1: Final lint + test pass**

Run `/home/jovyan/.mlspace/envs/evo/bin/ruff check . && /home/jovyan/.mlspace/envs/evo/bin/ruff format --check .`. Expected: clean.

Run `/run-tests tests/evolution/ tests/adversarial_pipeline/ tests/monitoring/ tests/experiment/ tests/prompts/ tests/memory/`. Expected: clean.

- [ ] **Step 21.2: Push and open PR**

```bash
rtk git push -u origin refactor/steady-state-true-jit-refresh
gh pr create --title "refactor(engine): true JIT-refresh steady-state engine" --body "$(cat <<'EOF'
## Summary

- Replaces the epoch-driven steady-state engine with a continuous async
  stream of mutation tasks that refresh only their selected parents on
  the spot.
- Single progress counter (`total_mutants`); deletes `EngineSnapshot.refresh_pass`,
  multi-pass + bucketed archive refresh, mutation gate, scoped drain,
  elite cache, epoch watermark heuristics.
- Splits 935-LOC `steady_state.py` into `engine.py` / `dispatcher.py` /
  `mutant_task.py` / `ingestor.py` / `refresh.py`.
- Deletes the generational `EvolutionEngine.step()` / `run()` loop;
  `evolution=default` now wires `SteadyStateEvolutionEngine`.
- `MaxGenerationsStopper` is **deleted**; `MaxMutantsStopper` takes
  its place. Hard rename, no alias — the semantic shift (epochs →
  individual mutants, ~8× difference) would silently change run length
  if aliased. Old `max_generations: 100` default replaced by
  `max_mutants: 800` (preserves prior ~800-mutant effective length).

Spec: `docs/superpowers/specs/2026-05-12-steady-state-engine-audit-and-redesign.md`.
Plan: `docs/superpowers/plans/2026-05-12-steady-state-true-jit-refresh.md`.

## Test plan

- [x] Unit tests pass: `tests/evolution/`, `tests/adversarial_pipeline/`,
      `tests/monitoring/`, `tests/experiment/`, `tests/prompts/`, `tests/memory/`.
- [x] Ruff clean.
- [x] Smoke run on `heilbron/d-tanh-no-lineage` (see spec §9).

## Migration notes

- **Stopper config keys hard-renamed**: `stopper=max_generations` no longer
  exists — use `stopper=max_mutants`. The global default `max_generations: 100`
  has been replaced by `max_mutants: 800` (preserves the ~800-mutant effective
  run length from the old generational model with `max_mutations_per_generation=8`).
  Any Hydra override still referencing `max_generations` will fail loudly at
  compose time. Intentional: a silent ~8× run-length change is worse than a
  config-load failure.
- Experiments using `evolution=default` now run the steady-state engine —
  flagged for review in any active branches that depend on generational
  `step()` semantics (none found at audit time).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR opens. Capture the URL.

- [ ] **Step 21.3: Telegram-notify the PR URL**

```bash
/home/jovyan/.mlspace/envs/evo/bin/python3 -c "from tools.telegram_notify import notify; notify('engine refactor: PR open — <URL>')"
```

---

## Self-review (already executed by the plan author)

**1. Spec coverage:** Every section of the spec maps to a task:
- §1 audit findings → Tasks 2-15 collectively eliminate every overlapping concept named.
- §2.2 concept table → Tasks 13 (epoch code), 14 (generational step), 4+13 (refresh_pass), 13 (elite cache, drains, gate, watermark).
- §3.1-3.3 target design → Tasks 9 (refresh), 10 (mutant_task), 11 (dispatcher), 12 (ingestor), 13 (compose).
- §3.4 `_refresh_parents` helper → Task 9.
- §3.5 counter consolidation → Tasks 2, 3, 7, 8.
- §3.6 generational engine deletion → Task 14.
- §4 module split → Tasks 9-13.
- §5 migration boundary → Tasks 4 (shared_benchmark_lineage), 5 (MainRunSyncHook), 6 (redis_queries), 16 (Hydra stopper), 17 (GenerationBoundary), 15 (collector iteration).
- §6 risks: descendant freshness (Task 20 smoke), tracker race (structurally eliminated by Tasks 9-13, validated by Task 19), FitnessPlateauStopper (Task 7), test inventory (Tasks 13, 14, 19), `*_in_iteration` (Task 15), multi-parent backpressure (Task 9 overlapping-parents test + Task 20 smoke).
- §8 success criteria: file size <300 LOC (Tasks 9-13), no "epoch" string (Tasks 13-14), `total_mutants` single counter (Task 2), integration test (Task 13), smoke run (Task 20).

**2. Placeholder scan:** No `TBD`/`TODO`/`fill in later` left in plan body. The `Program.minimal()` reference in Task 9 is flagged inline with a "use existing factory" instruction.

**3. Type consistency:**
- `ParentRefresher.refresh(parents: list[Program]) -> list[Program]` — used uniformly in Tasks 9, 10, 13.
- `run_one_mutant(engine, task_id: int) -> str | None` — used uniformly in Tasks 10, 11.
- `dispatcher_loop(engine) -> None`, `ingestor_loop(engine) -> None`, `poll_and_ingest(engine) -> int` — used uniformly in Tasks 11, 12, 13.
- `EngineMetrics.total_mutants`, `EngineSnapshot.total_mutants`, `StopContext.total_mutants` — all renamed consistently in Tasks 2, 3, 7.
- `MaxMutantsStopper(max_mutants: int)` — used uniformly in Tasks 7, 16, 18.

## Plan summary

21 tasks, sequenced so the tree compiles and tests pass at every commit boundary. Renames first (Tasks 2-8), new modules second (Tasks 9-12), composition + epoch deletion third (Task 13), generational deletion fourth (Task 14), downstream migrations fifth (Tasks 15-18), verification + PR last (Tasks 19-21). Each task is one commit, one Telegram notification, and (usually) one TDD red→green→commit cycle.
