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
