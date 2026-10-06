"""Overseer > MCP for both UIs (htmx ``overseer_mcp``, Flet ``mcp_modal``):
what an outside assistant is served, how to connect one, and what each
client did (``app.components.mcp.activity``, where there is a database)."""

from typing import Any

from app.core.config import settings
from app.core.formatting import format_bytes, format_duration_ms, format_relative_time
from app.core.tools import RegisteredTool, get_tool, load_tools, mcp_servable

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
NOT_KEPT = (
    "Without a database, calls are logged (mcp.call on stderr), not kept. "
    "Add the database component to keep them."
)


def _about(tool: RegisteredTool) -> str:
    """The registry's one-liner, else the docstring's first line."""
    doc = (tool.func.__doc__ or "").strip().splitlines()
    return tool.description or (doc[0] if doc else "")


def grant() -> dict[str, list[dict[str, str]]]:
    """``MCP_TOOLS`` split into what a client is served and what it never
    sees, with why: the same rule the server applies (``mcp_servable``)."""
    load_tools()
    served: list[dict[str, str]] = []
    dropped: list[dict[str, str]] = []
    for name in settings.MCP_TOOLS:
        tool = get_tool(name)
        if tool is None:
            dropped.append({"name": name, "reason": "No tool by that name"})
        elif not mcp_servable([name]):
            dropped.append({"name": name, "reason": "Writes are never served"})
        else:
            served.append({"name": name, "effect": tool.effect, "about": _about(tool)})
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
        commands.append(
            {
                "label": "Over HTTP",
                "command": f"claude mcp add --transport http {app} "
                f"{settings.API_BASE_URL}/mcp/ "
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
        {
            "when": format_relative_time(call.called_at),
            "client": call.client,
            "tool": call.tool,
            "effect": call.effect,
            "result": OK if call.ok else FAILED,
            "time": format_duration_ms(call.duration_ms),
            "size": format_bytes(call.result_bytes),
        }
        for call in await activity.recent(limit=limit)
    ]
    note = "" if clients else "No MCP client has called a tool yet."
    return {"note": note, "clients": clients, "calls": calls}


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
