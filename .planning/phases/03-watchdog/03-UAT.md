---
status: passed
phase: 03-watchdog
source: 03-01-PLAN.md through 03-05-PLAN.md
started: 2026-04-12T12:35:00Z
updated: 2026-04-12T12:36:00Z
---

## Tests

### 1. WatchdogPlugin ABC

**Status**: PASSED

- `WatchdogPlugin` is a proper `ABC` subclass (from `abc.ABC`)
- Cannot be instantiated directly: raises `TypeError("Can't instantiate abstract class WatchdogPlugin without an implementation for abstract methods 'format_status_body', 'generate_plots'")`
- Abstract methods: `frozenset({'format_status_body', 'generate_plots'})`
- Optional methods present with defaults: `extra_telegram_content` (returns `None`), `extra_redis_queries` (returns `{}`)
- Importable from `gigaevo.monitoring` top-level package

### 2. Plugin registry

**Status**: PASSED

- Registry implemented as module-level `_REGISTRY` dict with `@register(name)` decorator
- 4 plugins registered: `['adversarial', 'heilbron', 'prompt_coevo', 'solo']`
- All registered classes are proper `WatchdogPlugin` subclasses
- `resolve_plugin()` priority chain works correctly:
  - Explicit manifest field: `watchdog_plugin='heilbron'` -> `HeilbronPlugin`
  - Task heuristic: `task='adversarial'` -> `AdversarialPlugin`
  - Fallback (None manifest): -> `SoloPlugin`
  - Invalid plugin name raises `KeyError` with helpful message listing available plugins
- `get_registry()` returns a copy (safe for external use)

### 3. WatchdogConfig

**Status**: PASSED

- `WatchdogConfig` is a `@dataclass(frozen=True)` -- immutable
- Mutation raises `FrozenInstanceError`
- Fields: `poll_interval_s`, `max_restarts`, `restart_cooldown_s`, `heartbeat_ttl_multiplier`, `max_plot_files`, `stagnation_gens`, `model_drift_check`, `redis_host`, `redis_port`
- Derived property: `heartbeat_ttl_s = poll_interval_s * heartbeat_ttl_multiplier` (3600 * 3 = 10800)
- Sensible defaults: `poll_interval_s=3600`, `max_restarts=5`, `redis_host='localhost'`, `redis_port=6379`

Note: Fields `experiment_name` and `pr_number` are NOT on WatchdogConfig -- `experiment_name` is a direct constructor arg on WatchdogEngine, and `pr_number` lives on the dispatcher/channel layer. This is a reasonable design choice (config = engine tuning, identity = constructor args).

### 4. WatchdogEngine construction

**Status**: PASSED

- Constructible with `experiment_name`, `plugin`, `run_configs`, `config`, `max_generations`
- Accepts all 4 plugin types: `SoloPlugin`, `AdversarialPlugin`, `HeilbronPlugin`, `PromptCoevoPlugin`
- Has `run()` method (entry point with SIGTERM handler + restart loop)
- Internal state initialized: `_cycle_count=0`, `_shutdown=False`, `_frontier_history={}`
- Optional constructor args: `monitor`, `alert_detector`, `dispatcher`, `heartbeat_redis`, `plot_dir` (all injectable for testing)
- Default config used when `config=None`

### 5. All monitoring watchdog tests pass

**Status**: PASSED

```
tests/monitoring/test_watchdog_plugin.py    -- 16 passed
tests/monitoring/test_watchdog_config.py    --  5 passed
tests/monitoring/test_watchdog_engine.py    -- 20 passed
tests/monitoring/test_watchdog_integration.py -- 5 passed
----------------------------------------------
Total: 46 passed in 0.84s
```

## Summary

| Metric | Value |
|--------|-------|
| total  | 5     |
| passed | 5     |
| failed | 0     |
| skipped| 0     |

## Gaps

- `WatchdogConfig` does not include `experiment_name` or `pr_number` as fields -- these live on `WatchdogEngine` constructor and dispatcher/channel layer respectively. This is a design choice, not a deficiency: config holds tuning knobs, identity is injected via constructor.
- The `_TASK_HEURISTIC` mapping covers `adversarial`, `heilbron`, `hover`, `hotpotqa`, and `toy` -- but maps `hover`, `hotpotqa`, and `toy` to `"solo"`. If a new experiment type is added (e.g., `scrollprize`), it will also fallback to `solo` via the resolve chain. This is correct default behavior.
- No functional gaps identified. All five Phase 3 deliverables are present and working.
