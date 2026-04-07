# MutationAgent TDD Sprint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill five coverage gaps in `MutationAgent` via TDD, then apply three simplifications the new tests validate.

**Architecture:** All test additions go into the existing `tests/llm/test_mutation_agent.py`. All production simplifications are in `gigaevo/llm/agents/mutation.py`. No new files are created. Tests are written first (RED), run to confirm failure or discover bugs, then production code is adjusted (GREEN), then simplifications are applied (REFACTOR) while keeping tests green.

**Tech Stack:** Python, pytest, pytest-asyncio, unittest.mock, `gigaevo.llm.agents.mutation.MutationAgent`

---

## File Map

| File | Changes |
|------|---------|
| `tests/llm/test_mutation_agent.py` | Add 5 new test classes (13 test cases total) |
| `gigaevo/llm/agents/mutation.py` | S1: remove no-op; S2: collapse double-check; S3: extract private method |

---

## Task 0: Set Up Git Worktree

**Files:** none

- [ ] **Step 1: Create worktree from main**

```bash
git worktree add .worktrees/mutation-sprint -b chore/mutation-agent-tdd-sprint main
```

- [ ] **Step 2: Verify it's clean**

```bash
cd .worktrees/mutation-sprint
git status
```
Expected: `nothing to commit, working tree clean` on branch `chore/mutation-agent-tdd-sprint`.

---

## Task 1: TestFixJsonEscapedCode

`_fix_json_escaped_code` is a static method with no test class at all. It has four distinct code paths (early return, already-valid, fixable, unfixable) — all need coverage.

**Files:**
- Modify: `tests/llm/test_mutation_agent.py`

- [ ] **Step 1: Write the failing tests**

Append after the existing `TestMutationPromptFields` class in `tests/llm/test_mutation_agent.py`:

```python
# ---------------------------------------------------------------------------
# TestFixJsonEscapedCode
# ---------------------------------------------------------------------------


class TestFixJsonEscapedCode:
    """Tests for MutationAgent._fix_json_escaped_code (static method)."""

    def test_no_escape_sequences_returns_early_unchanged(self):
        """Code with no JSON escape sequences skips all parsing and is returned as-is."""
        code = "def solve():\n    return 42"
        assert MutationAgent._fix_json_escaped_code(code) == code

    def test_already_valid_python_with_literal_backslash_n_unchanged(self):
        """Valid Python that contains a literal \\n inside a string is returned unchanged."""
        # The code has a real newline for structure AND a two-char \\n inside a string literal.
        # ast.parse succeeds → no transformation applied.
        code = 'def solve():\n    msg = "hello\\nworld"\n    return msg'
        assert MutationAgent._fix_json_escaped_code(code) == code

    def test_json_escaped_newlines_are_fixed(self):
        """Two-char \\n sequences (JSON escaping) are converted to real newlines."""
        # LLM produced \\n (two chars) instead of actual newlines → invalid Python.
        # After replace("\\n", "\n") → valid Python → return cleaned.
        broken = "def solve():\\n    return 42"
        result = MutationAgent._fix_json_escaped_code(broken)
        assert result == "def solve():\n    return 42"

    def test_json_escaped_quotes_are_fixed(self):
        """Two-char \\" sequences (JSON escaping) are converted to real quote chars."""
        broken = 'def solve():\\n    return \\"hello\\"'
        result = MutationAgent._fix_json_escaped_code(broken)
        assert result == 'def solve():\n    return "hello"'

    def test_unfixable_code_returned_unchanged(self):
        """Code that remains invalid even after unescaping is returned as-is."""
        broken = "\\n!!! not valid python !!!\\n"
        assert MutationAgent._fix_json_escaped_code(broken) == broken
```

- [ ] **Step 2: Run the tests — expect all 5 to PASS (method already exists)**

```bash
/run-tests tests/llm/test_mutation_agent.py::TestFixJsonEscapedCode
```

If any test FAILS, a bug exists in `_fix_json_escaped_code`. Read the failure, fix the production code in `gigaevo/llm/agents/mutation.py`, then re-run until GREEN.

- [ ] **Step 3: Commit**

