"""The parts pattern: each service checked against the service standard
(``docs/services/index.md``): which of its conventional parts it has and
which rules it breaks, with the ``path:line`` that shows it.

One instance per services folder that is a part of the system model (a
service, a sub-service with a folder of its own like RAG, the app's shared
code), named by its node. Read from the source index, never imported.
Optional parts (a router, jobs) are inventory, counted on the strip; only
the rules are findings."""

import ast
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import cache, cached_property
from pathlib import Path
from typing import Any

from app.core import source_index
from app.core.ontology import Kind, current
from app.core.ontology.model import node_id, parse_node_id
from app.core.ontology.parts import node_of, service_folders
from app.core.source_index import Index, Module, within
from app.services.system import pattern_findings, patterns
from app.services.system.file_budget import (
    DECLARATION_LINES,
    LOGIC_LINES,
    cap_of,
    dominant,
    size_note,
)
from app.services.system.patterns import (
    API_PACKAGE,
    SERVICE_PACKAGE,
    Pattern,
    Report,
    Rule,
    SourceText,
    Step,
)

LOADERS = frozenset({"seed", "seeds", "demo_seed", "fixtures"})
LOADERS_WHY = "One-shot loaders, not runtime code: their reads need no queries module."
# A service that keeps its tables elsewhere by decision, with why.
MODELS_ELSEWHERE = {
    "auth": "Auth's tables are core (app/models): other services share them."
}
DATABASE = ("sqlmodel", "sqlalchemy")
# A service's top-level files as the standard names them, each the piece it
# is opened up (``service_pieces``): its title, and its lane, the way a call
# goes (in, wiring, the facade, its data; health a probe beside;
# constants and schemas, imported from every lane, on the rail above them
# all). The
# package its subsystems live in makes a piece of each too; any other
# top-level module is a subsystem left loose.
ROUTER = "Router"
PIECES = {
    "service": ("Facade", "facade"),
    "models": ("Models", "data"),
    "queries": ("Queries", "data"),
    "jobs": ("Jobs", "entry"),
    "scheduled_jobs": ("Jobs", "entry"),
    "health": ("Health", "probe"),
    "schemas": ("Schemas", "rail"),
    "deps": ("Deps", "wiring"),
    "constants": ("Constants", "rail"),
    "utils": ("Utils", "wiring"),
    "tools": ("Tools", "entry"),
    "change_types": ("Change types", "entry"),
    "sources": ("Sources", "entry"),  # research sources a plugin registers
    # What it talks to (providers, file formats, collectors): logic, drawn
    # with the domains, a package of its own so what it knows stays apart.
    "adapters": ("Adapters", "domains"),
}
DOMAINS = "domains"
# What a service keeps to itself: another service importing one reaches
# past its facade (service.py; its schemas and deps are public too).
INTERNALS = frozenset({DOMAINS, "adapters", "queries", "models"})


def is_health(word: str) -> bool:
    return word == "health" or word.startswith("health_")


def piece_of(word: str) -> tuple[str, str] | None:
    """The standard piece a top-level ``word`` names, its title and lane;
    None for anything else (a domain package, a loader, a loose module)."""
    return PIECES.get("health" if is_health(word) else word)


def _modules(index: Index, package: str) -> list[Module]:
    return [
        module
        for name in sorted(index.paths)
        if within(name, package) and (module := index.get(name)) is not None
    ]


def _execs(index: Index, module: Module) -> list[int]:
    """The lines ``module`` runs a query on: each ``.exec(`` call (parsed
    only where its text has one)."""
    if not any(".exec(" in line for line in module.lines):
        return []
    tree = index.tree(module.name)
    if tree is None:
        return []
    return sorted(
        {
            node.func.end_lineno or node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "exec"
        }
    )


def place_note(check: str, path: str, line: int, index: Index) -> str:
    """What one place a rule points at says: a file's size, for the size
    rule (its first line is no answer), else the line itself."""
    if check == f"{PARTS.key}.size":
        return size_note(path, index)
    return pattern_findings.text_at(index, path, line)


