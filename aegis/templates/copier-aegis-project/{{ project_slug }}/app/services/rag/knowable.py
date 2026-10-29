"""What of this app a knowledge base can know, so nobody types a path: each
part (the twin knows which files it owns, templates and stylesheets as
much as code) and the project's docs, with the files of each the loader
can read, by extension, the way ee-toolset's GitHub source offered a
repo's file types. Blocking (a walk of the project): off the loop."""

from collections.abc import Collection
from pathlib import PurePosixPath

from pydantic import BaseModel

from app.core import source_index
from app.core.config import settings
from app.core.ontology import current
from app.core.ontology.model import Kind, PartNode
from app.core.ontology.touches import parts_of
from app.services.rag.loaders import (
    DEFAULT_EXCLUDE_PATTERNS,
    DEFAULT_EXTENSIONS,
    LOADER_MAP,
    excluded,
)

DOCS = "docs"  # the project's own documentation, known beside its parts
# The kinds of part, then of file, in the order a picker shows them.
GROUPS = (
    (Kind.SERVICE, "Services"),
    (Kind.COMPONENT, "Components"),
    (Kind.SHARED, "Shared code"),
)
TYPES = {
    "code": "Code",
    "web": "Web",
    "config": "Config",
    "data": "Data",
    "documentation": "Docs",
    "script": "Scripts",
}


class Knowable(BaseModel):
    """The picker: parts grouped by kind (id, name, what it is), the file
    types found grouped by what they are, each pick's files and bytes by
    extension (what its total sums), the extensions ticked at first, and
    every one the loader reads (what an upload may be); and whose code it is
    and where it is read from, so nobody wonders which folder that is."""

    parts: list[tuple[str, list[tuple[str, str, str]]]]
    types: list[tuple[str, list[str]]]
    held: dict[str, dict[str, tuple[int, int]]]
    ticked: list[str]
    readable: list[str] = sorted(LOADER_MAP)  # what an upload may be
    app: str = settings.PROJECT_NAME  # whose code: this app's name
    root: str = str(source_index.ROOT)  # where it is read from: its folder


def knowable() -> Knowable:
    """What this app offers to be known, and how much of it there is."""
    found = _readable()
    held: dict[str, dict[str, list[int]]] = {}
    for path, pick in found.items():
        ext = PurePosixPath(path).suffix.lower()
        counted = held.setdefault(pick, {}).setdefault(ext, [0, 0])
        counted[0] += 1
        counted[1] += (source_index.ROOT / path).stat().st_size
    present = sorted({ext for exts in held.values() for ext in exts})
    return Knowable(
        parts=_parts(set(held)),
        types=[
            (label, [e for e in present if LOADER_MAP[e]["type"] == kind])
            for kind, label in TYPES.items()
            if any(LOADER_MAP[e]["type"] == kind for e in present)
        ],
        held=held,  # each [files, bytes], read as a pair
        ticked=[e for e in DEFAULT_EXTENSIONS if e in present],
    )


def paths_of(
    picked: Collection[str],
    extensions: Collection[str],
    exclude: list[str] | None = None,
) -> list[str]:
    """The files knowing ``picked`` (parts, the docs) reads, of
    ``extensions``, leaving out ``exclude`` (globs, in place of the
    loader's own): absolute paths."""
    return [
        str(source_index.ROOT / path)
        for path, pick in _readable(exclude, extensions).items()
        if pick in picked
    ]


def _parts(holding: set[str]) -> list[tuple[str, list[tuple[str, str, str]]]]:
    """Each part holding a readable file, grouped by kind and by name, then
    the docs."""
    parts = sorted(
        (n for n in current().nodes if isinstance(n, PartNode) and n.id in holding),
        key=lambda n: n.name,
    )
    named = [(n.kind, (n.id, n.name.replace("_", " "), n.description)) for n in parts]
    groups = [
        (label, [pick for of, pick in named if of is kind]) for kind, label in GROUPS
    ]
    if DOCS in holding:
        groups.append(("Docs", [(DOCS, "docs", "The project's documentation")]))
    return [(label, picks) for label, picks in groups if picks]


def _readable(
    exclude: list[str] | None = None, extensions: Collection[str] = LOADER_MAP
) -> dict[str, str]:
    """Each file of ``extensions`` (every type the loader reads, given
    none), not excluded, under ``app`` and ``docs``, from the project's
    root, to its pick: its part, or the docs. Filtered before the twin is
    asked who owns each."""
    patterns = exclude or DEFAULT_EXCLUDE_PATTERNS

    def reads(path: str) -> bool:
        found = PurePosixPath(path)
        return found.suffix.lower() in extensions and not excluded(found, patterns)

    root = source_index.ROOT
    found = parts_of(current(), [p for p in source_index.walk(root, "app") if reads(p)])
    found.update({p: DOCS for p in source_index.walk(root, DOCS) if reads(p)})
    return found
