# Memory System Quality Boost — Plan

**Branch**: TBD (suggest `feat/memory-quality-boost` once approved)
**Scope-frozen**: schema field names/types unchanged (parent-directive frozen-schema rule); no `ExtraMemoryStage` work; no further wholesale prompt rewrites (memory-prompts-v7 already converged twice).
**Out-of-scope**: card grammar redesign, swapping retriever backend, adding a 4th channel.

---

## 1. Premise — what we actually know

| Source | Finding | Confidence |
|---|---|---|
| `output/tabular_regression_intra_extra_20260523_161718/memory/api_index.json` (PRE-v4) | 18 idea cards: **11/18 (61%) specific mechanism, 7/18 (39%) vague/tautological** | high (graded by hand) |
| same | **dedup leakage**: `Removed target_log_transform log->raw` and `Replaced target_transform log->raw` survived as distinct cards; same for `n_clusters` 10→15 / 50→15; three population-transform variants (`household_count`, `log1p_population`, `household_count_train`) | high |
| same | **47/65 ProgramCards are `pending_analysis` stubs** (`"Top-N program ...; no recorded idea lineage - inspect `code` field for mechanism."`) — the post-run-hook analyzer ran but produced no real packed-grammar `description` for ~70% of top programs | high |
| same | Keywords are concrete (`l2 regularization`, `tree depth 7`, `n_clusters 15`) even on vague cards → **the keyword line is doing more useful work than the description line** for the mutator | medium (n=1 run, but striking) |
| `output/phase_c_smoke_20260524/memory/api_index.json` (POST-v4, n=1) | 1 ProgramCard, v4-compliant grammar, 0 idea cards (Qwen reasoning latency) | low (sample size) |

**Caveat that anchors everything below**: the 61% / dedup-leak / stub-dominance numbers are **PRE-v4**. The v4 prompt + wiring edits landed 2026-05-24 04:30+ MSK — **12h AFTER that run started**. So *before* we redesign anything we need a clean v4 baseline.

---

## 2. Causal chain (signal → behaviour → metric)

```
[poor card SPECIFICITY]      ──►  mutator picks levers but doesn't grok mechanism   ──►  archetype/justification drift, less directed search
[poor card DEDUP]            ──►  near-duplicate levers crowd top-K retrieval       ──►  mutator sees redundant suggestions, ignores diverse evidence
[ProgramCard STUB dominance] ──►  top programs lack any explanatory packed-grammar  ──►  cross-population transfer fails; mutator can't learn from peers
       │                                                                                            │
       └──────────────► fitness trajectory plateaus earlier, idea-bank size grows but information value flatlines ◄────────────┘
```

**Riskiest link**: the stub-dominance arrow. If 70% of top-program cards say "inspect code field," the entire ProgramCard channel collapses to "here are N pointers to source you must read yourself" — which is exactly what the packed grammar was supposed to remove.

