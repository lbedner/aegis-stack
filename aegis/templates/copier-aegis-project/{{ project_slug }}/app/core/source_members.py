"""What ``source_index`` leaves out, for a walk through the code (the dry
path): a definition by its qualified name (``BlogService.get``), a
class's methods, its own or a project base's, the class each attribute is
given, and which classes are tables. Read from syntax trees, each parsed
once while a ``Source`` lives: one walk."""

import ast

from app.core.source_index import Index, Symbol, resolve

Def = ast.FunctionDef | ast.AsyncFunctionDef


class Source:
    """The project's syntax trees and what they say about classes, for as
    long as one walk needs them."""

    def __init__(self, index: Index) -> None:
        self.index = index
        self._trees: dict[str, ast.Module | None] = {}
        self._found: dict[Symbol, Def | ast.ClassDef | None] = {}

    def tree(self, module: str) -> ast.Module | None:
        if module not in self._trees:
            self._trees[module] = self.index.tree(module)
        return self._trees[module]

    def definition(self, symbol: Symbol) -> Def | ast.ClassDef | None:
        """The function, method or class ``symbol`` names."""
        if symbol not in self._found:
            module, member = symbol
            found: ast.AST | None = self.tree(module)
            for name in (member or "").split("."):
                found = next(
                    (
                        n
                        for n in getattr(found, "body", [])
                        if isinstance(n, Def | ast.ClassDef) and n.name == name
                    ),
                    None,
                )
            kept = found if isinstance(found, Def | ast.ClassDef) else None
            self._found[symbol] = kept
        return self._found[symbol]

    def is_class(self, symbol: Symbol) -> bool:
        return isinstance(self.definition(symbol), ast.ClassDef)

    def typed(self, module: str, annotation: ast.expr | None) -> Symbol | None:
        """The project class an annotation in ``module`` names: ``Store``,
        ``Store | None``, ``"Store"``; the first of its names that is one."""
        if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
            try:
                annotation = ast.parse(annotation.value, mode="eval").body
            except SyntaxError:
                return None
        for node in ast.walk(annotation) if annotation else ():
            if isinstance(node, ast.Name):
                found = resolve(self.index, module, node.id)
                if found and found[1] and self.is_class(found):
                    return found
        return None

    def _bases(self, cls: Symbol) -> list[tuple[Symbol, ast.ClassDef]]:
        """``cls`` and its project bases, nearest first, each with its class."""
        found: dict[Symbol, ast.ClassDef] = {}
        pending = [cls]
        while pending:
            here = pending.pop(0)
            node = self.definition(here)
            if not isinstance(node, ast.ClassDef) or here in found:
                continue
            found[here] = node
            pending += [
                base for b in node.bases if (base := self.typed(here[0], b)) is not None
            ]
        return list(found.items())

    def method(self, cls: Symbol, name: str) -> Symbol | None:
        """``cls``'s method ``name``: its own, else its nearest project
        base's."""
        for (module, member), _ in self._bases(cls):
            method = (module, f"{member}.{name}")
            if isinstance(self.definition(method), Def):
                return method
        return None

    def attribute(self, cls: Symbol, name: str) -> Symbol | None:
        """The project class ``cls`` gives its attribute ``name``: annotated
        in the class body, or an annotated ``__init__`` parameter it keeps
        on ``self`` (``self.store = store``)."""
        for (module, _), node in self._bases(cls):
            for annotation in _annotations(node, name):
                if found := self.typed(module, annotation):
                    return found
        return None

    def table(self, symbol: Symbol) -> str | None:
        """The table a class is (``table=True``), by name: its
        ``__tablename__``, else its name in lower case, as SQLModel names it."""
        node = self.definition(symbol)
        if not isinstance(node, ast.ClassDef) or not any(
            k.arg == "table" and isinstance(k.value, ast.Constant) and k.value.value
            for k in node.keywords
        ):
            return None
        value = assigned(node, "__tablename__")
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
        return node.name.lower()


def _annotations(node: ast.ClassDef, name: str) -> list[ast.expr]:
    """Where class ``node`` says what its attribute ``name`` is: in its
    body, or as the ``__init__`` parameter it keeps under that name."""
    found = [
        s.annotation
        for s in node.body
        if isinstance(s, ast.AnnAssign)
        and isinstance(s.target, ast.Name)
        and s.target.id == name
    ]
    init = next(
        (s for s in node.body if isinstance(s, Def) and s.name == "__init__"), None
    )
    if init is None:
        return found
    params = {a.arg: a.annotation for a in init.args.args + init.args.kwonlyargs}
    for statement in ast.walk(init):
        if (
            isinstance(statement, ast.Assign)
            and isinstance(statement.value, ast.Name)
            and any(_on_self(t, name) for t in statement.targets)
            and (annotation := params.get(statement.value.id)) is not None
        ):
            found.append(annotation)
    return found


def _on_self(target: ast.expr, name: str) -> bool:
    return (
        isinstance(target, ast.Attribute)
        and target.attr == name
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
    )


def assigned(node: ast.Module | ast.ClassDef | None, name: str) -> ast.expr | None:
    """The value ``name = ...`` gives it at the top of a module or class."""
    for statement in node.body if node else ():
        if isinstance(statement, ast.Assign):
            targets = statement.targets
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            return statement.value
    return None
