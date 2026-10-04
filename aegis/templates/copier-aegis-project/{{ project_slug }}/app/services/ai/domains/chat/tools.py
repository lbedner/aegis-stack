"""Agent tool registry.

Maps tool names to Python callables. The ``tool`` table's rows key into
this registry by ``name``: the database decides WHICH tools an agent may
call (via ``agent_tool`` attachments); this module decides WHAT each name
executes. Framework-agnostic on purpose - entries are plain callables in
whatever shape the chat engine accepts (pydantic-ai takes functions or
``Tool`` instances), and nothing here imports an AI framework.

Applications register their own domain tools at import time:

    from app.services.ai.domains.chat.tools import register_tool

    async def lookup_order(order_id: str) -> str:
        \"\"\"Fetch an order summary.\"\"\"
        ...

    register_tool("lookup_order", lookup_order, effect="read")

A database row naming a tool with no registered callable is skipped with
a warning, never an error: a stale row must not brick chat.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal

from app.core.log import logger
from app.services.ai.domains.chat.tool_telemetry import instrument

ToolFunc = Callable[..., Any]

# What a call does to the app's state, declared by the tool itself:
# ``read`` changes nothing, ``proposes`` files work for the user's
# approval (nothing lands until they act), ``writes`` changes state at once.
ToolEffect = Literal["read", "proposes", "writes"]

# Effects an outside assistant may reach over MCP. An allowlist, so an
# effect added later is unservable until someone decides otherwise.
_MCP_SERVABLE_EFFECTS: frozenset[str] = frozenset({"read", "proposes"})


@dataclass(frozen=True)
class RegisteredTool:
    """A named tool entry: the callable plus registry metadata.

    Every non-read tool stays a visible native call even in code mode - a
    write or proposal the user has to see in the tool trail is never
    dispatched from inside the sandbox. The tool declares its ``effect`` at
    registration; the agent loader and the MCP server ask the registry
    rather than keeping their own lists.
    """

    name: str
    func: ToolFunc
    description: str | None = None
    effect: ToolEffect = "writes"


_registry: dict[str, RegisteredTool] = {}


def register_tool(
    name: str,
    func: ToolFunc,
    *,
    description: str | None = None,
    effect: ToolEffect | None = None,
    replace: bool = False,
) -> None:
    """Register a callable under a tool name.

    A tool that declares no ``effect`` is treated as ``writes``: default-deny,
    so a write that forgets to say so stays a visible native call and never
    reaches an outside assistant. Raises ValueError on a duplicate name
    unless ``replace=True``, and a rebind may not change the effect, so a
    later import can't quietly turn a proposal into a read.
    """
    if effect is None:
        logger.warning(f"Tool {name!r} declares no effect; treated as 'writes'")
        effect = "writes"
    existing = _registry.get(name)
    if existing is not None and not replace:
        raise ValueError(
            f"Tool '{name}' is already registered; pass replace=True to rebind it"
        )
    if existing is not None and existing.effect != effect:
        raise ValueError(
            f"Tool '{name}' is registered as {existing.effect!r}; a rebind "
            f"may not change its effect to {effect!r}"
        )
    _registry[name] = RegisteredTool(
        name=name, func=func, description=description, effect=effect
    )


def unregister_tool(name: str) -> None:
    """Remove a registered tool. Raises KeyError if the name is unknown."""
    try:
        del _registry[name]
    except KeyError:
        raise KeyError(f"Tool '{name}' is not registered") from None


def get_tool(name: str) -> RegisteredTool | None:
    """Return the registry entry for a name, or None if unregistered."""
    return _registry.get(name)


def native_write_tool_names() -> frozenset[str]:
    """Every registered tool that must stay native in code mode."""
    return frozenset(t.name for t in _registry.values() if t.effect != "read")


def mcp_servable(names: Iterable[str]) -> list[str]:
    """The granted names an MCP client may call: reads and proposals only.

    The one gate for MCP. A ``writes`` tool is dropped whatever the grant
    says, and so is a name with no registered tool. Order is preserved.
    """
    return [
        name
        for name in names
        if (tool := _registry.get(name)) is not None
        and tool.effect in _MCP_SERVABLE_EFFECTS
    ]


def registered_tool_names() -> list[str]:
    """All currently registered tool names, in registration order."""
    return list(_registry)


def resolve_tools(names: Iterable[str]) -> list[ToolFunc]:
    """Resolve tool names to callables, preserving order.

    Unknown names are skipped with a warning: a ``tool`` row whose
    callable was renamed or removed degrades that one tool, not the
    whole agent.

    Every callable is wrapped for the per-call ledger on the way out. This
    is the one seam an agent's tools all pass through, so a new tool is
    measured by existing rather than by remembering a decorator.
    """
    resolved: list[ToolFunc] = []
    for name in names:
        entry = _registry.get(name)
        if entry is None:
            logger.warning("Tool has no registered callable; skipping", tool_name=name)
            continue
        resolved.append(instrument(entry.name, entry.func))
    return resolved
