"""Who runs on each local inference engine: the agents whose model one
serves, and the voice that speaks or listens through one (with the voice
domain, ``voice/engine_use``). Agents own their model, so the AI service
answers, and the inference component's overview (Overseer > Inference, the
``inference status`` command and its API) reads it through the facade."""

from collections.abc import Collection, Mapping

from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.discovery import optional
from app.core.figures import FIGURES
from app.services.ai.domains.chat.agent_loader import provider_of
from app.services.ai.models.agents import Agent

from . import queries

VOICE = "app.services.ai.domains.voice.engine_use"


class EngineUse(BaseModel):
    """One thing that runs on an engine: ``engine`` is the engine's id (its
    ``inference[...]`` name, the speech server's slug, or
    ``speech_server.IN_APP``)."""

    model_config = FIGURES

    engine: str
    by: str


class InAppEngine(BaseModel):
    """A model the app's own process runs, and whether it is in memory."""

    model_config = FIGURES

    name: str
    loaded: bool


class EngineUsers(BaseModel):
    """Everything that runs on an engine, and the in-app engines in use."""

    model_config = FIGURES

    uses: list[EngineUse] = Field(default_factory=list)
    in_app: list[InAppEngine] = Field(default_factory=list)


def engine_of(agent: Agent, served: Mapping[str, Collection[str]]) -> str | None:
    """The engine an agent runs on: the provider serving its pinned model
    (``provider_of``), or, unpinned, the active one, where that is an
    engine here."""
    if agent.llm is None:
        provider = settings.AI_PROVIDER
    else:
        pinned = provider_of(agent)
        provider = pinned.value if pinned else None
    return provider if provider in served else None


async def engine_users(
    session: AsyncSession, served: Mapping[str, Collection[str]]
) -> EngineUsers:
    """Each active agent on the engine that runs its model (``served``: each
    text engine's id, and the models it has), then the voice."""
    uses = [
        EngineUse(engine=engine, by=agent.name)
        for agent in await queries.active_agents(session)
        if (engine := engine_of(agent, served))
    ]
    voice = optional(VOICE)
    if voice is None:
        return EngineUsers(uses=uses)
    spoken, in_app = await voice.voice_uses(session)
    return EngineUsers(uses=uses + spoken, in_app=in_app)
