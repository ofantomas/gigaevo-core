# Phase 4: Wire GSD into Experiment Lifecycle Skills - Research

**Researched:** 2026-04-13
**Domain:** Experiment lifecycle skill integration, structured planning, post-mortem automation
**Confidence:** HIGH

## Summary

This phase modifies Claude Code skill files (Markdown) and adds new experiment artifacts/skills to make experiment implementation and launch more robust through structured GSD planning, and to automate post-mortem issue capture and cross-experiment learning. The primary artifacts are: (1) modifications to `experiment-implement` and `experiment-launch` SKILL.md files to wire GSD plan generation and execution, (2) auto-capture hooks in lifecycle skills for `04_issues_log.md`, (3) structured "known failure" entries in `experiments/PATTERNS.md`, and (4) a `06_fixes_applied.md` generation step in `post-experiment-fixes`.

The domain is entirely internal to the project -- no external libraries, no new Python packages, no infrastructure changes. All modifications target Markdown skill files, the PATTERNS.md knowledge store, and experiment templates. The complexity is in understanding the existing skill architecture and GSD plan format well enough to wire them together correctly.

**Primary recommendation:** Modify skill SKILL.md files in place, adding GSD plan generation and execution steps. Use a centralized event-logging helper function (bash function or Python utility) called from each skill rather than duplicating auto-capture logic across skills.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Wire full GSD planning cycle (discuss->plan->execute) into `experiment-implement` and `experiment-launch` skills. Each invocation creates a GSD PLAN.md with atomic tasks, then executes via gsd-executor with atomic commits and verification.
- **D-02:** GSD plans for experiments live inside `experiments/<task>/<name>/plans/` -- keeps everything together with other experiment artifacts (design, review, results).
- **D-03:** Plan auto-generation: parse `01_design.md` (treatment, config, code changes) to auto-create a PLAN.md with atomic tasks. No interactive discussion -- the design IS the spec.
- **D-04:** Hybrid review gate: auto-generated plan is presented for user approval before execution begins. Fast but with a human checkpoint.
- **D-05:** Only `experiment-implement` and `experiment-launch` get GSD planning. Design, closeout, checkpoint, and restart are simpler and don't need full GSD.
- **D-06:** Auto-populate `04_issues_log.md` from full event stream: watchdog alerts, `/experiment-restart` invocations, checkpoint anomalies, launch failures, and manual interventions.
- **D-07:** Each lifecycle event (launch, restart, checkpoint, watchdog alert) auto-appends a structured entry to `04_issues_log.md` with timestamp, category, and description.
- **D-08:** Extend `experiments/PATTERNS.md` with structured "known failure" entries: trigger condition, symptoms, fix reference, affected experiment types. Preflight and experiment-implement can query these to avoid repeating known mistakes.
- **D-09:** After each experiment closeout, new patterns discovered in `04_issues_log.md` should be promoted to `PATTERNS.md` (via `/post-experiment-fixes`).
- **D-10:** `/post-experiment-fixes` generates a `06_fixes_applied.md` report mapping each issue to its fix commit or deferral reason.

### Claude's Discretion
- Exact format of auto-generated GSD plans from `01_design.md` -- follow GSD PLAN.md conventions
- How lifecycle events are captured (hook in each skill vs centralized event logger)
- Structure of "known failure" entries in PATTERNS.md -- whatever format is easiest for preflight to consume
- Whether `06_fixes_applied.md` is auto-generated or requires manual `/post-experiment-fixes` invocation

### Deferred Ideas (OUT OF SCOPE)
- Verification gates between lifecycle phases
- Auto-advance chains for experiment lifecycle
- Preflight check expansion from PATTERNS.md
- diagnose.py redesign
- resource_manager.py redesign
</user_constraints>

## Architecture Patterns

### Current Skill Architecture

All experiment lifecycle skills are Markdown files in `.claude/skills/experiment-*/SKILL.md`. They are instruction documents that Claude Code follows step-by-step when invoked via `/skill-name`. Each skill has:

1. YAML frontmatter (name, description, argument-hint, model)
2. Sequential steps with bash code blocks
3. Gate checks (status assertions via `gigaevo manifest gate`)
4. Human approval gates at critical points
5. A "Gotchas" section at the end

