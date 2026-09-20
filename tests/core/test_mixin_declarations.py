"""A mixin's attribute declarations must describe a real attribute.

Splitting a class across modules means the halves that hold behaviour
can no longer see where their state comes from, so they re-declare it::

    class SelectionMixin:
        if TYPE_CHECKING:
            _selected: set[int]

        def toggle(self, i: int) -> None:
            self._selected.add(i)

That declaration does not cross-check anything - it *replaces* what the
type checker would otherwise infer. Rename the attribute in the owning
``__init__`` and the mixin still type checks against the old name:

    ty    exit=0   All checks passed!
    ruff  exit=0
    run   AttributeError: 'Table' object has no attribute '_selected'

A green gate over a wrong binding, which is the worst failure shape
there is. This test is what actually checks it: for every class that
assigns state in ``__init__``, every attribute declared anywhere in its
inheritance chain must be assigned, or defined as a class attribute, or
be a method, somewhere in that same chain.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

TEMPLATE_APP = (
    Path(__file__).parent.parent.parent
    / "aegis/templates/copier-aegis-project/{{ project_slug }}/app"
)

# ``page`` and ``update`` come from Flet's ``Control``/``Container``,
# which this scanner cannot see - it only parses files in this repo, so
# every chain stops at ``ft.Container``. Two mixin stacks declare them so
# their module type checks alone (ChatPanel's, and UncategorizedPanel's),
# and nothing here assigns them because Flet does. Keep this list to
# names actually proven necessary: a speculative entry silently turns
# off the check for a name we do own.
FLET_PROVIDED = {"page", "update"}


def _neutralise(text: str) -> str:
    """Blank Jinja constructs in place so a .py.jinja parses as Python."""
    blank = lambda m: "\n" * m.group(0).count("\n")  # noqa: E731
    text = re.sub(r"\{#.*?#\}", blank, text, flags=re.S)
    return re.sub(r"\{%.*?%\}", blank, text, flags=re.S)


def _self_assigned(node: ast.ClassDef) -> set[str]:
    out: set[str] = set()
    for a in ast.walk(node):
        if not isinstance(a, ast.Assign | ast.AnnAssign):
            continue
        targets = a.targets if isinstance(a, ast.Assign) else [a.target]
        for target in targets:
            # Only a direct ``self.x = ...`` binds the attribute. Walking
            # into the target would also count ``self.x[k] = v``, which
            # READS self.x - and that is how the first version of this
            # test passed while seeing nothing.
            for element in (
                target.elts if isinstance(target, ast.Tuple | ast.List) else [target]
            ):
                if (
                    isinstance(element, ast.Attribute)
                    and isinstance(element.value, ast.Name)
                    and element.value.id == "self"
                ):
                    out.add(element.attr)
    return out


@dataclass
class _Class:
    """What one class declares, what it actually defines, and its bases."""

    file: str
    bases: list[str]
    declared: set[str] = field(default_factory=set)
    defined: set[str] = field(default_factory=set)
    concrete: bool = False


def _scan() -> dict[str, _Class]:
    classes: dict[str, _Class] = {}
    for path in TEMPLATE_APP.rglob("*"):
        if path.suffix not in (".py", ".jinja") or "__pycache__" in str(path):
            continue
        try:
            tree = ast.parse(_neutralise(path.read_text()))
        except SyntaxError:
            continue  # a template too tag-woven to parse; nothing to check
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            declared: set[str] = set()
            defined: set[str] = set()
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(
                    item.target, ast.Name
                ):
                    # a bare annotation declares; one with a value defines
                    (declared if item.value is None else defined).add(item.target.id)
                elif isinstance(item, ast.Assign):
                    defined |= {t.id for t in item.targets if isinstance(t, ast.Name)}
                elif isinstance(item, ast.If) and "TYPE_CHECKING" in ast.unparse(
                    item.test
                ):
                    for sub in item.body:
                        if isinstance(sub, ast.AnnAssign) and isinstance(
                            sub.target, ast.Name
                        ):
                            declared.add(sub.target.id)
                        elif isinstance(sub, ast.FunctionDef | ast.AsyncFunctionDef):
                            defined.add(sub.name)
                elif isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    defined.add(item.name)
            assigned = _self_assigned(node)
            classes.setdefault(
                node.name,
                _Class(
                    file=str(path.relative_to(TEMPLATE_APP)),
                    bases=[ast.unparse(b).split(".")[-1] for b in node.bases],
                    declared=declared,
                    defined=defined | assigned,
                    concrete="__init__" in defined and bool(assigned),
                ),
            )
    return classes


def _chain(
    name: str, classes: dict[str, _Class], seen: set[str] | None = None
) -> list[str]:
    seen = seen if seen is not None else set()
    if name in seen or name not in classes:
        return []
    seen.add(name)
    out = [name]
    for base in classes[name].bases:
        out += _chain(base, classes, seen)
    return out


def test_every_declared_attribute_is_really_there() -> None:
    classes = _scan()
    broken: dict[str, tuple[str, list[str]]] = {}
    for name, info in classes.items():
        if not info.concrete:
            continue
        chain = _chain(name, classes)
        declared: set[str] = set()
        defined: set[str] = set()
        for cls in chain:
            declared |= classes[cls].declared
            defined |= classes[cls].defined
        orphan = sorted(declared - defined - FLET_PROVIDED)
        if orphan:
            broken[name] = (info.file, orphan)

    assert not broken, (
        "these classes inherit an attribute declaration that nothing "
        "assigns - the declaration will keep the type checker quiet while "
        "the attribute is missing at runtime: "
        + "; ".join(f"{n} ({f}): {o}" for n, (f, o) in sorted(broken.items()))
    )


def test_the_guard_can_see_a_broken_declaration() -> None:
    """The check above is only worth having if it fails when it should.

    The shape is the real one: a mixin declares ``_selected``, the class
    that owns the state renamed it to ``_selected_ids``, and nothing
    else notices.
    """
    classes = {
        "Mixin": _Class(file="x.py", bases=[], declared={"_selected"}),
        "Table": _Class(
            file="x.py",
            bases=["Mixin"],
            defined={"__init__", "_selected_ids"},
            concrete=True,
        ),
    }
    declared: set[str] = set()
    defined: set[str] = set()
    for cls in _chain("Table", classes):
        declared |= classes[cls].declared
        defined |= classes[cls].defined
    assert sorted(declared - defined - FLET_PROVIDED) == ["_selected"]
