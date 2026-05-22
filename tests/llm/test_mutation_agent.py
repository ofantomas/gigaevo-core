"""Tests for MutationAgent: code extraction, diff, prompt building, parsing, LLM calls."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from gigaevo.evolution.mutation.constants import MUTATION_CONTEXT_METADATA_KEY
from gigaevo.llm.agents.mutation import (
    MutationAgent,
    MutationPromptFields,
    MutationState,
    MutationStructuredOutput,
)
from gigaevo.programs.program import Program

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(
    mutation_mode: str = "rewrite",
    system_prompt: str = "You are a mutation agent.",
    user_prompt_template: str = "Mutate {count} parent programs:\n{parent_blocks}",
) -> MutationAgent:
    """Create a MutationAgent with a fully mocked LLM."""
    mock_llm = MagicMock()
    mock_llm.with_structured_output = MagicMock(return_value=MagicMock())
    return MutationAgent(
        llm=mock_llm,
        system_prompt=system_prompt,
        user_prompt_template=user_prompt_template,
        mutation_mode=mutation_mode,
    )


def _make_program(
    code: str = "def solve(): return 42",
    metadata: dict[str, Any] | None = None,
) -> Program:
    """Create a minimal Program for tests."""
    p = Program(code=code)
    if metadata:
        p.metadata = metadata
    return p


def _make_structured_output(**kwargs) -> MutationStructuredOutput:
    defaults = {
        "archetype": "Precision Optimization",
        "justification": "Improved via targeted mutation.",
        "insights_used": ["insight_a"],
        "code": "def solve(): return 99",
    }
    defaults.update(kwargs)
    return MutationStructuredOutput(**defaults)


def _make_state(
    parents: list[Program] | None = None,
    mutation_mode: str = "rewrite",
    **overrides: Any,
) -> MutationState:
    """Build a MutationState dict with sensible defaults."""
    state: MutationState = {
        "input": parents or [_make_program()],
        "mutation_mode": mutation_mode,
        "messages": [],
        "llm_response": None,
        "final_code": "",
        "mutation_label": "",
    }
    state.update(overrides)  # type: ignore[typeddict-item]
    return state


# ---------------------------------------------------------------------------
# TestExtractCodeBlock
# ---------------------------------------------------------------------------


class TestExtractCodeBlock:
    """Tests for MutationAgent._extract_code_block."""

    def setup_method(self):
        self.agent = _make_agent()

    def test_fenced_python(self):
        """Standard fenced code block with python language tag."""
        text = "Some text\n```python\ndef solve(): return 1\n```\nMore text"
        result = self.agent._extract_code_block(text)
        assert result == "def solve(): return 1"

    def test_no_fence(self):
        """Plain text without fences is returned stripped."""
        text = "  def solve(): return 1  "
        result = self.agent._extract_code_block(text)
        assert result == "def solve(): return 1"

    def test_indented_fence_ignored(self):
        """Fences not at start-of-line are ignored (regex requires ^)."""
        text = "  ```python\ndef solve(): return 1\n  ```"
        result = self.agent._extract_code_block(text)
        # Indented fences don't match, so entire text is returned stripped
        assert result == text.strip()

    def test_backticks_in_code(self):
        """Backticks inside the code (e.g. docstrings) don't close the block."""
        inner = 'def solve():\n    """Uses `x` and `y`."""\n    return 1'
        text = f"```python\n{inner}\n```"
        result = self.agent._extract_code_block(text)
        assert result == inner

    def test_missing_close(self):
        """If closing fence is absent, entire text is returned stripped."""
        text = "```python\ndef solve(): return 1"
        result = self.agent._extract_code_block(text)
        assert result == text.strip()

    def test_multiple_blocks_takes_first(self):
        """Only the first (outermost) fenced block is extracted."""
        text = "```python\nfirst_block\n```\n\n```python\nsecond_block\n```"
        result = self.agent._extract_code_block(text)
        assert result == "first_block"


# ---------------------------------------------------------------------------
# TestApplyDiffAndExtract
# ---------------------------------------------------------------------------


