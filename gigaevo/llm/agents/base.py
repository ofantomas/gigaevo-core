"""Base class for LangGraph agents.

This module provides the abstract LangGraphAgent base class that all
LLM-based agents inherit from. Each agent defines its own domain-specific
state schema using TypedDict.
"""

import asyncio
from abc import ABC, abstractmethod
import json
import os
from typing import Any

from langchain_core.runnables import Runnable, RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from loguru import logger

from gigaevo.llm.models import MultiModelRouter, get_selected_model


def _langfuse_metadata_value(value: Any, max_len: int = 200) -> str:
    """Return a string value acceptable for Langfuse propagated metadata."""
    if isinstance(value, (list, tuple, set)):
        text = ",".join(str(item) for item in value)
    else:
        text = str(value)
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 3]}..."


class LangGraphAgent(ABC):
    """Abstract base for all LLM agents using LangGraph.

    Each agent must:
    1. Define its own StateSchema (TypedDict) with domain-specific fields
    2. Implement build_prompt() to create LangChain messages
    3. Implement parse_response() to extract structured output

    The base class provides:
    - Generic async LLM invocation (acall_llm)
    - Graph construction (build_prompt → call_llm → parse_response)
    - Agent execution (arun method)

    Example:
        >>> class MyState(TypedDict):
        ...     data: str
        ...     messages: list[BaseMessage]
        ...     llm_response: AIMessage
        ...     result: str
        >>>
        >>> class MyAgent(LangGraphAgent):
        ...     StateSchema = MyState
        ...
        ...     def build_prompt(self, state):
        ...         state["messages"] = [HumanMessage(state["data"])]
        ...         return state
        ...
        ...     def parse_response(self, state):
        ...         state["result"] = state["llm_response"].content
        ...         return state
    """

    # Subclasses must define their StateSchema
    StateSchema: type

    def __init__(self, llm: ChatOpenAI | MultiModelRouter | Runnable):
        """Initialize agent with LLM.

        Args:
            llm: LangChain chat model, multi-model router, or structured output runnable
        """
        self.llm = llm
        self.graph = self._build_graph()
        logger.info(f"[{self.__class__.__name__}] Initialized")

    @abstractmethod
    def build_prompt(self, state: Any) -> Any:
        """Build LangChain messages from domain state.

        Must populate state["messages"] with appropriate message list.

        Args:
            state: Domain-specific state dict

        Returns:
            Updated state with messages populated
        """
        pass

    async def acall_llm(self, state: Any) -> Any:
        """Generic async LLM call.

        Invokes the LLM with messages from state and stores response.
        Also tracks which model was used for debugging.

        Args:
            state: State with messages field

        Returns:
            Updated state with llm_response field
        """
        response = None
        for attempt in range(3):
            try:
                response = await self.llm.ainvoke(
                    state["messages"],
                    config=self._llm_run_config(state),
                )
                break
            except json.JSONDecodeError:
                if attempt == 2:
                    raise
                logger.warning(
                    "[{}] LLM response JSON decode failed; retrying ({}/3)",
                    self.__class__.__name__,
                    attempt + 2,
                )
                await asyncio.sleep(1.5 * (attempt + 1))

        state["llm_response"] = response

        # Track metadata
        if "metadata" not in state:
            state["metadata"] = {}
        model_used = get_selected_model()
        if model_used is None and hasattr(self.llm, "model_name"):
            model_used = getattr(self.llm, "model_name")
        if model_used:
            state["metadata"]["model_used"] = model_used

        return state

    def _llm_run_config(self, state: Any) -> RunnableConfig:
        """Build LangChain run config with useful Langfuse trace metadata."""
        agent_name = self.__class__.__name__
        stage_name = (
            agent_name.removesuffix("Agent") + "Stage"
            if agent_name.endswith("Agent")
            else agent_name
        )

        env_tags = [
            tag.strip()
            for tag in os.environ.get("LANGFUSE_TAGS", "").split(",")
            if tag.strip()
        ]
        tags = list(dict.fromkeys([*env_tags, stage_name, agent_name]))

        state_metadata = {}
        if isinstance(state, dict):
            raw_metadata = state.get("metadata", {})
            if isinstance(raw_metadata, dict):
                state_metadata = raw_metadata

        metadata: dict[str, Any] = {
            "stage": stage_name,
            "agent": agent_name,
            "langfuse_tags": tags,
        }
        for key, value in state_metadata.items():
            metadata[key] = _langfuse_metadata_value(value)

        session_id = os.environ.get("LANGFUSE_SESSION_ID")
        if not session_id:
            parent_id = state_metadata.get("parent_id")
            child_id = state_metadata.get("child_id")
            program_id = state_metadata.get("program_id")
            if parent_id and child_id:
                session_id = f"{stage_name}:{str(parent_id)[:8]}->{str(child_id)[:8]}"
            elif program_id:
                session_id = f"{stage_name}:{str(program_id)[:8]}"
            else:
                session_id = stage_name
        metadata["langfuse_session_id"] = _langfuse_metadata_value(session_id)

        return {
            "run_name": stage_name,
            "tags": tags,
            "metadata": metadata,
        }

    @abstractmethod
    def parse_response(self, state: Any) -> Any:
        """Parse LLM response into domain output.

        Extracts relevant information from state["llm_response"]
        and stores it in a domain-specific output field.

        Args:
            state: State with llm_response field

        Returns:
            Updated state with parsed output
        """
        pass

    def _build_graph(self) -> CompiledStateGraph:
        """Build LangGraph execution graph.

        Creates a simple 3-node linear graph:
        build_prompt → call_llm → parse_response → END

        Returns:
            Compiled LangGraph
        """
        workflow: StateGraph = StateGraph(self.StateSchema)

        workflow.add_node("build_prompt", self.build_prompt)
        workflow.add_node("call_llm", self.acall_llm)
        workflow.add_node("parse_response", self.parse_response)

        workflow.set_entry_point("build_prompt")
        workflow.add_edge("build_prompt", "call_llm")
        workflow.add_edge("call_llm", "parse_response")
        workflow.add_edge("parse_response", END)

        return workflow.compile()

    @abstractmethod
    async def arun(self, *args, **kwargs) -> Any:
        """Execute agent and return result.

        Each agent defines its own signature based on domain needs.
        For example:
        - InsightsAgent.arun(program: Program) -> list[dict]
        - LineageAgent.arun(parent: Program, child: Program) -> list[dict]

        This method should:
        1. Create initial state with domain-specific fields
        2. Invoke the graph
        3. Return the parsed output
        """
        pass
