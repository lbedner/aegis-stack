"""The backend's patterns, detected from the running app.

A pattern is one definition: the steps of its diagram, how to find its
instances, and its rules, each with the reason behind it and what is
exempt. The Overseer's Patterns page renders a report of it; a test holds
the enforced rules at zero violations; an agent can read the same report
before building. Instances are found, never listed by hand, so the
catalog cannot drift from the code.

Routes are defined here. A component with a pattern of its own defines
it beside its code (``app.components.worker.patterns``) with the same
pieces and the function helpers below.
"""

import ast
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
import inspect
from pathlib import Path
import textwrap
from types import ModuleType
import typing
from typing import Any, NamedTuple

from fastapi.routing import APIRoute
from pydantic import BaseModel
from starlette.responses import StreamingResponse
from starlette.routing import BaseRoute

from app.core.route_auth import route_requires_auth

API_PACKAGE = "app.components.backend.api"
SERVICE_PACKAGE = "app.services"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
# Past this many statements a handler or task is doing work a service
# should own. From the shipped routes: audited admin actions take four or
# five, the token and registration handlers ten or more.
THIN_STATEMENTS = 5

Check = Callable[[Any], bool]


def _never(_target: Any) -> bool:
    return False


def _no_rank(_target: Any) -> tuple[Any, ...]:
    return ()


@dataclass(frozen=True)
class Rule:
    key: str
    title: str
    why: str
    check: Check
    exempt: Check = _never
    # Enforced rules are held at zero violations by the test suite; the
    # rest are reported on the page and left to judgement.
    enforced: bool = False


@dataclass(frozen=True)
class Step:
    label: str
    detail: str
    # The instances this step is relevant to (all when None), and the
    # check that one of them follows it. A step with no ``follows`` is
    # counted but not scored: every protected route has a current user.
    applies: Check | None = None
    follows: Check | None = None


@dataclass(frozen=True)
class Pattern:
    key: str
    title: str
    summary: str
    steps: tuple[Step, ...]
    rules: tuple[Rule, ...]
    # source -> (label, target) for every instance; the page hands in the
    # app's routes, which a pattern that finds its own instances ignores.
    discover: Callable[[Any], list[tuple[str, Any]]]
    # The function to read for an instance's source.
    function: Callable[[Any], Any]
    # Orders clean instances; the highest is the canonical example.
    rank: Callable[[Any], tuple[Any, ...]] = field(default=_no_rank)


class SourceText(NamedTuple):
    """Source already read from disk, for patterns whose instances are not
    importable objects (services are read with ``ast``)."""

    text: str
    path: str


class Instance(NamedTuple):
    label: str
    target: Any
    findings: list[str]


class RuleReport(NamedTuple):
    key: str
    title: str
    why: str
    enforced: bool
    applicable: int
    violations: list[Instance]

    @property
    def followed(self) -> int:
        return self.applicable - len(self.violations)


class StepReport(NamedTuple):
    label: str
    detail: str
    applicable: int
    followed: int | None


class Report(NamedTuple):
    pattern: Pattern
    instances: list[Instance]
    rules: list[RuleReport]
    steps: list[StepReport]
    canonical: Instance | None

    @property
    def enforced(self) -> list[RuleReport]:
        return [rule for rule in self.rules if rule.enforced]


# Function helpers, shared by every pattern ---------------------------------


def returns(call: Any) -> object:
    """A callable's return annotation, resolved; None if unreadable."""
    try:
        return typing.get_type_hints(call).get("return")
    except (NameError, TypeError):
        return None


def from_services(obj: object) -> bool:
    """A service module, function or class; not a schema that lives there."""
    if isinstance(obj, ModuleType):
        return obj.__name__.startswith(SERVICE_PACKAGE)
    if isinstance(obj, type) and issubclass(obj, BaseModel):
        return False
    return str(getattr(obj, "__module__", "")).startswith(SERVICE_PACKAGE)


def body(func: Any) -> list[ast.stmt] | None:
    """A function's statements, docstring aside; None if unreadable."""
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    except (OSError, TypeError, SyntaxError):
        return None
    function = tree.body[0]
    if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
        return None
    statements = function.body
    first = statements[0] if statements else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
        statements = statements[1:]
    return statements


