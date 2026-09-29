"""A template never prints a macro it imported as if it were a value.

``{% from ... import action %}`` shadows a context variable of the same
name, so ``hx-post="{{ action }}"`` renders ``<Macro 'action'>`` and the
form posts to that. It happened twice (a form's URL named ``action``, a
drawer URL named ``drawer``); a bare ``{{ name }}`` of an imported macro
is always that mistake, since a macro is called, not printed.
"""

from pathlib import Path
import re

import pytest

TEMPLATES = Path(__file__).parents[2] / "app/components/web_frontend/templates"
_IMPORT = re.compile(r"\{%-?\s*from\s+\S+\s+import\s+([^%]+?)\s*-?%\}")
_COMMENT = re.compile(r"\{#.*?#\}", re.S)


def _imported(source: str) -> set[str]:
    names: set[str] = set()
    for group in _IMPORT.findall(source):
        for part in group.split(","):
            words = part.split()
            if words:
                names.add(words[-1])  # ``pager as pager_links`` binds the alias
    return names


@pytest.mark.parametrize(
    "path",
    sorted(TEMPLATES.rglob("*.html")),
    ids=lambda p: str(p.relative_to(TEMPLATES)),
)
def test_no_imported_macro_is_printed_bare(path: Path) -> None:
    source = _COMMENT.sub("", path.read_text())  # usage examples live in comments
    printed = [
        name
        for name in _imported(source)
        if re.search(r"\{\{-?\s*" + re.escape(name) + r"\s*(\||-?\}\})", source)
    ]
    assert not printed, f"prints imported macro(s) as a value: {printed}"
