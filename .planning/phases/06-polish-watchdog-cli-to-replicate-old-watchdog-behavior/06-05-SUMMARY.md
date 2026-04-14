# Phase 06 Plan 05: Skill Integration + Visual Verification

Updated experiment lifecycle skills to integrate watchdog monitoring configuration. Tasks 1-2 (auto) completed; Task 3 (human-verify) deferred — requires researcher visual inspection.

## Tasks Completed

### Task 1: Monitoring config proposal in experiment-design skill
Added Step 5a to `.claude/skills/experiment-design/SKILL.md`:
- YAML config templates for solo, adversarial, and prompt co-evolution experiment types
- Researcher questions (metrics, thresholds, custom plot commands)
- References `WatchdogSection`, `PlotCommand`, `AlertThresholds` from `manifest_schema.py`

### Task 2: Watchdog config step in experiment-implement skill
Added Step 7a to `.claude/skills/experiment-implement/SKILL.md`:
- Auto-detect plugin from run prefixes (`pop_a`/`pop_b` → adversarial, `prompt_evolution` → prompt_coevo, else solo)
- Researcher confirmation prompt for metrics, thresholds, plot commands
- Manifest gate validation after writing watchdog section
- References `WatchdogSection` schema from `manifest_schema.py`

### Task 3: Visual verification (DEFERRED — human checkpoint)
Requires researcher to compare new watchdog plots against reference plots at:
- `experiments/heilbron/asymmetric-iterations/plots/arms_race_hour_013.png`
- `experiments/heilbron/asymmetric-iterations/plots/g_fitness_hour_013.png`

Verification checklist: time-series curves, EMA smoothing, confidence bands, frontier dashes, SOTA baselines, proper legends, dual-panel arms-race layout.

## Verification
- experiment-design SKILL.md: 4 `watchdog` references, includes all 3 experiment type templates
- experiment-implement SKILL.md: 11 `watchdog` references, includes auto-detection rules + researcher confirmation
- Both skills reference `manifest_schema.py` WatchdogSection schema
