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

---
*Roadmap created: 2026-04-11*
*Last updated: 2026-04-12 — Phase 1 complete (3/3 plans, all skills migrated to gigaevo CLI)*
