"""The project's Python source as an index of names, read with ``ast``
rather than imported (no side effects): where each module defines its
top-level names, what it imports, and the lines each name is used on.
Overseer > Code goes from a name to its definition and lists every line
that names it; the Server map, the load costs, the Service pattern and
``ownership`` read what each module imports, declares (``Declared``) and
defines, and its docstring's first paragraph. Each file is parsed once per
change, whoever asks.

Static and shallow on purpose: a name defined at a module's top level, or
imported, resolves, directly or through its module (``store.put``); one
reached through an object (``self.store.put``) or made at runtime does
not. ponytail: jedi or a language server when method calls must resolve.
"""

import ast
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, fields
from enum import StrEnum
from functools import cache, lru_cache
from importlib.util import resolve_name
import os
from pathlib import Path
from typing import TypeVar

from app.core.constants import ComponentName, ServiceName
from app.core.parts import Category
from app.core.source_functions import Function, functions

ROOT = Path(__file__).resolve().parents[2]  # the project's: where ``app`` is
# The enums a ``Declared`` constant may name a member of.
DECLARED_IN: dict[str, type[StrEnum]] = {
    e.__name__: e for e in (ComponentName, ServiceName, Category)
}
# Folders never read, nor shown on Overseer > Code: generated, installed or
# holding data (hidden ones, ``.venv`` among them, never either).
SKIPPED = frozenset(
    {"__pycache__", "node_modules", "site-packages", "dist", "build", "data", "site"}
)

# A name's identity: its module (dotted), and the member it names there;
# None names the module itself.
Symbol = tuple[str, str | None]
# A name as written: ``put``, or ``store.put`` through its module.
Chain = tuple[str, ...]
# How far a name may be re-exported (imported to be imported again).
MAX_HOPS = 10
# A node that names something, with its position.
Named = ast.Name | ast.Attribute | ast.alias


@dataclass(frozen=True)
class Place:
    """A line of the source: the file, from the project's root, and the line."""

    path: str
    line: int
    text: str


@dataclass(frozen=True)
class Declared:
    """What a module says it is, read without importing it: the component
    a core client fronts (``FRONTS``), the part a folder belongs to
    (``PART_OF``, for ``ownership``), and a plugin's concern
    (``CATEGORY``). Each a string or a member of one of ``DECLARED_IN``."""

    fronts: str | None = None
    part_of: str | None = None
    category: str | None = None


# The constants themselves, as a module spells them.
DECLARED = frozenset(f.name.upper() for f in fields(Declared))


@dataclass(frozen=True)
class Module:
    """What one file says about names: kept small (no syntax tree), since
    every file the lookups reach stays cached."""

    path: str
    name: str
    lines: tuple[str, ...]
    defined: dict[str, int]  # top-level name -> its line
    imported: dict[str, Symbol]  # local name -> (module, member or None)
    uses: dict[Chain, tuple[int, ...]]  # each name as written -> its lines
    # Every module it imports, relative, lazy and TYPE_CHECKING ones too, and
    # each name imported from one by its full name (``from app.core import
    # cache`` is ``app.core.cache``), whether a module or not.
    imports: frozenset[str]
    declared: Declared
    functions: tuple[Function, ...]
    summary: str  # its docstring's first paragraph, on one line
    classes: frozenset[str]  # its top-level classes

    @property
    def public(self) -> list[str]:
        """Its top-level functions and classes not named private, in the
        order it defines them."""
        tops = {f.qualname for f in self.functions} | self.classes
        return [n for n in self.defined if n in tops and not n.startswith("_")]

    def place(self, line: int) -> Place:
        return Place(self.path, line, self.lines[line - 1].strip())


def module_name(path: str) -> str:
    """``app/core/store.py`` -> ``app.core.store``; a package's
    ``__init__.py`` is the package."""
    parts = path.removesuffix(".py").split("/")
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def module_paths(name: str) -> tuple[str, str]:
    """``module_name`` the other way: the files ``app.core.store`` can be,
    a module's own or its package's ``__init__.py``."""
    base = name.replace(".", "/")
    return f"{base}.py", f"{base}/__init__.py"


