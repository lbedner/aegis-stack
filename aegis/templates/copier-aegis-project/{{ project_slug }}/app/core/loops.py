"""Which asyncio event loop the app runs on.

Its own module, and a deliberately cheap one: the entrypoint needs it and
so does ``scripts/bench_engines.py``, and the benchmark must not import the
app factory just to ask a settings question. Importing that would fire the
observability auto-tracing hook in a process that serves nothing.
"""

from __future__ import annotations

import importlib.util

from app.core.config import settings

# The compatibility matrix, in one place because it is the thing that
# grows: zuvloop reaches uvicorn only through `loop="none"` and does not
# reach granian at all (its Loops enum refuses the name, and zuvloop ships
# no EventLoopPolicy to redirect granian's asyncio builder).
ENGINE_LOOPS: dict[str, tuple[str, ...]] = {
    "uvicorn": ("asyncio", "uvloop"),
    "granian": ("asyncio", "uvloop", "rloop"),
}


def resolve_loop(choice: str | None = None) -> str:
    """The loop to pin, never ``auto``.

    Granian's own ``auto`` prefers rloop over uvloop whenever rloop is
    importable, so a transitive dependency could move a deployment onto an
    alpha loop with no code change and nothing in the logs. Resolving here
    means the loop is always a decision, and always the same decision
    whoever is asking.

    ``choice`` overrides the setting, for callers that were given one on a
    command line.
    """
    chosen = choice or settings.WEBSERVER_LOOP
    if chosen != "auto":
        return chosen
    return "uvloop" if importlib.util.find_spec("uvloop") else "asyncio"
