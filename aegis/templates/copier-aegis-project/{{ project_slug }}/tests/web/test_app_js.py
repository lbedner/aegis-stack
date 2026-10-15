"""After a direct API action, app.js reloads the page it was on
(static/js/app.js, run in node).

An action button with ``data-api-done`` gets JSON back, not HTML, so on
success the page's main area is re-requested. The page is the whole URL:
state such as the storage browser's open bucket and folder lives in the
query string, and dropping it sends the viewer back to the top.
"""

import json
from pathlib import Path
import re

import pytest

from tests.test_formatting import MATCH_CASES
from tests.web.node import run

APP_JS = Path("app/components/web_frontend/static/js/app.js")

# The browser app.js expects, stubbed once: every listener it adds is kept
# in ``handlers`` (``fire(name, event)`` runs them), and a harness sets only
# what it watches (window.dispatchEvent, document.getElementById, htmx.ajax).
STUBS = """
const handlers = {};
const on = (name, fn) => { (handlers[name] ||= []).push(fn); };
const fire = (name, event) => (handlers[name] || []).forEach((fn) => fn(event));
global.Event = class { constructor(name) { this.type = name; } };
global.CustomEvent = class extends global.Event {
  constructor(name, init) { super(name); this.detail = init && init.detail; } };
global.window = { location: { origin: 'http://app', pathname: '/', search: '' },
                  addEventListener: on, dispatchEvent: () => {} };
global.document = { addEventListener: on, getElementById: () => null,
                    querySelector: () => null, querySelectorAll: () => [],
                    body: { addEventListener: on, dispatchEvent: () => {} } };
global.htmx = { ajax: () => {} };
global.requestAnimationFrame = () => 0;
global.cancelAnimationFrame = () => {};
"""

HARNESS = (
    STUBS
    + """
window.location.pathname = '/overseer/components/storage/browse';
window.location.search = '?bucket=demo-files&prefix=invoices%2F';
const requested = [];
htmx.ajax = (verb, url) => requested.push(url);
require(APP_JS);
fire('htmx:afterRequest',
  { detail: { elt: { dataset: { apiDone: 'File deleted' } }, successful: true } });
console.log(JSON.stringify(requested));
"""
)


def test_a_finished_action_reloads_the_same_url_query_and_all() -> None:
    out = run(HARNESS, APP_JS=APP_JS)
    assert out == [
        "/overseer/components/storage/browse?bucket=demo-files&prefix=invoices%2F"
    ]


DISMISS_HARNESS = (
    STUBS
    + """
const toasts = [];
window.dispatchEvent = (e) => toasts.push(e.detail && e.detail.text);
htmx.ajax = () => Promise.resolve();
const { outsideClick, dismiss } = require(APP_JS);
function panel(dirty) {
  let closed = false;
  return { open: true, dataset: { param: 'post', ...(dirty ? { dirty: '1' } : {}) },
           contains: (t) => t.inside === true, close: () => { closed = true; },
           get closed() { return closed; } };
}
const at = (spot) => ({ inside: spot === 'inside',
  closest: (sel) => (spot === 'row' && sel.includes('[href*="post="]') ? {} : null)
                    || (spot === 'modal' && sel === 'dialog[open]' ? {} : null) });
const clean = panel(false), dirty = panel(true);
const results = {
  clean_outside: outsideClick(clean, at('outside')),
  dirty_outside: outsideClick(dirty, at('outside')),
  clean_row: outsideClick(clean, at('row')),
  dirty_row: outsideClick(dirty, at('row')),
  inside: outsideClick(clean, at('inside')),
  modal: outsideClick(clean, at('modal')),
};
dismiss(dirty); results.dirty_closed = dirty.closed; results.toasts = toasts.length;
dismiss(clean); results.clean_closed = clean.closed;
console.log(JSON.stringify(results));
"""
)