Skills are NOT executable scripts -- they are prompts that Claude Code reads and follows. Modifications are text edits to Markdown. [VERIFIED: direct file reads of all 8 lifecycle skills]

### GSD Plan Format

GSD plans use a structured PLAN.md format with YAML frontmatter and XML-like task definitions. Key elements: [VERIFIED: read of phase-prompt.md template and existing 01-01-PLAN.md]

```
---
phase: XX-name
plan: NN
type: execute
wave: N
depends_on: []
files_modified: []
autonomous: true
requirements: []
must_haves:
  truths: []
  artifacts: []
  key_links: []
---

<objective>...</objective>
<execution_context>...</execution_context>
<context>...</context>
<tasks>
  <task type="auto">
    <name>Task N: [Action]</name>
    <files>path/to/file.ext</files>
    <action>[Specific implementation]</action>
    <verify>[Check command]</verify>
    <done>[Acceptance criteria]</done>
  </task>
</tasks>
```

### Recommended Integration Architecture

#### For experiment-implement (D-01, D-03, D-04)

Current flow:
```
Step 0: Gate check -> Step 1: Read CONTEXT -> Step 2: Read review
-> Step 3: Phase order check -> Step 4: Research patterns
-> Step 4a: Plan with superpowers:writing-plans
-> Step 5: GitNexus check -> Step 5a: Implement code/config
-> Steps 6-15: Test, review, manifest, smoke, commit, verify
```

New flow (insert between Steps 4 and 5):
```
Step 4a: Parse 01_design.md -> auto-generate PLAN.md
         in experiments/<task>/<name>/plans/implement-PLAN.md
Step 4b: Present plan to researcher for approval (D-04 gate)
Step 4c: Execute plan tasks sequentially with atomic commits
```

The existing Step 4a (`superpowers:writing-plans`) is the natural upgrade point -- replace it with full GSD plan generation. [VERIFIED: experiment-implement SKILL.md Step 4a references superpowers:writing-plans]

#### For experiment-launch (D-01, D-05)

Current flow:
```
Step 0: Gate -> Steps 1-5: Context, preflight, config dump, server capture, env freeze
-> Step 5a: Commit pre-launch artifacts
-> Step 6: Researcher confirms -> Step 7: Launch
-> Steps 8-12: PID verify, status, watchdog, PR, commit
```

New flow (insert at beginning):
```
Step 0a: Parse experiment.yaml runs -> auto-generate launch-PLAN.md
         in experiments/<task>/<name>/plans/launch-PLAN.md
Step 0b: Present plan (shows run matrix, server assignments, DB allocations)
Step 0c: Execute plan tasks
```

Launch is more mechanical (fewer code changes, more config verification), so its plan will be simpler -- mostly a checklist of preflight, config dump, and launch steps with explicit verification at each stage. [VERIFIED: experiment-launch SKILL.md shows 13 sequential steps]

### Event Auto-Capture Architecture (D-06, D-07)

**Recommended approach: Per-skill inline hooks** (not centralized logger).

Rationale: Skills are Markdown instruction files, not executable code. There is no centralized event bus or logging framework to hook into. Each skill already has explicit bash code blocks where events occur. The simplest, most reliable approach is to add a bash snippet at each event point that appends to `04_issues_log.md`. [ASSUMED]

Event capture points identified across lifecycle skills:

| Skill | Event | Trigger Point |
|-------|-------|---------------|
| experiment-launch | Launch started | After Step 7 (launch.sh execution) |
| experiment-launch | Watchdog started | After Step 10 |
| experiment-launch | Launch failed | Any step failure |
| experiment-restart | Restart initiated | After Step 2 (confirmation) |
| experiment-restart | Archive completed | After Step 2a |
| experiment-restart | Flush completed | After Step 4 |
| experiment-checkpoint | Checkpoint recorded | After Step 8 |
| experiment-checkpoint | Anomaly detected | After Step 4 (diagnose findings) |
| experiment-checkpoint | Stopping rule triggered | After Step 2a |
| experiment-checkpoint | Test eval triggered | After Step 6 |
| experiment-closeout | Closeout started | After Step 0 |
| experiment-diagnose | Critical/Major findings | After Step 8 (report) |

A bash helper function at the top of each skill simplifies the capture:

