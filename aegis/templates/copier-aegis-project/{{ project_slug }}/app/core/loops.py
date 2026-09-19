"""Which asyncio event loop the app runs on.

Its own module, and a deliberately cheap one: the entrypoint needs it and
so does ``scripts/bench_engines.py``, and the benchmark must not import the
app factory just to ask a settings question. Importing that would fire the
observability auto-tracing hook in a process that serves nothing.
"""

from __future__ import annotations

import importlib.util
import sys

from app.core.config import settings

# The compatibility matrix, in one place because it is the thing that
# grows: zuvloop reaches uvicorn only through `loop="none"` and does not
# reach granian at all (its Loops enum refuses the name, and zuvloop ships
# no EventLoopPolicy to redirect granian's asyncio builder).
ENGINE_LOOPS: dict[str, tuple[str, ...]] = {
    "uvicorn": ("asyncio", "uvloop", "zuvloop"),
    "granian": ("asyncio", "uvloop", "rloop"),
}

# zuvloop's wheels start at 3.14, and the dependency marker in
# pyproject.toml already keeps it out of older environments. This is the
# second half: a clear sentence instead of an ImportError when someone
# pins the loop by hand on 3.13.
ZUVLOOP_MIN_PYTHON = (3, 14)


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
    if chosen == "zuvloop" and sys.version_info < ZUVLOOP_MIN_PYTHON:
        running = ".".join(str(part) for part in sys.version_info[:2])
        wanted = ".".join(str(part) for part in ZUVLOOP_MIN_PYTHON)
        raise ValueError(
            f"zuvloop needs Python {wanted} or newer; this is {running}."
        )
    if chosen != "auto":
        return chosen
    # Never zuvloop: it is 0.0.x, so it stays something you ask for.
    return "uvloop" if importlib.util.find_spec("uvloop") else "asyncio"