**Quantitative predictions (to falsify after Phase A measurement on a fresh v4 run)**:
| Metric | Pre-v4 (observed) | v4 target | Fix-pack target |
|---|---|---|---|
| Idea-card mechanism specificity | 61% (11/18) | ≥70% | ≥85% |
| Duplicate-lever pairs surviving canonical-key | ≥3 of 18 (17%) | ≤2 of 18 (≤11%) | ≤1 of 18 (≤6%) |
| ProgramCard `pending_analysis` stub share | 72% (47/65) | ≤50% | ≤20% |
| Mutator `insights_used` citing card by `card:<rank>` form | not measured | TBD | ≥40% |
| Heilbron 800-mutant best fitness vs n=4 baseline 0.0365 | n/a (different task) | — | within ±5% (quality work shouldn't regress) |

If v4 alone hits the middle column, Workstreams B+C+D need to be re-scoped down. If v4 misses, the fix-pack targets become the gate.

---

## 3. Phase A — Measure v4 ground truth (gate before any code change)

**Goal**: produce the right-hand column of the table above on FRESH v4 output, not pre-v4 data.

### A.1 Build a measurement harness (one-shot tool, not framework-promoted)
- New script `tools/memory_quality_audit.py` taking `--run-dir` and emitting one row per card + summary metrics.
- Reads `<run-dir>/memory/api_index.json`, splits by `category` (`general` vs `program`).
- Per-card features extracted (regex on `description`, parsed via `parse_packed_description` where possible):
  - `parses_v4` — boolean (does it match `_PACKED_RE`?)
  - `verb_stem`, `target_stem`, `mechanism_text`, `support`, `delta_best`, `unverified`
  - `mechanism_word_count`, `mechanism_has_tautology_template` (regex against curated list — see A.2)
  - `keywords_concrete_count` (numeric tokens, identifier-like tokens)
- Per-store metrics:
  - **specificity_rate**: `mechanism_has_tautology_template == False` count / total parses
  - **dedup_collisions**: group by `(verb_stem_normalized, target_stem_normalized_lev1)` — collision = >1 card per group; report pairs
  - **stub_rate**: ProgramCards whose `description` matches `^Top-\d+ program.*pending_analysis|no recorded idea lineage` / total ProgramCards
  - **verb_distribution**, **archetype_distribution** (sanity)

### A.2 Tautology template list (seed; refine after first pass)
The PRE-v4 vague clauses fell into 6 templates:
1. `"models complex .* interactions"` (depth #03)
2. `"captures .* patterns"` (geo #04, density #15)
3. `"allows more complex .* without overfitting"` (l2_leaf_reg #06)
4. `"fundamental .* for "` (demographic #07)
5. `"reflects .* in "` (urban/rural #17)
6. `"captures .* per "` (efficiency #14)

These are the seeds for `mechanism_has_tautology_template`. The harness flags matches; specificity is `1 - tautology_rate` after parsing succeeds.

### A.3 Run a v4 baseline (the single experimental dependency)
Two options, pick one:
- **(cheap)** `pipeline=intra_extra_memory` on `heilbron`, ~200 mutants, ~1.5h on Qwen proxy — but Qwen-Thinking latency cap risks producing few idea cards (see phase_c smoke postmortem).
- **(better)** `pipeline=intra_extra_memory` on `tabular_regression` (matches the dataset we already graded), ~200-400 mutants. Same CLI as the existing 800-mutant run but with current `HEAD`.

**Mirror-baseline rule (feedback-mirror-baseline-exactly)**: copy the launch CLI from `tabular_regression_intra_extra_20260523_161718/.hydra/config.yaml` verbatim, only swap `redis.db` + `hydra.run.dir`. Do NOT add new overrides.

**Gate**: results of A.3 → run harness from A.1 → compare to the v4-target column. If we MEET all v4 targets, Workstreams B/C/D collapse to "don't bother, file as future-quality-work." If we MISS, the fix-pack targets become the work plan.

---

## 4. Phase B — Workstreams (ordered by leverage, gated on Phase A)

### WS-B: Dedup canonical-key normalization
**Hypothesis**: target-stem variation (`target_log_transform` vs `target_transform`) bypasses canonical-key dedup. v4's 5-verb collapse helps verb-side; target-side still leaks.

**Touch**:
- `gigaevo/memory/ideas_tracker/idea_bank.py:93-96` — `derive_canonical_key()`
- Add stem-suffix stripping: `target_log_transform` → `target_transform`, `household_count_train` → `household_count`, `log1p_population` → `log1p_population` (no-op).
- Strategy: TDD. Tests in `tests/memory/test_canonical_key_dedup.py` covering the exact PRE-v4 collision pairs (#00/#01, #07/#10, #11/#13) — each must canonicalize to ONE key.
- **Don't over-normalize**: `n_neighbors` vs `n_clusters` are different levers, not stems of the same lever. Stem stripping operates on a small whitelist (`_train`, `_log_transform`, `_clip_upper`, `_clip_lower`), not generic suffix removal.

**Stop rule**: if after WS-B the harness reports duplicate-lever rate ≤6%, ship it; if not, the gap is in target-name choice (LLM-side), and we add a normalization pass in `parse_packed_description` instead.

### WS-C: ProgramCard analysis path — kill the stub dominance
**Hypothesis**: 47/65 stubs means the post-run-hook ProgramCard analyzer is failing/skipping on most top programs, falling back to `pending_analysis:true`. Pre-v4 root cause unknown; v4 wiring (`gigaevo/llm/agents/lineage.py`, `gigaevo/entrypoint/lineage_memory_pipeline.py`) touched this path but we don't know if it fixed the failure mode.

**Steps**:
1. Diagnostic (Phase A.3 output already gives us this): grep the stub cards' `program_id`s in `run.log` for the lineage-agent invocation result. Three possible failure modes: (a) LLM timeout/empty, (b) program too large for context, (c) lineage-agent disabled by config, (d) `mutator.changes[]` empty on those programs so packed-grammar synthesis has no source.
2. Touch site depends on failure mode found. Likely candidates:
   - `gigaevo/llm/agents/lineage.py` — retry/fallback when LLM returns empty.
   - `gigaevo/entrypoint/lineage_memory_pipeline.py` — gating logic that decides whether to call lineage-agent at all.
   - `gigaevo/memory/shared_memory/card_search.py:322` — stub fallback writes `keywords=["pending_analysis:true", ...]`; check who calls it and why.
3. **Don't add silent fallbacks** (feedback-no-defensive-coding) — if lineage-agent fails, log loudly and emit a `keywords=["analysis_failed:<reason>"]` ProgramCard instead of a generic stub.

**Stop rule**: stub_rate ≤20% on a fresh run. If we can't get below 50% even with a clean diagnosis, escalate as "lineage-agent is unfit for purpose, redesign needed" — separate work item.

### WS-D: Mechanism specificity validator (post-emission)
**Hypothesis**: even with v4 prompts, ~15-30% of mechanism clauses will still match the 6 tautology templates. Prompt fixes have hit diminishing returns; a post-emission validator is more reliable than another prompt iteration.

**Touch**:
- New module `gigaevo/memory/quality/mechanism_validator.py` containing:
  - `is_tautology(clause: str) -> bool` — regex against the curated template list from A.2 (extended after Phase A run reveals v4-era templates).
  - `validate_or_flag(card) -> card_with_keywords` — if tautology detected, append `"low_specificity:true"` keyword. Card still enters the store (don't lose the lever) but mutator-side ranker can downrank.
- Wire into `gigaevo/memory/write_pipeline.py` after parse_packed_description succeeds.
- Mutator-side: `gigaevo/llm/agents/memory_selector.py` already filters by keywords; teach it to downrank `low_specificity:true` cards.

**NO prompt rewrite as part of this WS**. Per feedback-memory-prompts-v7-bundle: prompts are frozen.

**Stop rule**: idea-card specificity ≥85% (post-validator: any card with `low_specificity:true` counts as non-specific). If validator catches >50% of cards, the tautology list is too aggressive — refine before shipping.

### WS-E: (deferred) Mutator citation telemetry
Measure how often the mutator's `insights_used` actually cites a `card:<rank>: <idea>` token vs falling back to `tried:` / `plateau:` / no-citation. If <20% citation rate, the cards aren't being read regardless of their quality — that's a SEPARATE problem (prompt or retrieval, not card content). Park until Phase A finishes.

---

## 5. Sequencing & gates

```
Phase A.1 (harness, ~1 day)
     │
     ├─►  Phase A.3 (v4 baseline run, ~1.5-3h compute + grade)
     │           │
     │           ├─► PASS all v4 targets  ──►  STOP, file as done
     │           │
     │           └─► MISS some targets    ──►  open WS-B / WS-C / WS-D as needed
     │                                                │
     │                                                ├─► WS-B (TDD, ~1 day)
     │                                                ├─► WS-C (diagnostic-driven, ~1-3 days)
     │                                                └─► WS-D (validator, ~1 day)
     │
     └─►  Final v4+fix re-run (mirror A.3 CLI), re-grade, ship if fix-pack targets met
```

**Hard gate between A.1 and A.3**: harness must reproduce the PRE-v4 grades (11/18 specific, 3 dedup pairs, 47/65 stubs) on the existing run before we trust it on v4 data. If the harness disagrees with my hand-grading by >2 cards in either direction, the harness needs fixing first.

**Hard gate between A.3 and WS-B/C/D**: write to `docs/audits/memory_quality_v4_baseline.md` with the actual numbers before opening any WS PR.

**Commit policy**: per feedback-commit-approval, no autonomous commits. Each WS lands as one PR after explicit user approval. Harness lands as its own PR (it's a measurement tool, not a behavior change).

---

## 6. Out of scope (explicit)

- **No prompt edits** in this plan. v4 prompts are frozen per feedback-memory-prompts-v7-bundle until A.3 data says otherwise.
- **No schema changes**. New signal goes through `keywords` (`low_specificity:true`, `analysis_failed:<reason>`) — `description` text remains the existing v4 grammar.
- **No new memory channels** (no ExtraMemoryStage, no GAM redesign).
- **No retriever / ChromaDB tuning**. Retrieval ranking is a separate axis from card content quality.
- **No `gigaevo/memory/live_memory_hook.py` refactor**. It was just hardened in PR `7220dd03` — don't re-touch.

---

## 7. Risks

| Risk | Mitigation |
|---|---|
| Phase A.3 produces too few idea cards (Qwen latency, suggestion-stage timeouts) → grading underpowered | Use `tabular_regression` not `heilbron` (richer levers, more cards historically); set `max_mutants≥200`; if still empty, switch model for Phase A only (one-off, declared as deviation) |
| Stem-stripping in WS-B accidentally merges distinct levers | Whitelist suffixes only; TDD with both COLLISION pairs (must merge) and DISTINCT pairs (must NOT merge — e.g. `n_neighbors` vs `n_clusters`) |
| WS-C diagnosis reveals lineage-agent is structurally broken → much bigger refactor than 1-3 days | Time-box diagnosis to 1 day; if root cause is a redesign, file a separate plan and ship WS-B/D first |
| Validator (WS-D) over-flags → idea bank becomes empty for the mutator | Cards always enter store; validator only adds a keyword. Mutator-side downrank is a soft signal, not a filter. Worst case: nothing changes (graceful degradation) |
| Harness disagrees with hand-grading by >2 cards | Tautology template list is wrong/incomplete. Iterate template list on the PRE-v4 sample until ≤2-card disagreement, THEN apply to v4 data. (This is why A.1 has its own gate.) |
| User decides direction shifts before Phase A finishes | Phase A.1 harness is independently useful (it's a measurement tool we'll want anyway) — never dead work |

---

## 8. Definition of Done

- `docs/audits/memory_quality_v4_baseline.md` exists with v4 numbers
- Either: all v4 targets met → plan closed with "no fixes needed" note in same audit doc
- Or: WS-B/C/D PRs merged, re-run grades meet fix-pack targets, audit doc updated with delta
- Test coverage: `tests/memory/test_canonical_key_dedup.py` (WS-B), `tests/memory/test_mechanism_validator.py` (WS-D), `tests/memory/test_lineage_fallback.py` (WS-C diagnostic outcome)

---

## Appendix A — links to durable feedback that constrain this plan

- `[[feedback_memory_prompts_v7_bundle]]` — no wholesale prompt rewrites
- `[[feedback_no_extra_memory_stage]]` — no ExtraMemoryStage
- `[[parent-directive-#2]]` — schema field NAMES/TYPES frozen for external-service compat
- `[[feedback_plans_need_causal_chain]]` — §2 above (this is why §2 exists)
- `[[feedback_mirror_baseline_exactly]]` — §3 A.3 launch rule
- `[[feedback-commit-approval]]` — §5 sequencing rule
- `[[feedback_no_defensive_coding]]` — WS-C "no silent fallbacks" rule
- `[[feedback_thorough_testing]]` — A.1 hard gate (reproduce PRE-v4 grade)
- `[[feedback_paranoia_grade_testing]]` — not invoked here; this is feature work, not a foundational refactor
