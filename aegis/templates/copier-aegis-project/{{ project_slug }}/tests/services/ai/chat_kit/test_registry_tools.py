"""Registry-resolved tools participate in the ToolChatAgent tool loop.

Lives in the chat_kit test package on purpose: this file exercises the
pydantic-ai loop, and the chat_kit test directory is what gets pruned on
langchain-framework and memory-backend stacks.
"""

from collections.abc import Generator
from dataclasses import dataclass
from typing import Any

from pydantic_ai.models.test import TestModel
import pytest

from app.services.ai.domains.chat.chat_kit import ChatScope, DoneFrame, ToolChatAgent
from app.services.ai.domains.chat.tools import (
    register_tool,
    resolve_tools,
    unregister_tool,
)


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


async def _turn(tool: str, scope: ChatScope) -> list[Any]:
    """One turn in which the model calls ``tool``, as its frames."""
    agent: ToolChatAgent[_Deps] = ToolChatAgent(
        model=TestModel(call_tools=[tool]),
        model_name="test-model",
        instructions="You are a test persona.",
        deps_type=_Deps,
        tools=resolve_tools([tool]),
        recorder=lambda **kwargs: 0.0,
    )
    return [f async for f in agent.stream_turn(scope=scope, deps=_Deps(1), message="q")]


async def test_registered_tool_is_called_in_the_loop(registered_lookup: str) -> None:
    """An app-registered tool, resolved by name, runs inside a turn."""
    frames = await _turn(registered_lookup, ChatScope(user_id="u1", surface="test"))

    done = frames[-1]
    assert isinstance(done, DoneFrame)
    assert done.tool_calls == 1


async def test_a_tool_runs_as_the_scopes_owner_and_conversation() -> None:
    """The kit binds the scope's owner and conversation for the tools it
    runs (``memory_user``), and restores them after the turn."""
    from app.services.ai.domains.chat.user_memory import (
        current_conversation_id,
        current_owner_user_id,
    )

    seen: list[tuple[int | None, str | None]] = []

    async def whose_turn() -> str:
        """Report whose turn this is."""
        seen.append((current_owner_user_id.get(), current_conversation_id.get()))
        return "ok"

    register_tool("whose_turn", whose_turn)
    try:
        scope = ChatScope(
            user_id="u7", surface="test", owner_user_id=7, conversation_id="c7"
        )
        await _turn("whose_turn", scope)
    finally:
        unregister_tool("whose_turn")

    assert seen == [(7, "c7")]
    assert current_owner_user_id.get() is None
