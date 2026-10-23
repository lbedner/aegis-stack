"""The async pattern, read from the app's source with ``ast``: an async
function runs on the event loop, alongside every other request, so work
that blocks (the system model's build, a sleep, a subprocess) is handed to
a thread (``await asyncio.to_thread(f)``), never called in it. Called
there, it holds the whole server until it returns.

An instance is an async function that runs blocking work: one that hands
it to a thread, or calls it on the loop. A blocking call is one made
without ``await`` to a name its module imports from where the blocking
function lives (``BLOCKING``), however it is spelled or aliased:
``replays.current()`` is a request's recording, not the model. The CLI's
commands are exempt: their loop serves no one else."""

from dataclasses import dataclass
from typing import Any

from app.core.source_functions import Function
from app.core.source_index import Module
from app.services.system.patterns import (
    Pattern,
    Rule,
    SourceText,
    Step,
    read_functions,
)

APP = "app"
# What blocks, by where it lives: the system model's build (it parses the
# source), a sleep, a subprocess or a URL waited on.
BLOCKING = frozenset(
    {
        *(
            f"app.core.ontology{at}.{name}"
            for at in ("", ".system")
            for name in ("current", "system_model", "with_app")
        ),
        "time.sleep",
        "subprocess.run",
        "subprocess.check_call",
        "subprocess.check_output",
        "urllib.request.urlopen",
    }
)


@dataclass(frozen=True)
class AsyncFunction:
    path: str  # under ``app/``
    qualname: str
    blocks: frozenset[str]  # what it calls on the loop that blocks
    hands_off: bool
    statements: int
    source: SourceText

    @property
    def group(self) -> str:
        """The part of the app it is in: ``services/system``."""
        return "/".join(self.path.split("/")[:2])


def resolved(spelled: str, module: Module) -> str | None:
    """A call as written (``f``, ``x.f``) as the full name its module's
    imports make it (``time.sleep``); None for a name not imported."""
    head, _, attr = spelled.partition(".")
    found = module.imported.get(head)
    if found is None:
        return None
    full = ".".join(part for part in found if part)
    return f"{full}.{attr}" if attr else full


def _function(function: Function, module: Module, path: str) -> AsyncFunction | None:
    """``function`` as the pattern reads it, if it is async and runs
    blocking work."""
    names = (resolved(call, module) for call in function.unawaited)
    blocks = frozenset(name for name in names if name in BLOCKING)
    hands_off = "to_thread" in function.calls
    if not function.is_async or not (blocks or hands_off):
        return None
    return AsyncFunction(
        path=path,
        qualname=function.qualname,
        blocks=blocks,
        hands_off=hands_off,
        statements=function.statements,
        source=SourceText.of(function, module.lines, f"{APP}/{path}"),
    )


def functions(source: Any = None) -> list[tuple[str, AsyncFunction]]:
    """Every async function that runs blocking work. ``source`` may be
    another root (tests); anything else means this project's ``app``."""
    return read_functions(source, APP, _function)


def _off_the_loop(f: AsyncFunction) -> bool:
    return not f.blocks


ASYNC = Pattern(
    key="async",
    title="Async function",
    summary=(
        "Runs on the event loop with every other request. Blocking work is "
        "handed to a thread; called on the loop, it holds the whole server."
    ),
    steps=(
        Step("Async function", "A route, a task, a service call: on the loop"),
        Step(
            "Blocking work",
            "Handed to a thread: await asyncio.to_thread(f)",
            follows=_off_the_loop,
        ),
    ),
    rules=(
        Rule(
            "off-the-loop",
            "Blocking work is off the loop",
            "An async function shares the event loop with every request in "
            "flight: a blocking call in it (the system model's build parses "
            "the source for seconds) stalls them all until it returns. Hand "
            "it to a thread: await asyncio.to_thread(f).",
            _off_the_loop,
            exempt=lambda f: f.path.startswith("cli/"),
            gate=True,
            action="await asyncio.to_thread(...) instead of calling it on the loop",
        ),
    ),
    discover=functions,
    function=lambda f: f.source,
    rank=lambda f: (f.hands_off, -f.statements),
)