def test_clicking_off_closes_unless_something_is_unsaved() -> None:
    """Light dismiss: a click outside (or Escape) closes a panel, a row
    click switches to that item, and typed-but-unsaved work holds it open
    with a toast; the X still closes on purpose."""
    out = run(DISMISS_HARNESS, APP_JS=APP_JS)
    assert out == {
        "clean_outside": "close",
        "dirty_outside": "hold",
        "clean_row": "ignore",
        "dirty_row": "hold",
        "inside": "ignore",
        "modal": "ignore",
        "dirty_closed": False,
        "toasts": 1,
        "clean_closed": True,
    }


COPY_HARNESS = (
    STUBS
    + """
const toasts = [];
window.dispatchEvent = (e) => toasts.push(e.detail);
const written = [];
// Node ships its own read-only navigator; replace it outright.
Object.defineProperty(globalThis, 'navigator', {
  value: { clipboard: { writeText: async (t) => { written.push(t); } } },
  configurable: true,
});
require(APP_JS);
const button = { dataset: { copy: 'postgres://db' }, querySelector: () => null };
fire('click', { target: { closest: (sel) => (sel === '[data-copy]' ? button : null) } });
setTimeout(() => console.log(JSON.stringify({ written, toasts })), 0);
"""
)


def test_any_copy_button_copies_its_text() -> None:
    """One copier for the whole app: a ``data-copy`` button's text goes to
    the clipboard, and a button with no tick of its own says so in a toast."""
    out = run(COPY_HARNESS, APP_JS=APP_JS)
    result = out
    assert result["written"] == ["postgres://db"]
    assert result["toasts"][-1]["tone"] == "ok"


PROGRESS_HARNESS = (
    STUBS
    + """
const { navigates } = require(APP_JS);
const link = (more = {}) => ({ origin: 'http://app', target: '',
  getAttribute: () => more.href || '/overseer/components/cache',
  hasAttribute: (name) => name in more, ...more });
const click = (to, more = {}) => ({ button: 0, defaultPrevented: false,
  target: { closest: () => to }, ...more });
console.log(JSON.stringify({
  link: navigates(click(link())),
  new_tab: navigates(click(link(), { metaKey: true })),
  other_site: navigates(click(link({ origin: 'http://elsewhere' }))),
  target_blank: navigates(click(link({ target: '_blank' }))),
  download: navigates(click(link({ download: '' }))),
  anchor: navigates(click(link({ href: '#top' }))),
  htmx_took_it: navigates(click(link(), { defaultPrevented: true })),
  not_a_link: navigates(click(null)),
}));
"""
)


def test_only_a_click_that_leaves_the_page_starts_the_bar() -> None:
    """The progress bar along the top starts for a link that loads another
    page here; htmx shows it for its own requests, so a link htmx took,
    a new tab, another site, a download or an anchor leave it alone."""
    out = run(PROGRESS_HARNESS, APP_JS=APP_JS)
    assert out == {
        "link": True,
        "new_tab": False,
        "other_site": False,
        "target_blank": False,
        "download": False,
        "anchor": False,
        "htmx_took_it": False,
        "not_a_link": False,
    }


SSE_SWAP_HARNESS = (
    STUBS
    + """
require(APP_JS);
fire('htmx:afterSwap', { detail: { elt: {} } });
console.log('true');
"""
)


def test_a_live_stream_swap_has_no_target_and_breaks_nothing() -> None:
    """The SSE extension's swaps raise ``htmx:afterSwap`` without a
    ``target``; the swap handlers must let them pass."""
    assert run(SSE_SWAP_HARNESS, APP_JS=APP_JS) is True


PENDING_HARNESS = (
    STUBS
    + """
let pending = true;
const classes = new Set();
const bar = { classList: { toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)) } };
document.getElementById = (id) => (id === 'page-progress' ? bar : null);
document.querySelector = (sel) => (sel === '[data-pending]' && pending ? {} : null);
require(APP_JS);
const seen = [];
fire('htmx:load', { detail: { elt: { dataset: {} } } }); seen.push(classes.has('is-loading'));
pending = false;
fire('htmx:load', { detail: { elt: { dataset: {} } } }); seen.push(classes.has('is-loading'));
console.log(JSON.stringify(seen));
"""
)


