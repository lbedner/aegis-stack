"""Who runs on each local inference engine (``chat/engine_users``): an agent
on the engine that serves its model, the voice on the server or the
in-app model it speaks and listens through."""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.services.ai.domains.chat import engine_users as users
from app.services.ai.models.agents import Agent

SERVED = {"ollama": {"qwen2.5:7b", "llama3.1:8b"}}


async def _agent(session: AsyncSession, slug: str, **extra: object) -> None:
    session.add(Agent(slug=slug, name=slug.title(), system_prompt="Hi.", **extra))  # type: ignore[arg-type]
    await session.commit()


@pytest.fixture(autouse=True)
def _no_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    """The agents alone; the voice's own tests cover it."""
    monkeypatch.setattr(users, "VOICE", "app.services.ai.domains.no_such_voice")


async def test_an_agent_runs_on_the_engine_that_serves_its_model(
    async_db_session: AsyncSession,
) -> None:
    await _agent(async_db_session, "coder", model_id="llama3.1:8b")
    await _agent(async_db_session, "writer", model_id="gpt-4o")

    found = await users.engine_users(async_db_session, SERVED)

    assert [u.by for u in found.uses if u.engine == "ollama"] == ["Coder"]


async def test_an_unpinned_agent_runs_on_the_active_provider(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _agent(async_db_session, "helper")
    await _agent(async_db_session, "resting", is_active=False)
    monkeypatch.setattr(settings, "AI_PROVIDER", "ollama")

    found = await users.engine_users(async_db_session, SERVED)

    assert {(u.engine, u.by) for u in found.uses} >= {("ollama", "Helper")}
    assert "Resting" not in {u.by for u in found.uses}


async def test_an_unpinned_agent_on_a_cloud_provider_runs_on_none(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _agent(async_db_session, "helper")
    monkeypatch.setattr(settings, "AI_PROVIDER", "openai")

    found = await users.engine_users(async_db_session, SERVED)

    assert "Helper" not in {u.by for u in found.uses}