def _target(node: ast.ImportFrom, path: str) -> str:
    """The module an ``from ... import`` reads from, relative ones resolved
    against the importing file's package (an ``__init__.py`` its own)."""
    if not node.level:
        return node.module or ""
    package = module_name(path)
    if not path.endswith("__init__.py"):
        package = package.rpartition(".")[0]
    try:
        return resolve_name("." * node.level + (node.module or ""), package)
    except ImportError:
        return ""  # above the project's top package


def _spans(nodes: Iterable[ast.AST]) -> Iterator[tuple[Named, Chain]]:
    """Every name in ``nodes`` (a tree, walked) with the chain it ends:
    ``store.put`` is ``("store", "put")``; an import's name too."""
    for node in nodes:
        if isinstance(node, ast.Name):
            yield node, (node.id,)
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            yield node, (node.value.id, node.attr)
        elif isinstance(node, ast.alias):
            yield node, (node.asname or node.name.split(".")[0],)


def _parse(path: str, source: str) -> Module:
    tree = ast.parse(source)
    name = module_name(path)
    defined: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            defined[node.name] = node.lineno
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            defined.update(
                {t.id: node.lineno for t in targets if isinstance(t, ast.Name)}
            )
    nodes = list(ast.walk(tree))  # walked once, for imports and for names
    imported: dict[str, Symbol] = {}
    imports: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                imported[local] = (alias.name if alias.asname else local, None)
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            source_module = _target(node, path)
            imports.add(source_module)
            for alias in node.names:
                imported[alias.asname or alias.name] = (source_module, alias.name)
                if alias.name != "*":
                    imports.add(f"{source_module}.{alias.name}")
    uses: dict[Chain, set[int]] = {}
    for node, chain in _spans(nodes):
        uses.setdefault(chain, set()).add(node.lineno)
    lines = tuple(source.splitlines())
    return Module(
        path,
        name,
        lines,
        defined,
        imported,
        {chain: tuple(sorted(lines)) for chain, lines in uses.items()},
        frozenset(imports - {""}),
        _declared(tree),
        tuple(functions(tree, lines)),
        " ".join((ast.get_docstring(tree) or "").partition("\n\n")[0].split()),
        frozenset(n.name for n in tree.body if isinstance(n, ast.ClassDef)),
    )


def _value(node: ast.expr) -> str | None:
    """A string as written, or a ``DECLARED_IN`` enum member's value."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        names = DECLARED_IN.get(node.value.id)
        if names is not None and node.attr in names.__members__:
            return names[node.attr].value
    return None


def _declared(tree: ast.Module) -> Declared:
    """What the module's top-level ``FRONTS``, ``PART_OF`` and
    ``CATEGORY`` say."""
    found: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and (value := _value(node.value)):
            found |= {
                t.id.lower(): value
                for t in node.targets
                if isinstance(t, ast.Name) and t.id in DECLARED
            }
    return Declared(**found)


Kept = TypeVar("Kept")
# Each file's source and what it says, as of its last change: one entry a
# file, replaced when the file changes, so as many as there are files.
_texts: dict[tuple[Path, str], tuple[float, str]] = {}
_modules: dict[tuple[Path, str], tuple[float, Module | None]] = {}


def _kept(
    store: dict[tuple[Path, str], tuple[float, Kept]],
    key: tuple[Path, str],
    mtime: float,
    make: Callable[[], Kept],
) -> Kept:
    found = store.get(key)
    if found is None or found[0] != mtime:
        found = store[key] = (mtime, make())
    return found[1]


def _text(root: Path, path: str, mtime: float) -> str:
    """``path``'s source, read again only once it changes (``mtime``)."""
    return _kept(
        _texts,
        (root, path),
        mtime,
        lambda: (root / path).read_text(encoding="utf-8", errors="replace"),
    )