```bash
git add tests/llm/test_mutation_agent.py
git commit -m "test: TestFixJsonEscapedCode — cover all 4 code paths"
```

---

## Task 2: TestBuildMemoryBlock

`_build_memory_block` has no direct tests. Three cases: no memory key, first parent wins, whitespace-only is empty.

**Files:**
- Modify: `tests/llm/test_mutation_agent.py`

- [ ] **Step 1: Write the failing tests**

Update the existing constants import line at the top of `tests/llm/test_mutation_agent.py`:
```python
from gigaevo.evolution.mutation.constants import (
    MUTATION_CONTEXT_METADATA_KEY,
    MUTATION_MEMORY_METADATA_KEY,
)
```

Append after `TestFixJsonEscapedCode`:

```python
# ---------------------------------------------------------------------------
# TestBuildMemoryBlock
# ---------------------------------------------------------------------------


class TestBuildMemoryBlock:
    """Tests for MutationAgent._build_memory_block."""

    def setup_method(self):
        self.agent = _make_agent()

    def test_no_memory_key_returns_empty_string(self):
        """Parents with no memory metadata key produce an empty string."""
        parents = [_make_program(metadata={}), _make_program(metadata={})]
        assert self.agent._build_memory_block(parents) == ""

    def test_first_parent_with_memory_key_wins(self):
        """The first parent that has a non-empty memory key is used; later parents ignored."""
        parents = [
            _make_program(metadata={MUTATION_MEMORY_METADATA_KEY: "Use caching."}),
            _make_program(metadata={MUTATION_MEMORY_METADATA_KEY: "Should be ignored."}),
        ]
        result = self.agent._build_memory_block(parents)
        assert result == "## Memory Instructions\nUse caching."
        assert "ignored" not in result

    def test_whitespace_only_memory_value_treated_as_absent(self):
        """A memory value that is all whitespace is skipped (treated as no memory)."""
        parents = [_make_program(metadata={MUTATION_MEMORY_METADATA_KEY: "   "})]
        assert self.agent._build_memory_block(parents) == ""
```

- [ ] **Step 2: Run the tests — expect all 3 to PASS**

```bash
/run-tests tests/llm/test_mutation_agent.py::TestBuildMemoryBlock
```

If any FAIL, fix `_build_memory_block` in `gigaevo/llm/agents/mutation.py`.

- [ ] **Step 3: Commit**

```bash
git add tests/llm/test_mutation_agent.py
git commit -m "test: TestBuildMemoryBlock — no key, first-wins, whitespace"
```

---

## Task 3: TestBuildUserPromptWithMemory

`build_user_prompt` calls both `_build_parent_blocks` and `_build_memory_block` but the memory branch has never been exercised through the public method.

**Files:**
- Modify: `tests/llm/test_mutation_agent.py`

- [ ] **Step 1: Write the failing tests**

Append after `TestBuildMemoryBlock`:

```python
# ---------------------------------------------------------------------------
# TestBuildUserPromptWithMemory
# ---------------------------------------------------------------------------


class TestBuildUserPromptWithMemory:
    """Tests for build_user_prompt — memory block integration."""

    def test_memory_block_appended_when_present(self):
        """When a parent has memory instructions, they appear in the user prompt."""
        agent = _make_agent()
        parent = _make_program(
            code="def solve(): return 1",
            metadata={
                MUTATION_CONTEXT_METADATA_KEY: "score=0.9",
                MUTATION_MEMORY_METADATA_KEY: "Prefer vectorised ops.",
            },
        )
        result = agent.build_user_prompt([parent])
        assert "## Memory Instructions" in result
        assert "Prefer vectorised ops." in result

    def test_no_memory_block_when_absent(self):
        """When no parent has memory instructions, the memory section is absent."""
        agent = _make_agent()
        parent = _make_program(
            code="def solve(): return 1",
            metadata={MUTATION_CONTEXT_METADATA_KEY: "score=0.9"},
        )
        result = agent.build_user_prompt([parent])
        assert "## Memory Instructions" not in result
```

- [ ] **Step 2: Run the tests — expect both to PASS**

```bash
/run-tests tests/llm/test_mutation_agent.py::TestBuildUserPromptWithMemory
```

- [ ] **Step 3: Commit**

