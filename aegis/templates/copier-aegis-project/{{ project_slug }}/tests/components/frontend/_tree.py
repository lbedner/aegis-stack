"""Control-tree walkers for the Flet component suite.

One canonical traversal. Before this file, ``_walk``/``_texts`` were
re-typed in five test files and had already drifted - one returned a
list of ``ft.Text`` values (``None`` included), one a list of non-empty
strings, one a newline-joined blob - which is the same failure mode the
finance factories module exists to prevent. Files alias these on import
(``from tests.components.frontend._tree import texts as _texts``) so
call sites stay short.
"""

from collections.abc import Iterator
from typing import Any


def walk(node: Any) -> Iterator[Any]:
    """Every control in the tree, depth-first: the node itself, its
    ``content``, then ``controls`` - the two container conventions every
    Flet control uses."""
    if node is None:
        return
    yield node
    yield from walk(getattr(node, "content", None))
    for child in getattr(node, "controls", None) or []:
        yield from walk(child)


def texts(node: Any) -> list[str]:
    """Every non-empty rendered string in the tree, in walk order.

    Includes ``TextSpan`` text: a value split into styled spans still
    reads as one rendered line."""
    out: list[str] = []
    for n in walk(node):
        value = getattr(n, "value", None)
        if isinstance(value, str) and value:
            out.append(value)
        for span in getattr(n, "spans", None) or []:
            text = getattr(span, "text", None)
            if isinstance(text, str) and text:
                out.append(text)
    return out


def rendered(node: Any) -> str:
    """The tree's strings as one newline-joined blob - for substring
    assertions ("Due Sep 10" in rendered(card))."""
    return "\n".join(texts(node))


def accent_texts(node: Any, accent: str) -> list[str]:
    """Every string rendered in ``accent`` color - a plain node's own
    ``.color``, or a styled ``TextSpan``'s ``.style.color`` (the "before
    -> AFTER" pattern splits one value into spans so only the target
    pops)."""
    out: list[str] = []
    for n in walk(node):
        value = getattr(n, "value", None)
        if isinstance(value, str) and value and getattr(n, "color", None) == accent:
            out.append(value)
        for span in getattr(n, "spans", None) or []:
            text = getattr(span, "text", None)
            color = getattr(getattr(span, "style", None), "color", None)
            if isinstance(text, str) and text and color == accent:
                out.append(text)
    return out


def panel_source(panel: type) -> str:
    """A panel's source plus every mixin it inherits from.

    The dashboard panels are thin classes over several mixin modules,
    so ``inspect.getsource(panel)`` reads a fraction of the behaviour
    and calls anything that lives on a mixin "missing". Only ``app.``
    bases are read - Flet's own source is noise here. The panel comes
    first, so a test that slices from a marker in ``__init__`` still
    slices the panel.
    """
    import inspect

    return "".join(
        inspect.getsource(base)
        for base in panel.__mro__
        if base.__module__.startswith("app.")
    )