def _cached(root: Path, path: str, mtime: float) -> Module | None:
    """``path`` parsed, once per change (``mtime``)."""

    def parse() -> Module | None:
        try:
            return _parse(path, _text(root, path, mtime))
        except (OSError, SyntaxError, ValueError):
            return None  # unreadable or not valid Python: no names to offer

    return _kept(_modules, (root, path), mtime, parse)


@lru_cache(maxsize=256)
def _tree(root: Path, path: str, mtime: float) -> ast.Module | None:
    """``path``'s syntax tree, once per change: only the files read lately."""
    try:
        return ast.parse(_text(root, path, mtime))
    except (OSError, SyntaxError, ValueError):
        return None


class Index:
    """The project's modules by name, each parsed only when a lookup reaches
    it, and again only once its file changes: a click reads a handful of
    files, not the project."""

    def __init__(self, root: Path, paths: list[str]) -> None:
        self.root = root
        self.paths = {module_name(path): path for path in paths}

    def __contains__(self, name: object) -> bool:
        return name in self.paths

    def _mtime(self, path: str) -> float | None:
        try:
            return (self.root / path).stat().st_mtime
        except OSError:
            return None

    def _stamp(self, name: str) -> tuple[str, float] | None:
        """A module's file and when it last changed, while it is there."""
        path = self.paths.get(name)
        mtime = self._mtime(path) if path else None
        return None if path is None or mtime is None else (path, mtime)

    def get(self, name: str) -> Module | None:
        stamp = self._stamp(name)
        return _cached(self.root, *stamp) if stamp else None

    def tree(self, name: str) -> ast.Module | None:
        """A module's syntax tree (``_tree``), for a reader that leaves it be."""
        stamp = self._stamp(name)
        return _tree(self.root, *stamp) if stamp else None

    def _texts(self) -> Iterator[tuple[str, str]]:
        """Each module's name and source; one gone or unreadable is skipped."""
        for name, path in self.paths.items():
            if (mtime := self._mtime(path)) is None:
                continue
            try:
                text = _text(self.root, path, mtime)
            except OSError:
                continue
            yield name, text

    def warm(self) -> None:
        """Read every file now, ahead of the first ``naming``, which reads
        them all: the reads, not the parsing, are most of a cold click."""
        for _ in self._texts():
            pass

    def packages_in(self, package: str) -> list[str]:
        """The packages directly in ``package`` (``app.services``), by
        name: the services, or the components."""
        depth = package.count(".") + 1
        return sorted(
            name.rpartition(".")[2]
            for name, path in self.paths.items()
            if within(name, package)
            and name.count(".") == depth
            and path.endswith("/__init__.py")
        )

    def imports_under(self, package: str) -> set[str]:
        """Every module ``package``'s modules import, it and those in it."""
        found: set[str] = set()
        for name in self.paths:
            if within(name, package):
                module = self.get(name)
                found |= module.imports if module else set()
        return found

    def naming(self, word: str) -> Iterator[Module]:
        """The modules whose source has ``word`` in it, the only ones a
        reference to it can be in."""
        for name, text in self._texts():
            if word in text and (module := self.get(name)) is not None:
                yield module


def within(module: str, package: str) -> bool:
    """Whether ``module`` is ``package`` or in it."""
    return module == package or module.startswith(f"{package}.")


def at(root: Path, folder: str = "") -> Index:
    """The Python files under ``root``'s ``folder`` (all of ``root``, given
    none), named from ``root``; hidden and ``SKIPPED`` folders left out."""
    paths = []
    for here, folders, names in os.walk(root / folder):
        folders[:] = [f for f in folders if not f.startswith(".") and f not in SKIPPED]
        base = Path(here).relative_to(root).as_posix()
        paths += [
            n if base == "." else f"{base}/{n}" for n in names if n.endswith(".py")
        ]
    return Index(root, paths)


@cache
def project() -> Index:
    """This project's Python files, listed once per process (each one is
    still read again once it changes). ponytail: a file added since is not
    in it; list again per ask if a reader ever needs new files live."""
    return at(ROOT)


