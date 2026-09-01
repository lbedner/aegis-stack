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
from app.services.ai.domains.chat.agent_loader import (
    DEFAULT_AGENT_SLUG,
    default_agent_config,
)

# Importing the module registers the built-in memory tools. The registry
# only holds tools whose module was imported, and seeding runs in
# processes that never build a chat agent (a CLI, a startup hook): without
# this the sync writes no rows and every later grant silently no-ops.
import app.services.ai.domains.chat.readings  # noqa: F401
from app.services.ai.domains.chat.tools import get_tool, registered_tool_names
import app.services.ai.domains.chat.user_memory  # noqa: F401
from app.services.ai.models.agents import Agent, Tool

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
        "code_mode": config.code_mode,
    }


def load_agent_fixtures(session: Session) -> dict[str, int]:
    """Seed the default agent, skipping rows that already exist.

    Idempotent: re-running against a seeded database adds nothing and
    never mutates an existing (possibly user-edited) agent row.

    Args:
        session: Database session

    Returns:
        dict with counts: {"agents": N added, "tools": N added}
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

    # Sync registered tools into grantable rows: every callable in the
    # Python registry gets a matching ``tool`` row (by name) so the agent
    # CRUD can attach it. Rows are never mutated or deleted here - a
    # stale row degrades to a skipped-name warning at resolve time.
    tools_added = 0
    present = set(session.exec(select(Tool.name)).all())
    for name in registered_tool_names():
        if name in present:
            continue
        entry = get_tool(name)
        session.add(Tool(name=name, description=entry.description if entry else None))
        tools_added += 1
    if tools_added:
        session.commit()
        logger.info(f"Seeded {tools_added} tool row(s) from the registry")

    return {"agents": added, "tools": tools_added}
