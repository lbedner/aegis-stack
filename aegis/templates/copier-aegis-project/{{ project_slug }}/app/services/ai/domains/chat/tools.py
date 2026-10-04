"""An agent's tools: its ``agent_tool`` rows' names, resolved from the
core registry (``app.core.tools``) and wrapped for the tool-call ledger."""

from collections.abc import Iterable

from app.core.log import logger
from app.core.tools import ToolFunc, get_tool
from app.services.ai.domains.chat.tool_telemetry import instrument


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
        entry = get_tool(name)
        if entry is None:
            logger.warning("Tool has no registered callable; skipping", tool_name=name)
            continue
        resolved.append(instrument(entry.name, entry.func))
    return resolved