```bash
log_event() {
  local EXP="$1" WHEN="$2" WHAT="$3" CATEGORY="$4"
  local PROJ="$(git rev-parse --show-toplevel)"
  local LOG="$PROJ/experiments/$EXP/04_issues_log.md"
  [ ! -f "$LOG" ] && cp "$PROJ/experiments/_template/04_issues_log.md" "$LOG"
  cat >> "$LOG" << ENTRY

### $WHEN — $WHAT

- **When**: $WHEN
- **What**: $WHAT
- **Category**: $CATEGORY
- **Impact**: [auto-logged event]
- **Root cause**: N/A (automated capture)
- **Fix applied**: N/A
- **Systemic fix needed**: NO
ENTRY
}
```

### Known Failure Pattern Structure (D-08)

Extend `experiments/PATTERNS.md` with a new section: `## Known Failures`. Each entry should be structured for preflight consumption:

```markdown
## Known Failures

| ID | Trigger | Symptoms | Fix | Affected Types | Ref |
|----|---------|----------|-----|----------------|-----|
| KF-01 | adversarial pipeline + `evolution=generational` missing | Runs deadlock at gen 0 | Add `evolution=steady_state` to extra_overrides | adversarial | heilbron/asymmetric-iterations#1 |
| KF-02 | Hydra `${}` interpolation in extra_overrides | launch.sh expands as empty shell var | Single-quote all `${}` refs in generate_launch.py | all | heilbron/asymmetric-iterations#1 |
```

This tabular format is easy for both humans and Claude to parse during `/experiment-implement` Step 4 (research existing patterns). [ASSUMED]

### Fix Tracking Output (D-10)

`06_fixes_applied.md` should be generated by `/post-experiment-fixes` after processing `04_issues_log.md`. Format:

```markdown
# Fixes Applied: <task/name>

**Generated:** <date>
**Source:** 04_issues_log.md (<N> entries processed)

| # | Issue Summary | Fix Type | Files Changed | Status | Commit/Reason |
|---|--------------|----------|---------------|--------|----------------|
| 1 | description | template/tool/skill/core | file.py | DONE | abc1234 |
| 2 | description | skill update | SKILL.md | DEFERRED | Needs design discussion |
```

This maps directly to the existing Step 6 summary format in post-experiment-fixes/SKILL.md. [VERIFIED: post-experiment-fixes SKILL.md Step 6]

### Plan Auto-Generation from 01_design.md (D-03)

The `01_design.md` contains structured sections that map directly to plan tasks:

| Design Section | Maps to Plan Task |
|---------------|-------------------|
| Treatment specification (files, classes, Hydra overrides) | Code implementation tasks |
| Config specification (pipeline, extra_overrides) | Config file creation tasks |
| Control invariants | Verification tasks |
| Treatment verification (observable evidence) | Smoke test verification tasks |

The plan generator should read `01_design.md` and `codebase_map.md` (if exists from design phase), then produce a PLAN.md with tasks for:
1. Creating/modifying experiment-specific code (pipeline configs, validate.py, etc.)
2. Filling experiment.yaml fields (runs, servers, config, custom_env)
3. Generating launch.sh
4. Writing watchdog and test eval scripts
5. Running treatment verification
6. Running implementation alignment check
7. Running smoke test

Each task has explicit files, actions, and verification criteria. [VERIFIED: these are the existing steps in experiment-implement SKILL.md Steps 5a-12]

### Recommended Project Structure for Plans

```
experiments/
  <task>/
    <name>/
      plans/                    # NEW: GSD plans for this experiment
        implement-PLAN.md       # Auto-generated from 01_design.md
        implement-SUMMARY.md    # Created after execution
        launch-PLAN.md          # Auto-generated from experiment.yaml
        launch-SUMMARY.md       # Created after execution
      01_design.md
      02_review.md
      03_plan.md               # Scientific plan (separate from GSD plan)
      04_issues_log.md
      05_results.md
      06_fixes_applied.md      # NEW: generated by /post-experiment-fixes
      experiment.yaml
      ...
```

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Plan format | Custom plan format | GSD PLAN.md template (phase-prompt.md) | Consistent with existing GSD infrastructure; executor understands it |
| Issue log format | New structured format | Existing 04_issues_log.md template | Already established, has field structure, understood by closeout |
| Pattern storage | Separate database/YAML | Existing PATTERNS.md with new section | Already read by all agents; single source of truth |
| Event logging | Complex event bus | Inline bash snippets in skills | Skills are Markdown, not code; simplest reliable approach |