def _wired(index: Index, module: str, name: str) -> bool:
    """Whether code outside the tests reaches ``module``'s ``name``."""
    symbol = (module, name)
    start = source_index.definition(index, symbol)
    return any(
        place != start and not within(source_index.module_name(place.path), "tests")
        for place in source_index.references(index, symbol)
    )


@dataclass(eq=False)
class Folder:
    """A services folder as the pattern reads it, each answer worked out
    once a report."""

    subject: str  # its node in the system model: ``service:blog``
    name: str  # its folder in app/services
    held: bool  # a service of its own: held to the service rules
    index: Index
    routers: list[Module]  # its HTTP surface, in the API package
    tested: bool  # a test imports it
    services: dict[str, str | None]  # each folder's service; None: shared

    @property
    def service(self) -> str | None:
        return self.services.get(self.name)

    @property
    def package(self) -> str:
        return f"{SERVICE_PACKAGE}.{self.name}"

    def words(self, module: Module) -> list[str]:
        """A module's names below the folder: ``domains.chat.queries``."""
        return module.name.removeprefix(self.package).strip(".").split(".")

    @cached_property
    def modules(self) -> list[Module]:
        return _modules(self.index, self.package)

    @cached_property
    def named(self) -> frozenset[str]:
        """Every name its modules go by, at any depth."""
        return frozenset(w for m in self.modules for w in self.words(m))

    @cached_property
    def top(self) -> frozenset[str]:
        """The names at its top level: where the standard's files sit."""
        return frozenset(self.words(m)[0] for m in self.modules)

    @cached_property
    def has(self) -> dict[str, bool]:
        return {label: found(self) for label, (_, found) in HAS.items()}

    @cached_property
    def reads(self) -> list[str]:
        """Each ``.exec(`` outside a queries module (a loader's aside)."""
        return [
            f"{m.path}:{n}"
            for m in self.modules
            if not {"queries", *LOADERS} & set(self.words(m))
            for n in _execs(self.index, m)
        ]

    @cached_property
    def router_db(self) -> list[str]:
        """Each line a router queries on: ``.exec(``, or the ``select`` it
        imports from the database's library."""
        found = []
        for module in self.routers:
            imported, _ = module.imported.get("select", ("", None))
            uses = module.uses.get(("select",), ())
            selects = uses if imported.startswith(DATABASE) else ()
            lines = {*selects, *_execs(self.index, module)}
            found += [f"{module.path}:{n}" for n in sorted(lines)]
        return found

    @cached_property
    def loose(self) -> list[str]:
        """Each top-level module or package the standard does not name (a
        loader's aside): a subsystem, which lives under domains/."""
        return [
            f"{m.path}:1"
            for m in self.modules
            if len(words := self.words(m)) == 1
            and words[0] not in {"", DOMAINS, *LOADERS}
            and piece_of(words[0]) is None
        ]

    @cached_property
    def oversized(self) -> list[str]:
        """Each file past the size budget: over its cap, or most of its
        package."""
        over = {m.path for m in self.modules if len(m.lines) > cap_of(m.path)}
        found = over | set(dominant(self.modules))
        return [f"{path}:1" for path in sorted(found)]

    @cached_property
    def reaching(self) -> list[str]:
        """Each line importing another service's ``INTERNALS``: one line
        once, however many names it imports."""
        found = {
            (m.path, min(m.uses.get((local,), (1,))))
            for m in [*self.modules, *self.routers]
            for local, (source, member) in m.imported.items()
            if self._internal(f"{source}.{member}" if member else source)
        }
        order = {m.path: n for n, m in enumerate([*self.modules, *self.routers])}
        return [f"{p}:{n}" for p, n in sorted(found, key=lambda f: (order[f[0]], f[1]))]

    def _internal(self, module: str) -> bool:
        words = module.split(".")
        if self.service is None or words[:2] != ["app", "services"]:
            return False
        theirs = self.services.get(words[2]) if len(words) > 3 else None
        return theirs not in (None, self.service) and words[3] in INTERNALS

    @cached_property
    def unwired(self) -> list[str]:
        """Each job (``*_job``) in a ``jobs`` module nothing runs."""
        return [
            f"{m.path}:{function.start}"
            for m in self.modules
            if self.words(m)[-1] == "jobs"
            for function in m.functions
            if "." not in function.qualname
            and function.qualname.endswith("_job")
            and not _wired(self.index, m.name, function.qualname)
        ]


