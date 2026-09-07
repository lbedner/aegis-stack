"""DOM assertions for rendered HTML.

Page tests select elements and read their text instead of grepping the raw
response for substrings. A substring check passes when the words appear in a
comment or the wrong element, and fails on a harmless attribute reorder;
selectors do neither.

    from tests.web.dom import none, one, select, text

    row = one(resp.text, "#txn-42")
    assert text(one(row, "td.amount")) == "$12.00"
    none(row, "button.delete")  # read-only view
"""

from __future__ import annotations

from lxml import html
from lxml.html import HtmlElement

Markup = str | HtmlElement


def _is_document(markup: str) -> bool:
    lowered = markup.lstrip().lower()
    return lowered.startswith("<!doctype") or lowered.startswith("<html")


def select(markup: Markup, css: str) -> list[HtmlElement]:
    """Every element matching ``css``. Empty list on no match.

    A full document is parsed as one (so ``head script`` resolves); a
    fragment is wrapped so multi-root markup parses, and the wrapper itself
    never counts as a match. An element scopes the search to itself and
    its descendants.
    """
    if isinstance(markup, HtmlElement):
        return markup.cssselect(css)
    if _is_document(markup):
        return html.document_fromstring(markup).cssselect(css)
    wrapper = html.fromstring(f"<div>{markup}</div>")
    return [element for element in wrapper.cssselect(css) if element is not wrapper]


def one(markup: Markup, css: str) -> HtmlElement:
    """The single element matching ``css``; fails on zero or many."""
    found = select(markup, css)
    assert len(found) == 1, f"expected 1 element for {css!r}, got {len(found)}"
    return found[0]


def none(markup: Markup, css: str) -> None:
    """Assert nothing matches ``css``; the message names what was there."""
    found = select(markup, css)
    assert not found, f"expected no {css!r}, found {len(found)}"


def text(element: HtmlElement) -> str:
    """Visible text of ``element`` and its descendants, whitespace collapsed."""
    return " ".join(element.text_content().split())