class TestApplyDiffAndExtract:
    """Tests for MutationAgent._apply_diff_and_extract."""

    def setup_method(self):
        self.agent = _make_agent()

    def test_parse_search_replace_blocks(self):
        """SEARCH/REPLACE blocks are parsed into exact pairs."""
        payload = (
            "<<<<<<< SEARCH\n"
            "    x = 1\n"
            "=======\n"
            "    x = 2\n"
            ">>>>>>> REPLACE\n"
            "\n"
            "<<<<<<< SEARCH\n"
            "    return x\n"
            "=======\n"
            "    return x + 1\n"
            ">>>>>>> REPLACE\n"
        )
        blocks = self.agent._parse_search_replace_blocks(payload)
        assert blocks == [
            ("    x = 1", "    x = 2"),
            ("    return x", "    return x + 1"),
        ]

    def test_valid_search_replace(self):
        """A SEARCH/REPLACE block is applied to original Python code."""
        original = "def solve():\n    x = 1\n    y = 2\n    return x + y\n"
        patch = (
            "<<<<<<< SEARCH\n"
            "    y = 2\n"
            "=======\n"
            "    y = 3\n"
            ">>>>>>> REPLACE\n"
        )
        result = self.agent._apply_diff_and_extract(original, patch)
        assert "    y = 3" in result
        assert "    y = 2" not in result

    def test_multiple_search_replace_blocks_apply_in_order(self):
        """Multiple SEARCH/REPLACE blocks are applied sequentially."""
        original = "def solve():\n    x = 1\n    y = 2\n    return x + y\n"
        patch = (
            "<<<<<<< SEARCH\n"
            "    x = 1\n"
            "=======\n"
            "    x = 10\n"
            ">>>>>>> REPLACE\n"
            "<<<<<<< SEARCH\n"
            "    return x + y\n"
            "=======\n"
            "    return x - y\n"
            ">>>>>>> REPLACE\n"
        )
        result = self.agent._apply_diff_and_extract(original, patch)
        assert result == "def solve():\n    x = 10\n    y = 2\n    return x - y\n"

    def test_empty_diff_raises(self):
        """An empty diff raises ValueError."""
        original = "line1\nline2\n"
        with pytest.raises(ValueError, match="Empty diff"):
            self.agent._apply_diff_and_extract(original, "```\n   \n```")

    def test_invalid_diff_raises(self):
        """A malformed diff raises ValueError about missing SEARCH/REPLACE blocks."""
        original = "line1\nline2\n"
        bad_diff = "```diff\nthis is not a diff\n```"
        with pytest.raises(ValueError, match="No SEARCH/REPLACE blocks"):
            self.agent._apply_diff_and_extract(original, bad_diff)

    def test_missing_search_text_raises(self):
        """A SEARCH block must appear in the parent code."""
        original = "def solve():\n    return 1\n"
        patch = (
            "<<<<<<< SEARCH\n"
            "    return 2\n"
            "=======\n"
            "    return 3\n"
            ">>>>>>> REPLACE\n"
        )
        with pytest.raises(ValueError, match="SEARCH text not found"):
            self.agent._apply_diff_and_extract(original, patch)

    def test_non_unique_search_text_raises(self):
        """A SEARCH block must identify exactly one location."""
        original = "def solve():\n    x = 1\n    x = 1\n    return x\n"
        patch = (
            "<<<<<<< SEARCH\n"
            "    x = 1\n"
            "=======\n"
            "    x = 2\n"
            ">>>>>>> REPLACE\n"
        )
        with pytest.raises(ValueError, match="matches 2 locations"):
            self.agent._apply_diff_and_extract(original, patch)

    def test_empty_search_text_raises(self):
        """A SEARCH block cannot be empty."""
        original = "def solve():\n    return 1\n"
        patch = (
            "<<<<<<< SEARCH\n"
            "\n"
            "=======\n"
            "    return 2\n"
            ">>>>>>> REPLACE\n"
        )
        with pytest.raises(ValueError, match="empty SEARCH text"):
            self.agent._apply_diff_and_extract(original, patch)

    def test_invalid_patched_python_raises(self):
        """The final patched program must still parse as Python."""
        original = "def solve():\n    return 1\n"
        patch = (
            "<<<<<<< SEARCH\n"
            "    return 1\n"
            "=======\n"
            "    return (\n"
            ">>>>>>> REPLACE\n"
        )
        with pytest.raises(ValueError, match="not valid Python"):
            self.agent._apply_diff_and_extract(original, patch)

    def test_json_escaped_search_replace_payload(self):
        """JSON-escaped diff payloads are unescaped before block parsing."""
        original = "def solve():\n    return 1\n"
        patch = (
            "<<<<<<< SEARCH\\n"
            "    return 1\\n"
            "=======\\n"
            "    return 2\\n"
            ">>>>>>> REPLACE\\n"
        )
        fixed = self.agent._fix_json_escaped_code(patch, mode="diff")
        result = self.agent._apply_diff_and_extract(original, fixed)
        assert result == "def solve():\n    return 2\n"