## Common Pitfalls

### Pitfall 1: Over-engineering the plan generator
**What goes wrong:** Attempting to parse 01_design.md with complex regex/NLP to auto-generate plans. The design doc is free-form Markdown written by an LLM agent.
**Why it happens:** Desire for full automation.
**How to avoid:** The plan generator IS Claude Code reading the design doc and producing a plan. The "auto-generation" is a prompt instruction in the skill, not a script. Claude reads 01_design.md, codebase_map.md, and the GSD plan template, then writes a PLAN.md.
**Warning signs:** Writing a Python script to parse Markdown design docs.

### Pitfall 2: Breaking existing skill flow
**What goes wrong:** Restructuring experiment-implement so heavily that the existing step numbering and gate logic breaks. Other skills (run-experiment, checkpoint) dispatch to experiment-implement and expect specific behavior.
**Why it happens:** GSD integration touches the core skill workflow.
**How to avoid:** ONLY modify the Step 4a insertion point. Keep all other steps and their numbering intact. Add new steps (4a, 4b, 4c) at the existing insertion point.
**Warning signs:** Renumbering existing steps, removing gate checks, changing the skill's frontmatter.

### Pitfall 3: Circular dependency between plan execution and skill steps
**What goes wrong:** The generated plan includes tasks for "run smoke test" and "set status to implemented" but these are already explicit steps in experiment-implement (Steps 11-13). The plan executor and the skill both try to do the same thing.
**Why it happens:** Unclear boundary between what the GSD plan covers vs what the remaining skill steps cover.
**How to avoid:** The GSD plan covers Steps 5-10 (code, config, manifest, launch.sh, watchdog, treatment verification). Steps 11+ (smoke test, status update, commit) remain as explicit skill steps OUTSIDE the plan. The plan's scope is "produce all artifacts needed for smoke test."
**Warning signs:** Plan tasks that duplicate later skill steps.

### Pitfall 4: Auto-capture noise drowning signal
**What goes wrong:** Every lifecycle event writes to 04_issues_log.md, making it 100+ entries of "CHECKPOINT gen=5 -- No deviations. All runs healthy" with the actual problems buried.
**Why it happens:** D-06 says "full event stream" and D-07 says "each lifecycle event."
**How to avoid:** Distinguish between EVENTS (logged always, brief) and ISSUES (logged when something goes wrong, detailed). Events get a one-line entry; issues get the full structured format. Use a different heading format: `### [EVENT ...]` vs `### [ISSUE ...]`.
**Warning signs:** Issues log growing to hundreds of entries per experiment, most with "Impact: N/A".

### Pitfall 5: PATTERNS.md known failures becoming stale
**What goes wrong:** Known failure entries are added but never pruned when the underlying bug is fixed. New experiments read stale warnings.
**Why it happens:** No lifecycle for known failure entries.
**How to avoid:** Each known failure entry should have a "Status" field (ACTIVE/FIXED) and a "Fixed in" reference. The `/post-experiment-fixes` skill should update status when a fix is applied.
**Warning signs:** Known failures with no status field.

## Code Examples

### Example: Modified experiment-implement Step 4a (GSD Plan Generation)

```markdown
## Step 4a -- Generate GSD implementation plan

Read `experiments/$EXP/01_design.md` and `experiments/$EXP/codebase_map.md` (if exists).
Read `experiments/PATTERNS.md` section "Known Failures" for failure patterns relevant to this experiment type.

Create `experiments/$EXP/plans/implement-PLAN.md` following the GSD plan format:

```bash
EXP='$ARGUMENTS'
PROJ="$(git rev-parse --show-toplevel)"
mkdir -p "$PROJ/experiments/$EXP/plans"
```

Generate the plan with these task categories:
1. **Code tasks**: Create/modify experiment-specific code (pipeline configs, validate.py, prompts)
2. **Config tasks**: Fill experiment.yaml (runs, servers, config, custom_env)
3. **Script tasks**: Generate launch.sh, write watchdog, write test eval
4. **Verification tasks**: Treatment verification checks, implementation alignment check

Each task must have:
- Explicit file paths (from codebase_map.md if available)
- Concrete acceptance criteria
- Known failure avoidance (from PATTERNS.md)

## Step 4b -- Researcher approves plan

Present the generated plan summary to the researcher:
- Number of tasks
- Files to be created/modified
- Known failure mitigations included
- Estimated scope

Ask: "Implementation plan generated at `experiments/$EXP/plans/implement-PLAN.md`. 
Review and approve? (yes/revise/abort)"

## Step 4c -- Execute plan

Execute each task in the plan sequentially. For each task:
1. Read the task specification
2. Implement the change
3. Run the verification check
4. Commit atomically (if task modifies files)

After all plan tasks complete, create `experiments/$EXP/plans/implement-SUMMARY.md`.
```