HAS: dict[str, tuple[str, Callable[[Folder], bool]]] = {
    ROUTER: ("api/<name>: its HTTP surface", lambda f: bool(f.routers)),
    "Facade": ("service.py: what callers import", lambda f: "service" in f.top),
    "Models": (
        "models: its tables",
        lambda f: f.name in MODELS_ELSEWHERE or "models" in f.named,
    ),
    "Queries": (
        "queries: every read (none needed with nothing read)",
        lambda f: "queries" in f.named or not f.reads,
    ),
    "Jobs": (
        "jobs: scheduled work",
        lambda f: not f.named.isdisjoint({"jobs", "scheduled_jobs"}),
    ),
    "Health": (
        "health: its check",
        lambda f: any(is_health(w) for w in f.top),
    ),
    "Tests": ("a test that imports it", lambda f: f.tested),
}

# The parts every service is expected to have (Queries once it reads, by
# its check): a missing one is a gap, its instance's ``missed``. The rest
# are inventory: a service with no scheduled work lacks no jobs.
EXPECTED = frozenset({"Facade", "Queries", "Health", "Tests"})


def _imported(tested: Iterable[str], package: str) -> bool:
    return any(within(name, package) for name in tested)


def _service_of(subject: str) -> str | None:
    """The service a folder's node is part of: ``service:ai.rag`` is the
    AI service's; shared code is none."""
    kind, name = parse_node_id(subject)
    return name.partition(".")[0] if kind is Kind.SERVICE else None


def folders(source: Any = None) -> list[tuple[str, Folder]]:
    """Each services folder that is a part of the system model. ``source``
    may be another project's root (tests): each folder there a service,
    its router the API package of its name."""
    if isinstance(source, Path):
        index = source_index.at(source)
        tested = index.imports_under("tests")
        names = index.packages_in(SERVICE_PACKAGE)
        found = [
            Folder(
                node_id(Kind.SERVICE, name),
                name,
                True,
                index,
                _modules(index, f"{API_PACKAGE}.{name}"),
                _imported(tested, f"{SERVICE_PACKAGE}.{name}"),
                {other: other for other in names},
            )
            for name in names
        ]
        return [(f.subject, f) for f in found]
    index = source_index.project()
    nodes = {n.id: n for n in current().nodes}
    tested = index.imports_under("tests")
    api = [
        (m, node_of(m.name, index, set(nodes))) for m in _modules(index, API_PACKAGE)
    ]
    named = service_folders(index, set(nodes))
    services = {name: _service_of(subject) for name, subject in named}
    found = [
        Folder(
            subject,
            name,
            nodes[subject].kind is Kind.SERVICE and nodes[subject].owner is None,
            index,
            [m for m, owner in api if owner == subject],
            _imported(tested, f"{SERVICE_PACKAGE}.{name}"),
            services,
        )
        for name, subject in named
    ]
    return [(f.subject, f) for f in found]


@cache
def report() -> Report:
    """This project's parts report, built once a process (Overseer's page
    and map share it): the code it reads changes only by a reload, which
    starts a new one."""
    return patterns.report(PARTS)


def _layout(f: Folder) -> SourceText:
    """Its modules, as the canonical example shows them: copy the layout."""
    paths = [m.path for m in [*f.modules, *f.routers]]
    return SourceText("\n".join(paths), f.index.paths[f.package])


def _part(label: str) -> Callable[[Folder], bool]:
    return lambda f: f.has[label]


