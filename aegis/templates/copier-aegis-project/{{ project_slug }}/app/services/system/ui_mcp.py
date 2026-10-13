"""Overseer > MCP for both UIs (htmx ``overseer_mcp``, Flet ``mcp_modal``):
what an outside assistant is served, how to connect one, and what each
client did (``app.components.mcp.activity``, where there is a database)."""

import json
from typing import Any

from app.components.mcp.server import RUN_CODE, served_effects
from app.core.config import settings
from app.core.formatting import (
    first_sentence,
    format_bytes,
    format_duration_ms,
    format_relative_time,
)
from app.core.tools import RegisteredTool, get_tool, load_tools

NAME = "mcp"
NONE_SERVED = "No tools served: grant some in MCP_TOOLS"
# A call's result as both UIs label it.
OK, FAILED = "OK", "Failed"

SERVED_COLUMNS = (("name", "Tool"), ("effect", "Effect"), ("about", "What it does"))
DROPPED_COLUMNS = (("name", "Tool"), ("reason", "Why not"))
CLIENT_COLUMNS = (
    ("client", "Client"),
    ("calls", "Calls"),
    ("reads", "Reads"),
    ("proposals", "Proposals"),
    ("failed", "Failed"),
    ("last", "Last call"),
)
CALL_COLUMNS = (
    ("when", "When"),
    ("client", "Client"),
    ("via", "Via"),
    ("tool", "Tool"),
    ("effect", "Effect"),
    ("result", "Result"),
    ("time", "Time"),
    ("size", "Size"),
)
TOKEN_COLUMNS = (
    ("name", "Name"),
    ("scope", "Reaches"),
    ("hint", "Token"),
    ("created", "Made"),
    ("last_used", "Last used"),
)
SCOPE_LABELS = {"read": "Read", "propose": "Read and propose"}
NO_TOKENS = "No tokens yet. A client beyond stdio needs one."
SHOWN_ONCE = "Copy it now: it is not shown again."
RUN_CODE_ABOUT = "Runs a script against the read tools, in the sandbox"
NOT_KEPT = (
    "Without a database, calls are logged (mcp.call on stderr), not kept. "
    "Add the database component to keep them."
)


def _about(tool: RegisteredTool) -> str:
    """The registry's one-liner, else the docstring's first sentence, however
    its lines wrap."""
    if tool.description:
        return tool.description
    return first_sentence(tool.func.__doc__).rstrip(".")


def _why_not(name: str) -> str:
    if name == RUN_CODE:
        return "Needs the AI service's code mode"
    return (
        "No tool by that name" if get_tool(name) is None else "Writes are never served"
    )


def grant() -> dict[str, list[dict[str, str]]]:
    """``MCP_TOOLS`` split into what a client is served and what it never
    sees, with why: the same rule the server applies (``served_effects``)."""
    load_tools()
    effects = served_effects(settings.MCP_TOOLS)
    served: list[dict[str, str]] = []
    dropped: list[dict[str, str]] = []
    for name in settings.MCP_TOOLS:
        if name not in effects:
            dropped.append({"name": name, "reason": _why_not(name)})
            continue
        tool = get_tool(name)
        about = _about(tool) if tool is not None else RUN_CODE_ABOUT
        served.append({"name": name, "effect": effects[name], "about": about})
    return {"served": served, "dropped": dropped}


def connect() -> list[dict[str, str]]:
    """How a client starts the server over stdio (it runs the command), and,
    with tokens, how one elsewhere reaches it over HTTP."""
    app = settings.PROJECT_NAME
    commands = [
        {"label": "From the project", "command": f"uv run {app} mcp"},
        {
            "label": "In Docker",
            "command": f"docker compose exec -T webserver {app} mcp",
        },
        {
            "label": "Claude Code",
            "command": f"claude mcp add {app} -- uv run --directory <project> {app} mcp",
        },
    ]
    if has_tokens():
        from app.components.mcp.http import PATH

        commands.append(
            {
                "label": "Over HTTP",
                "command": f"claude mcp add --transport http {app} "
                f"{settings.API_BASE_URL}{PATH}/ "
                '--header "Authorization: Bearer <token>"',
            }
        )
    return commands


