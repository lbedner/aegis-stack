"""The service pattern, read from the service source files.

A service is a folder convention, not a runtime object, so its functions
are read with ``ast`` rather than imported: deterministic, and no import
side effects. An instance is a service function that touches the
database, either by taking a session or by opening one, or a registered
tool (whose answer is held to a model whatever it reads).

The rule is the unit of work: the caller (a route's dependency, a job, a
task) opens one session and hands it down; a service function takes it
as a required parameter and never opens its own. On SQLite a second
session inside a request waits on the first one's write lock and fails
with "database is locked". Entry points with no caller (``jobs.py``,
``health.py``, an agent's tool) open the one session and pass it on.
"""

from dataclasses import dataclass
from pathlib import Path
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

SERVICES = "app/services"  # the services' folder, from the project's root
# Modules whose functions start a unit of work themselves (and any
# ``health_*`` check module, and any registered tool).
ENTRY_POINTS = frozenset({"jobs", "health", "tools"})
OPENERS = frozenset(
    {"get_async_session", "db_session", "AsyncSessionLocal", "SessionLocal"}
)
SESSION_NAMES = frozenset({"session", "db"})
# A record handed back by its keys, which no type checker holds: a label's
# counts (``dict[str, int]``) are figures, not a record.
RECORDS = frozenset({"dict", "dict[str,Any]", "list[dict[str,Any]]"})


@dataclass(frozen=True)
class ServiceFunction:
    path: str
    qualname: str
    is_async: bool
    takes: bool
    optional: bool
    opens: bool
    typed: bool
    statements: int
    source: SourceText
    returns: str | None
    tool: bool  # registered: an agent's or an MCP client's

    @property
    def service(self) -> str:
        return self.path.split("/")[0]

    @property
    def group(self) -> str:
        """What the Patterns page groups it by: its service."""
        return self.service

    @property
    def entry_point(self) -> bool:
        stem = Path(self.path).stem
        return self.tool or stem in ENTRY_POINTS or stem.startswith("health_")


def _function(function: Function, module: Module, path: str) -> ServiceFunction | None:
    """``function`` as the pattern reads it, if it touches the database
    (takes a session, by name or annotation, or opens one) or is a tool."""
    params = [
        p
        for p in function.params
        if p.name in SESSION_NAMES or "Session" in (p.annotation or "")
    ]
    opens = bool(function.calls & OPENERS)
    tool = function.qualname in module.tools
    if not params and not opens and not tool:
        return None
    return ServiceFunction(
        path=path,
        qualname=function.qualname,
        is_async=function.is_async,
        takes=bool(params),
        optional=any(p.default == "None" for p in params),
        opens=opens,
        typed=any("Session" in (p.annotation or "") for p in params),
        statements=function.statements,
        source=SourceText.of(function, module.lines, f"{SERVICES}/{path}"),
        returns=function.returns,
        tool=tool,
    )


def _record(returns: str | None) -> bool:
    """A record handed back by its keys, optional or not: ``dict[str, Any]
    | None`` is one too."""
    spelled = (returns or "").replace(" ", "")
    for none in ("|None", "None|"):
        spelled = spelled.replace(none, "")
    if spelled.startswith("Optional[") and spelled.endswith("]"):
        spelled = spelled[len("Optional[") : -1]
    return spelled in RECORDS


def services(source: Any = None) -> list[tuple[str, ServiceFunction]]:
    """Every service function that touches the database. ``source`` may be
    another services root (tests); anything else means this project's."""
    return read_functions(source, SERVICES, _function)


def _follows(f: ServiceFunction) -> bool:
    return f.takes and not f.optional and not f.opens


def _rank(f: ServiceFunction) -> tuple[bool, bool, bool, int]:
    """Async, typed, a few statements of real work; then the fewest."""
    return (f.is_async, f.typed, 2 <= f.statements <= 8, -f.statements)


SERVICE = Pattern(
    key="service",
    title="Service",
    summary=(
        "Business logic, reachable from routes, tasks, jobs and the CLI alike. "
        "The caller opens one session and hands it down; a service function "
        "takes it as a required parameter and never opens its own."
    ),
    steps=(
        Step("Caller", "A route, task, job or CLI command"),
        Step(
            "Session",
            "Opened once by the caller: Depends(get_async_db), or one "
            "async with get_async_session() in a job",
        ),
        Step(
            "Service",
            "Takes session: AsyncSession, opens none",
            applies=lambda f: not f.entry_point,
            follows=_follows,
        ),
        Step("Queries", "Run on the session it was handed"),
        Step("Commit", "The caller that opened the session commits it"),
    ),
    rules=(
        Rule(
            "takes-session",
            "Takes its session",
            "A second session inside a request waits on the first one's write "
            'lock (SQLite: "database is locked") and splits one unit of work in '
            "two. Entry points with no caller (jobs.py, health.py, an agent's "
            "tool) open the one session themselves.",
            lambda f: not f.opens,
            exempt=lambda f: f.entry_point,
            gate=True,
        ),
        Rule(
            "returns-model",
            "Hands back a model",
            "A dict's keys are a contract no type checker holds: a renamed key "
            "breaks the health check, the API or an agent at run time. A read "
            "returns a typed model (FIGURES where an agent, the API or Overseer "
            "reads it); a label's counts may stay a dict[str, int]. A tool's "
            "answer too: its schema types code mode's script and an MCP client.",
            lambda f: not _record(f.returns),
            gate=True,
            action="Return a model with model_config = FIGURES.",
        ),
        Rule(
            "required-session",
            "Session is required",
            "A session=None fallback works until a caller forgets to pass one, "
            "then quietly opens a second session. Required, it fails at the call.",
            lambda f: not f.optional,
            exempt=lambda f: not f.takes,
        ),
    ),
    discover=services,
    function=lambda f: f.source,
    rank=_rank,
)