### Example: Event auto-capture in experiment-restart

```markdown
## Step 2 -- Confirm with researcher

Ask: "About to kill all runs for $ARGUMENTS and flush Redis DBs..."

Do NOT proceed without explicit confirmation.

After confirmation, log the restart event:
```bash
EXP='$ARGUMENTS'
PROJ="$(git rev-parse --show-toplevel)"
LOG="$PROJ/experiments/$EXP/04_issues_log.md"
[ ! -f "$LOG" ] && cp "$PROJ/experiments/_template/04_issues_log.md" "$LOG"
GEN_INFO=$(gigaevo -e "$EXP" manifest get runs --format json | \
  $GIGAEVO_PYTHON -c "
import sys, json, redis
runs = json.load(sys.stdin)
for run in runs:
    db = int(run.get('DB') or run.get('db'))
    prefix = run.get('Prefix') or run.get('prefix')
    label = run.get('Label') or run.get('label')
    r = redis.Redis(host='localhost', port=6379, db=db)
    gen = int(r.hget(f'{prefix}:run_state', 'engine:total_generations') or 0)
    print(f'{label}=gen{gen}', end=' ')
")

cat >> "$LOG" << ENTRY

### [EVENT $(date -u +%Y-%m-%dT%H:%M:%SZ)] -- Experiment restart initiated

- **When**: $(date -u +%Y-%m-%dT%H:%M:%SZ)
- **What**: Full experiment restart. Progress at restart: $GEN_INFO
- **Category**: restart
- **Impact**: All run progress destroyed. Redis DBs flushed.
ENTRY
echo "Restart event logged to 04_issues_log.md"
```

### Example: Known failure entry in PATTERNS.md

```markdown
## Known Failures

Structured entries for preflight and experiment-implement to check proactively.
Updated by `/post-experiment-fixes` and `/experiment-closeout`.

| ID | Trigger Condition | Symptoms | Root Cause | Fix | Status | Affected Types | Source |
|----|-------------------|----------|------------|-----|--------|----------------|--------|
| KF-01 | adversarial pipeline + missing `evolution=steady_state` | Deadlock at gen 0 | MainRunSyncHook waits on total_generations incremented after hook call | Override pre_step_hook to ProgressBasedSyncHook; or add evolution=steady_state | FIXED (e69021c0) | adversarial | heilbron/asymmetric-iterations |
| KF-02 | extra_overrides containing `${}` Hydra refs | launch.sh expands as empty shell variable | generate_launch.py does not quote Hydra interpolation refs | Single-quote `${}` refs in extra_overrides | FIXED (fdd3dae1) | all | heilbron/asymmetric-iterations |
| KF-03 | Missing `population_role` in adversarial_asymmetric runs | Pipeline cannot differentiate G vs D roles | experiment.yaml missing per-run role overrides | Add population_role=constructor/improver per run | ACTIVE | adversarial_asymmetric | heilbron/asymmetric-iterations |
| KF-04 | CompositionInjectionHook programs missing `iteration` field | MetricsTracker crashes on KeyError, kills entire tracker async task | Programs created without iteration in metadata | Promote iteration to typed Program field with default=0 | FIXED | adversarial with composition | heilbron/asymmetric-iterations |
```

### Example: 06_fixes_applied.md output

```markdown
# Fixes Applied: heilbron/asymmetric-iterations

**Generated:** 2026-04-13
**Source:** 04_issues_log.md (5 entries processed)

| # | Issue | Fix Type | Files Changed | Status | Commit/Reason |
|---|-------|----------|---------------|--------|----------------|
| 1 | Orphan processes repopulating Redis after flush | N/A | -- | SKIPPED | Self-resolving race condition |
| 2 | Full experiment restart from config issues | config/skill | experiment.yaml, launch.sh | DONE | 5a36157d, 3fd6bfce, fdd3dae1 |
| 3 | MainRunSyncHook deadlock in SteadyState | config | adversarial_asymmetric.yaml | DONE | e69021c0 |
| 4 | MetricsTracker crash on missing iteration | core code | gigaevo/core/program.py, gigaevo/monitoring/metrics_tracker.py | DONE | (commit) |
| 5 | Watchdog plugin hardcodes task names | tool | gigaevo/monitoring/watchdog_plugin.py | DEFERRED | Needs design discussion (plugin resolution chain) |

**Summary:** 3 fixed, 1 skipped, 1 deferred
**Patterns promoted to PATTERNS.md:** KF-01, KF-02, KF-03, KF-04
```

## Files to Modify

### Skills (primary targets)

| File | Modification | Scope |
|------|-------------|-------|
| `.claude/skills/experiment-implement/SKILL.md` | Replace Step 4a with GSD plan generation (4a-4c). Add event auto-capture at key failure points. | D-01, D-03, D-04, D-07 |
| `.claude/skills/experiment-launch/SKILL.md` | Add GSD plan generation (Step 0a-0c) before existing steps. Add event auto-capture at launch/watchdog events. | D-01, D-05, D-07 |
| `.claude/skills/experiment-restart/SKILL.md` | Add event auto-capture at restart confirmation and flush completion. | D-06, D-07 |
| `.claude/skills/experiment-checkpoint/SKILL.md` | Add event auto-capture at checkpoint recording and anomaly detection. | D-06, D-07 |
| `.claude/skills/experiment-closeout/SKILL.md` | Add pattern promotion step (issue->PATTERNS.md) before merge. | D-09 |
| `.claude/skills/experiment-diagnose/SKILL.md` | Add event auto-capture for critical/major findings. | D-06, D-07 |
| `.claude/skills/post-experiment-fixes/SKILL.md` | Add 06_fixes_applied.md generation step. Update PATTERNS.md known failure statuses. | D-09, D-10 |

### Knowledge stores

| File | Modification | Scope |
|------|-------------|-------|
| `experiments/PATTERNS.md` | Add "Known Failures" section with structured entries from existing issues logs. | D-08 |
| `experiments/_template/04_issues_log.md` | Add EVENT vs ISSUE format guidance. | D-07 |

### New files

| File | Purpose | Scope |
|------|---------|-------|
| `experiments/<task>/<name>/plans/implement-PLAN.md` | Auto-generated per experiment (not a template) | D-02, D-03 |
| `experiments/<task>/<name>/plans/launch-PLAN.md` | Auto-generated per experiment (not a template) | D-02, D-05 |
| `experiments/<task>/<name>/06_fixes_applied.md` | Generated by /post-experiment-fixes | D-10 |

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `superpowers:writing-plans` free-form | GSD PLAN.md with atomic tasks and verification | This phase | Structured, repeatable, auditable implementation |
| Manual issues log entries | Auto-capture from lifecycle events | This phase | Comprehensive event trail without manual effort |
| Issues stay per-experiment | Known failures promoted to PATTERNS.md | This phase | Cross-experiment learning prevents recurrence |
| No fix tracking | 06_fixes_applied.md report | This phase | Clear audit of what was fixed vs deferred |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Per-skill inline hooks are better than a centralized event logger for auto-capture | Architecture Patterns | Low -- if centralized is better, refactoring is straightforward (move snippets to one file) |
| A2 | The tabular format for Known Failures in PATTERNS.md is optimal for preflight consumption | Architecture Patterns | Low -- format can be adjusted; the content matters more |
| A3 | GSD plan scope should cover Steps 5-10 of experiment-implement, NOT Steps 11+ (smoke test, status, commit) | Common Pitfalls | Medium -- if scope is wrong, plan and skill steps may conflict |

## Open Questions

1. **How should the plan generator handle novel experiment types?**
   - What we know: `01_design.md` and `codebase_map.md` provide the specification. Standard experiments (solo, adversarial) have well-known patterns.
   - What's unclear: For truly novel mechanism types (e.g., new pipeline builder, new evaluation approach), the plan generator may not have enough patterns to draw from.
   - Recommendation: Include a "novel mechanism" flag in the plan that triggers additional human review of implementation tasks.

2. **Should event auto-capture include watchdog alert text?**
   - What we know: D-06 says "watchdog alerts" should be captured. Watchdog writes Telegram messages and PR comments already.
   - What's unclear: Whether the full watchdog alert text should be duplicated into 04_issues_log.md, or just a reference.
   - Recommendation: Log a brief event entry with severity and a one-line summary. Full alert text lives in watchdog.log and PR comments.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (existing) |
| Config file | `pyproject.toml` |
| Quick run command | `/run-tests tests/cli/` |
| Full suite command | `/run-tests` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| D-01 | GSD plan generated for experiment-implement | manual-only | Verify SKILL.md contains plan generation steps | N/A (Markdown) |
| D-02 | Plans live in experiments/<task>/<name>/plans/ | manual-only | Verify SKILL.md references correct path | N/A (Markdown) |
| D-03 | Plan auto-generated from 01_design.md | manual-only | Verify SKILL.md parsing instructions | N/A (Markdown) |
| D-04 | Hybrid review gate before execution | manual-only | Verify SKILL.md has approval gate | N/A (Markdown) |
| D-05 | Only implement+launch get GSD | manual-only | Verify other skills unchanged | N/A (Markdown) |
| D-06 | Auto-capture from full event stream | manual-only | Verify capture snippets in all lifecycle skills | N/A (Markdown) |
| D-07 | Structured log entries auto-appended | manual-only | Verify bash snippets write correct format | N/A (Markdown) |
| D-08 | Known failure entries in PATTERNS.md | manual-only | Verify new section exists with real entries | N/A (Markdown) |
| D-09 | Pattern promotion at closeout | manual-only | Verify closeout skill has promotion step | N/A (Markdown) |
| D-10 | 06_fixes_applied.md generation | manual-only | Verify post-experiment-fixes has generation step | N/A (Markdown) |

### Note on Testing
This phase modifies only Markdown skill files and knowledge stores -- there is no Python code to unit test. Validation is through manual review of the modified skill files to confirm:
1. New steps are correctly numbered and don't break existing flow
2. Bash code blocks are syntactically correct
3. Gate checks and human approval points are preserved
4. Event capture snippets write the correct format

### Wave 0 Gaps
None -- no test infrastructure needed for Markdown modifications.

## Sources

### Primary (HIGH confidence)
- Direct file reads of all 8 experiment lifecycle skills (experiment-design, implement, launch, checkpoint, closeout, diagnose, restart, run-experiment)
- Direct file read of GSD plan template (`phase-prompt.md`) and existing plans (`01-01-PLAN.md`)
- Direct file read of `experiments/PATTERNS.md`, `04_issues_log.md` from 2 experiments
- Direct file read of `post-experiment-fixes/SKILL.md`
- Direct file read of `04-CONTEXT.md` and `04-DISCUSSION-LOG.md` (locked decisions)

### Secondary (MEDIUM confidence)
- GSD workflow architecture from `execute-plan.md`

## Project Constraints (from CLAUDE.md)

- **TDD non-negotiable** -- however, this phase modifies only Markdown files, not Python code. No tests to write.
- **GitNexus pre-flight gates** -- since this phase modifies `.claude/skills/` Markdown files (not Python symbols), GitNexus impact analysis is not applicable. However, `gitnexus_detect_changes` should still be run before committing to verify scope.
- **Always use `/run-tests` skill** -- run after any changes to verify existing tests still pass (skills should not break framework behavior).
- **Always use `rtk git`** in bash, not plain `git`.
- **Use `gigaevo` CLI commands**, not `PYTHONPATH=. python tools/...`.

## Metadata

**Confidence breakdown:**
- Architecture: HIGH -- all target files read and understood; modification points clearly identified
- Integration pattern: HIGH -- GSD plan format and skill architecture are well-documented and stable
- Event capture design: MEDIUM -- the per-skill inline approach is the simplest but untested in practice
- Known failure format: MEDIUM -- format is reasonable but may need iteration after first use

**Research date:** 2026-04-13
**Valid until:** 2026-05-13 (stable domain -- Markdown skill files change infrequently)
