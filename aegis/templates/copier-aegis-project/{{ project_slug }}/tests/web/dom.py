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

import json
from typing import Any

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


def card(markup: Markup, title: str) -> HtmlElement:
    """The ``card`` macro's section whose heading is ``title``."""
    for section in select(markup, "section"):
        headings = select(section, "h2")
        if headings and text(headings[0]) == title:
            return section
    raise AssertionError(f"no card titled {title!r}")


def stat(markup: Markup, label: str) -> str:
    """The value under a ``stat_tile`` label."""
    for dt in select(markup, "dl dt"):
        if text(dt) == label:
            return text(dt.getnext())
    raise AssertionError(f"no stat tile {label!r}")


def chart_data(markup: Markup, kind: str) -> dict[str, Any]:
    """The JSON a ``chart_panel`` canvas of ``kind`` points at."""
    canvas = one(markup, f'canvas[data-chart="{kind}"]')
    payload = one(markup, f"#{canvas.get('data-chart-data')}")
    return json.loads(payload.text or "")


def location(response: Any) -> str:
    """Where a navigating response sends the content area (HX-Location)."""
    return json.loads(response.headers["HX-Location"])["path"]


def triggers(response: Any) -> dict[str, Any]:
    """Every client event a response carries, across htmx's three trigger
    headers (``dialog:close`` rides the after-settle one)."""
    merged: dict[str, Any] = {}
    for header in ("HX-Trigger", "HX-Trigger-After-Swap", "HX-Trigger-After-Settle"):
        raw = response.headers.get(header)
        if raw:
            merged.update(json.loads(raw))
    return merged


def oob(markup: str) -> tuple[list[HtmlElement], list[HtmlElement]]:
    """Split an action response into its primary elements and its
    out-of-band siblings (those carrying ``hx-swap-oob``), so a test asserts
    the swapped row and the moved counters separately."""
    wrapper = html.fromstring(f"<div>{markup}</div>")
    primary = [el for el in wrapper if el.get("hx-swap-oob") is None]
    siblings = [el for el in wrapper if el.get("hx-swap-oob") is not None]
    return primary, siblings


def table_rows(markup: Markup, table: str = "table") -> list[dict[str, HtmlElement]]:
    """Each body row of ``table`` as ``{header label: cell}``, so tests read
    cells by name instead of counting columns."""
    root = one(markup, table)
    headers = [text(th) for th in select(root, "thead th")]
    return [
        dict(zip(headers, tr.getchildren(), strict=False))
        for tr in select(root, "tbody tr")
    ]