# ---------------------------------------------------------------------------
# TestBuildPrompt
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    """Tests for MutationAgent.build_prompt."""

    def test_system_and_human_messages(self):
        """build_prompt produces SystemMessage + HumanMessage."""
        from langchain_core.messages import HumanMessage, SystemMessage

        agent = _make_agent(system_prompt="SYS")
        parent = _make_program(metadata={MUTATION_CONTEXT_METADATA_KEY: "context info"})
        state = _make_state(parents=[parent])

        result = agent.build_prompt(state)

        msgs = result["messages"]
        assert len(msgs) == 2
        assert isinstance(msgs[0], SystemMessage)
        assert isinstance(msgs[1], HumanMessage)
        assert msgs[0].content == "SYS"

    def test_parent_blocks_content(self):
        """Parent code and mutation context appear in user prompt."""
        agent = _make_agent()
        parent = _make_program(
            code="def solve(): return 1",
            metadata={MUTATION_CONTEXT_METADATA_KEY: "metrics: score=0.9"},
        )
        state = _make_state(parents=[parent])

        result = agent.build_prompt(state)

        user_content = result["messages"][1].content
        assert "def solve(): return 1" in user_content
        assert "metrics: score=0.9" in user_content
        assert "=== Parent 1 ===" in user_content

    def test_count_substitution(self):
        """Template {count} is replaced with number of parents."""
        agent = _make_agent()
        parents = [
            _make_program(metadata={MUTATION_CONTEXT_METADATA_KEY: f"ctx{i}"})
            for i in range(3)
        ]
        state = _make_state(parents=parents)

        result = agent.build_prompt(state)

        user_content = result["messages"][1].content
        assert "Mutate 3 parent programs:" in user_content

    def test_template_substitution_custom(self):
        """Custom template with {count} and {parent_blocks} placeholders."""
        agent = _make_agent(
            user_prompt_template="Process {count} programs.\n{parent_blocks}\nDone."
        )
        parent = _make_program(metadata={MUTATION_CONTEXT_METADATA_KEY: "some context"})
        state = _make_state(parents=[parent])

        result = agent.build_prompt(state)

        user_content = result["messages"][1].content
        assert user_content.startswith("Process 1 programs.")
        assert user_content.endswith("Done.")

    def test_inspiration_context_appended(self):
        """Optional inspiration context appears after the parent block."""
        agent = _make_agent(mutation_mode="diff")
        parent = _make_program(metadata={MUTATION_CONTEXT_METADATA_KEY: "parent ctx"})
        state = _make_state(
            parents=[parent],
            inspiration_context="## Inspiration Transitions\n\n### Inspiration Transition IT-1",
        )

        result = agent.build_prompt(state)

        user_content = result["messages"][1].content
        assert "parent ctx" in user_content
        assert "### Inspiration Transition IT-1" in user_content

    def test_rewrite_prompt_ignores_inspiration_context(self):
        """Rewrite prompts never receive inspiration cards."""
        agent = _make_agent(mutation_mode="rewrite")
        parent = _make_program(metadata={MUTATION_CONTEXT_METADATA_KEY: "parent ctx"})
        state = _make_state(
            parents=[parent],
            inspiration_context="## Inspiration Transitions\n\n### Inspiration Transition IT-1",
        )

        result = agent.build_prompt(state)

        user_content = result["messages"][1].content
        assert "parent ctx" in user_content
        assert "### Inspiration Transition IT-1" not in user_content


