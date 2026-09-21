"""A mount guard must test the control it is about to update.

Flet refuses ``control.update()`` before the control is on a page, so
the frontend guards those calls. The guard has to name the *same*
control::

    if self._table.page:        # right
        self._table.update()

    if self.page:               # wrong, when self.page is assigned
        self._table.update()

The wrong version is not obviously wrong, which is the problem. A
control inherits ``page`` from Flet and it is ``None`` until mount, so
``if self.page`` usually is a real mount check. But a class that does
``self.page = page`` in its own ``__init__`` has overwritten that: the
attribute is truthy from the first line and says nothing about whether
anything is mounted. Pair that with ``page.run_task(self._load)`` in
the same ``__init__`` - the standard way these tabs fetch - and the
task reliably wins the race against the mount.

That is not hypothetical. ``documents_modal.TagsTab`` shipped with it
on 2026-09-01, survived five commits touching the file, and passed lint,
typecheck and the whole generated suite for three weeks, because nothing
in the suite mounts a modal. It surfaced the first time a person clicked
the tab: ``AssertionError: Container Control must be added to the page
first``, and the modal did not open.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

FRONTEND = (
    Path(__file__).parent.parent.parent
    / "aegis/templates/copier-aegis-project/{{ project_slug }}/app/components/frontend"
)


def _neutralise(text: str) -> str:
    """Blank the Jinja so a ``.jinja`` template parses as Python."""
    blank = lambda m: "\n" * m.group(0).count("\n")  # noqa: E731
    text = re.sub(r"\{#.*?#\}", blank, text, flags=re.S)
    text = re.sub(r"\{%.*?%\}", blank, text, flags=re.S)
    return re.sub(r"\{\{.*?\}\}", "JINJA_EXPR", text, flags=re.S)


def _dotted(node: ast.AST) -> str | None:
    """``self._table`` for an attribute chain, else None."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _overwrites_page(cls: ast.ClassDef) -> bool:
    """True when the class assigns ``self.page`` itself.

    That is what turns ``if self.page`` from a mount check into a
    constant.
    """
    return any(
        isinstance(node, ast.Assign)
        and any(_dotted(t) == "self.page" for t in node.targets)
        for node in ast.walk(cls)
    )


def _vacuous_guards() -> list[str]:
    found: list[str] = []
    for path in sorted(FRONTEND.rglob("*")):
        if path.suffix not in (".py", ".jinja") or "__pycache__" in str(path):
            continue
        try:
            tree = ast.parse(_neutralise(path.read_text(errors="replace")))
        except SyntaxError:
            continue
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            if not _overwrites_page(cls):
                continue
            for node in ast.walk(cls):
                found += _mismatches_in(node, path, cls)
    return found


def _mismatches_in(node: ast.AST, path: Path, cls: ast.ClassDef) -> list[str]:
    """``if self.page:`` bodies that update something other than self."""
    if not isinstance(node, ast.If):
        return []
    test = node.test
    if isinstance(test, ast.Compare) and len(test.comparators) == 1:
        test = test.left
    if not (isinstance(test, ast.Attribute) and test.attr == "page"):
        return []
    if _dotted(test.value) != "self":
        return []
    out = []
    for stmt in node.body:
        if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)):
            continue
        call = stmt.value
        if not (isinstance(call.func, ast.Attribute) and call.func.attr == "update"):
            continue
        receiver = _dotted(call.func.value)
        if receiver and receiver.startswith("self.") and receiver != "self.page":
            rel = path.relative_to(FRONTEND) if path.is_absolute() else path
            out.append(
                f"{rel}:{stmt.lineno} {cls.name}: guards `self.page` "
                f"(which this class assigns, so it is always truthy) "
                f"but updates `{receiver}` — guard `{receiver}.page`"
            )
    return out


def test_no_control_is_updated_behind_a_guard_for_a_different_control() -> None:
    offenders = _vacuous_guards()
    assert not offenders, (
        "These update a control behind a guard that cannot be false:\n  "
        + "\n  ".join(offenders)
    )


def test_the_detector_sees_the_shape_it_is_looking_for() -> None:
    """The guard above is static analysis, so it can silently match
    nothing. This is the bug as it actually shipped; if the detector
    stops recognising it, the real test stops meaning anything."""
    source = """
class TagsTab(ft.Container):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self._table = ft.Container(expand=True)
        page.run_task(self._load)

    async def _load(self):
        self._table.content = "loaded"
        if self.page:
            self._table.update()
"""
    tree = ast.parse(source)
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
    assert _overwrites_page(cls), "did not notice self.page being assigned"
    hits = [h for n in ast.walk(cls) for h in _mismatches_in(n, Path("x.py"), cls)]
    assert len(hits) == 1, f"expected to catch the shipped bug, got {hits}"
    assert "_table" in hits[0]


def test_a_guard_naming_its_own_control_is_fine() -> None:
    """The fix must not read as a violation."""
    source = """
class TagsTab(ft.Container):
    def __init__(self, page):
        self.page = page
        self._table = ft.Container()

    async def _load(self):
        if self._table.page:
            self._table.update()
"""
    tree = ast.parse(source)
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
    hits = [h for n in ast.walk(cls) for h in _mismatches_in(n, Path("x.py"), cls)]
    assert hits == []
