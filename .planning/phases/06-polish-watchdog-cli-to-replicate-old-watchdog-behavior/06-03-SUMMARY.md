# Phase 06 Plan 03: GitHubPRChannel Experiment-Path Upload + Redis Rolling Comment

Enhanced GitHubPRChannel with experiment-branch plot upload, Redis-backed rolling comment persistence, and baseline wiring.

## Tasks Completed

### Task 1: Enhance GitHubPRChannel
- Added `experiment_name`, `rolling_comment_redis`, `rolling_comment_threshold_hours` constructor params
- Upload path now uses `experiments/{name}/plots/{filename}` when experiment_name set
- Returns raw.githubusercontent.com URLs instead of API download_url
- Added `_get_rolling_comment_id()` / `_set_rolling_comment_id()` with Redis persistence
- Constructor loads existing rolling comment ID from Redis on startup
- `send_status()` uses threshold-based strategy: POST new comments for first N hours, then PATCH
- At threshold boundary, persists comment ID to Redis for cross-restart persistence
- 33 tests pass (updated 2 existing + added 15 new covering upload paths, Redis round-trip, threshold behavior)

### Task 2: Wire into watchdog_cmd.py
- Added `_get_github_token()` helper reading from `~/.config/gh/hosts.yml`
- Creates `NotificationDispatcher` with `GitHubPRChannel` when token + PR number available
- Passes `experiment_name`, `rolling_comment_redis`, `rolling_comment_threshold_hours` to channel
- Extracts `baseline` from `manifest.baseline.mean`, passes to `WatchdogEngine`
- 13 tests pass (added 4 new: baseline propagation, dispatcher creation, GitHub channel wiring)

## Verification
- Upload path matches `experiments/{name}/plots/{filename}` pattern
- Rolling comment ID persisted to Redis and loaded on restart
- Comment switches from POST to PATCH after threshold hours
- Raw GitHub URL format correct for inline rendering
- Engine receives baseline from manifest
- All tests pass (82 monitoring + CLI tests)