async def recorded(limit: int = 50) -> dict[str, Any]:
    """Each client's totals and the newest calls, or why there are none."""
    try:
        from app.components.mcp import activity
    except ImportError:  # no database: the record is the log
        return {"note": NOT_KEPT, "clients": [], "calls": []}
    clients = [
        {
            "client": c.client,
            "calls": str(c.calls),
            "reads": str(c.reads),
            "proposals": str(c.proposals),
            "failed": str(c.failed),
            "last": format_relative_time(c.last_at),
        }
        for c in await activity.by_client()
    ]
    calls = [
        row
        for call in await activity.recent(limit=limit)
        for row in [_call_row(call), *(_call_row(step) for step in call.steps)]
    ]
    note = "" if clients else "No MCP client has called a tool yet."
    return {"note": note, "clients": clients, "calls": calls}


def _call_row(call: Any) -> dict[str, Any]:
    """One call as the Recent calls table shows it (its detail is read when
    the row is opened, ``call_detail``); a read a script made sits under its
    run_code call (``child``), named with its arguments."""
    row: dict[str, Any] = {
        "id": call.id,
        "when": format_relative_time(call.called_at),
        "client": call.client,
        "via": call.transport or "",
        "tool": call.tool,
        "effect": call.effect,
        "result": OK if call.ok else FAILED,
        "time": format_duration_ms(call.duration_ms),
        "size": format_bytes(call.result_bytes),
    }
    if call.parent_id is None:
        return row
    shown = call.args if call.args and call.args != "{}" else ""
    return row | {
        "when": "",
        "client": "",
        "tool": f"{call.tool} {shown}".strip(),
        "child": True,
    }


async def call_detail(call_id: int) -> dict[str, Any] | None:
    """What a call sent and got back (or its error), and who made it how:
    its row's detail, read when opened. None for no such call, or where
    nothing is kept."""
    try:
        from app.components.mcp import activity
    except ImportError:
        return None
    call = await activity.one(call_id)
    if call is None:
        return None
    return {
        **_shown("args", call.args),
        **_shown("response", call.response),
        "error": call.error,
        "facts": [
            ("Client version", call.client_version),
            ("Session", call.session),
            ("Acting for", f"user {call.user_id}" if call.user_id else None),
            ("Token", call.token),
        ],
    }


def _shown(key: str, text: str | None) -> dict[str, str | None]:
    """A call's arguments or response to read, and the language to
    highlight it in (``<key>_lang``): a script as its Python, JSON
    indented, anything else (or JSON clipped past parsing) as sent."""
    try:
        parsed = json.loads(text) if text else None
    except ValueError:
        return {key: text, f"{key}_lang": None}
    if isinstance(parsed, dict) and isinstance(parsed.get("code"), str):
        return {key: parsed["code"], f"{key}_lang": "python"}
    if parsed is None:
        return {key: None, f"{key}_lang": None}
    return {key: json.dumps(parsed, indent=2), f"{key}_lang": "json"}


def has_tokens() -> bool:
    """Whether people can make tokens here: only with auth, since each
    belongs to someone."""
    try:
        from app.components.mcp import tokens  # noqa: F401
    except ImportError:
        return False
    return True


def token_row(token: dict[str, Any]) -> dict[str, Any]:
    """A token (``McpTokenResponse``'s fields, from a row or the API) as
    both UIs show it."""
    return {
        "id": token["id"],
        "name": token["name"],
        "scope": SCOPE_LABELS[token["scope"]],
        "hint": f"{token['hint']}...",
        "created": format_relative_time(token["created_at"]),
        "last_used": format_relative_time(token["last_used_at"])
        if token.get("last_used_at")
        else "Never",
    }