def _not_held(f: Folder) -> bool:
    return not f.held


PARTS = Pattern(
    key="parts",
    title="Service parts",
    summary=(
        "Each service against the service standard: the parts it has (a "
        "router, a service.py facade, models, queries, jobs, a health check, "
        "tests) and the rules it breaks. Optional parts are counted, not failed."
    ),
    steps=tuple(
        Step(
            label,
            detail,
            applies=lambda f: f.held,
            follows=_part(label),
            expected=label in EXPECTED,
        )
        for label, (detail, _) in HAS.items()
    ),
    rules=(
        Rule(
            "reads-in-queries",
            "Reads live in queries",
            "Reads belong to a package's queries module; domain modules own "
            "writes and orchestration. A .exec( anywhere else is a read the "
            "next N+1 audit cannot find.",
            lambda f: not f.reads,
            enforced=True,
            evidence=lambda f: f.reads,
            action="Move each read into the package's queries module.",
        ),
        Rule(
            "jobs-wired",
            "Every job is wired",
            "A job function no JOBS list and no caller reaches never runs: "
            "built, tested, and silently not scheduled.",
            lambda f: not f.unwired,
            enforced=True,
            evidence=lambda f: f.unwired,
            action="Add it to JOBS, or delete it.",
        ),
        Rule(
            "router-no-db",
            "Routers leave the database to the service",
            "A router that queries takes the read out of reach of the service's "
            "other callers (jobs, tasks, the CLI) and of the queries module.",
            lambda f: not f.router_db,
            evidence=lambda f: f.router_db,
            action="Move the query into the service and call it from the router.",
        ),
        Rule(
            "has-health",
            "Has a health check",
            "Overseer and the health endpoint only see what checks in: a "
            "service with no health check fails without a word.",
            _part("Health"),
            exempt=_not_held,
            enforced=True,
            action="Add a health.py and register its check.",
        ),
        Rule(
            "has-tests",
            "Has tests",
            "No test imports it: a change to it is checked by nothing.",
            _part("Tests"),
            exempt=_not_held,
            action="Add a test that imports and exercises it.",
        ),
        Rule(
            "domains",
            "Logic lives in domains",
            "The standard names a service's top-level files; any other module "
            "is a subsystem, and goes in a package under domains/, where every "
            "service keeps them and the next reader looks.",
            lambda f: not f.loose,
            exempt=_not_held,
            evidence=lambda f: f.loose,
            action=(
                "Move it into a package under domains/, named for what it owns, "
                "or under adapters/ if it is something the service talks to."
            ),
        ),
        Rule(
            "size",
            "Files stay readable",
            f"A file is what an agent loads whole: past {LOGIC_LINES} lines "
            f"({DECLARATION_LINES} for models, schemas and other lists) it pages "
            "instead, and one file holding most of its package is a god module "
            "wearing a folder.",
            lambda f: not f.oversized,
            evidence=lambda f: f.oversized,
            action="Move some of its classes or functions into new files beside it.",
        ),
        Rule(
            "through-facade",
            "Other services through their facade",
            "A service that imports another's domains, adapters, queries or "
            "models depends on how that one is organised, not on what it "
            "offers: a refactor inside it breaks a service it never knew of.",
            lambda f: not f.reaching,
            evidence=lambda f: f.reaching,
            action=(
                "Call what you need through the other service's service.py, "
                "adding it there if it is missing."
            ),
        ),
        Rule(
            "facade",
            "Has a service.py facade",
            "Callers import one module (service.py, or a service/ package) "
            "rather than reaching into its internals.",
            _part("Facade"),
            exempt=_not_held,
            action="Add a service.py that the routers and jobs call.",
        ),
    ),
    discover=folders,
    function=_layout,
    rank=lambda f: (sum(f.has.values()), f.name),
    subject=lambda f: f.subject,
    exemptions=(
        ("Seeds and fixtures", LOADERS_WHY),
        *((f"{name}'s models", why) for name, why in MODELS_ELSEWHERE.items()),
    ),
)
