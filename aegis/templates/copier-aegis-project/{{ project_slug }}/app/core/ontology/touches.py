"""What a change touches, read from the system model (``touched``): each
changed file to the part owning it, the parts that depend on those, and
the tables, routes and jobs its files define. A path may be a project's
(``app/...``) or its template's (``.../{{ project_slug }}/app/...py.jinja``).

Static structure only: a CI checkout has no traffic, so what the running
app was seen doing is not in it."""

from collections.abc import Callable, Iterable

from pydantic import BaseModel, ConfigDict

from app.core import source_index
from app.core.ontology.model import EdgeKind, Kind, SystemModel
from app.core.ontology.parts import node_of

# The edges along which a change reaches another part: what it needs, what
# it calls, what holds it.
REACHES = frozenset({EdgeKind.DEPENDS_ON, EdgeKind.CALLS, EdgeKind.CONTAINS})
ROOTS = ("app", "tests")


class Touched(BaseModel):
    """The parts a change touches and what reaches them, each by node id."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parts: tuple[str, ...]  # owning a changed file
    dependents: tuple[str, ...]  # depending on one of them, untouched
    tables: tuple[str, ...]
    routes: tuple[str, ...]
    jobs: tuple[str, ...]
    elsewhere: tuple[str, ...]  # changed files no part owns


def module_of(path: str) -> str | None:
    """A changed file's module, from its ``app`` (or ``tests``) folder on:
    ``app.core.db``; None outside both."""
    parts = path.removesuffix(".jinja").split("/")
    at = next((i for i, part in enumerate(parts) if part in ROOTS), None)
    return None if at is None else source_index.module_name("/".join(parts[at:]))


def touched(
    model: SystemModel,
    paths: Iterable[str],
    owner_of: Callable[[str], str | None] | None = None,
) -> Touched:
    """What changing ``paths`` touches in ``model``. ``owner_of`` gives a
    module's part (``ownership``'s rule over this project's source)."""
    found = {n.id: n for n in model.nodes}
    owner_of = owner_of or _owners(set(found))
    modules = {path: module_of(path) for path in paths}
    owned = {path: owner_of(m) if m else None for path, m in modules.items()}
    parts = {part for part in owned.values() if part}
    held = parts | {o for p in parts if (o := found[p].owner)}

    def defined(kind: Kind) -> tuple[str, ...]:
        changed = set(modules.values()) - {None}
        return tuple(
            sorted(
                n.id
                for n in model.nodes
                if n.kind is kind and getattr(n, "module", None) in changed
            )
        )

    return Touched(
        parts=tuple(sorted(parts)),
        dependents=tuple(
            sorted(
                {
                    e.source
                    for e in model.edges
                    if e.kind in REACHES and e.target in held and e.source not in parts
                }
            )
        ),
        tables=defined(Kind.OBJECT),
        routes=defined(Kind.ROUTE),
        jobs=defined(Kind.JOB),
        elsewhere=tuple(path for path, part in owned.items() if part is None),
    )


def _owners(ids: set[str]) -> Callable[[str], str | None]:
    index = source_index.project()
    return lambda module: node_of(module, index, ids)


def summary(found: Touched) -> str:
    """``found`` as Markdown: a pull request's job summary."""
    rows = (
        ("Parts", found.parts),
        ("Depended on by", found.dependents),
        ("Tables", found.tables),
        ("Routes", found.routes),
        ("Jobs", found.jobs),
    )
    lines = [
        f"- **{label}:** {', '.join(f'`{i}`' for i in ids)}"
        for label, ids in rows
        if ids
    ]
    if found.elsewhere:
        count = len(found.elsewhere)
        lines.append(f"- **In no part:** {count} file{'' if count == 1 else 's'}")
    return "\n".join(["### What this change touches", "", *lines, ""])
