"""Registry-resolved tools participate in the ToolChatAgent tool loop.

Lives in the chat_kit test package on purpose: this file exercises the
pydantic-ai loop, and the chat_kit test directory is what gets pruned on
langchain-framework and memory-backend stacks.
"""

from collections.abc import Generator
from dataclasses import dataclass

from pydantic_ai.models.test import TestModel
import pytest

from app.services.ai.chat_kit import ChatScope, DoneFrame, ToolChatAgent
from app.services.ai.tools import register_tool, resolve_tools, unregister_tool


@dataclass
class _Deps:
    subject_id: int


@pytest.fixture
def registered_lookup() -> Generator[str]:
    async def lookup(key: str) -> str:
        """Look up a value for a key."""
        return f"val-{key}"

    register_tool("lookup", lookup)
    yield "lookup"
    unregister_tool("lookup")


async def test_registered_tool_is_called_in_the_loop(registered_lookup: str) -> None:
    """An app-registered tool, resolved by name, runs inside a turn."""
    agent: ToolChatAgent[_Deps] = ToolChatAgent(
        model=TestModel(call_tools=[registered_lookup]),
        model_name="test-model",
        instructions="You are a test persona.",
        deps_type=_Deps,
        tools=resolve_tools([registered_lookup]),
        recorder=lambda **kwargs: 0.0,
    )

    frames = [
        f
        async for f in agent.stream_turn(
            scope=ChatScope(user_id="u1", surface="test"),
            deps=_Deps(1),
            message="q",
        )
    ]

    done = frames[-1]
    assert isinstance(done, DoneFrame)
    assert done.tool_calls == 1
