# Test Polishing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate test quality issues identified by the TDD Guardian — duplicate coverage, private-method coupling, trivial assertions, and implementation-detail mock assertions.

**Architecture:** Four skill-guided phases: (1) mutation baseline on acceptor.py before touching anything, (2) consolidate duplicate acceptor test files, (3) strip private-state assertions from MetricsTracker, (4) clean up trivial/mock-call assertions across prompt and memory tests.

**Tech Stack:** Python, pytest, pytest-asyncio, mutmut (mutation testing)

---

## Task 0: Set up git worktree

**Files:**
- No files modified — worktree creation only

- [ ] **Step 1: Create an isolated worktree for this work**

```bash
cd /mnt/virtual_ai0001071-04017_SR004-nfs1/CFS-SR008/workspace/mathemage/gigaevo-core-internal
git worktree add ../gigaevo-test-polish -b test/polish-tests
cd ../gigaevo-test-polish
```

- [ ] **Step 2: Verify worktree is clean and on the new branch**

```bash
git status
git branch
```

Expected: `On branch test/polish-tests`, clean working tree.

---

## Task 1: Mutation baseline — acceptor.py

Run the `mutation-testing` skill to establish a baseline *before* consolidating the acceptor files. This is necessary because the duplicate coverage inflates kill rates and makes scores misleading.

**Files:**
- Read: `gigaevo/evolution/engine/acceptor.py`
- Read: `tests/evolution/test_acceptor.py`

- [ ] **Step 1: Invoke mutation-testing skill**

```
/mutation-testing
```

When prompted, target `gigaevo/evolution/engine/acceptor.py` with test file `tests/evolution/test_acceptor.py`.

- [ ] **Step 2: Record surviving mutants**

Note the mutation score and any surviving mutants. Save output to a scratch file:

```bash
# The skill will print results — copy the summary to a scratch note
echo "# Baseline mutation score" > /tmp/mutation_baseline.txt
# paste skill output here
```

Expected: mutation score ≥ 85% if tests are solid. If lower, note the surviving mutants — they will need new tests in Task 2.

---

## Task 2: Consolidate acceptor test files

`test_acceptors.py` (241 lines) duplicates almost every test in `test_acceptor.py` (273 lines). The only unique content is `TestMutationContextAndBehaviorKeysAcceptor` (lines 195–241 in `test_acceptors.py`), which tests a class not covered in `test_acceptor.py`.

**Files:**
- Modify: `tests/evolution/test_acceptor.py`
- Delete: `tests/evolution/test_acceptors.py`

- [ ] **Step 1: Add missing import to test_acceptor.py**

Open `tests/evolution/test_acceptor.py`. After the existing import block (around line 21), add:

```python
from gigaevo.evolution.engine.acceptor import (
    CompositeAcceptor,
    DefaultProgramEvolutionAcceptor,
    MetricsExistenceAcceptor,
    MutationContextAcceptor,
    MutationContextAndBehaviorKeysAcceptor,  # add this
    RequiredBehaviorKeysAcceptor,
    StandardEvolutionAcceptor,
    StateAcceptor,
    ValidityMetricAcceptor,
)
```

- [ ] **Step 2: Append the unique test class to test_acceptor.py**

Add at the end of `tests/evolution/test_acceptor.py`:

```python
# ===========================================================================
# MutationContextAndBehaviorKeysAcceptor
# ===========================================================================


class TestMutationContextAndBehaviorKeysAcceptor:
    def test_fully_valid(self):
        """DONE + metrics + behavior keys + mutation context -> accepted."""
        p = _make_program(
            metrics={"behavior_a": 0.5, "score": 1.0},
            metadata={MUTATION_CONTEXT_METADATA_KEY: "ctx"},
        )
        acc = MutationContextAndBehaviorKeysAcceptor(
            required_behavior_keys={"behavior_a"},
        )
        assert acc.is_accepted(p)

    def test_missing_behavior_key(self):
        """Missing required behavior key -> rejected."""
        p = _make_program(
            metrics={"score": 1.0},
            metadata={MUTATION_CONTEXT_METADATA_KEY: "ctx"},
        )
        acc = MutationContextAndBehaviorKeysAcceptor(
            required_behavior_keys={"behavior_a"},
        )
        assert not acc.is_accepted(p)

    def test_missing_mutation_context(self):
        """Missing mutation context -> rejected."""
        p = _make_program(
            metrics={"behavior_a": 0.5, "score": 1.0},
        )
        acc = MutationContextAndBehaviorKeysAcceptor(
            required_behavior_keys={"behavior_a"},
        )
        assert not acc.is_accepted(p)

    def test_no_validity_check(self):
        """Unlike StandardEvolutionAcceptor, does NOT check is_valid."""
        p = _make_program(
            metrics={VALIDITY_KEY: 0.0, "behavior_a": 0.5},
            metadata={MUTATION_CONTEXT_METADATA_KEY: "ctx"},
        )
        acc = MutationContextAndBehaviorKeysAcceptor(
            required_behavior_keys={"behavior_a"},
        )
        assert acc.is_accepted(p)
```

