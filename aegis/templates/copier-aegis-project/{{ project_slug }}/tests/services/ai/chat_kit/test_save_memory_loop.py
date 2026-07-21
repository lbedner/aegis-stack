"""The built-in save_memory tool works end-to-end in the tool loop."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
from pydantic_ai.models.test import TestModel
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select

import app.services.ai.user_memory as user_memory_module
from app.services.ai.chat_kit import ChatScope, DoneFrame, ToolChatAgent
from app.services.ai.models.agents import AgentUserMemory
from app.services.ai.tools import resolve_tools
from app.services.ai.user_memory import current_user_id
from sqlmodel.ext.asyncio.session import AsyncSession


@dataclass
class _Deps:
    subject_id: int


async def test_model_driven_save_memory_persists_a_fact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    @asynccontextmanager
    async def fake_session() -> AsyncGenerator[AsyncSession]:
        async with AsyncSession(engine) as session:
            yield session

    monkeypatch.setattr(user_memory_module, "get_async_session", fake_session)

    agent: ToolChatAgent[_Deps] = ToolChatAgent(
        model=TestModel(call_tools=["save_memory"]),
        model_name="test-model",
        instructions="You are a test persona.",
        deps_type=_Deps,
        tools=resolve_tools(["save_memory"]),
        recorder=lambda **kwargs: 0.0,
    )

    token = current_user_id.set("u7")
    try:
        frames = [
            f
            async for f in agent.stream_turn(
                scope=ChatScope(user_id="u7", surface="test"),
                deps=_Deps(1),
                message="remember this",
            )
        ]
    finally:
        current_user_id.reset(token)

    done = frames[-1]
    assert isinstance(done, DoneFrame)
    assert done.tool_calls == 1

    async with AsyncSession(engine) as session:
        result = await session.exec(
            select(AgentUserMemory).where(AgentUserMemory.user_id == "u7")
        )
        row = result.first()
    await engine.dispose()

    assert row is not None
    assert len(row.memory["structured_facts"]) == 1
