"""The built-in save_memory tool works end-to-end in the tool loop: it
files an approval card for the turn's user, and remembers nothing yet."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from pydantic_ai.models.test import TestModel
import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.ai.domains.chat.chat_kit import ChatScope, DoneFrame, ToolChatAgent
from app.services.ai.domains.chat.tools import resolve_tools
import app.services.ai.domains.chat.user_memory as user_memory_module
from app.services.ai.domains.chat.user_memory import current_user_id
from app.services.ai.models.agents import AgentUserMemory
from app.services.change_queue import PendingChange
from tests._change_queue import queue_tools_on


@dataclass
class _Deps:
    subject_id: int


async def test_model_driven_save_memory_persists_a_fact(
    async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    acting_owner_user_id: int | None,
) -> None:
    # The root conftest's session: a bare local engine cannot create the
    # project's schema-qualified tables (finance, scheduler, ...).
    @asynccontextmanager
    async def fake_session() -> AsyncGenerator[AsyncSession]:
        yield async_db_session

    monkeypatch.setattr(user_memory_module, "get_async_session", fake_session)
    queue_tools_on(async_db_session, monkeypatch)

    agent: ToolChatAgent[_Deps] = ToolChatAgent(
        model=TestModel(call_tools=["save_memory"]),
        model_name="test-model",
        instructions="You are a test persona.",
        deps_type=_Deps,
        tools=resolve_tools(["save_memory"]),
        recorder=lambda **kwargs: 0.0,
    )

    # The scope's user is the ONLY identity the turn is given: the runtime
    # binds it for the tool. A test that set the ContextVar itself would
    # pass against a runtime that never binds it - which is what shipped.
    frames = [
        f
        async for f in agent.stream_turn(
            scope=ChatScope(
                user_id="u7", surface="test", owner_user_id=acting_owner_user_id
            ),
            deps=_Deps(1),
            message="remember this",
        )
    ]

    assert current_user_id.get() is None  # restored after the turn

    done = frames[-1]
    assert isinstance(done, DoneFrame)
    assert done.tool_calls == 1

    (card,) = (await async_db_session.exec(select(PendingChange))).all()
    assert card.change_type == "memory.save"
    assert card.payload["user_id"] == "u7"
    remembered = await async_db_session.exec(select(AgentUserMemory))
    assert remembered.first() is None
