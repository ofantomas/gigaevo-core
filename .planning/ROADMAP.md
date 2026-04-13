# Roadmap: GigaEvo Monitoring & Tools Overhaul

## Milestones

- ✅ **v1.0 MVP** — Phases 1-5 (shipped 2026-04-12)

## Phases

<details>
<summary>✅ v1.0 MVP (Phases 1-5) — SHIPPED 2026-04-12</summary>

- [x] Phase 1: Foundation (3/3 plans) — completed 2026-04-11
- [x] Phase 2: Notifications (4/4 plans) — completed 2026-04-11
- [x] Phase 3: Watchdog (5/5 plans) — completed 2026-04-11
- [x] Phase 4: CLI (4/4 plans) — completed 2026-04-12
- [x] Phase 5: Integration (3/3 plans) — completed 2026-04-12

</details>

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Foundation | v1.0 | 3/3 | Complete | 2026-04-11 |
| 2. Notifications | v1.0 | 4/4 | Complete | 2026-04-11 |
| 3. Watchdog | v1.0 | 5/5 | Complete | 2026-04-11 |
| 4. CLI | v1.0 | 4/4 | Complete | 2026-04-12 |
| 5. Integration | v1.0 | 3/3 | Complete | 2026-04-12 |

Full details: [v1.0-ROADMAP.md](milestones/v1.0-ROADMAP.md)

### Phase 1: Update research experiment lifecycle with CLI tooling

**Goal:** Migrate all experiment lifecycle skills and agents from legacy PYTHONPATH inline Python to gigaevo CLI. Delete project-pm. Remove resource_manager.py references from skills. Zero inline Python in skills after this phase.
**Requirements**: D-01, D-02, D-03, D-04, D-05, D-06, D-07, D-08
**Depends on:** v1.0 MVP (Phase 5)
**Plans:** 3 plans

Plans:
- [x] 01-01-PLAN.md — Create gigaevo manifest CLI subcommand (get/set/update/gate/pr-description)
- [x] 01-02-PLAN.md — Delete project-pm + update batch 1 skills (design, implement, diagnose, scheduler, optimize, anomaly-detector)
- [x] 01-03-PLAN.md — Update batch 2 skills (launch, closeout, checkpoint, restart, run-experiment)

### Phase 2: Fix adversarial injection logic and watchdog plots

**Goal:** Fix three critical bugs in the adversarial co-evolution pipeline: (1) rewrite CompositionInjectionHook to compose D(G) as valid G programs and wire it into the engine, (2) create D-G improvement tracking and integrate per-program D selection into GradientInPromptStage, (3) fix watchdog plots by filtering sentinel values and using correct adversarial metrics/formats.
**Requirements**: Bug fixes — no formal requirement IDs
**Depends on:** Phase 1
**Plans:** 3 plans

Plans:
- [x] 02-01-PLAN.md — Fix watchdog plots: sentinel filtering + correct metric + arms-race format
- [x] 02-02-PLAN.md — Rewrite CompositionInjectionHook + add post_step_hook to engine
- [x] 02-03-PLAN.md — D-G improvement tracker + per-program D selection in GradientInPromptStage

### Phase 3: Fix CLI metrics reporting and manifest wiring for adversarial experiments

**Goal:** Propagate metric discovery from metrics.yaml to all CLI commands and the watchdog engine so that all experiment types (standard, feedback, adversarial, prompt co-evolution, heilbron) get correct multi-metric reporting, formatted display, and proper plugin resolution.
**Requirements**: MON-05, CLI-03, MAN-02, MON-03
**Depends on:** Phase 2
**Plans:** 2 plans

Plans:
- [x] 03-01-PLAN.md — Fix metric discovery in watchdog_cmd, trajectory, top + add manifest watchdog_plugin field
- [x] 03-02-PLAN.md — Fix status/checkpoint metric formatting + wire analyze/collect into CLI registry

### Phase 4: Wire GSD into experiment lifecycle skills for robust implementation and debugging

**Goal:** Wire GSD plan generation into experiment-implement and experiment-launch skills, add event auto-capture to all lifecycle skills, establish Known Failures in PATTERNS.md, and add fix tracking reports to post-experiment-fixes.
**Requirements**: D-01, D-02, D-03, D-04, D-05, D-06, D-07, D-08, D-09, D-10
**Depends on:** Phase 3
**Plans:** 4 plans

Plans:
- [x] 04-01-PLAN.md — Foundation: issues log template update (EVENT/ISSUE) + PATTERNS.md Known Failures section
- [x] 04-02-PLAN.md — Wire GSD plan generation into experiment-implement and experiment-launch
- [x] 04-03-PLAN.md — Event auto-capture in experiment-restart, checkpoint, and diagnose
- [x] 04-04-PLAN.md — Pattern promotion in closeout + fix tracking in post-experiment-fixes

### Phase 5: Polish CLI/watchdog/manifest wiring and eliminate legacy tools/ imports

**Goal:** Make the watchdog, CLI, and observability stack reliable for any experiment type. Eliminate guesswork in plugin resolution (explicit or solo fallback). Consolidate dual manifest system (Pydantic vs legacy dataclass). Remove all `tools/` imports from `gigaevo/cli/` and `gigaevo/monitoring/`. Merge heilbron plugin into adversarial. Ensure agents can invoke CLI commands without crashes.
**Requirements**: Bug fixes + reliability — derived from 04_issues_log.md Known Failures and CLI audit
**Depends on:** Phase 4
**Plans:** 4 plans

Plans:
- [ ] 05-01-PLAN.md — Create migration target modules: manifest ops, flush ops, dataframes, plotting
- [ ] 05-02-PLAN.md — Rewrite plugin resolution + merge heilbron into adversarial
- [ ] 05-03-PLAN.md — Replace all tools/ imports in CLI + register manifest subcommand
- [ ] 05-04-PLAN.md — Audit skills and agents for CLI correctness + update CLAUDE.md

---
*Roadmap created: 2026-04-11*
*Last updated: 2026-04-13 — Phase 5 planned (4 plans, 3 waves)*
