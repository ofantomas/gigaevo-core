# MutationAgent TDD Sprint — Design Spec

**Date:** 2026-04-07
**Branch:** `chore/mutation-agent-tdd-sprint` (from `main`)
**File under test:** `gigaevo/llm/agents/mutation.py`
**Test file:** `tests/llm/test_mutation_agent.py`

---

## Goal

Fill coverage gaps in `MutationAgent` via TDD, then simplify the code paths
the new tests reveal are over-complicated or redundant.

---

## Coverage Gaps to Fix (RED → GREEN)

| # | Target | What to test |
|---|--------|-------------|
| 1 | `_fix_json_escaped_code` | Already-valid code returned unchanged; escaped `\n`/`\t`/`\"` fixed when broken; unfixable code returned as-is; no escape sequences → early return |
| 2 | `_build_memory_block` | No parents with memory key → empty string; first parent with key wins; whitespace-only value treated as empty |
| 3 | `build_user_prompt` + memory | Memory block appended to parent blocks when present; absent when not present |
| 4 | Dynamic `prompt_fetcher` path in `build_prompt` | `is_dynamic=True` fetcher refreshes system prompt + stamps `prompt_id`; `is_dynamic=False` (fixed) fetcher leaves prompt unchanged and sets `prompt_id=None` |
| 5 | JSON template guard in `parse_response` | Code starting with `{` and lacking `def ` triggers error path |

---

## Simplifications to Apply (after tests are green)

| # | Location | Change |
|---|----------|--------|
| S1 | `parse_response` lines 421–423 | Remove the no-op branch: `if final_code == code_from_llm.strip(): final_code = code_from_llm.strip()` — dead code, `_extract_code_block` already strips |
| S2 | `_build_memory_block` | Collapse the double-check (`if memory_instructions:` then `if memory_text:`) into a single condition |
| S3 | `build_prompt` | Extract the 10-line dynamic fetch block into `_refresh_prompts_from_fetcher(state)` private method |

---

## Approach

- TDD throughout: write each failing test, run to confirm RED, implement minimum change to go GREEN, run full suite
- Use `superpowers:test-driven-development` skill during implementation
- Simplifications only after all new tests pass (refactor phase of RED→GREEN→REFACTOR)
- Use `superpowers:verification-before-completion` before declaring done
- Use `superpowers:finishing-a-development-branch` to clean up and open PR

---

## Out of Scope

- `_dump_prompt_to_file` (defensive logging only, low value)
- Other files in `gigaevo/llm/agents/`
- Async integration tests (would require a live LLM)
