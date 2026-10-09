"""The Overseer AI page's Agents and Memory sections.

Agents: the agent registry, each agent's definition edited in the drawer
(persona, sampling, model pin, active). Grants (tools, memory modules) are
shown, not edited: the registry keeps them out of its editable fields.

Memory: the memory modules an agent opts into, edited in the drawer beside
a preview of what the module renders right now (the only way to tell a
working fetcher from a silently empty one), and the facts saved about the
user, corrected and forgotten.

Split from ``overseer_ai`` (imported when a section is asked for); both
registries exist only with a persistence backend.
"""

from typing import Any

from app.core.db import release_lock
from app.core.model_picker import display_title, group_models

from . import chat_models
from .overseer_ai_common import PARTIALS, section_url
from .rendering import drawer_state, form_number, status_cell

AGENT_PARAM = "agent"
MODULE_PARAM = "module"


def agents_url(**query: str | None) -> str:
    return section_url("agents", **query)


def agent_drawer_url(slug: str) -> str:
    return f"{PARTIALS}/agents/{slug}/drawer"


async def agent_rows(db: Any) -> list[dict[str, Any]]:
    """Every agent in the registry, as the admin surfaces serialize it."""
    from app.services.ai.domains.chat.agent_registry import list_agents, serialize_agent

    return [serialize_agent(a) for a in await list_agents(session=db)]


async def agent_row(db: Any, slug: str) -> dict[str, Any] | None:
    return next((a for a in await agent_rows(db) if a["slug"] == slug), None)


def _active(row: dict[str, Any]) -> dict[str, str]:
    """An agent's or a module's on/off badge."""
    return (
        status_cell("Active", "ok")
        if row.get("is_active")
        else status_cell("Off", "muted")
    )


def _row(agent: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": {"label": agent["name"], "url": agents_url(agent=agent["slug"])},
        "slug": agent["slug"],
        "category": agent.get("category"),
        "model": agent.get("model_id") or "Default",
        "state": _active(agent),
        "tools": len(agent.get("tools") or []),
        "modules": len(agent.get("memory_modules") or []),
    }


async def agents_context(db: Any, query: Any) -> dict[str, Any]:
    wanted = query.get(AGENT_PARAM) or ""
    return drawer_state(AGENT_PARAM, agent_drawer_url(wanted) if wanted else None) | {
        "rows": [_row(a) for a in await agent_rows(db)]
    }


async def agent_context(db: Any, slug: str) -> dict[str, Any] | None:
    """One agent for the drawer's editor, or None when there is no such agent."""
    agent = await agent_row(db, slug)
    if agent is None:
        return None
    # The catalog reads on its own connection: never behind this request's.
    await release_lock(db)
    return {
        "agent": agent,
        "save_url": f"{PARTIALS}/agents/{slug}",
        "model_choices": await model_choices(agent.get("model_id")),
        "grants": [
            ("Tools", ", ".join(agent.get("tools") or []) or None),
            ("Memory modules", ", ".join(agent.get("memory_modules") or []) or None),
            (
                "Knowledge bases",
                ", ".join(map(str, agent.get("knowledge_base_ids") or [])) or None,
            ),
            ("Code mode", "On" if agent.get("code_mode") else None),
        ],
    }


async def model_choices(current: str | None) -> list[dict[str, Any]]:
    """The models an agent can run on, grouped by vendor as the chat's
    picker groups them (``chat_models.catalog``); its own model kept, first,
    when the catalog no longer lists it, so saving does not drop it."""
    models = await chat_models.catalog("chat")
    groups = [
        {
            "label": vendor,
            "options": [
                {"id": m["model_id"], "name": display_title(m, under_vendor=vendor)}
                for m in rows
            ],
        }
        for vendor, rows in group_models(models)
    ]
    if current and all(m["model_id"] != current for m in models):
        unlisted = {"id": current, "name": f"{current} (not in the catalog)"}
        groups.insert(0, {"label": "Chosen", "options": [unlisted]})
    return groups