def _resolve(node: ast.expr, scope: dict[str, Any]) -> list[object]:
    """Each object along a dotted call target (``job.func`` gives the job
    and its ``func``), as far as it resolves."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name) or node.id not in scope:
        return []
    chain = [scope[node.id]]
    for name in reversed(parts):
        chain.append(getattr(chain[-1], name, None))
    return chain


def calls_service(func: Any) -> bool:
    """The function calls a service: a module, function or class from
    ``app.services``, reached by name, attribute or a lazy import."""
    statements = body(func)
    if statements is None:
        return False
    try:
        names = inspect.getclosurevars(func)
    except TypeError:
        return False
    scope = {**names.globals, **names.nonlocals}
    for node in ast.walk(ast.Module(body=statements, type_ignores=[])):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            SERVICE_PACKAGE
        ):
            return True
        if isinstance(node, ast.Call) and any(
            from_services(obj) for obj in _resolve(node.func, scope)
        ):
            return True
    return False


def _logs(statement: ast.stmt) -> bool:
    """A bare ``logger.<level>(...)`` line: not work."""
    call = statement.value if isinstance(statement, ast.Expr) else None
    target = call.func if isinstance(call, ast.Call) else None
    return (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "logger"
    )


def thin(func: Any, uses_service: bool) -> bool:
    """Hands the work to a service in a few statements, or is one statement
    (a constant answer, or a single delegation) with no work to hand over.
    Log lines are not counted."""
    statements = body(func)
    if statements is None:
        return False
    work = [s for s in statements if not _logs(s)]
    return len(work) == 1 or (uses_service and len(work) <= THIN_STATEMENTS)


def statement_count(func: Any) -> int:
    return len(body(func) or [])


# Routes ---------------------------------------------------------------------


def label(route: APIRoute) -> str:
    methods = ",".join(sorted(m for m in route.methods if m != "HEAD"))
    return f"{methods} {route.path}"


def dependency_names(route: APIRoute) -> set[str]:
    """Every dependency the route pulls in, however deeply nested."""
    names: set[str] = set()
    pending = list(route.dependant.dependencies)
    while pending:
        dependant = pending.pop()
        names.add(getattr(dependant.call, "__name__", ""))
        pending.extend(dependant.dependencies)
    return names


def _streams(route: APIRoute) -> bool:
    """True when the route answers with a stream rather than a model."""
    response_class = getattr(route.response_class, "value", route.response_class)
    for candidate in (response_class, returns(route.endpoint)):
        if isinstance(candidate, type) and issubclass(candidate, StreamingResponse):
            return True
    return False


def _untyped_ok(route: APIRoute) -> bool:
    """No body to type: 204 No Content, or a stream."""
    return route.status_code == 204 or _streams(route)


def _injects_service(route: APIRoute) -> bool:
    """A handler dependency hands it a service (which brings the session)."""
    return any(from_services(returns(d.call)) for d in route.dependant.dependencies)


def _uses_service(route: APIRoute) -> bool:
    return _injects_service(route) or calls_service(route.endpoint)


def _thin_route(route: APIRoute) -> bool:
    return thin(route.endpoint, _uses_service(route))


def routes(source: Iterable[BaseRoute]) -> list[tuple[str, APIRoute]]:
    """The routes the API publishes: everything in the OpenAPI schema."""
    return [
        (label(r), r) for r in source if isinstance(r, APIRoute) and r.include_in_schema
    ]


def _route_rank(route: APIRoute) -> tuple[bool, bool, bool, int, int]:
    """Protected, handed a service, taking a path parameter, in the fewest
    statements (shortest path on a tie)."""
    return (
        route_requires_auth(route),
        _injects_service(route),
        "{" in route.path,
        -statement_count(route.endpoint),
        -len(route.path),
    )


ROUTE = Pattern(
    key="route",
    title="Route",
    summary=(
        "An HTTP endpoint in the API package: a tagged router under a versioned "
        "path, the current user injected when protected, a service injected that "
        "brings the session and does the work, and a response model as the contract."
    ),
    steps=(
        Step("Request", "Arrives at /api/v1/..."),
        Step("Router", "Grouped by tag", follows=lambda r: bool(r.tags)),
        Step(
            "Current user", "Injected on protected routes", applies=route_requires_auth
        ),
        Step(
            "Service",
            "Injected with Depends(get_..._service), which brings the session; "
            "the handler only calls it",
            follows=_uses_service,
        ),
        Step(
            "Response model",
            "The typed contract",
            applies=lambda r: not _untyped_ok(r),
            follows=lambda r: r.response_model is not None,
        ),
    ),
    rules=(
        Rule(
            "api-package",
            "Lives in the API package",
            "The OpenAPI schema is the API's contract. Pages and htmx fragments "
            "are defined elsewhere and set include_in_schema=False.",
            lambda r: r.endpoint.__module__.startswith(API_PACKAGE),
            enforced=True,
        ),
        Rule(
            "versioned",
            "Versioned path",
            "Clients pin a version under /api/v1; /health is the one unversioned probe.",
            lambda r: r.path.startswith(("/api/v1/", "/health")),
        ),
        Rule(
            "tagged",
            "Tagged",
            "Tags group the API docs, the Server's route list and this catalog.",
            lambda r: bool(r.tags),
        ),
        Rule(
            "typed",
            "Typed response",
            "A response model is the contract clients generate against. Streams "
            "and 204 No Content have no body to type.",
            lambda r: r.response_model is not None,
            exempt=_untyped_ok,
        ),
        Rule(
            "thin",
            "Thin handler",
            "The handler takes the request apart and hands it to a service, so the "
            "work lives where routes, tasks and jobs can all reach it: at most "
            f"{THIN_STATEMENTS} statements around a service call, or one statement.",
            _thin_route,
        ),
    ),
    discover=routes,
    function=lambda r: r.endpoint,
    rank=_route_rank,
)


# Reports --------------------------------------------------------------------


def _follows_steps(steps: tuple[Step, ...], target: Any) -> bool:
    return all(
        s.follows(target)
        for s in steps
        if s.follows and (s.applies is None or s.applies(target))
    )


def report(pattern: Pattern, source: Any = ()) -> Report:
    """Every instance of ``pattern`` found in ``source``, checked against its
    rules and steps. The canonical example is the highest-ranked instance
    that follows every rule and every step: an agent copies the example,
    not the diagram, so the example must be the diagram."""
    listed = [
        Instance(
            name,
            target,
            [
                rule.key
                for rule in pattern.rules
                if not rule.exempt(target) and not rule.check(target)
            ],
        )
        for name, target in pattern.discover(source)
    ]
    rules = [
        RuleReport(
            rule.key,
            rule.title,
            rule.why,
            rule.enforced,
            sum(1 for i in listed if not rule.exempt(i.target)),
            [i for i in listed if rule.key in i.findings],
        )
        for rule in pattern.rules
    ]
    steps = []
    for step in pattern.steps:
        relevant = [
            i.target for i in listed if step.applies is None or step.applies(i.target)
        ]
        followed = None if step.follows is None else sum(map(step.follows, relevant))
        steps.append(StepReport(step.label, step.detail, len(relevant), followed))
    clean = [
        i for i in listed if not i.findings and _follows_steps(pattern.steps, i.target)
    ]
    canonical = max(
        clean, key=lambda i: (pattern.rank(i.target), i.label), default=None
    )
    return Report(pattern, listed, rules, steps, canonical)


def source(func: Any) -> tuple[str, str]:
    """A function's source and its file relative to the project."""
    if isinstance(func, SourceText):
        return func.text, func.path
    path = Path(inspect.getsourcefile(func) or "")
    try:
        shown = str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        shown = path.name
    return inspect.getsource(func), shown


def installed_patterns() -> dict[str, Pattern]:
    """Every pattern this project has: routes and services always, worker
    tasks when the worker component is installed."""
    from app.services.system.service_patterns import SERVICE

    found = {"route": ROUTE, "service": SERVICE}
    try:
        from app.components.worker.patterns import TASK
    except ImportError:  # no worker component in this project
        return found
    return found | {"task": TASK}
