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
        raise ValueError(f"zuvloop needs Python {wanted} or newer; this is {running}.")
    if chosen == "asyncio":
        return chosen
    if chosen != "auto":
        # Checked here rather than left to the engine: granian's worker dies
        # on a loop it cannot import, which ends a bench sweep outright.
        if importlib.util.find_spec(chosen) is None:
            raise ValueError(
                f"{chosen} is not installed; add it with `uv add {chosen}`."
            )
        return chosen
    # Never zuvloop: it is 0.0.x, so it stays something you ask for.
    return "uvloop" if importlib.util.find_spec("uvloop") else "asyncio"


def check_engine_loop(engine: str, loop: str) -> None:
    """Raise unless ``engine`` can actually run ``loop``.

    One function because the two serve paths disagreed: uvicorn raised a
    sentence naming both engines, granian raised nothing at all and let
    ``Loops(loop)`` fail on an enum lookup. The benchmark deliberately
    does not use this - sweeping a loop only one engine runs is normal,
    so it skips the other rather than dying halfway through the matrix.
    ``auto`` always passes: it resolves to something the engine accepts.
    """
    if loop == "auto":
        return
    accepted = ENGINE_LOOPS.get(engine)
    if accepted is None:
        raise ValueError(
            f"unknown engine {engine!r}; expected one of "
            f"{', '.join(sorted(ENGINE_LOOPS))}."
        )
    if loop not in accepted:
        other = ", ".join(
            f"{name} accepts {', '.join(loops)}"
            for name, loops in ENGINE_LOOPS.items()
            if name != engine
        )
        raise ValueError(
            f"{engine} cannot run on {loop!r}. It accepts "
            f"{', '.join(accepted)}; {other}."
        )
