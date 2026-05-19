import ast
from datetime import UTC, datetime
import os
import re
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from loguru import logger
from pydantic import BaseModel, Field

from gigaevo.evolution.mutation.base import MutationSpec
from gigaevo.evolution.mutation.constants import (
    MUTATION_CONTEXT_METADATA_KEY,
    MUTATION_MEMORY_METADATA_KEY,
)
from gigaevo.llm.agents.base import LangGraphAgent
from gigaevo.llm.models import MultiModelRouter, get_selected_model
from gigaevo.programs.program import Program

if TYPE_CHECKING:
    from gigaevo.programs.metrics.context import MetricsContext
    from gigaevo.prompts.fetcher import PromptFetcher


class MutationChange(BaseModel):
    """Tracker-friendly description of one introduced change."""

    description: str = Field(
        description=(
            "Generalizable description of the introduced change, optionally followed "
            "by concrete specifics when they matter. Prefer `general pattern + "
            "concrete instance` over a narrow one-off description."
        )
    )
    explanation: str = Field(
        description=(
            "Explain why this change was introduced, why it helped for this "
            "program, and when possible why the same idea could transfer to future "
            "mutations."
        )
    )


class MutationStructuredOutput(BaseModel):
    """Structured output from the mutation LLM.

    Simplified schema to reduce cognitive overhead and let LLM focus on code quality.
    """

    archetype: str = Field(
        description="Selected evolutionary archetype (e.g., 'Precision Optimization', 'Computational Reinvention')"
    )
    justification: str = Field(
        description="2-3 sentences: which insights acted on, strategy used, expected mechanism of improvement"
    )
    insights_used: list[str] = Field(
        default_factory=list,
        description="Flat list of insight strings that were acted on (verbatim from input)",
    )
    changes: list[MutationChange] = Field(
        default_factory=list,
        description=(
            "Key introduced changes. Each item must contain a reusable or "
            "generalizable description plus an explanation of why the change was "
            "introduced."
        ),
    )
    code: str = Field(
        description=(
            "The complete mutated Python source code. "
            "Must be valid Python starting with imports or def statements. "
            "NEVER put JSON, format examples, or templates here. "
            "Use actual newlines between lines, not literal backslash-n."
        )
    )


class MutationStructuredOutputDiff(MutationStructuredOutput):
    """Diff-mode variant: `code` holds SEARCH/REPLACE blocks against the parent."""

    code: str = Field(
        description=(
            "One or more SEARCH/REPLACE blocks against Parent 1. Each block has "
            "the exact form:\n"
            "<<<<<<< SEARCH\n"
            "<verbatim block from Parent 1, including leading/trailing whitespace>\n"
            "=======\n"
            "<replacement block (or empty to delete)>\n"
            ">>>>>>> REPLACE\n"
            "The SEARCH text must appear EXACTLY ONCE in Parent 1 — copy enough "
            "surrounding context to make it unique. Multiple blocks are applied "
            "in order. Do NOT emit unified diffs (no `---`/`+++`/`@@`), do NOT "
            "emit full Python source, do NOT wrap in markdown fences. Use actual "
            "newlines, not literal backslash-n."
        )
    )


def _select_output_schema(mutation_mode: str) -> type[MutationStructuredOutput]:
    """Return the Pydantic output schema appropriate for the mutation mode."""
    if mutation_mode == "diff":
        return MutationStructuredOutputDiff
    return MutationStructuredOutput


# Re-export from canonical location for backward compatibility
MUTATION_OUTPUT_METADATA_KEY = MutationSpec.META_OUTPUT


class MutationPromptFields(BaseModel):
    """
    Example template:
        "Mutate {count} parent programs:\n{parent_blocks}"
    """

    count: int = Field(description="Number of parent programs")
    parent_blocks: str = Field(
        description="Formatted parent program blocks with code, metrics, insights"
    )