```bash
git add tests/llm/test_mutation_agent.py
git commit -m "test: TestBuildUserPromptWithMemory — memory appended/absent"
```

---

## Task 4: TestDynamicPromptFetcher

The `if self._prompt_fetcher is not None and self._prompt_fetcher.is_dynamic` branch in `build_prompt` is completely untested. Two cases: dynamic fetcher refreshes prompt + stamps `prompt_id`; non-dynamic fetcher leaves prompt unchanged and sets `prompt_id=None`.

**Files:**
- Modify: `tests/llm/test_mutation_agent.py`

- [ ] **Step 1: Write the failing tests**

Add to the top-of-file imports in `tests/llm/test_mutation_agent.py`:
```python
from unittest.mock import MagicMock
from gigaevo.prompts.fetcher import FetchedPrompt, PromptFetcher
```

(`MagicMock` is already imported — skip if present. `FetchedPrompt` and `PromptFetcher` are new.)

Append after `TestBuildUserPromptWithMemory`:

```python
# ---------------------------------------------------------------------------
# TestDynamicPromptFetcher
# ---------------------------------------------------------------------------


class TestDynamicPromptFetcher:
    """Tests for the dynamic prompt_fetcher path inside build_prompt."""

    def _make_dynamic_fetcher(
        self,
        system_text: str = "Dynamic: {task_description} {metrics_description}",
        prompt_id: str = "abc123def456",
        user_prompt_id: str | None = None,
    ) -> MagicMock:
        """Return a mock PromptFetcher with is_dynamic=True."""
        fetcher = MagicMock(spec=PromptFetcher)
        fetcher.is_dynamic = True

        def _fetch(agent_name: str, prompt_type: str) -> FetchedPrompt:
            if prompt_type == "system":
                return FetchedPrompt(text=system_text, prompt_id=prompt_id)
            return FetchedPrompt(text="user template {count} {parent_blocks}", prompt_id=user_prompt_id)

        fetcher.fetch.side_effect = _fetch
        return fetcher

    def test_dynamic_fetcher_refreshes_system_prompt_and_stamps_prompt_id(self):
        """Dynamic fetcher: system prompt is refreshed and prompt_id stamped in state."""
        fetcher = self._make_dynamic_fetcher(
            system_text="Dynamic: {task_description} {metrics_description}",
            prompt_id="abc123def456",
        )
        agent = _make_agent(system_prompt="original static prompt")
        agent._prompt_fetcher = fetcher
        agent._task_description = "solve problems"
        agent._metrics_formatter = MagicMock()
        agent._metrics_formatter.format_metrics_description.return_value = "fitness: 0-1"

        state = _make_state(parents=[_make_program()])
        result = agent.build_prompt(state)

        assert result["prompt_id"] == "abc123def456"
        assert "Dynamic: solve problems fitness: 0-1" in result["system_prompt"]
        # Original static prompt is no longer active
        assert "original static prompt" not in result["system_prompt"]

    def test_non_dynamic_fetcher_leaves_prompt_unchanged_and_sets_prompt_id_none(self):
        """Non-dynamic (fixed) fetcher: system prompt unchanged, prompt_id=None."""
        fetcher = MagicMock(spec=PromptFetcher)
        fetcher.is_dynamic = False

        agent = _make_agent(system_prompt="static prompt")
        agent._prompt_fetcher = fetcher

        state = _make_state(parents=[_make_program()])
        result = agent.build_prompt(state)

        assert result["prompt_id"] is None
        assert result["system_prompt"] == "static prompt"
        fetcher.fetch.assert_not_called()
```

- [ ] **Step 2: Run the tests — expect both to PASS**

```bash
/run-tests tests/llm/test_mutation_agent.py::TestDynamicPromptFetcher
```

If a test FAILS, a bug exists in the dynamic fetcher path in `build_prompt`. Read the failure and fix `gigaevo/llm/agents/mutation.py`.

- [ ] **Step 3: Commit**

```bash
git add tests/llm/test_mutation_agent.py
git commit -m "test: TestDynamicPromptFetcher — dynamic refresh and fixed no-op paths"
```

---

## Task 5: TestJsonTemplateGuard