def test_the_bar_runs_while_part_of_the_page_is_still_on_its_way() -> None:
    """A section that renders before its data (``data-pending``, the
    Container section's first read) keeps the bar going until it lands."""
    out = run(PENDING_HARNESS, APP_JS=APP_JS)
    assert out == [True, False]


REQUEST_HARNESS = (
    STUBS
    + """
const classes = new Set();
const bar = { classList: { toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)) } };
document.getElementById = (id) => (id === 'page-progress' ? bar : null);
require(APP_JS);
const ends = [];
const xhr = { addEventListener: (name, fn) => { if (name === 'loadend') ends.push(fn); } };
const seen = [];
fire('htmx:beforeRequest', { detail: { elt: {}, xhr } }); seen.push(classes.has('is-loading'));
ends.forEach((fn) => fn());  // no htmx:afterRequest reaches the page
seen.push(classes.has('is-loading'));
console.log(JSON.stringify(seen));
"""
)


def test_the_bar_stops_when_a_request_ends_even_if_its_sender_was_swapped_out() -> None:
    """A live frame can swap out the element that sent a request while it is
    out (a Restart button in a row the stream re-sends): htmx's
    ``afterRequest`` then fires on a detached element and never bubbles
    here, so the bar counts the request down when it ends (its ``loadend``)."""
    assert run(REQUEST_HARNESS, APP_JS=APP_JS) == [True, False]


SCROLL_HARNESS = (
    STUBS
    + """
const shown = [];
document.querySelector = (sel) => ({ scrollIntoView: (how) => shown.push([sel, how.block]) });
require(APP_JS);
const button = { dataset: { scrollTo: '#rows > tr:last-child' } };
fire('click', { target: { closest: (sel) => (sel === '[data-scroll-to]' ? button : null) } });
fire('click', { target: { closest: () => null } });
console.log(JSON.stringify({ shown }));
"""
)


def test_a_scroll_button_brings_its_target_into_view() -> None:
    """A ``data-scroll-to`` button scrolls to the element its selector names
    (a list's first or last row); a click elsewhere scrolls nothing."""
    assert run(SCROLL_HARNESS, APP_JS=APP_JS)["shown"] == [
        ["#rows > tr:last-child", "nearest"]
    ]


MARK_HARNESS = (
    STUBS
    + """
const { markCurrent } = require(APP_JS);
const link = (href) => {
  const attrs = {};
  return { attrs, getAttribute: () => href,
           setAttribute: (k, v) => { attrs[k] = v; },
           removeAttribute: (k) => { delete attrs[k]; } };
};
const links = ['/overseer', '/overseer/services/payment', '/overseer/services/ai'].map(link);
links[2].attrs['aria-current'] = 'page';
markCurrent(links, '/overseer/services/payment/transactions');
console.log(JSON.stringify(links.map((l) => l.attrs['aria-current'] || null)));
"""
)


def test_the_sidebar_marks_the_page_it_leads_to() -> None:
    """The sidebar stays put across navigation, so the current mark moves
    to the link whose page holds the new address (a section under it
    included), and only the home link for the home page itself."""
    assert run(MARK_HARNESS, APP_JS=APP_JS) == [None, "page", None]


RANGE_HARNESS = (
    STUBS
    + """
const { spanned, inView } = require(APP_JS);
const bars = ['a', 'b', 'c', 'd'];
const timed = [[0, 10], [10, 20], [20, 30], [30, 40]].map(([f, t]) => ({ dataset: { from: String(f), to: String(t) } }));
console.log(JSON.stringify({
  seen: inView(timed, 12, 25).map((b) => b.dataset.from),
  none: inView(timed, null, null).length,
  forward: spanned(bars, 'b', 'd'),
  backward: spanned(bars, 'd', 'b'),
}));
"""
)


def test_dragging_across_the_volume_covers_every_bar_between() -> None:
    """From the first bar to the last, whichever way the drag ran."""
    out = run(RANGE_HARNESS, APP_JS=APP_JS)
    assert out["forward"] == out["backward"] == ["b", "c", "d"]


