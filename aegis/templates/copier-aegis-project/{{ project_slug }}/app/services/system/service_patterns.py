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

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.log import logger
from app.services.system.patterns import (
    PROJECT_ROOT,
    Pattern,
    Rule,
    SourceText,
    Step,
)

SERVICES_ROOT = PROJECT_ROOT / "app" / "services"
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


def _session_params(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[tuple[ast.arg, Any]]:
    """Each session parameter, by name or by annotation, with its default."""
    args = node.args
    positional = args.posonlyargs + args.args
    defaults: dict[str, ast.expr | None] = dict.fromkeys(a.arg for a in positional)
    for arg, default in zip(
        positional[len(positional) - len(args.defaults) :], args.defaults
    ):
        defaults[arg.arg] = default
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        defaults[arg.arg] = default
    return [
        (arg, defaults.get(arg.arg))
        for arg in positional + args.kwonlyargs
        if arg.arg in SESSION_NAMES
        or (arg.annotation is not None and "Session" in ast.unparse(arg.annotation))
    ]


def _opens(node: ast.AST) -> bool:
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        target = call.func
        name = (
            target.id if isinstance(target, ast.Name) else getattr(target, "attr", "")
        )
        if name in OPENERS:
            return True
    return False


def _statements(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    body = node.body
    first = body[0] if body else None
    docstring = isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
    return len(body) - int(docstring)


def _function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    qualname: str,
    path: str,
    lines: list[str],
) -> ServiceFunction | None:
    params = _session_params(node)
    opens = _opens(node)
    if not params and not opens:
        return None
    start = min([d.lineno for d in node.decorator_list] + [node.lineno])
    return ServiceFunction(
        path=path,
        qualname=qualname,
        is_async=isinstance(node, ast.AsyncFunctionDef),
        takes=bool(params),
        optional=any(
            isinstance(default, ast.Constant) and default.value is None
            for _, default in params
        ),
        opens=opens,
        typed=any(
            arg.annotation is not None and "Session" in ast.unparse(arg.annotation)
            for arg, _ in params
        ),
        statements=_statements(node),
        source=SourceText(
            "\n".join(lines[start - 1 : node.end_lineno]), f"app/services/{path}"
        ),
    )


def _module_functions(path: Path, root: Path) -> list[ServiceFunction]:
    text = path.read_text()
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        logger.warning(
            "Service pattern skipped an unreadable module",
            path=str(path),
            error=str(exc),
        )
        return []
    relative, lines = path.relative_to(root).as_posix(), text.splitlines()
    found: list[ServiceFunction] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}{child.name}.")
            elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                function = _function(child, prefix + child.name, relative, lines)
                if function is not None:
                    found.append(function)

    visit(tree, "")
    return found


def services(source: Any = None) -> list[tuple[str, ServiceFunction]]:
    """Every service function that touches the database. ``source`` may be
    another services root (tests); anything else means this project's."""
    root = source if isinstance(source, Path) else SERVICES_ROOT
    return [
        (f"{f.path}: {f.qualname}", f)
        for path in sorted(root.rglob("*.py"))
        for f in _module_functions(path, root)
    ]


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