- [ ] **Step 3: Run tests to confirm green**

```bash
PYTHONPATH=. /home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/evolution/test_acceptor.py -v
```

Expected: all tests pass, including the 4 new `TestMutationContextAndBehaviorKeysAcceptor` tests.

- [ ] **Step 4: Delete the duplicate file**

```bash
git rm tests/evolution/test_acceptors.py
```

- [ ] **Step 5: Run tests again to confirm nothing broke**

```bash
PYTHONPATH=. /home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/evolution/test_acceptor.py -v
```

Expected: same pass count as Step 3.

- [ ] **Step 6: Commit**

```bash
git add tests/evolution/test_acceptor.py
git commit -m "test: consolidate acceptor tests, migrate MutationContextAndBehaviorKeysAcceptor coverage"
```

---

## Task 3: Re-run mutation testing post-consolidation

Verify the consolidation did not lose kill coverage.

- [ ] **Step 1: Invoke mutation-testing skill again**

```
/mutation-testing
```

Target `gigaevo/evolution/engine/acceptor.py` with `tests/evolution/test_acceptor.py`.

- [ ] **Step 2: Compare scores**

Mutation score should be ≥ baseline from Task 1. If any new surviving mutants appeared (coverage gap), add tests for them in `tests/evolution/test_acceptor.py` before continuing.

---

## Task 4: Invoke test-design-reviewer on MetricsTracker

Use the skill to get a precise, Dave-Farley-scored assessment of `TestProcessProgram` before making changes.

**Files:**
- Read: `tests/test_metrics_tracker.py:161–462`

- [ ] **Step 1: Invoke test-design-reviewer skill**

```
/test-design-reviewer
```

Point it at `tests/test_metrics_tracker.py`, class `TestProcessProgram`.

- [ ] **Step 2: Note specific lines flagged**

The reviewer will flag private-state assertions (`tracker._invalid_count`, `tracker._valid_count`, `tracker._best_valid`). Record those line numbers for Task 5.

---

## Task 5: Strip private-state assertions from TestProcessProgram

The `TestProcessProgram` class already captures all behavior through `writer.scalars`. The `tracker._invalid_count` / `tracker._valid_count` / `tracker._best_valid` assertions are redundant and couple tests to implementation state. Remove them; keep all `writer.scalars` assertions.

**Files:**
- Modify: `tests/test_metrics_tracker.py`

- [ ] **Step 1: Search for all private-state assertions**

```bash
grep -n "_invalid_count\|_valid_count\|_best_valid" tests/test_metrics_tracker.py
```

- [ ] **Step 2: Delete each private-state assertion line**

For each match, delete the line. Example — in `test_invalid_program_counts` (around line 219):

Before:
```python
        result = await tracker._process_program(prog)
        assert result is True
        assert tracker._invalid_count == 1      # DELETE THIS
        assert tracker._valid_count == 0        # DELETE THIS

        tag_to_val = {t: v for t, v, _ in writer.scalars}
        assert tag_to_val[VALIDITY_KEY] == 0.0
        assert tag_to_val["programs/invalid_count"] == pytest.approx(1.0)
```

After:
```python
        result = await tracker._process_program(prog)
        assert result is True

        tag_to_val = {t: v for t, v, _ in writer.scalars}
        assert tag_to_val[VALIDITY_KEY] == 0.0
        assert tag_to_val["programs/invalid_count"] == pytest.approx(1.0)
```

Apply the same pattern to all instances identified in Step 1.

- [ ] **Step 3: Run MetricsTracker tests**

```bash
PYTHONPATH=. /home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/test_metrics_tracker.py -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_metrics_tracker.py
git commit -m "test: remove private-state assertions from TestProcessProgram"
```

---

## Task 6: Fix trivial `assert X is not None` assertions

At least 5 locations have `assert fetcher/stage is not None` after construction — vacuous assertions that would pass even with a broken constructor.

**Files:**
- Modify: `tests/prompts/test_fetcher.py`
- Modify: `tests/prompts/test_coevolution_stages.py`

- [ ] **Step 1: Find all occurrences**

```bash
grep -rn "is not None" tests/prompts/
```

- [ ] **Step 2: Fix test_fetcher.py `test_initialization`**

File: `tests/prompts/test_fetcher.py`, around line 50.

Before:
```python
    def test_initialization(self):
        """FixedDirPromptFetcher can be initialized."""
        fetcher = FixedDirPromptFetcher(prompts_dir=None)
        assert fetcher is not None
        assert fetcher.is_dynamic is False
```

After (delete the vacuous assertion, keep the behavioral one):
```python
    def test_initialization(self):
        """FixedDirPromptFetcher is non-dynamic by default."""
        fetcher = FixedDirPromptFetcher(prompts_dir=None)
        assert fetcher.is_dynamic is False
```

- [ ] **Step 3: Fix test_coevolution_stages.py**

