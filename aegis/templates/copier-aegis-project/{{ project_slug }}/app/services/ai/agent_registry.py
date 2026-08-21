"""Agent registry admin operations (list, activate/deactivate).

The read/write surface behind the dashboard agents tab and the API.
Writes invalidate the agent loader's warm cache so the next chat request
sees the change.
"""

from typing import Any

from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_async_session
from app.core.log import logger
from app.services.ai.agent_loader import invalidate_agent_cache
from app.services.ai.models.agents import Agent


class AgentNotFoundError(ValueError):
    """Raised when an operation targets a slug with no agent row."""


class InvalidAgentUpdateError(ValueError):
    """Raised when an agent update violates the field invariants."""


# Fields the admin surfaces may edit. Slug is identity; grants (tools,
# modules, KBs) have their own management paths.
EDITABLE_FIELDS = frozenset(
    {
        "name",
        "description",
        "category",
        "model_id",
        "temperature",
        "max_tokens",
        "system_prompt",
        "is_active",
    }
)


# Editable fields whose columns reject NULL; description/category/model_id
# stay nullable (model_id None = follow the active default).
_NON_NULLABLE_FIELDS = frozenset(
    {"name", "temperature", "max_tokens", "system_prompt", "is_active"}
)


def _validate_changes(changes: dict[str, Any]) -> None:
    unknown = set(changes) - EDITABLE_FIELDS
    if unknown:
        raise InvalidAgentUpdateError(f"Unknown agent fields: {sorted(unknown)}")
    null_fields = sorted(
        field
        for field in _NON_NULLABLE_FIELDS
        if field in changes and changes[field] is None
    )
    if null_fields:
        raise InvalidAgentUpdateError(
            f"Fields cannot be null: {', '.join(null_fields)}"
        )
    if "name" in changes and not str(changes["name"]).strip():
        raise InvalidAgentUpdateError("Agent name cannot be empty")
    if "system_prompt" in changes and not str(changes["system_prompt"]).strip():
        raise InvalidAgentUpdateError("System prompt cannot be empty")
    if "temperature" in changes:
        temperature = float(changes["temperature"])
        if not 0.0 <= temperature <= 2.0:
            raise InvalidAgentUpdateError("temperature must be between 0.0 and 2.0")
    if "max_tokens" in changes and int(changes["max_tokens"]) <= 0:
        raise InvalidAgentUpdateError("max_tokens must be positive")


async def list_agents(*, session: AsyncSession | None = None) -> list[Agent]:
    """All agents, tools eager-loaded, ordered by slug."""
    if session is None:
        async with get_async_session() as owned_session:
            return await list_agents(session=owned_session)
    result = await session.exec(
        select(Agent)
        .options(selectinload(Agent.tools))  # type: ignore[arg-type]
        .order_by(Agent.slug)  # type: ignore[arg-type]
    )
    return list(result.all())


async def update_agent(
    slug: str,
    changes: dict[str, Any],
    *,
    session: AsyncSession | None = None,
) -> Agent:
    """Apply editable-field changes and invalidate the cached config."""
    if session is None:
        async with get_async_session() as owned_session:
            return await update_agent(slug, changes, session=owned_session)

    _validate_changes(changes)
    result = await session.exec(select(Agent).where(Agent.slug == slug))
    agent = result.first()
    if agent is None:
        raise AgentNotFoundError(f"Agent '{slug}' not found")
    for field, value in changes.items():
        setattr(agent, field, value)
    session.add(agent)
    await session.commit()
    invalidate_agent_cache(slug)
    logger.info("Agent updated", agent_slug=slug, fields=sorted(changes))
    # Commit expires the instance; re-select (tools eager) so callers can
    # serialize without triggering sync lazy-loads in async land.
    refreshed = await session.exec(
        select(Agent)
        .options(selectinload(Agent.tools))  # type: ignore[arg-type]
        .where(Agent.slug == slug)
    )
    return refreshed.one()


async def set_agent_active(
    slug: str,
    active: bool,
    *,
    session: AsyncSession | None = None,
) -> Agent:
    """Flip an agent's active flag (thin wrapper over update_agent)."""
    return await update_agent(slug, {"is_active": active}, session=session)


def serialize_agent(agent: Agent) -> dict[str, Any]:
    """API/UI shape for one agent row."""
    return {
        "slug": agent.slug,
        "name": agent.name,
        "description": agent.description,
        "category": agent.category,
        "model_id": agent.model_id,
        "temperature": agent.temperature,
        "max_tokens": agent.max_tokens,
        "system_prompt": agent.system_prompt,
        "is_active": agent.is_active,
        "tools": [tool.name for tool in agent.tools],
        "memory_modules": list(agent.memory_modules),
        "knowledge_base_ids": list(agent.knowledge_base_ids),
    }