class MutationState(TypedDict):
    """State for mutation agent."""

    input: list[Program]
    mutation_mode: str
    messages: list[BaseMessage]
    llm_response: Any
    final_code: str
    mutation_label: str
    # Fields set during prompt building (optional initially)
    system_prompt: NotRequired[str]
    user_prompt: NotRequired[str]
    # Prompt tracking ID (None for fixed prompts, sha256[:16] for co-evolved prompts)
    prompt_id: NotRequired[str | None]
    # Fields set during response parsing (optional initially)
    parsed_output: NotRequired[dict[str, Any]]
    structured_output: NotRequired[MutationStructuredOutput]
    metadata: NotRequired[dict[str, Any]]
    error: NotRequired[str]


def _langfuse_metadata_value(value: Any, max_len: int = 200) -> str:
    """Return a string value acceptable for Langfuse propagated metadata."""
    if isinstance(value, (list, tuple, set)):
        text = ",".join(str(item) for item in value)
    else:
        text = str(value)
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 3]}..."


class MutationAgent(LangGraphAgent):
    """Agent for LLM-based code mutation.

    This agent handles the complete workflow of mutating programs:
    1. Build prompt from parent programs using pre-formatted mutation context
    2. Call LLM to generate structured output (archetype, justification, code)
    3. Extract and parse the structured output (handling diffs if needed)

    Attributes:
        mutation_mode: "rewrite" or "diff"
        system_prompt: System prompt
        user_prompt_template: User prompt template string
        structured_llm: LLM configured for structured output
    """

    StateSchema = MutationState

    def __init__(
        self,
        llm: ChatOpenAI | MultiModelRouter,
        system_prompt: str,
        user_prompt_template: str,
        mutation_mode: str = "rewrite",
        # Optional: enable dynamic prompt fetching
        prompt_fetcher: "PromptFetcher | None" = None,
        task_description: str = "",
        metrics_context: "MetricsContext | None" = None,
    ):
        """Initialize mutation agent.

        Args:
            llm: LangChain chat model or router
            mutation_mode: "rewrite" or "diff"
            system_prompt: System prompt string (static or initial value)
            user_prompt_template: User prompt template string
            prompt_fetcher: Optional fetcher for dynamic prompt co-evolution.
                When set and is_dynamic=True, system_prompt is refreshed on
                every build_prompt() call. For FixedDirPromptFetcher, the
                static system_prompt is used without re-fetching.
            task_description: Task description for prompt template formatting
                (required when prompt_fetcher.is_dynamic is True)
            metrics_context: Metrics context for prompt template formatting
                (required when prompt_fetcher.is_dynamic is True)
        """
        self.mutation_mode = mutation_mode
        self.system_prompt = system_prompt
        self.user_prompt_template = user_prompt_template
        # Prompt-type names used for (re)fetching from the prompt fetcher.
        # In diff mode we prefer mutation/{system,user}_diff.txt so the LLM
        # sees diff-specific instructions and so a co-evolving prompt archive
        # can hold a separate diff-mode champion.
        if mutation_mode == "diff":
            self._system_prompt_type = "system_diff"
            self._user_prompt_type = "user_diff"
        else:
            self._system_prompt_type = "system"
            self._user_prompt_type = "user"

        # Dynamic prompt fetching support
        self._prompt_fetcher = prompt_fetcher
        self._task_description = task_description
        if metrics_context is not None:
            from gigaevo.programs.metrics.formatter import MetricsFormatter

            self._metrics_formatter: MetricsFormatter | None = MetricsFormatter(
                metrics_context
            )
        else:
            self._metrics_formatter = None

        # Create structured output LLM (schema varies with mutation mode so
        # the `code` field description tells the LLM what to emit).
        self.structured_llm = llm.with_structured_output(
            _select_output_schema(mutation_mode)
        )

        super().__init__(llm)

    _PROMPT_LOG_DIR = os.environ.get("GIGAEVO_PROMPT_LOG_DIR", "")

    def _dump_prompt_to_file(
        self, prompt_id: str | None, system: str, user: str
    ) -> None:
        """Write full system+user prompts to a log file for offline inspection."""
        log_dir = self._PROMPT_LOG_DIR
        if not log_dir:
            return
        try:
            os.makedirs(log_dir, exist_ok=True)
            ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
            pid = prompt_id or "fixed"
            path = os.path.join(log_dir, f"{ts}_{pid[:12]}.txt")
            with open(path, "w") as f:
                f.write(f"=== PROMPT DUMP {ts} ===\n")
                f.write(f"prompt_id: {prompt_id}\n\n")
                f.write("=== SYSTEM PROMPT ===\n")
                f.write(system)
                f.write("\n\n=== USER PROMPT ===\n")
                f.write(user)
                f.write("\n")
        except Exception as exc:
            logger.debug(f"[MutationAgent] prompt dump failed: {exc}")

    async def arun(self, input: list[Program], mutation_mode: str) -> dict:
        """Execute mutation agent.

        Args:
            input: List of parent programs to mutate
            mutation_mode: Mutation mode

        Returns:
            Dict with 'code', 'structured_output', 'prompt_id', and other results
        """
        initial_state: MutationState = {
            "input": input,
            "mutation_mode": mutation_mode,
            "messages": [],
            "llm_response": None,
            "final_code": "",
            "mutation_label": "",
        }

        final_state = await self.graph.ainvoke(initial_state)
        result = final_state.get("parsed_output", {})
        # Forward prompt_id from state into result for operator to stamp in metadata
        result["prompt_id"] = final_state.get("prompt_id")
        return result

    def _llm_run_config(self, state: MutationState) -> RunnableConfig:
        """Build tracing config for the mutation structured LLM call."""
        parents = state.get("input", [])
        parent_ids = [p.id for p in parents]
        parent_short_ids = [p.short_id for p in parents]
        prompt_id = state.get("prompt_id") or "fixed"
        mutation_mode = state["mutation_mode"]

        mutation_tags = [
            "MutationStage",
            "MutationAgent",
            f"mutation_mode:{mutation_mode}",
            f"prompt:{prompt_id}",
        ]
        env_tags = [
            tag.strip()
            for tag in os.environ.get("LANGFUSE_TAGS", "").split(",")
            if tag.strip()
        ]
        tags = list(dict.fromkeys([*env_tags, *mutation_tags]))

        parent_fragment = ",".join(parent_short_ids) or "no-parents"
        synthetic_session_id = f"mutation:{mutation_mode}:{parent_fragment}"[:200]
        session_id = os.environ.get("LANGFUSE_SESSION_ID") or synthetic_session_id

        metadata: dict[str, Any] = {
            "stage": "MutationStage",
            "agent": "MutationAgent",
            "mutation_mode": mutation_mode,
            "parent_count": _langfuse_metadata_value(len(parents)),
            "parent_ids": _langfuse_metadata_value(parent_ids),
            "parent_short_ids": _langfuse_metadata_value(parent_short_ids),
            "prompt_id": _langfuse_metadata_value(prompt_id),
            # Langfuse's LangChain handler reads these trace attributes from metadata.
            "langfuse_session_id": session_id,
            "langfuse_tags": tags,
        }

        return {
            "run_name": "MutationStage",
            "tags": tags,
            "metadata": metadata,
        }

    async def acall_llm(self, state: MutationState) -> MutationState:
        """Call LLM with structured output.

        Uses the structured LLM to get a MutationStructuredOutput response.

        Args:
            state: State with messages field

        Returns:
            Updated state with llm_response and structured_output fields
        """
        structured_response: Any = None
        try:
            structured_response = await self.structured_llm.ainvoke(
                state["messages"],
                config=self._llm_run_config(state),
            )
            state["llm_response"] = structured_response
            state["structured_output"] = structured_response
            if "metadata" not in state:
                state["metadata"] = {}
            model_used = get_selected_model()
            if model_used:
                state["metadata"]["model_used"] = model_used

            logger.debug(
                "[MutationAgent] Received structured output — archetype: {}, model: {}",
                structured_response.archetype,
                model_used or "(single model)",
            )

        except Exception as e:
            logger.error(f"[MutationAgent] Structured LLM call failed: {e}")
            state["error"] = str(e)
            state["llm_response"] = None

        return state

    def build_prompt(self, state: MutationState) -> MutationState:
        """Build mutation prompt from parent programs.

        Uses pre-formatted mutation context from MutationContextStage that includes:
        - Metrics (formatted)
        - Insights
        - Family tree lineage

        If a dynamic prompt_fetcher is configured (is_dynamic=True), refreshes the
        system prompt from the co-evolving archive and stamps prompt_id in state.

        Args:
            state: Current state with parents field

        Returns:
            Updated state with messages field and optional prompt_id
        """
        # Refresh system and user prompts from dynamic fetcher if available
        if (
            self._prompt_fetcher is not None
            and self._prompt_fetcher.is_dynamic
            and self._metrics_formatter is not None
        ):
            fetched_sys = self._prompt_fetcher.fetch(
                "mutation", self._system_prompt_type
            )
            self.system_prompt = fetched_sys.text.format(
                task_description=self._task_description,
                metrics_description=self._metrics_formatter.format_metrics_description(),
            )
            state["prompt_id"] = fetched_sys.prompt_id
            # Also refresh user prompt template if a co-evolved version is available
            fetched_user = self._prompt_fetcher.fetch(
                "mutation", self._user_prompt_type
            )
            if fetched_user.prompt_id is not None:
                self.user_prompt_template = fetched_user.text
        else:
            state["prompt_id"] = None

        parents = state["input"]
        user_prompt = self.build_user_prompt(parents)

        # Store prompts in state for logging
        state["system_prompt"] = self.system_prompt
        state["user_prompt"] = user_prompt

        # Build messages
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=user_prompt),
        ]

        state["messages"] = messages

        logger.info(
            f"[MutationAgent] Built prompt with {len(parents)} parents "
            f"(system: {len(self.system_prompt)} chars, "
            f"user: {len(user_prompt)} chars, "
            f"prompt_id={state.get('prompt_id', 'N/A')})"
        )
        # Dump full prompts to file for offline verification
        self._dump_prompt_to_file(
            state.get("prompt_id"), self.system_prompt, user_prompt
        )

        return state

    def build_user_prompt(self, parents: list[Program]) -> str:
        """Build the mutation user prompt for a set of parents."""
        parent_blocks = self._build_parent_blocks(parents)
        memory_block = self._build_memory_block(parents)
        if memory_block:
            parent_blocks = f"{parent_blocks}\n\n{memory_block}"
        prompt_fields = MutationPromptFields(
            count=len(parents), parent_blocks=parent_blocks
        )
        return self.user_prompt_template.format(**prompt_fields.model_dump())

    def _build_parent_blocks(self, parents: list[Program]) -> str:
        """Build formatted parent blocks for the mutation prompt."""
        blocks: list[str] = []
        for i, p in enumerate(parents):
            formatted_context = p.metadata.get(MUTATION_CONTEXT_METADATA_KEY) or ""

            block = f"""=== Parent {i + 1} ===
```python
{p.code}
```

{formatted_context}
"""
            blocks.append(block)

        return "\n\n".join(blocks)

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

    def parse_response(self, state: MutationState) -> MutationState:
        """Parse LLM structured response to extract code and metadata.

        Handles both rewrite mode (direct code from structured output) and diff mode
        (extract and apply diff from code field).

        Args:
            state: Current state with llm_response (structured output) field

        Returns:
            Updated state with parsed_output field containing final code and metadata
        """
        structured_output: MutationStructuredOutput | None = state.get(
            "structured_output"
        )
        model_used = state.get("metadata", {}).get("model_used")

        if structured_output is None:
            error_msg = state.get("error", "No structured output received")
            logger.error(f"[MutationAgent] No structured output: {error_msg}")
            state["parsed_output"] = {
                "code": "",
                "structured_output": None,
                "error": error_msg,
                "model_used": model_used,
            }
            return state

        try:
            # Get code from structured output
            code_from_llm = structured_output.code

            # Fix JSON-escaped sequences from structured output serialization.
            # LLMs sometimes produce literal \n, \t, \" in the code field when
            # they confuse JSON escaping with Python syntax. The acceptance
            # test for the unescaped result differs by mode (Python AST in
            # rewrite mode; SEARCH/REPLACE shape in diff mode).
            code_from_llm = self._fix_json_escaped_code(
                code_from_llm, mode=state["mutation_mode"]
            )

            if state["mutation_mode"] == "diff":
                # Apply diff to parent code
                parents = state["input"]
                if len(parents) != 1:
                    raise ValueError("Diff mode requires exactly 1 parent")

                parent_code = parents[0].code
                # The code field contains the diff in diff mode
                final_code = self._apply_diff_and_extract(parent_code, code_from_llm)
            else:
                # In rewrite mode, clean up the code (remove any remaining fences)
                final_code = self._extract_code_block(code_from_llm)
                # If no code block markers found, use as-is
                if final_code == code_from_llm.strip():
                    final_code = code_from_llm.strip()

            # Guard: reject code that is a JSON template echoed back instead of Python
            if "def " not in final_code and final_code.lstrip().startswith("{"):
                raise ValueError(
                    "LLM returned JSON template as code instead of Python. "
                    f"Code starts with: {final_code[:80]!r}"
                )

            state["final_code"] = final_code

            # Convert structured output to dict for storage
            structured_dict = structured_output.model_dump()

            state["parsed_output"] = {
                "code": final_code,
                "structured_output": structured_dict,
                "archetype": structured_output.archetype,
                "justification": structured_output.justification,
                "insights_used": structured_output.insights_used,
                "changes": structured_output.changes,
                "model_used": model_used,
            }

            logger.debug(
                f"[MutationAgent] Extracted code ({len(final_code)} chars) "
                f"with archetype: {structured_output.archetype}"
            )

        except Exception as e:
            logger.error(f"[MutationAgent] Failed to parse structured response: {e}")
            state["error"] = str(e)
            state["parsed_output"] = {
                "code": "",
                "structured_output": (
                    structured_output.model_dump() if structured_output else None
                ),
                "error": str(e),
                "model_used": model_used,
            }

        return state

    @staticmethod
    def _looks_like_diff_payload(text: str) -> bool:
        """Heuristic: does *text* look like a SEARCH/REPLACE diff payload?

        Used to decide whether a JSON-unescaped payload is a plausible
        SEARCH/REPLACE diff in diff mode (where AST-parsing isn't a valid
        acceptance test). Conservative: requires all three marker tokens
        so we don't accidentally treat arbitrary text as a diff.
        """
        return (
            "<<<<<<< SEARCH" in text
            and "=======" in text
            and ">>>>>>> REPLACE" in text
        )

    @classmethod
    def _fix_json_escaped_code(cls, code: str, mode: str = "rewrite") -> str:
        """Fix JSON-escaped sequences in code from structured output.

        LLMs using structured output sometimes produce literal JSON escape
        sequences in the code field instead of the actual characters:
        - ``\\"`` instead of ``"`` (double-escaped quotes)
        - ``\\n`` instead of actual newlines (escaped newlines)
        - ``\\t`` instead of actual tabs (escaped tabs)

        Acceptance test for the unescaped result depends on *mode*:

        - ``rewrite`` (default): unescape iff the result parses as Python.
          Preserves prior behavior.
        - ``diff``: unescape iff the result looks like a SEARCH/REPLACE
          payload (contains all three marker tokens). The Python AST check
          is not applicable to diffs, so without this branch the unescape
          would never fire and JSON-escaped diffs would reach the
          SEARCH/REPLACE parser as one giant line with literal ``\\n``
          sequences.
        """
        # Quick check: does code contain any JSON escape sequences?
        if "\\n" not in code and '\\"' not in code and "\\t" not in code:
            return code

        if mode == "diff":
            # Don't pre-check the original — a JSON-escaped diff *can*
            # contain marker substrings on one giant line; we care that the
            # *unescaped* version is plausibly a multi-line SEARCH/REPLACE
            # payload.
            cleaned = (
                code.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')
            )
            if cls._looks_like_diff_payload(cleaned):
                logger.debug(
                    '[MutationAgent] Fixed JSON-escaped diff (\\n={}, \\t={}, \\"={})',
                    code.count("\\n"),
                    code.count("\\t"),
                    code.count('\\"'),
                )
                return cleaned
            return code  # Unescaped result doesn't look like a diff — leave alone

        # Rewrite mode (default): gate on AST validity, as before.
        try:
            ast.parse(code)
            return code  # Already valid — don't touch it
        except SyntaxError:
            pass

        # Try unescaping JSON sequences
        cleaned = code.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')
        try:
            ast.parse(cleaned)
            logger.debug(
                '[MutationAgent] Fixed JSON-escaped code (\\n={}, \\t={}, \\"={})',
                code.count("\\n"),
                code.count("\\t"),
                code.count('\\"'),
            )
            return cleaned
        except SyntaxError:
            return code  # Unescaping didn't help — return original

    def _extract_code_block(self, text: str) -> str:
        """Extract outer fenced code block from LLM response.

        Treats only fences at start-of-line as valid markers to avoid
        premature closing on backticks inside code (e.g., docstrings).

        Args:
            text: LLM response text

        Returns:
            Extracted code string
        """
        # Find first opening fence at start-of-line
        open_match = re.search(r"(?m)^```(?:[a-zA-Z0-9_+\-]+)?\s*$", text)
        if not open_match:
            return text.strip()

        # Find closing fence after opener
        after_open = text[open_match.end() :]
        close_match = re.search(r"(?m)^```\s*$", after_open)
        if not close_match:
            return text.strip()

        code_block = after_open[: close_match.start()]

        # Trim single leading newline if present
        if code_block.startswith("\n"):
            code_block = code_block[1:]

        return code_block.rstrip()

    # SEARCH/REPLACE block markers. Loose matching on the marker line allows
    # minor LLM variations (extra spaces, trailing text) but the marker tokens
    # themselves are fixed.
    _SR_BLOCK_RE = re.compile(
        r"<{5,}\s*SEARCH\s*\n(.*?)\n={5,}\s*\n(.*?)\n>{5,}\s*REPLACE",
        re.DOTALL,
    )

    @classmethod
    def _parse_search_replace_blocks(cls, text: str) -> list[tuple[str, str]]:
        """Extract (search, replace) pairs from LLM output."""
        blocks = [
            (m.group(1), m.group(2)) for m in cls._SR_BLOCK_RE.finditer(text)
        ]
        if not blocks:
            raise ValueError(
                "No SEARCH/REPLACE blocks found. Expected `<<<<<<< SEARCH ... "
                "======= ... >>>>>>> REPLACE` markers."
            )
        return blocks

    @staticmethod
    def _apply_search_replace_blocks(
        original_code: str, blocks: list[tuple[str, str]]
    ) -> str:
        """Apply SEARCH/REPLACE blocks sequentially to original_code.

        Each SEARCH text must appear exactly once in the running parent. Multiple
        occurrences or zero occurrences cause rejection so the LLM must include
        enough surrounding context to disambiguate.
        """
        current = original_code
        for idx, (search, replace) in enumerate(blocks, start=1):
            if not search:
                raise ValueError(f"Block {idx}: empty SEARCH text")
            count = current.count(search)
            if count == 0:
                preview = search.splitlines()[0][:80] if search else ""
                raise ValueError(
                    f"Block {idx}: SEARCH text not found in parent "
                    f"(first line: {preview!r}). The LLM must copy the "
                    f"block verbatim from the parent including whitespace."
                )
            if count > 1:
                preview = search.splitlines()[0][:80] if search else ""
                raise ValueError(
                    f"Block {idx}: SEARCH text matches {count} locations in "
                    f"parent (first line: {preview!r}). Include more "
                    f"surrounding context to make the match unique."
                )
            current = current.replace(search, replace, 1)
        return current

    def _apply_diff_and_extract(self, original_code: str, response_text: str) -> str:
        """Extract SEARCH/REPLACE blocks from LLM response, apply, and validate.

        Args:
            original_code: Original parent code
            response_text: LLM response containing SEARCH/REPLACE blocks

        Returns:
            Patched code that is guaranteed to parse as valid Python.

        Raises:
            ValueError: If no blocks are found, a SEARCH text is missing /
                non-unique in the parent, or the final patched output does
                not parse as valid Python.
        """
        diff_text = self._extract_code_block(response_text)
        if not diff_text.strip():
            raise ValueError("Empty diff returned by LLM")

        try:
            blocks = self._parse_search_replace_blocks(diff_text)
            patched = self._apply_search_replace_blocks(original_code, blocks)
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Failed to apply patch: {e}") from e

        try:
            ast.parse(patched)
        except SyntaxError as e:
            raise ValueError(
                f"Patched code is not valid Python (line {e.lineno}): {e.msg}"
            ) from e

        return patched