Apply the same pattern — find `assert stage is not None` and delete each line. Keep any adjacent behavioral assertions.

- [ ] **Step 4: Run affected tests**

```bash
PYTHONPATH=. /home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest tests/prompts/ -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/prompts/test_fetcher.py tests/prompts/test_coevolution_stages.py
git commit -m "test: remove vacuous 'is not None' assertions in prompt tests"
```

---

## Task 7: Invoke testing skill — audit assert_called_once pattern

Use the `testing` skill to understand the behavior-over-implementation principle before changing the memory/prompt mock assertions.

- [ ] **Step 1: Invoke testing skill**

```
/testing
```

Read the section on "test doubles" / "mocks" — specifically when `assert_called` is appropriate (verifying side effects) vs. when it tests internal delegation (should be replaced by return-value assertions).

- [ ] **Step 2: Identify the four target files**

```
tests/memory/test_ideas_tracker_pipeline.py  (lines 510–511, 523, 569)
tests/memory/test_api_search.py              (lines 58–59, 205, 295)
tests/prompts/test_coevolution_sync.py       (lines 72–74)
tests/memory/test_provider.py               (lines 66, 125, 145)
```

---

## Task 8: Fix assert_called_once in behavior tests

For each `assert_called_once()` / `assert_called_once_with()` that verifies delegation (not side effects), replace with an assertion on the return value or output.

**Files:**
- Modify: `tests/memory/test_provider.py`
- Modify: `tests/memory/test_api_search.py`
- Modify: `tests/prompts/test_coevolution_sync.py`
- Modify: `tests/memory/test_ideas_tracker_pipeline.py`

- [ ] **Step 1: Find all assert_called occurrences in target files**

```bash
grep -n "assert_called" \
  tests/memory/test_provider.py \
  tests/memory/test_api_search.py \
  tests/prompts/test_coevolution_sync.py \
  tests/memory/test_ideas_tracker_pipeline.py
```

- [ ] **Step 2: For each match, apply the rule**

**Keep** `assert_called` when the side effect IS the behavior (e.g., `proc.stdin.close.assert_called_once()` — subprocess resource cleanup, `redis_client.set.assert_called_once_with(key, val)` — writing to external store).

**Delete** `assert_called` when a return-value assertion already covers the behavior. Example from `test_provider.py` around line 66:

Before:
```python
        result = provider.select(candidates)
        assert result is expected_candidate
        mock_selector.select.assert_called_once()   # DELETE — covered by assert above
```

After:
```python
        result = provider.select(candidates)
        assert result is expected_candidate
```

Example from `test_api_search.py` around lines 58–59:

Before:
```python
        result = searcher.search("query")
        assert "idea-1" in result
        mock_api.search_concepts.assert_called_once()           # DELETE
        mock_api.get_concept.assert_called_once_with("e1", channel="latest")  # DELETE
```

After:
```python
        result = searcher.search("query")
        assert "idea-1" in result
```

- [ ] **Step 3: Run affected tests**

```bash
PYTHONPATH=. /home/jovyan/.mlspace/envs/evo/bin/python3 -m pytest \
  tests/memory/test_provider.py \
  tests/memory/test_api_search.py \
  tests/prompts/test_coevolution_sync.py \
  tests/memory/test_ideas_tracker_pipeline.py \
  -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add \
  tests/memory/test_provider.py \
  tests/memory/test_api_search.py \
  tests/prompts/test_coevolution_sync.py \
  tests/memory/test_ideas_tracker_pipeline.py
git commit -m "test: replace delegation mock assertions with return-value assertions"
```

---

## Task 9: Final verification

- [ ] **Step 1: Run full test suite via skill**

```
/run-tests
```

Expected: all tests pass, linting clean.

- [ ] **Step 2: Run mutation testing on acceptor.py one final time**

```
/mutation-testing
```

Target `gigaevo/evolution/engine/acceptor.py`. Score should be ≥ baseline from Task 1 and ≥ baseline from Task 3.

- [ ] **Step 3: Request code review**

```
/superpowers:requesting-code-review
```

Scope: `test/polish-tests` branch vs `main`. Summary: "Polished test quality — consolidated acceptor files, removed private-state assertions, fixed trivial assertions and delegation mock-call assertions."

---

## Self-Review

**Spec coverage:**
- Duplicate acceptor files → Task 2 ✓
- Private-state assertions in TestProcessProgram → Task 5 ✓
- Trivial `is not None` → Task 6 ✓
- `assert_called_once` delegation assertions → Task 8 ✓
- Mutation testing baseline + verification → Tasks 1, 3, 9 ✓
- test-design-reviewer → Task 4 ✓
- testing skill reference → Task 7 ✓
- Worktree isolation → Task 0 ✓

**Placeholder scan:** No TBD, TODO, or "similar to Task N" references. All code blocks are complete.

**Type consistency:** `_make_program` factory in Task 2 matches the signature in `test_acceptor.py:32–43`. No type mismatches across tasks.