# ---------------------------------------------------------------------------
# TestParseResponse
# ---------------------------------------------------------------------------


class TestParseResponse:
    """Tests for MutationAgent.parse_response."""

    def test_rewrite_mode(self):
        """In rewrite mode, code is extracted from structured output directly."""
        agent = _make_agent(mutation_mode="rewrite")
        output = _make_structured_output(code="def solve(): return 99")
        state = _make_state(
            mutation_mode="rewrite",
            structured_output=output,
        )

        result = agent.parse_response(state)

        assert result["parsed_output"]["code"] == "def solve(): return 99"
        assert result["parsed_output"]["archetype"] == "Precision Optimization"
        assert (
            result["parsed_output"]["justification"]
            == "Improved via targeted mutation."
        )
        assert result["parsed_output"]["insights_used"] == ["insight_a"]
        assert result["parsed_output"]["inspirations_used"] == []

    def test_diff_mode(self):
        """In diff mode, the code field is treated as SEARCH/REPLACE blocks."""
        agent = _make_agent(mutation_mode="diff")
        original = "def solve():\n    x = 1\n    y = 2\n    return x + y\n"
        patch = (
            "<<<<<<< SEARCH\n"
            "    y = 2\n"
            "=======\n"
            "    y = 3\n"
            ">>>>>>> REPLACE\n"
        )
        parent = _make_program(code=original)
        output = _make_structured_output(code=patch)
        state = _make_state(
            parents=[parent],
            mutation_mode="diff",
            structured_output=output,
        )

        result = agent.parse_response(state)

        assert result["parsed_output"]["code"] == (
            "def solve():\n    x = 1\n    y = 3\n    return x + y"
        )

    def test_no_output(self):
        """When structured_output is None, parsed_output has empty code + error."""
        agent = _make_agent()
        state = _make_state()
        # No structured_output set

        result = agent.parse_response(state)

        assert result["parsed_output"]["code"] == ""
        assert "error" in result["parsed_output"]

    def test_diff_multi_parents_raises(self):
        """Diff mode with >1 parent raises ValueError (stored in error)."""
        agent = _make_agent(mutation_mode="diff")
        parents = [_make_program(), _make_program()]
        output = _make_structured_output(code="some diff text")
        state = _make_state(
            parents=parents,
            mutation_mode="diff",
            structured_output=output,
        )

        result = agent.parse_response(state)

        assert result["parsed_output"]["code"] == ""
        assert "exactly 1 parent" in result["parsed_output"]["error"]


# ---------------------------------------------------------------------------
# TestAcallLlm
# ---------------------------------------------------------------------------


