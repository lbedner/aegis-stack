"""The project's Python source as an index of names, read with ``ast``
rather than imported (no side effects): where each module defines its
top-level names, what it imports, and the lines each name is used on.
Overseer > Code goes from a name to its definition and lists every line
that names it.

Static and shallow on purpose: a name defined at a module's top level, or
imported, resolves, directly or through its module (``store.put``); one
reached through an object (``self.store.put``) or made at runtime does
not. ponytail: jedi or a language server when method calls must resolve.
"""

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

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
class Module:
    """What one file says about names: kept small (no syntax tree), since
    every file the lookups reach stays cached."""

    path: str
    name: str
    lines: tuple[str, ...]
    defined: dict[str, int]  # top-level name -> its line
    imported: dict[str, Symbol]  # local name -> (module, member or None)
    uses: dict[Chain, tuple[int, ...]]  # each name as written -> its lines

    def place(self, line: int) -> Place:
        return Place(self.path, line, self.lines[line - 1].strip())


def module_name(path: str) -> str:
    """``app/core/store.py`` -> ``app.core.store``; a package's
    ``__init__.py`` is the package."""
    parts = path.removesuffix(".py").split("/")
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _target(node: ast.ImportFrom, name: str) -> str:
    """The module an ``from ... import`` reads from, relative ones
    resolved against the importing module ``name``."""
    if not node.level:
        return node.module or ""
    package = name.split(".")[: -node.level]
    return ".".join([*package, *([node.module] if node.module else [])])


def _spans(tree: ast.Module) -> Iterator[tuple[Named, Chain]]:
    """Every name in ``tree`` with the chain it ends: ``store.put`` is
    ``("store", "put")``; an import's name too."""
    for node in ast.walk(tree):
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
    imported: dict[str, Symbol] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                imported[local] = (alias.name if alias.asname else local, None)
        elif isinstance(node, ast.ImportFrom):
            source_module = _target(node, name)
            for alias in node.names:
                imported[alias.asname or alias.name] = (source_module, alias.name)
    uses: dict[Chain, set[int]] = {}
    for node, chain in _spans(tree):
        uses.setdefault(chain, set()).add(node.lineno)
    return Module(
        path,
        name,
        tuple(source.splitlines()),
        defined,
        imported,
        {chain: tuple(sorted(lines)) for chain, lines in uses.items()},
    )


@lru_cache(maxsize=2048)
def _text(root: Path, path: str, mtime: float) -> str:
    """``path``'s source; ``mtime`` keys the cache, so a change reads it again."""
    return (root / path).read_text(encoding="utf-8", errors="replace")


@lru_cache(maxsize=2048)
def _cached(root: Path, path: str, mtime: float) -> Module | None:
    """``path`` parsed, once per change (``mtime``)."""
    try:
        return _parse(path, _text(root, path, mtime))
    except (OSError, SyntaxError, ValueError):
        return None  # unreadable or not valid Python: no names to offer


class Index:
    """The project's modules by name, each parsed only when a lookup reaches
    it, and again only once its file changes: a click reads a handful of
    files, not the project. Each file is looked at (``stat``) once."""

    def __init__(self, root: Path, paths: list[str]) -> None:
        self.root = root
        self.paths = {module_name(path): path for path in paths}
        self._mtimes: dict[str, float | None] = {}

    def __contains__(self, name: object) -> bool:
        return name in self.paths

    def _mtime(self, path: str) -> float | None:
        if path not in self._mtimes:
            try:
                self._mtimes[path] = (self.root / path).stat().st_mtime
            except OSError:
                self._mtimes[path] = None
        return self._mtimes[path]

    def get(self, name: str) -> Module | None:
        path = self.paths.get(name)
        mtime = self._mtime(path) if path else None
        return (
            None if path is None or mtime is None else _cached(self.root, path, mtime)
        )

    def tree(self, name: str) -> ast.Module | None:
        """A module's syntax tree, parsed afresh: only the clicked file needs one."""
        path = self.paths.get(name)
        mtime = self._mtime(path) if path else None
        if path is None or mtime is None:
            return None
        try:
            return ast.parse(_text(self.root, path, mtime))
        except (OSError, SyntaxError, ValueError):
            return None

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

    def naming(self, word: str) -> Iterator[Module]:
        """The modules whose source has ``word`` in it, the only ones a
        reference to it can be in."""
        for name, text in self._texts():
            if word in text and (module := self.get(name)) is not None:
                yield module


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
    tree: ast.Module, lines: tuple[str, ...], name: str, line: int, col: int
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
                return Hit(module=_target(node, name))
    for node, chain in _spans(tree):
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
    hit = _at(tree, module.lines, name, line, col) if module and tree else None
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