def resolve(modules: Index, module: str, name: str) -> Symbol | None:
    """What ``name`` means in ``module``: defined there, or imported (and
    followed through re-exports); a module it names, if a project one."""
    for _ in range(MAX_HOPS):
        found = modules.get(module)
        if found is None:
            return None
        if name in found.defined:
            return (module, name)
        if name not in found.imported:
            return None
        target, member = found.imported[name]
        if member is None:
            return (target, None) if target in modules else None
        if f"{target}.{member}" in modules:  # ``from app.core import store``
            return (f"{target}.{member}", None)
        module, name = target, member
    return None


def _meaning(modules: Index, module: str, chain: Chain) -> Symbol | None:
    """What ``chain`` means in ``module``: ``store.put`` through its module."""
    found = resolve(modules, module, chain[0])
    if len(chain) == 2:
        return (
            resolve(modules, found[0], chain[1]) if found and found[1] is None else None
        )
    return found


def definition(modules: Index, symbol: Symbol) -> Place | None:
    module, member = symbol
    found = modules.get(module)
    if found is None:
        return None
    line = 1 if member is None else found.defined.get(member)
    return found.place(line) if line and found.lines else None


@dataclass(frozen=True)
class Hit:
    """What a click landed on: a name as written, or a module named by
    ``from ... import``."""

    chain: Chain = ()
    module: str = ""


def _at(
    tree: ast.Module, lines: tuple[str, ...], path: str, line: int, col: int
) -> Hit | None:
    """What is at ``line``:``col`` (1-based line, 0-based column)."""
    for node in ast.walk(tree):
        defines = isinstance(
            node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
        )
        if defines and node.lineno == line:
            start = lines[line - 1].find(node.name, node.col_offset)
            if start <= col < start + len(node.name):
                return Hit((node.name,))
        if isinstance(node, ast.ImportFrom) and node.lineno == line and node.module:
            start = lines[line - 1].find(node.module)
            if start <= col < start + len(node.module):
                return Hit(module=_target(node, path))
    for node, chain in _spans(ast.walk(tree)):
        if node.lineno != line:
            continue
        end = node.end_col_offset or 0
        if isinstance(node, ast.Attribute):
            if end - len(node.attr) <= col < end:
                return Hit(chain)
            if node.value.col_offset <= col < (node.value.end_col_offset or 0):
                return Hit(chain[:1])
        elif node.col_offset <= col < end:
            return Hit(chain)
    return None


def symbol_at(
    modules: Index, path: str, line: int, col: int
) -> tuple[str, Symbol | None] | None:
    """The name clicked at ``line``:``col`` of ``path`` and what it is, or
    None when no name is there."""
    name = module_name(path)
    module, tree = modules.get(name), modules.tree(name)
    hit = _at(tree, module.lines, path, line, col) if module and tree else None
    if hit is None:
        return None
    if hit.module:
        return hit.module, ((hit.module, None) if hit.module in modules else None)
    return ".".join(hit.chain), _meaning(modules, name, hit.chain)


def _may_name(module: Module, chain: Chain, word: str) -> bool:
    """Whether ``chain`` can name something called ``word``: it says the
    word, or starts with a name imported as it (``put as p``, or a module
    ``...store``). Only these are worth resolving."""
    head = module.imported.get(chain[0])
    return word in chain or (
        head is not None and word in (head[1], head[0].rpartition(".")[2])
    )


def references(modules: Index, symbol: Symbol) -> list[Place]:
    """Every line naming ``symbol``: its definition, the imports of it, and
    each use, directly or through its module. Only modules whose source
    has its name are read, and each one's names are looked up, not walked."""
    module, member = symbol
    word = member or module.rpartition(".")[2]
    places = set()
    for found in modules.naming(word):
        for chain, lines in found.uses.items():
            if (
                _may_name(found, chain, word)
                and _meaning(modules, found.name, chain) == symbol
            ):
                places.update(found.place(line) for line in lines)
    if (start := definition(modules, symbol)) and member is not None:
        places.add(start)
    return sorted(places, key=lambda p: (p.path, p.line))