FACETS_HARNESS = (
    STUBS
    + """
const { kept, volumeOf } = require(APP_JS);
const row = { level: 'error', service: 'worker', container: 'w-1', app_service: 'ai' };
const of = (name) => row[name];
const bars = [{ from: 0, to: 10 }, { from: 10, to: 20 }];
const rows = [
  { at: -5, tone: 'error' }, { at: 5, tone: 'error' }, { at: 12, tone: 'warn' },
  { at: 15, tone: '' }, { at: 25, tone: 'muted' },
];
console.log(JSON.stringify({
  nothing: kept([], of),
  oneOf: kept([[['level', 'error'], ['level', 'critical']]], of),
  missed: kept([[['level', 'info']]], of),
  anySource: kept([[['service', 'redis'], ['app_service', 'ai']]], of),
  everyList: kept([[['level', 'error']], [['service', 'redis']]], of),
  volume: volumeOf(bars, rows),
}));
"""
)


def test_each_list_narrows_and_any_tick_in_it_keeps() -> None:
    """The Logs filters on the page (``data-facets``): a list with nothing
    ticked keeps every row; one with ticks keeps a row any of them matches
    (a service, a container or an application service); every list must
    keep it."""
    out = run(FACETS_HARNESS, APP_JS=APP_JS)
    assert [
        out[k] for k in ("nothing", "oneOf", "missed", "anySource", "everyList")
    ] == [
        True,
        True,
        False,
        True,
        False,
    ]


def test_the_volume_recounts_the_rows_the_filters_keep() -> None:
    """``ui_logs._volume``'s twin: each bar counts its rows by tone; one
    before the window is left out, one after it lands in the last bar."""
    out = run(FACETS_HARNESS, APP_JS=APP_JS)
    assert out["volume"] == [
        {"error": 1, "warn": 0, "other": 0, "total": 1},
        {"error": 0, "warn": 1, "other": 2, "total": 3},
    ]


def test_the_bars_behind_the_lines_on_screen_are_marked() -> None:
    """A bar is in view when its time overlaps the oldest to the newest line
    showing; with no line showing, none is."""
    out = run(RANGE_HARNESS, APP_JS=APP_JS)
    assert out["seen"] == ["10", "20"] and out["none"] == 0


@pytest.mark.parametrize(("text", "query", "runs"), MATCH_CASES)
def test_a_filter_marks_the_same_matches_as_the_server(
    text: str, query: str, runs: list[tuple[str, bool]]
) -> None:
    """The client-side filter's highlighter is ``split_matches``' twin, held
    to one table (``MATCH_CASES``)."""
    found = run(
        STUBS
        + "const { splitMatches } = require(APP_JS);"
        + f"console.log(JSON.stringify(splitMatches({json.dumps(text)}, {json.dumps(query)})));",
        APP_JS=APP_JS,
    )
    assert [tuple(r) for r in found] == runs


FOCUS_HARNESS = (
    STUBS
    + """
require(APP_JS);
const c = require(APP_JS);
const lines = [{ from: 'service_auth', to: 'database' },
               { from: 'service_payment', to: 'outside:Stripe' },
               { from: 'service_documents', to: 'database' }];
console.log(JSON.stringify([...c.mapFocus(lines, 'database')].sort()));
"""
)


def test_hovering_a_map_node_keeps_it_and_its_neighbours_lit() -> None:
    """Who uses the Database: the node and every node a line joins it to;
    the rest of the map dims."""
    assert run(FOCUS_HARNESS, APP_JS=APP_JS) == [
        "database",
        "service_auth",
        "service_documents",
    ]


LIT_HARNESS = (
    STUBS
    + """
const c = require(APP_JS);
console.log(JSON.stringify([...c.pathFocus('service_blog,database')].sort()));
"""
)


def test_a_dry_path_keeps_the_parts_it_crosses_lit() -> None:
    """Its parts lit (``?lit=``), and with them the lines between two of
    them (``applyMapFocus``); the rest dims."""
    assert run(LIT_HARNESS, APP_JS=APP_JS) == ["database", "service_blog"]


