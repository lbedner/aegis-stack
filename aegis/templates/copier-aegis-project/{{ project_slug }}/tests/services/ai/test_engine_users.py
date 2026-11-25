"""Who runs on each local inference engine (``chat/engine_users``): an agent
on the engine that serves its model, the voice on the server or the
in-app model it speaks and listens through."""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.services.ai.domains.chat import engine_users as users
from app.services.ai.models.agents import Agent
from tests.services.ai._catalog import listed

SERVED = {"ollama": {"qwen2.5:7b", "llama3.1:8b"}}


async def _agent(session: AsyncSession, slug: str, **extra: object) -> None:
    session.add(Agent(slug=slug, name=slug.title(), system_prompt="Hi.", **extra))  # type: ignore[arg-type]
    await session.commit()


@pytest.fixture(autouse=True)
def _no_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    """The agents alone; the voice's own tests cover it."""
    monkeypatch.setattr(users, "VOICE", "app.services.ai.domains.no_such_voice")


@pytest.mark.queryspy(allow_n_plus_one=True)  # two models, two agents
async def test_an_agent_runs_on_the_engine_that_serves_its_model(
    async_db_session: AsyncSession,
) -> None:
    llama = await listed(async_db_session, "llama3.1:8b", served_by="ollama")
    gpt = await listed(async_db_session, "gpt-4o")
    await _agent(async_db_session, "coder", llm_id=llama.id)
    await _agent(async_db_session, "writer", llm_id=gpt.id)

    found = await users.engine_users(async_db_session, SERVED)

    assert [u.by for u in found.uses if u.engine == "ollama"] == ["Coder"]


async def test_the_engine_is_the_one_its_catalog_row_names(
    async_db_session: AsyncSession,
) -> None:
    """Where its calls go (the row's serving org), not whichever engine
    happens to list a model of that name."""
    hosted = await listed(async_db_session, "qwen2.5:7b", served_by="openai")
    await _agent(async_db_session, "hosted", llm_id=hosted.id)

    found = await users.engine_users(async_db_session, SERVED)

    assert [u.by for u in found.uses if u.engine == "ollama"] == []


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
