"""Agent registry seed data.

Seeds the default ``assistant`` agent so a fresh project behaves exactly
like pre-registry chat: same system prompt, same sampling defaults. The
agent loader resolves this row on DB backends and falls back to the same
in-code definition on the memory backend, so this seed is the single DB
source of the default agent.
"""

from typing import Any

from sqlmodel import Session, select

from app.core.log import logger
from app.services.ai.agent_loader import DEFAULT_AGENT_SLUG, default_agent_config
from app.services.ai.models.agents import Agent

__all__ = ["DEFAULT_AGENT_SLUG", "default_agent_definition", "load_agent_fixtures"]


def default_agent_definition() -> dict[str, Any]:
    """The seed row for the default agent.

    Built from the loader's in-code config so the DB source and the
    memory-mode fallback can never drift: same prompt, same sampling
    values (captured from settings at seed time).
    """
    config = default_agent_config()
    return {
        "slug": config.slug,
        "name": config.name,
        "description": "Default conversational agent",
        "category": "general",
        "model_id": config.model_id,
        "system_prompt": config.system_prompt,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "memory_modules": list(config.memory_modules),
        "knowledge_base_ids": list(config.knowledge_base_ids),
        "is_active": True,
    }


def load_agent_fixtures(session: Session) -> dict[str, int]:
    """Seed the default agent, skipping rows that already exist.

    Idempotent: re-running against a seeded database adds nothing and
    never mutates an existing (possibly user-edited) agent row.

    Args:
        session: Database session

    Returns:
        dict with counts: {"agents": N added}
    """
    added = 0
    definition = default_agent_definition()
    existing = session.exec(
        select(Agent).where(Agent.slug == definition["slug"])
    ).first()
    if existing is None:
        session.add(Agent(**definition))
        session.commit()
        added = 1
        logger.info(f"Seeded default agent '{definition['slug']}'")
    else:
        logger.debug(f"Default agent '{definition['slug']}' already present")

    return {"agents": added}