LET_GO_HARNESS = (
    STUBS
    + """
const root = { dataset: {}, querySelector: () => null };
document.getElementById = (id) => (id === 'overview-stack' ? root : null);
require(APP_JS);
const node = { dataset: { node: 'database' } };
const over = (sel) => (sel === '[data-map] [data-node]' ? node : sel === '[data-map]' ? {} : null);
const seen = [];
const focus = () => root.dataset.pinned || root.dataset.hover || '';
fire('mouseover', { target: { closest: over } }); seen.push(focus());
// A click holds nothing: off the node, nothing stays lit.
fire('click', { target: { closest: over } });
fire('mouseover', { target: { closest: (sel) => (sel === '[data-map]' ? {} : null) } });
seen.push(focus());
// Out of the window straight from a node: no mouseover follows to clear it.
fire('mouseover', { target: { closest: over } });
fire('mouseout', { relatedTarget: null });
seen.push(focus());
console.log(JSON.stringify(seen));
"""
)


def test_a_maps_focus_follows_the_pointer_and_nothing_holds_it() -> None:
    """A node lights while hovered and lets go when the pointer leaves it,
    the window included; a click holds nothing, so nothing stays dimmed."""
    assert run(LET_GO_HARNESS, APP_JS=APP_JS) == ["database", "", ""]


COLUMN = (
    STUBS
    + """
const { sourceColumn } = require(APP_JS);
// Line 8 of a file: its number, then ``    store.put(2)`` token by token.
const text = (s, number = false) => ({ length: s.length, parentElement: { closest: () => number } });
const nodes = [text('8', true), text('    '), text('store'), text('.'), text('put'), text('(2)')];
global.NodeFilter = { SHOW_TEXT: 4 };
document.createTreeWalker = () => { let i = -1; return { nextNode: () => nodes[++i] || null }; };
const at = (node) => sourceColumn({}, { contains: (n) => n === node });
console.log(JSON.stringify([at(nodes[4]), at(nodes[2]), at({})]));
"""
)


def test_a_clicked_name_is_found_by_its_column_in_the_source() -> None:
    """Overseer > Code asks where a name is by line and column: the column
    counts the line's source only, never its number."""
    assert run(COLUMN, APP_JS=APP_JS) == [10, 4, None]


# A declaration at a script's top level (``function mount``, ``const KEY``).
TOP_LEVEL = re.compile(
    r"^(?:async\s+)?(?:function\*?|const|let|var|class)\s+(\w+)", re.M
)


def test_the_page_scripts_declare_no_name_twice() -> None:
    """Classic scripts share one global scope: a second ``function mount``
    replaces the first, and its script's listeners call the other's."""
    seen: dict[str, str] = {}
    clashes = []
    for path in sorted(APP_JS.parent.glob("*.js")):
        if path.name == "mic-worklet.js":  # an audio worklet's own scope
            continue
        for name in TOP_LEVEL.findall(path.read_text()):
            if name in seen and seen[name] != path.name:
                clashes.append((name, seen[name], path.name))
            seen.setdefault(name, path.name)
    assert clashes == []


# A script fetched from another origin: a tag's ``src``, or a URL a page
# script loads itself (``createElement('script')``, ``import()``).
REMOTE_TAG = re.compile(r"<script\b[^>]*\bsrc=\"https?://[^>]*>")
REMOTE_URL = re.compile(r"['\"`]https?://[^'\"`]+['\"`]")


def test_no_third_party_script_runs_unverified() -> None:
    """A changed CDN file would run on Overseer's origin, where requests
    carry the admin's cookie: each pins its version and the hash the
    browser checks (``integrity``), or ships with the app."""
    templates = APP_JS.parents[2] / "templates"
    unverified = [
        f"{path.name}: {tag}"
        for path in templates.rglob("*.html")
        for tag in REMOTE_TAG.findall(path.read_text())
        if "integrity=" not in tag or "crossorigin=" not in tag
    ]
    for path in APP_JS.parent.glob("*.js"):
        source = path.read_text()
        if REMOTE_URL.search(source) and ".integrity = " not in source:
            unverified.append(f"{path.name}: loads a remote script unhashed")
    assert unverified == []