The guard in `parse_response` that rejects JSON-as-code (`"def " not in final_code and lstrip().startswith("{")`) has no test.

**Files:**
- Modify: `tests/llm/test_mutation_agent.py`

- [ ] **Step 1: Write the failing test**

Append after `TestDynamicPromptFetcher`:

```python
# ---------------------------------------------------------------------------
# TestJsonTemplateGuard
# ---------------------------------------------------------------------------


class TestJsonTemplateGuard:
    """Tests for the JSON-template guard in parse_response."""

    def test_json_template_echoed_as_code_is_rejected(self):
        """When LLM returns a JSON object instead of Python, parse_response captures the error."""
        agent = _make_agent(mutation_mode="rewrite")
        # Simulate LLM echoing the schema template back as the code field
        output = _make_structured_output(code='{"archetype": "x", "code": "..."}')
        state = _make_state(mutation_mode="rewrite", structured_output=output)

        result = agent.parse_response(state)

        assert result["parsed_output"]["code"] == ""
        assert "JSON template" in result["parsed_output"]["error"]

    def test_valid_python_starting_with_brace_is_not_rejected(self):
        """A dict literal assigned to a variable is valid Python and must not be rejected."""
        agent = _make_agent(mutation_mode="rewrite")
        # Valid Python: a module that starts with a dict assignment, has a def
        output = _make_structured_output(
            code='CONFIG = {"key": 1}\n\ndef solve(x):\n    return CONFIG["key"] + x'
        )
        state = _make_state(mutation_mode="rewrite", structured_output=output)

        result = agent.parse_response(state)

        assert result["parsed_output"]["code"] != ""
        assert "error" not in result["parsed_output"]
```

- [ ] **Step 2: Run the tests — expect both to PASS**

```bash
/run-tests tests/llm/test_mutation_agent.py::TestJsonTemplateGuard
```

- [ ] **Step 3: Commit**

```bash
git add tests/llm/test_mutation_agent.py
git commit -m "test: TestJsonTemplateGuard — JSON echoed as code is rejected"
```

---

## Task 6: S1 — Remove No-Op Branch in parse_response

The lines immediately after `_extract_code_block` in rewrite mode are dead code: `_extract_code_block` already returns `text.strip()` when no fence is found, so the condition `final_code == code_from_llm.strip()` and its assignment are always a no-op.

**Files:**
- Modify: `gigaevo/llm/agents/mutation.py:419-423`

- [ ] **Step 1: Delete the dead code**

In `gigaevo/llm/agents/mutation.py`, find this block (in `parse_response`, inside the `else:` branch):

```python
            else:
                # In rewrite mode, clean up the code (remove any remaining fences)
                final_code = self._extract_code_block(code_from_llm)
                # If no code block markers found, use as-is
                if final_code == code_from_llm.strip():
                    final_code = code_from_llm.strip()
```

Replace with:

```python
            else:
                final_code = self._extract_code_block(code_from_llm)
```

- [ ] **Step 2: Run the full test suite to confirm no regressions**

```bash
/run-tests tests/llm/test_mutation_agent.py
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add gigaevo/llm/agents/mutation.py
git commit -m "refactor: remove no-op branch in parse_response rewrite path"
```

---

## Task 7: S2 — Simplify _build_memory_block

The current implementation uses a mutable accumulator + two nested truthiness checks. A direct early-return is equivalent and clearer.

**Files:**
- Modify: `gigaevo/llm/agents/mutation.py` (`_build_memory_block` method)

- [ ] **Step 1: Replace the method body**

Find the current `_build_memory_block`:

```python
    def _build_memory_block(self, parents: list[Program]) -> str:
        """Build a single memory block from any parent metadata."""
        memory_text = ""
        for parent in parents:
            memory_instructions = parent.metadata.get(MUTATION_MEMORY_METADATA_KEY)
            if memory_instructions:
                memory_text = str(memory_instructions).strip()
                if memory_text:
                    break
        if not memory_text:
            return ""
        return f"## Memory Instructions\n{memory_text}"
```

Replace with:

