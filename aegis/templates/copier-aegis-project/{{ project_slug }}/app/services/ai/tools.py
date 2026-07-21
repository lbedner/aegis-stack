"""Agent tool registry.

Maps tool names to Python callables. The ``tool`` table's rows key into
this registry by ``name``: the database decides WHICH tools an agent may
call (via ``agent_tool`` attachments); this module decides WHAT each name
executes. Framework-agnostic on purpose - entries are plain callables in
whatever shape the chat engine accepts (pydantic-ai takes functions or
``Tool`` instances), and nothing here imports an AI framework.

Applications register their own domain tools at import time:

    from app.services.ai.tools import register_tool

    async def lookup_order(order_id: str) -> str:
        \"\"\"Fetch an order summary.\"\"\"
        ...

    register_tool("lookup_order", lookup_order)

A database row naming a tool with no registered callable is skipped with
a warning, never an error: a stale row must not brick chat.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from app.core.log import logger

ToolFunc = Callable[..., Any]


@dataclass(frozen=True)
class RegisteredTool:
    """A named tool entry: the callable plus registry metadata."""

    name: str
    func: ToolFunc
    description: str | None = None


_registry: dict[str, RegisteredTool] = {}


def register_tool(
    name: str,
    func: ToolFunc,
    *,
    description: str | None = None,
    replace: bool = False,
) -> None:
    """Register a callable under a tool name.

    Raises ValueError on a duplicate name unless ``replace=True``, so two
    modules can't silently fight over one name.
    """
    if not replace and name in _registry:
        raise ValueError(
            f"Tool '{name}' is already registered; pass replace=True to rebind it"
        )
    _registry[name] = RegisteredTool(name=name, func=func, description=description)


def unregister_tool(name: str) -> None:
    """Remove a registered tool. Raises KeyError if the name is unknown."""
    try:
        del _registry[name]
    except KeyError:
        raise KeyError(f"Tool '{name}' is not registered") from None


def get_tool(name: str) -> RegisteredTool | None:
    """Return the registry entry for a name, or None if unregistered."""
    return _registry.get(name)


def registered_tool_names() -> list[str]:
    """All currently registered tool names, in registration order."""
    return list(_registry)


def resolve_tools(names: Iterable[str]) -> list[ToolFunc]:
    """Resolve tool names to callables, preserving order.

    Unknown names are skipped with a warning: a ``tool`` row whose
    callable was renamed or removed degrades that one tool, not the
    whole agent.
    """
    resolved: list[ToolFunc] = []
    for name in names:
        entry = _registry.get(name)
        if entry is None:
            logger.warning(
                "Tool has no registered callable; skipping", tool_name=name
            )
            continue
        resolved.append(entry.func)
    return resolved
