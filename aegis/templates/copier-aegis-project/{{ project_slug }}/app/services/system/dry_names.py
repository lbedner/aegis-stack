"""What a name means in the code a dry path walks (``dry_walk``): a
function, class or module, reached by name, through a module or class,
or as a method of a typed instance (``self``, a typed local, an attribute
of one, what a call makes or says it returns); a task by its registered
name; the callables in a registry. Project code only: a library's name
means nothing here."""

import ast
from collections.abc import Mapping
from dataclasses import dataclass, field
import inspect
import sys

from app.core.ontology.model import Mode
from app.core.source_index import Index, Module, Symbol, resolve, within
from app.core.source_members import Def, Source, assigned

SELF = frozenset({"self", "cls"})
WORKER = "app.components.worker"  # where a task by name is looked for


@dataclass
class Scope:
    """One function being walked: what its names are."""

    module: Module
    parent: int  # the hop that reached it
    mode: Mode = Mode.SYNC
    depth: int = 0
    owner: Symbol | None = None  # the class ``self`` is
    types: dict[str, Symbol] = field(default_factory=dict)  # name: project class
    params: dict[str, bool] = field(default_factory=dict)  # name: annotated
    covered: set[str] = field(default_factory=set)  # bound to registry entries
    unread: set[str] = field(default_factory=set)  # ... of a registry unread


def symbol_of(found: object) -> Symbol | None:
    """Where a callable is defined: an instance called as a dependency by
    its class's ``__call__``."""
    found = inspect.unwrap(getattr(found, "func", found))  # type: ignore[arg-type]
    if not (
        inspect.isfunction(found) or inspect.ismethod(found) or inspect.isclass(found)
    ):
        found = type(found).__call__
    module = getattr(found, "__module__", None)
    name = getattr(found, "__qualname__", "")
    return None if not module or "<" in name else (module, name)


class Names:
    """The project's names, as one walk reads them (``Source``)."""

    def __init__(self, index: Index) -> None:
        self.index = index
        self.source = Source(index)

    def is_function(self, symbol: Symbol | None) -> bool:
        return symbol is not None and isinstance(self.source.definition(symbol), Def)

    def resolve(self, expr: ast.expr, scope: Scope) -> Symbol | None:
        """The project function, class or module ``expr`` names."""
        if isinstance(expr, ast.Name):
            if _local(expr.id, scope):
                return None  # an instance or a value, not a definition
            return self.alias(resolve(self.index, scope.module.name, expr.id))
        if not isinstance(expr, ast.Attribute):
            return None
        if cls := self.class_of(expr.value, scope):
            return self.source.method(cls, expr.attr)
        base = self.resolve(expr.value, scope)
        if base is None:
            return None
        if base[1] is None:
            return self.alias(resolve(self.index, base[0], expr.attr))
        return (
            self.source.method(base, expr.attr) if self.source.is_class(base) else None
        )

    def class_of(self, expr: ast.expr, scope: Scope) -> Symbol | None:
        """The project class of an instance: ``self``, a typed name, an
        attribute of one (``self.store``), or one a call makes or returns."""
        if isinstance(expr, ast.Call):
            return self.made(expr, scope)
        if isinstance(expr, ast.Name):
            if expr.id in SELF and scope.owner:
                return scope.owner
            return scope.types.get(expr.id)
        if isinstance(expr, ast.Attribute) and (
            inner := self.class_of(expr.value, scope)
        ):
            return self.source.attribute(inner, expr.attr)
        return None

    def made(self, value: ast.expr, scope: Scope) -> Symbol | None:
        """The project class a call makes, or says it returns."""
        if isinstance(value, ast.Await):
            value = value.value
        target = (
            self.resolve(value.func, scope) if isinstance(value, ast.Call) else None
        )
        found = self.source.definition(target) if target else None
        if isinstance(found, ast.ClassDef):
            return target
        if target and isinstance(found, Def):
            return self.source.typed(target[0], found.returns)
        return None

    def unsaid(self, call: ast.Call, scope: Scope) -> bool:
        """A project function that does not say what it returns."""
        target = self.resolve(call.func, scope)
        found = self.source.definition(target) if target else None
        return isinstance(found, Def) and found.returns is None

    def alias(self, symbol: Symbol | None) -> Symbol | None:
        """A top-level name bound to another (``start = start_here``) as
        the one it names."""
        if symbol is None or symbol[1] is None or self.source.definition(symbol):
            return symbol
        value = assigned(self.source.tree(symbol[0]), symbol[1])
        if isinstance(value, ast.Name):
            return resolve(self.index, symbol[0], value.id) or symbol
        return symbol

    def table(self, arg: ast.expr, scope: Scope) -> tuple[Symbol, str] | None:
        """The table class an argument names (``Post``, ``Post.id``, or a
        local made as one), and its table."""
        head = arg
        while isinstance(head, ast.Attribute):
            head = head.value
        if not isinstance(head, ast.Name):
            return None
        cls = scope.types.get(head.id) or resolve(
            self.index, scope.module.name, head.id
        )
        table = self.source.table(cls) if cls and cls[1] else None
        return (cls, table) if cls and table else None

    def task(self, name: str) -> Symbol | None:
        """The task registered as ``name``: in the module the worker's live
        registry has it in (a wrapper renames its function), else a function
        of that name in the worker's own code."""
        try:
            from app.components.worker.tasks import get_task_by_name
        except ImportError:
            found = None
        else:
            found = symbol_of(task) if (task := get_task_by_name(name)) else None
        if found and self.is_function((found[0], name)):
            return found[0], name
        return next(
            (
                (m.name, name)
                for m in self.index.naming(name)
                if within(m.name, WORKER)
                and any(f.qualname == name for f in m.functions)
            ),
            None,
        )

    def registry(self, loop: ast.For | ast.AsyncFor, scope: Scope) -> Symbol | None:
        """The top-level value a loop goes over (``CHECKS``,
        ``CHECKS.items()``), if that is what it does."""
        source = loop.iter
        if (
            isinstance(source, ast.Call)
            and isinstance(source.func, ast.Attribute)
            and source.func.attr in ("items", "values")
        ):
            source = source.func.value
        if not isinstance(source, ast.Name) or _local(source.id, scope):
            return None
        symbol = resolve(self.index, scope.module.name, source.id)
        if symbol is None or symbol[1] is None or self.source.definition(symbol):
            return None  # not a top-level value
        return symbol

    def entries(self, symbol: Symbol) -> list[Symbol] | None:
        """The project functions in a registry, read live, else from its
        literal; None if it can be read neither way."""
        module, name = symbol
        live = getattr(sys.modules.get(module), name or "", None)
        if isinstance(live, Mapping):
            live = list(live.values())
        if isinstance(live, list | tuple | set | frozenset):
            found = [symbol_of(v) for v in live if callable(v)]
        else:
            written = _literal(assigned(self.source.tree(module), name or ""))
            if written is None:
                return None
            found = [
                resolve(self.index, module, v.id)
                for v in written
                if isinstance(v, ast.Name)
            ]
        return [s for s in found if s and self.is_function(s)]


def _local(name: str, scope: Scope) -> bool:
    """A name the function holds a value under: a typed local or a parameter."""
    return name in scope.types or name in scope.params


def _literal(value: ast.expr | None) -> list[ast.expr] | None:
    if isinstance(value, ast.Dict):
        return [v for v in value.values if v is not None]
    if isinstance(value, ast.List | ast.Tuple | ast.Set):
        return list(value.elts)
    return None
