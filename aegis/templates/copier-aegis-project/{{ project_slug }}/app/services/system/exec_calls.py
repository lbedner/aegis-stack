"""The ``.exec(`` calls a module's tree makes, and which of them write: a
``delete``, ``update`` or ``insert`` statement, passed directly or by the
name it was last assigned to, is no read."""

import ast
from functools import lru_cache

WRITES = frozenset({"delete", "update", "insert"})

Assigned = dict[str, list[tuple[int, ast.expr]]]


def exec_lines(tree: ast.AST, *, writes: bool = True) -> list[int]:
    """The line of each ``.exec(`` call in ``tree``, its writes left out
    unless ``writes``."""
    calls, assigned = _scan(tree)
    if not writes:
        calls = tuple(c for c in calls if not _writes(c, assigned))
    return sorted({c.func.end_lineno or c.lineno for c in calls})


# The size of the source index's tree cache: a tree it still holds is the
# same object here, so asking for reads then for every query walks it once.
@lru_cache(maxsize=256)
def _scan(tree: ast.AST) -> tuple[tuple[ast.Call, ...], Assigned]:
    """One walk of ``tree``: its ``.exec(`` calls, and each plain name's
    assignments (their line and value)."""
    calls: list[ast.Call] = []
    assigned: Assigned = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "exec":
                calls.append(node)
            continue
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                assigned.setdefault(target.id, []).append((node.lineno, value))
    return tuple(calls), assigned


def _writes(call: ast.Call, assigned: Assigned) -> bool:
    """Whether ``call`` runs a write statement: its first argument one, or a
    name last assigned one above it."""
    if not call.args:
        return False
    statement = call.args[0]
    if isinstance(statement, ast.Name):
        # ponytail: the module's last assignment above the call, not its
        # scope's; scope it if a parameter ever shadows a ``stmt = delete()``.
        before = [a for a in assigned.get(statement.id, []) if a[0] < call.lineno]
        statement = max(before, key=lambda a: a[0])[1] if before else statement
    return _root(statement) in WRITES


def _root(node: ast.expr) -> str:
    """The function a statement's chain starts from: ``delete`` for
    ``delete(T).where(...)`` and for ``sa.delete(T)``."""
    name = ""
    while isinstance(node, ast.Call | ast.Attribute):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            node = func
        else:
            node = node.value
    return name
