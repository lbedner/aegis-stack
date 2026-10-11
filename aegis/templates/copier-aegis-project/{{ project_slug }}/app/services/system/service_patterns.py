"""The service pattern, read from the service source files.

A service is a folder convention, not a runtime object, so its functions
are read with ``ast`` rather than imported: deterministic, and no import
side effects. An instance is a service function that touches the
database, either by taking a session or by opening one.

The rule is the unit of work: the caller (a route's dependency, a job, a
task) opens one session and hands it down; a service function takes it
as a required parameter and never opens its own. On SQLite a second
session inside a request waits on the first one's write lock and fails
with "database is locked". Entry points with no caller (``jobs.py``,
``health.py``) open the one session and pass it on.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core import source_index
from app.core.log import logger
from app.core.source_functions import Function
from app.services.system.patterns import (
    PROJECT_ROOT,
    Pattern,
    Rule,
    SourceText,
    Step,
)

SERVICES = "app/services"  # the services' folder, from the project's root
# Modules whose functions start a unit of work themselves (and any
# ``health_*`` check module).
ENTRY_POINTS = frozenset({"jobs", "health"})
OPENERS = frozenset(
    {"get_async_session", "db_session", "AsyncSessionLocal", "SessionLocal"}
)
SESSION_NAMES = frozenset({"session", "db"})


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

    @property
    def service(self) -> str:
        return self.path.split("/")[0]

    @property
    def entry_point(self) -> bool:
        stem = Path(self.path).stem
        return stem in ENTRY_POINTS or stem.startswith("health_")


def _function(
    function: Function, path: str, lines: tuple[str, ...]
) -> ServiceFunction | None:
    """``function`` as the pattern reads it, if it touches the database:
    takes a session (by name or annotation) or opens one."""
    params = [
        p
        for p in function.params
        if p.name in SESSION_NAMES or "Session" in (p.annotation or "")
    ]
    opens = bool(function.calls & OPENERS)
    if not params and not opens:
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
        source=SourceText(
            "\n".join(lines[function.start - 1 : function.end]), f"{SERVICES}/{path}"
        ),
    )


def services(source: Any = None) -> list[tuple[str, ServiceFunction]]:
    """Every service function that touches the database. ``source`` may be
    another services root (tests); anything else means this project's."""
    if isinstance(source, Path):
        index, prefix = source_index.at(source), ""
    else:
        index, prefix = source_index.at(PROJECT_ROOT, SERVICES), f"{SERVICES}/"
    found = []
    for name, path in sorted(index.paths.items(), key=lambda item: item[1]):
        module = index.get(name)
        if module is None:
            logger.warning("Service pattern skipped an unreadable module", path=path)
            continue
        relative = path.removeprefix(prefix)
        for function in module.functions:
            if read := _function(function, relative, module.lines):
                found.append((f"{relative}: {read.qualname}", read))
    return found


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
            "two. Entry points with no caller (jobs.py, health.py) open the one "
            "session themselves.",
            lambda f: not f.opens,
            exempt=lambda f: f.entry_point,
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
