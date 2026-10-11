"""What a module's functions say, read from its syntax tree for
``source_index``: each one's parameters as written, the names it calls and
how much it does. The Service pattern reads its rule from these."""

import ast
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class Param:
    """A function's parameter: its annotation and default as written."""

    name: str
    annotation: str | None
    default: str | None


@dataclass(frozen=True)
class Function:
    """A function at a module's top level or in a class (``Store.count``)."""

    qualname: str
    start: int  # its first decorator's line, or its own
    end: int
    is_async: bool
    params: tuple[Param, ...]
    calls: frozenset[str]  # each name called in it: ``f()`` and ``x.f()`` call ``f``
    statements: int  # in its body, a docstring not counted


def _written(lines: tuple[str, ...], node: ast.expr | None) -> str | None:
    """``node`` as the source spells it: a slice of ``lines``, by the byte
    offsets ``ast`` gives, rather than an unparse."""
    if node is None:
        return None
    first, last = node.lineno - 1, (node.end_lineno or node.lineno) - 1
    text = "\n".join(lines[first : last + 1]).encode()
    end = len(text) - len(lines[last].encode()) + (node.end_col_offset or 0)
    return text[node.col_offset : end].decode(errors="replace")


def _params(
    node: ast.FunctionDef | ast.AsyncFunctionDef, lines: tuple[str, ...]
) -> tuple[Param, ...]:
    args = node.args
    positional = args.posonlyargs + args.args
    defaults: list[ast.expr | None] = [None] * (len(positional) - len(args.defaults))
    pairs = zip(
        positional + args.kwonlyargs,
        [*defaults, *args.defaults, *args.kw_defaults],
        strict=True,
    )
    return tuple(
        Param(arg.arg, _written(lines, arg.annotation), _written(lines, default))
        for arg, default in pairs
    )


def _function(
    node: ast.FunctionDef | ast.AsyncFunctionDef, qualname: str, lines: tuple[str, ...]
) -> Function:
    body = node.body
    docstring = (
        bool(body)
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
    )
    calls = {
        call.func.id if isinstance(call.func, ast.Name) else call.func.attr
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name | ast.Attribute)
    }
    return Function(
        qualname,
        min([d.lineno for d in node.decorator_list] + [node.lineno]),
        node.end_lineno or node.lineno,
        isinstance(node, ast.AsyncFunctionDef),
        _params(node, lines),
        frozenset(calls),
        len(body) - int(docstring),
    )


def functions(
    node: ast.AST, lines: tuple[str, ...], prefix: str = ""
) -> Iterator[Function]:
    """The functions at ``node``'s top level and in its classes, nested."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            yield from functions(child, lines, f"{prefix}{child.name}.")
        elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            yield _function(child, prefix + child.name, lines)