def parse_agent_form(form: dict[str, str]) -> dict[str, Any]:
    """The editor's fields as registry changes: blanks are "unset" (None),
    numbers are numbers, and an unticked box is off. Raises ``ValueError``
    on a number that is not one."""

    return {
        "name": (form.get("name") or "").strip(),
        "description": (form.get("description") or "").strip() or None,
        "category": (form.get("category") or "").strip() or None,
        "model_id": (form.get("model_id") or "").strip() or None,
        "temperature": form_number(form.get("temperature"), "Temperature", float),
        "max_tokens": form_number(form.get("max_tokens"), "Max tokens"),
        "system_prompt": form.get("system_prompt") or None,
        "is_active": form.get("is_active") == "on",
    }


def memory_url(**query: str | None) -> str:
    return section_url("memory", **query)


async def module_rows(db: Any) -> list[dict[str, Any]]:
    """Every memory module, active or not, in render order."""
    from app.services.ai.domains.chat.memory_modules import (
        list_memory_modules,
        serialize_memory_module,
    )

    modules = await list_memory_modules(db, active_only=False)
    return [serialize_memory_module(m) for m in modules]


async def module_row(db: Any, slug: str) -> dict[str, Any] | None:
    return next((m for m in await module_rows(db) if m["slug"] == slug), None)


async def render_preview(db: Any, slug: str) -> str | None:
    """What the module hands an agent now, rendered by the real renderer."""
    from app.services.ai.domains.chat.module_context import render_memory_modules
    from app.services.ai.domains.chat.user_memory import DEFAULT_MEMORY_USER_ID

    return await render_memory_modules(
        [slug], user_id=DEFAULT_MEMORY_USER_ID, session=db
    )


async def fact_rows(db: Any) -> list[dict[str, Any]]:
    """The facts saved about the user, each with the index that addresses it."""
    from app.services.ai.domains.chat.user_memory import (
        DEFAULT_MEMORY_USER_ID,
        list_user_facts,
    )

    return await list_user_facts(DEFAULT_MEMORY_USER_ID, session=db)


async def memory_context(db: Any, query: Any) -> dict[str, Any]:
    from app.core.formatting import format_relative_time

    from .rendering import hx_dialog

    wanted = query.get(MODULE_PARAM) or ""
    modules = await module_rows(db)
    return drawer_state(
        MODULE_PARAM, f"{PARTIALS}/modules/{wanted}/drawer" if wanted else None
    ) | {
        "modules": [
            {
                "name": {"label": m["name"], "url": memory_url(module=m["slug"])},
                "category": m.get("category"),
                "source": f"Fetcher: {m['fetch_function']}"
                if m.get("fetch_function")
                else "Static text",
                "priority": m.get("priority"),
                "tokens": m.get("token_estimate"),
                "state": _active(m),
            }
            for m in modules
        ],
        "facts": [
            {
                "fact": f["fact"],
                "category": f.get("category"),
                "saved": format_relative_time(f.get("saved_at")),
                "edit": hx_dialog(f"{PARTIALS}/facts/{f['index']}/edit"),
                "forget": hx_dialog(f"{PARTIALS}/facts/{f['index']}/confirm-forget"),
            }
            for f in await fact_rows(db)
        ],
    }


async def module_context(db: Any, slug: str) -> dict[str, Any] | None:
    """One module for the drawer: its editor and its live preview."""
    module = await module_row(db, slug)
    if module is None:
        return None
    return {
        "module": module,
        "save_url": f"{PARTIALS}/modules/{slug}",
        "preview": await render_preview(db, slug),
    }


def parse_module_form(form: dict[str, str], static: bool) -> dict[str, Any]:
    """The module editor as registry changes. Only a static module's text is
    editable here; a fetcher's output is code. Raises ``ValueError`` on a
    number that is not one."""

    changes: dict[str, Any] = {
        "name": (form.get("name") or "").strip(),
        "description": (form.get("description") or "").strip() or None,
        "category": (form.get("category") or "").strip() or None,
        "priority": form_number(form.get("priority"), "Priority"),
        "token_estimate": form_number(form.get("token_estimate"), "Token estimate"),
        "is_active": form.get("is_active") == "on",
    }
    if static:
        changes["prompt_content"] = form.get("prompt_content") or None
    return changes
