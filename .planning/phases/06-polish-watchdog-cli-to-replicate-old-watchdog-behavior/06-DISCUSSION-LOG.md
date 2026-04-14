# Phase 6: Polish watchdog CLI to replicate old-watchdog behavior - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-13
**Phase:** 06-polish-watchdog-cli-to-replicate-old-watchdog-behavior
**Areas discussed:** Plot generation approach, GitHub integration, Watchdog lifecycle features, Telegram formatting, Testing

---

## Plot Generation Approach

| Option | Description | Selected |
|--------|-------------|----------|
| Delegate to gigaevo plot CLI | Plugins invoke gigaevo plot arms-race/comparison as subprocesses (same as old watchdog). Reuses existing plotting code, guaranteed visual parity. | ✓ |
| Shared plotting library | Extract comparison.py/arms-race logic into gigaevo.monitoring.plotting module. Plugins call library functions directly. | |
| You decide | Claude chooses the approach. | |

**User's choice:** Delegate to gigaevo plot CLI
**Notes:** None

### Plot Configuration

| Option | Description | Selected |
|--------|-------------|----------|
| watchdog_plots section | New top-level section in experiment.yaml | |
| Extend watchdog_plugin_options | Add plot config under existing watchdog_plugin_options | |
| You decide | Claude decides | |

**User's choice:** Custom — "Option 1 but I would prefer hydra/oop combination for config instantiation as in other codebase (so we directly construct plot plugin in experiment yaml)"
**Notes:** Hydra/OOP instantiation style, consistent with rest of codebase

### Configurable Metrics

**User's choice (multi-select):** Plot metrics (time-series curves), Alert thresholds
**Notes:** Top-k tracking not selected for this phase

### Agent Integration

| Option | Description | Selected |
|--------|-------------|----------|
| experiment-implement asks | Agent asks during implementation | |
| experiment-design asks | Agent asks during design | |
| Both (design proposes, implement confirms) | Design doc includes monitoring section, implement confirms | ✓ |

**User's choice:** Both (design proposes, implement confirms)

---

## GitHub Integration

### Plot Image Display

| Option | Description | Selected |
|--------|-------------|----------|
| Upload to GitHub repo | Upload PNGs to experiment branch via API, embed raw URLs | ✓ |
| Attach as comment images | Use GitHub's drag-and-drop upload API | |
| You decide | Claude decides | |

**User's choice:** Upload to GitHub repo

### PR Comment Management

| Option | Description | Selected |
|--------|-------------|----------|
| Rolling comment (edit after N hours) | Create new comments initially, then edit-in-place | ✓ |
| Always edit-in-place | Single comment, always edited | |
| Create new, collapse old | Always new comments with collapsed old reports | |

**User's choice:** Rolling comment (edit after N hours)

### Logic Placement

| Option | Description | Selected |
|--------|-------------|----------|
| GitHubPRChannel | Channel handles upload + rolling comment | ✓ |
| WatchdogEngine core | Engine handles upload + comment management | |
| You decide | Claude decides | |

**User's choice:** GitHubPRChannel

---

## Watchdog Lifecycle Features

### Features to Include

**User's choice (multi-select):** Redis checkpoint/completion markers, Model drift detection
**Notes:** DB claims refresh not selected

### Model Drift Placement

| Option | Description | Selected |
|--------|-------------|----------|
| Anomaly detector rule | Pluggable rule, only runs if configured | ✓ |
| Core engine feature | Built into WatchdogEngine._cycle() | |

**User's choice:** Anomaly detector rule

### Extras (NO_PROXY, retry)

| Option | Description | Selected |
|--------|-------------|----------|
| NO_PROXY yes, retry yes | Both included | ✓ |
| Skip NO_PROXY, retry yes | Only retry | |
| You decide | Claude decides | |

**User's choice:** NO_PROXY yes, retry yes

---

## Telegram Formatting

### Message Format

| Option | Description | Selected |
|--------|-------------|----------|
| Plugin-specific formatting | Each plugin provides format_telegram_body() | ✓ |
| Generic + extra_telegram_content | Engine produces generic table, plugin adds extras | |
| You decide | Claude decides | |

**User's choice:** Plugin-specific formatting

### SOTA Comparison

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, always show vs SOTA | Always show when baseline configured | |
| Only if plugin supports it | Plugin-dependent | ✓ |

**User's choice:** Only if plugin supports it

---

## Testing

### Testing Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Full integration tests with mock Redis | Mock Redis, GitHub, Telegram, LiteLLM. Full watchdog cycles. | ✓ |
| Unit tests per component + thin integration | Independent component tests with one integration test per type | |
| Both layers | Unit AND integration tests | |

**User's choice:** Full integration tests with mock Redis

### Test Fixtures

| Option | Description | Selected |
|--------|-------------|----------|
| YAML fixture files | experiment.yaml + metrics.yaml fixtures in tests/fixtures/watchdog/ | ✓ |
| Factory functions | Python factory functions for programmatic test data | |
| Both | YAML for realistic, factories for edge cases | |

**User's choice:** YAML fixture files

### Experiment Setups

**User's choice (multi-select):** All three — Solo MAP-Elites (hover), Adversarial pairs (heilbron-style), Prompt co-evolution

### CLI Tests

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, Click CliRunner tests | End-to-end CLI tests that catch import/wiring errors | ✓ |
| Library-level tests only | Test underlying Python functions only | |

**User's choice:** Yes, Click CliRunner tests

---

## Claude's Discretion

- Exact Hydra config schema for watchdog plot configuration
- format_telegram_body() abstract vs default implementation
- Plot retry backoff strategy details
- Redis checkpoint milestone percentages
- Anomaly detector model-drift rule configuration schema

## Deferred Ideas

- Top-k program tracking configurability (user mentioned but deselected for this phase)
- DB claims refresh (not selected as lifecycle feature)
- Watch mode / Rich Live dashboard (deferred from v1.0)
- Generation-aware sync hook for SteadyState
