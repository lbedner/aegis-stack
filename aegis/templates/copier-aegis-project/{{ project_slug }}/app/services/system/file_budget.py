"""The size budget, as the parts pattern's "size" rule holds a service to
it: a file's line cap, a file holding most of its package, and what makes
one too big, said."""

from app.core import source_index
from app.core.source_index import Index, Module

# The size budget (the "size" rule; the framework's own, held on its
# templates by its tests). A list (DECLARATIONS) is grepped, not read.
LOGIC_LINES = 500
DECLARATION_LINES = 900
DECLARATIONS = ("models", "schemas", "i18n", "seeds", "fixtures", "locales")
SHARE = 0.4
SHARE_LINES = 400


def cap_of(path: str) -> int:
    """A file's line budget: a list's (a ``DECLARATIONS`` folder, a file
    named one or ending ``_<one>``) or logic's."""
    *folders, file = path.split("/")
    stem = file.removesuffix(".py")
    listed = any(
        part in folders or stem == part or stem.endswith(f"_{part}")
        for part in DECLARATIONS
    )
    return DECLARATION_LINES if listed else LOGIC_LINES


def dominant(modules: list[Module]) -> list[str]:
    """Each package's largest file, where past ``SHARE`` of a package of
    three or more and ``SHARE_LINES`` long."""
    packages: dict[str, list[tuple[int, str]]] = {}
    for m in modules:
        packages.setdefault(m.path.rpartition("/")[0], []).append(
            (len(m.lines), m.path)
        )
    found = []
    for members in packages.values():
        lines, path = max(members)
        total = sum(n for n, _ in members)
        if len(members) >= 3 and lines > SHARE_LINES and lines / total > SHARE:
            found.append(path)
    return found


def size_note(path: str, index: Index) -> str:
    """What makes a file too big, said: ``612 lines; the limit is 500``,
    or, under its cap, its share of its folder (``dominant``)."""
    module = index.get(source_index.module_name(path))
    lines = len(module.lines) if module else 0
    if lines > (cap := cap_of(path)):
        return f"{lines:,} lines; the limit is {cap:,}"
    folder = path.rpartition("/")[0]
    package = [
        found
        for name, other in index.paths.items()
        if other.rpartition("/")[0] == folder and (found := index.get(name))
    ]
    total = sum(len(m.lines) for m in package)
    return f"{lines:,} of the {total:,} lines in its folder: too much for one file"
