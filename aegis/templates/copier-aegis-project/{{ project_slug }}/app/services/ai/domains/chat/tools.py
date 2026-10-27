"""An agent's tools: its ``agent_tool`` rows' names, resolved from the
core registry (``app.core.tools``) and wrapped for the tool-call ledger."""

from collections.abc import Iterable
import functools
import inspect
from typing import Any

from app.core.log import logger
from app.core.tools import ADMIN_ONLY, Refused, ToolFunc, get_tool
from app.services.ai.domains.chat.tool_telemetry import instrument
from app.services.shared.deps import caller_is_admin


def resolve_tools(names: Iterable[str]) -> list[ToolFunc]:
    """Resolve tool names to callables, preserving order.

    Unknown names are skipped with a warning: a ``tool`` row whose
    callable was renamed or removed degrades that one tool, not the
    whole agent.

    Every callable is wrapped for the per-call ledger on the way out. This
    is the one seam an agent's tools all pass through, so a new tool is
    measured by existing rather than by remembering a decorator. Outside
    that, a refused argument is answered (``_told``) rather than raised.
    """
    resolved: list[ToolFunc] = []
    for name in names:
        entry = get_tool(name)
        if entry is None:
            logger.warning("Tool has no registered callable; skipping", tool_name=name)
            continue
        func = _admins_only(entry.func) if entry.admin else entry.func
        resolved.append(_told(instrument(entry.name, func)))
    return resolved


def _told(func: ToolFunc) -> ToolFunc:
    """``func`` answering its ``ValueError`` (a tool refusing an argument,
    naming what it knows) as the model's to correct, as a LangChain turn
    does: raised, Pydantic AI ends the turn, a live call with it. The
    ledger beneath has recorded it as failed."""

    def told(exc: ValueError) -> Refused:
        return Refused(error=f"{type(exc).__name__}: {exc}")

    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def answer(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except ValueError as exc:
                return told(exc)

        return answer

    @functools.wraps(func)
    def answer_sync(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except ValueError as exc:
            return told(exc)

    return answer_sync


def _admins_only(func: ToolFunc) -> ToolFunc:
    """``func`` answering only an admin (``caller_is_admin``), as MCP
    serves an admin tool: an agent granted it serves whoever chats."""

    @functools.wraps(func)  # the schema the model sees is func's
    async def guarded(*args: Any, **kwargs: Any) -> Any:
        if not await caller_is_admin():
            return Refused(error=ADMIN_ONLY)
        result = func(*args, **kwargs)
        return await result if inspect.isawaitable(result) else result

    return guarded