```python
    def _build_memory_block(self, parents: list[Program]) -> str:
        """Build a single memory block from any parent metadata."""
        for parent in parents:
            memory_text = str(parent.metadata.get(MUTATION_MEMORY_METADATA_KEY, "")).strip()
            if memory_text:
                return f"## Memory Instructions\n{memory_text}"
        return ""
```

- [ ] **Step 2: Run the full test suite to confirm no regressions**

```bash
/run-tests tests/llm/test_mutation_agent.py
```

Expected: all tests pass (including `TestBuildMemoryBlock` from Task 2).

- [ ] **Step 3: Commit**

```bash
git add gigaevo/llm/agents/mutation.py
git commit -m "refactor: simplify _build_memory_block — collapse double-check into early return"
```

---

## Task 8: S3 — Extract _refresh_prompts_from_fetcher

The 10-line dynamic-fetch block inside `build_prompt` mixes prompt refresh, state mutation, and template formatting in one dense block. Extract to a private method.

**Files:**
- Modify: `gigaevo/llm/agents/mutation.py` (`build_prompt` method + new private method)

- [ ] **Step 1: Add the private method**

In `gigaevo/llm/agents/mutation.py`, add this method directly before `build_prompt`:

```python
    def _refresh_prompts_from_fetcher(self, state: MutationState) -> None:
        """Refresh system and user prompts from the dynamic co-evolving fetcher.

        Stamps prompt_id in state for downstream tracking.
        Called only when prompt_fetcher.is_dynamic is True.
        """
        fetched_sys = self._prompt_fetcher.fetch("mutation", "system")
        self.system_prompt = fetched_sys.text.format(
            task_description=self._task_description,
            metrics_description=self._metrics_formatter.format_metrics_description(),
        )
        state["prompt_id"] = fetched_sys.prompt_id
        fetched_user = self._prompt_fetcher.fetch("mutation", "user")
        if fetched_user.prompt_id is not None:
            self.user_prompt_template = fetched_user.text
```

- [ ] **Step 2: Replace the inline block in build_prompt**

Find this block in `build_prompt`:

```python
        # Refresh system and user prompts from dynamic fetcher if available
        if (
            self._prompt_fetcher is not None
            and self._prompt_fetcher.is_dynamic
            and self._metrics_formatter is not None
        ):
            fetched_sys = self._prompt_fetcher.fetch("mutation", "system")
            self.system_prompt = fetched_sys.text.format(
                task_description=self._task_description,
                metrics_description=self._metrics_formatter.format_metrics_description(),
            )
            state["prompt_id"] = fetched_sys.prompt_id
            # Also refresh user prompt template if a co-evolved version is available
            fetched_user = self._prompt_fetcher.fetch("mutation", "user")
            if fetched_user.prompt_id is not None:
                self.user_prompt_template = fetched_user.text
        else:
            state["prompt_id"] = None
```

Replace with:

```python
        if (
            self._prompt_fetcher is not None
            and self._prompt_fetcher.is_dynamic
            and self._metrics_formatter is not None
        ):
            self._refresh_prompts_from_fetcher(state)
        else:
            state["prompt_id"] = None
```

- [ ] **Step 3: Run the full test suite to confirm no regressions**

```bash
/run-tests tests/llm/test_mutation_agent.py
```

Expected: all tests pass (including `TestDynamicPromptFetcher` from Task 4).

- [ ] **Step 4: Commit**

```bash
git add gigaevo/llm/agents/mutation.py
git commit -m "refactor: extract _refresh_prompts_from_fetcher from build_prompt"
```

---

## Task 9: Full Suite + PR

- [ ] **Step 1: Run the complete test suite and linter**

```bash
/run-tests
```

Expected: all tests pass, ruff clean.

- [ ] **Step 2: Push branch and open PR**

```bash
git push -u origin chore/mutation-agent-tdd-sprint
gh pr create \
  --base main \
  --title "test+refactor: MutationAgent TDD sprint — 5 coverage gaps + 3 simplifications" \
  --body "Adds 13 tests covering _fix_json_escaped_code, _build_memory_block, build_user_prompt memory path, dynamic prompt_fetcher, and JSON template guard. Removes one no-op branch, collapses a double-check, and extracts _refresh_prompts_from_fetcher. All changes verified by the new and existing test suite."
```