class TestAcallLlm:
    """Tests for MutationAgent.acall_llm."""

    @pytest.mark.asyncio
    async def test_success(self):
        """Successful LLM call populates llm_response and structured_output."""
        agent = _make_agent()
        expected = _make_structured_output()
        agent.structured_llm = AsyncMock(return_value=expected)
        agent.structured_llm.ainvoke = AsyncMock(return_value=expected)

        state = _make_state()
        from langchain_core.messages import HumanMessage

        state["messages"] = [HumanMessage(content="test")]

        result = await agent.acall_llm(state)

        assert result["llm_response"] is expected
        assert result["structured_output"] is expected

    @pytest.mark.asyncio
    async def test_success_forwards_messages_to_llm(self):
        """acall_llm passes the exact messages list to structured_llm.ainvoke."""
        agent = _make_agent()
        expected = _make_structured_output()
        agent.structured_llm = MagicMock()
        agent.structured_llm.ainvoke = AsyncMock(return_value=expected)

        from langchain_core.messages import HumanMessage, SystemMessage

        msgs = [SystemMessage(content="sys"), HumanMessage(content="user")]
        state = _make_state()
        state["messages"] = msgs

        await agent.acall_llm(state)

        agent.structured_llm.ainvoke.assert_awaited_once()
        args, kwargs = agent.structured_llm.ainvoke.await_args
        assert args == (msgs,)
        assert kwargs["config"]["run_name"] == "MutationStage"

    @pytest.mark.asyncio
    async def test_success_adds_langfuse_trace_config(self, monkeypatch):
        """acall_llm names and tags mutation calls for Langfuse tracing."""
        monkeypatch.delenv("LANGFUSE_SESSION_ID", raising=False)
        monkeypatch.delenv("LANGFUSE_TAGS", raising=False)

        agent = _make_agent()
        expected = _make_structured_output()
        agent.structured_llm = MagicMock()
        agent.structured_llm.ainvoke = AsyncMock(return_value=expected)

        from langchain_core.messages import HumanMessage

        parent = _make_program()
        state = _make_state(parents=[parent], prompt_id="prompt-123")
        state["messages"] = [HumanMessage(content="test")]

        await agent.acall_llm(state)

        config = agent.structured_llm.ainvoke.await_args.kwargs["config"]
        assert config["run_name"] == "MutationStage"
        assert "MutationStage" in config["tags"]
        assert config["metadata"]["langfuse_session_id"].startswith("mutation:rewrite:")
        assert config["metadata"]["langfuse_tags"] == config["tags"]
        assert config["metadata"]["parent_ids"] == [parent.id]

    @pytest.mark.asyncio
    async def test_success_preserves_langfuse_env_trace_config(self, monkeypatch):
        """acall_llm preserves launch-level Langfuse session and tags."""
        monkeypatch.setenv("LANGFUSE_SESSION_ID", "launch-session")
        monkeypatch.setenv("LANGFUSE_TAGS", "run-tag,MutationStage,prod,,run-tag")

        agent = _make_agent()
        expected = _make_structured_output()
        agent.structured_llm = MagicMock()
        agent.structured_llm.ainvoke = AsyncMock(return_value=expected)

        from langchain_core.messages import HumanMessage

        parent = _make_program()
        state = _make_state(parents=[parent], prompt_id="prompt-123")
        state["messages"] = [HumanMessage(content="test")]

        await agent.acall_llm(state)

        config = agent.structured_llm.ainvoke.await_args.kwargs["config"]
        tags = config["tags"]
        assert config["metadata"]["langfuse_session_id"] == "launch-session"
        assert tags == config["metadata"]["langfuse_tags"]
        assert tags.count("MutationStage") == 1
        assert tags.count("run-tag") == 1
        assert set(tags) >= {"MutationStage", "MutationAgent", "run-tag", "prod"}

    @pytest.mark.asyncio
    async def test_exception_sets_error(self):
        """When the LLM raises, state gets an error field and llm_response is None."""
        agent = _make_agent()
        agent.structured_llm = MagicMock()
        agent.structured_llm.ainvoke = AsyncMock(
            side_effect=RuntimeError("LLM exploded")
        )

        state = _make_state()
        from langchain_core.messages import HumanMessage

        state["messages"] = [HumanMessage(content="test")]

        result = await agent.acall_llm(state)

        assert result["llm_response"] is None
        assert "LLM exploded" in result["error"]


# ---------------------------------------------------------------------------
# TestArun
# ---------------------------------------------------------------------------


class TestArun:
    """Tests for MutationAgent.arun end-to-end."""

    @pytest.mark.asyncio
    async def test_end_to_end_mocked_graph(self):
        """arun invokes the graph and returns parsed_output from final state."""
        agent = _make_agent()

        expected_parsed = {
            "code": "def solve(): return 99",
            "structured_output": {"archetype": "test"},
            "archetype": "test",
            "justification": "test justification",
            "insights_used": [],
        }

        # Mock the compiled graph's ainvoke to return a state with parsed_output
        agent.graph = AsyncMock()
        agent.graph.ainvoke = AsyncMock(return_value={"parsed_output": expected_parsed})

        parent = _make_program(metadata={MUTATION_CONTEXT_METADATA_KEY: "ctx"})
        result = await agent.arun(input=[parent], mutation_mode="rewrite")

        assert result == expected_parsed
        agent.graph.ainvoke.assert_called_once()

        # Verify the initial state structure passed to graph
        call_args = agent.graph.ainvoke.call_args[0][0]
        assert call_args["input"] == [parent]
        assert call_args["mutation_mode"] == "rewrite"
        assert call_args["messages"] == []
        assert call_args["final_code"] == ""

    @pytest.mark.asyncio
    async def test_arun_returns_empty_dict_when_no_parsed_output(self):
        """When graph returns state without parsed_output, arun returns {}."""
        agent = _make_agent()
        agent.graph = AsyncMock()
        agent.graph.ainvoke = AsyncMock(return_value={"error": "something"})

        parent = _make_program(metadata={MUTATION_CONTEXT_METADATA_KEY: "ctx"})
        result = await agent.arun(input=[parent], mutation_mode="rewrite")
        assert result == {"prompt_id": None}


