"""The guard around code mode's ``run_code`` (``agent_capabilities``).

One script per user at a time, and a script that failed calling a write
tool (writes stay out of the sandbox) is told to call it directly.
"""

import asyncio
import re
from typing import Any
import weakref

from app.core.tools import RUN_CODE

# How the sandbox says a name is not there: its checker before the script
# runs, or the interpreter when it does.
_NOT_IN_THE_SANDBOX = re.compile(
    r"Unknown function: (\w+)|Name `(\w+)` used when not defined"
)


def native_write_hint(message: str, natives: frozenset[str]) -> str | None:
    """What to tell a model that called a write tool from inside a script.

    Writes stay out of the sandbox (they must surface as their own tool
    call), so a script calling one fails "Unknown function". A model told
    only that retried the identical script and stalled: an error that only
    says what went wrong leaves it nothing to try. None when the missing
    name is not one of ``natives``."""
    for match in _NOT_IN_THE_SANDBOX.finditer(message):
        name = match.group(1) or match.group(2)
        if name in natives:
            return (
                f"`{name}` is its own tool, not a function inside {RUN_CODE}: "
                f"work out what it needs in {RUN_CODE}, then call `{name}` "
                "directly as a separate tool call."
            )
    return None


# One lock per user while any of their scripts is running or waiting; weak
# values, so an idle user's lock goes away on its own.
# ponytail: per process; a multi-worker webserver allows one run per user
# per worker. Move to a Redis lock if the webserver scales out.
_RUN_CODE_LOCKS: weakref.WeakValueDictionary[str | None, asyncio.Lock] = (
    weakref.WeakValueDictionary()
)


def run_code_guard(granted: frozenset[str]) -> Any:
    """A capability around each ``run_code`` call; every other tool passes
    straight through.

    One script per user at a time: a second WAITS rather than failing (a
    model often sends two run_code calls in one response, and a refusal
    would just come back as a retry), keyed on the turn's user
    (``current_user_id``, bound by every chat runtime); calls with none
    bound (MCP) share a single lock. And a script that failed calling one
    of the write tools in ``granted`` is told to call it directly
    (``native_write_hint``).
    """
    from pydantic_ai.capabilities import AbstractCapability
    from pydantic_ai.exceptions import ToolRetryError

    from app.services.ai.domains.chat.user_memory import current_user_id

    class _RunCodeGuard(AbstractCapability[Any]):
        async def wrap_tool_execute(
            self, ctx: Any, *, call: Any, tool_def: Any, args: Any, handler: Any
        ) -> Any:
            if tool_def.name != RUN_CODE:
                return await handler(args)
            user = current_user_id.get()
            lock = _RUN_CODE_LOCKS.setdefault(user, asyncio.Lock())
            async with lock:
                # The sandbox's failure arrives as the retry the model reads.
                try:
                    return await handler(args)
                except ToolRetryError as retry:
                    told = retry.tool_retry.content
                    hint = native_write_hint(str(retry), granted)
                    if hint is not None and isinstance(told, str):
                        retry.tool_retry.content = f"{told}\n\n{hint}"
                    raise

    return _RunCodeGuard()