# ---------------------------------------------------------------------------
# TestMutationStructuredOutput
# ---------------------------------------------------------------------------


class TestMutationStructuredOutput:
    """Tests for the MutationStructuredOutput Pydantic model."""

    def test_defaults(self):
        """List fields default to empty lists."""
        out = MutationStructuredOutput(
            archetype="test",
            justification="just",
            code="print(1)",
        )
        assert out.insights_used == []
        assert out.inspirations_used == []
        assert out.changes == []

    def test_model_dump(self):
        """model_dump returns all fields."""
        out = _make_structured_output()
        d = out.model_dump()
        assert set(d.keys()) == {
            "archetype",
            "justification",
            "insights_used",
            "inspirations_used",
            "changes",
            "code",
        }
        assert d["changes"] == []


# ---------------------------------------------------------------------------
# TestMutationPromptFields
# ---------------------------------------------------------------------------


class TestMutationPromptFields:
    """Tests for MutationPromptFields validation."""

    def test_valid(self):
        fields = MutationPromptFields(count=2, parent_blocks="block1\nblock2")
        assert fields.count == 2
        assert "block1" in fields.parent_blocks


# ---------------------------------------------------------------------------
# TestBuildPromptEdgeCases
# ---------------------------------------------------------------------------


class TestBuildPromptEdgeCases:
    """Edge cases for build_prompt."""

    def test_missing_mutation_context_key_produces_empty_context(self):
        """When MUTATION_CONTEXT_METADATA_KEY is absent, formatted_context is empty string."""
        agent = _make_agent()
        parent = _make_program(code="def solve(): return 1", metadata={})
        state = _make_state(parents=[parent])

        result = agent.build_prompt(state)
        user_content = result["messages"][1].content
        # metadata.get(key) returns None → or "" → no "None" literal in prompt
        assert "None" not in user_content

    def test_multiple_parents_count(self):
        """build_prompt with 3 parents produces count=3."""
        agent = _make_agent()
        parents = [
            _make_program(metadata={MUTATION_CONTEXT_METADATA_KEY: f"ctx{i}"})
            for i in range(3)
        ]
        state = _make_state(parents=parents)

        result = agent.build_prompt(state)
        user_content = result["messages"][1].content
        assert "Mutate 3 parent programs:" in user_content
        assert "=== Parent 1 ===" in user_content
        assert "=== Parent 2 ===" in user_content
        assert "=== Parent 3 ===" in user_content


# ---------------------------------------------------------------------------
# TestParseResponseEdgeCases
# ---------------------------------------------------------------------------


class TestParseResponseEdgeCases:
    """Edge cases for parse_response."""

    def test_rewrite_with_fenced_code(self):
        """In rewrite mode, code surrounded by fences is extracted properly."""
        agent = _make_agent(mutation_mode="rewrite")
        output = _make_structured_output(code="```python\ndef solve(): return 99\n```")
        state = _make_state(mutation_mode="rewrite", structured_output=output)

        result = agent.parse_response(state)
        assert result["parsed_output"]["code"] == "def solve(): return 99"

    def test_error_in_diff_application_stored_in_parsed_output(self):
        """When diff application fails, error is captured in parsed_output."""
        agent = _make_agent(mutation_mode="diff")
        parent = _make_program(code="original code\n")
        output = _make_structured_output(code="this is not a valid diff")
        state = _make_state(
            parents=[parent], mutation_mode="diff", structured_output=output
        )

        result = agent.parse_response(state)
        assert result["parsed_output"]["code"] == ""
        assert "error" in result["parsed_output"]
