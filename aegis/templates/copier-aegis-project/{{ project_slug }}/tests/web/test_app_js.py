"""After a direct API action, app.js reloads the page it was on
(static/js/app.js, run in node).

An action button with ``data-api-done`` gets JSON back, not HTML, so on
success the page's main area is re-requested. The page is the whole URL:
state such as the storage browser's open bucket and folder lives in the
query string, and dropping it sends the viewer back to the top.
"""

import json
from pathlib import Path

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
const { rangeUrl, spanned, inView } = require(APP_JS);
const bars = ['a', 'b', 'c', 'd'];
const timed = [[0, 10], [10, 20], [20, 30], [30, 40]].map(([f, t]) => ({ dataset: { from: String(f), to: String(t) } }));
console.log(JSON.stringify({
  seen: inView(timed, 12, 25).map((b) => b.dataset.from),
  none: inView(timed, null, null).length,
  url: rangeUrl('/overseer/logs?window=900&service=worker&service=redis&from=1&to=2', 9),
  forward: spanned(bars, 'b', 'd'),
  backward: spanned(bars, 'd', 'b'),
}));
"""
)


def test_dragging_across_the_volume_narrows_to_every_bar_it_covers() -> None:
    """The first bar's request (every filter it carries) with the last bar's
    end, whichever way the drag ran."""
    out = run(RANGE_HARNESS, APP_JS=APP_JS)
    assert out["url"] == (
        "/overseer/logs?window=900&service=worker&service=redis&from=1&to=9"
    )
    assert out["forward"] == out["backward"] == ["b", "c", "d"]


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


PIN_HARNESS = (
    STUBS
    + """
const root = { dataset: {}, querySelector: () => null };
document.getElementById = (id) => (id === 'overview-stack' ? root : null);
require(APP_JS);
const node = { dataset: { node: 'database' } };
const at = (sel) => (sel === '[data-map] [data-node]' ? node : sel === '[data-map]' ? {} : null);
const seen = [];
fire('click', { target: { closest: at } }); seen.push(root.dataset.pinned || '');
fire('mouseover', { target: { closest: (sel) => (sel === '[data-map] [data-node]' ? { dataset: { node: 'cache' } } : null) } });
seen.push(root.dataset.pinned || '');
fire('keydown', { key: 'Escape' }); seen.push(root.dataset.pinned || '');
fire('click', { target: { closest: at } });
fire('click', { target: { closest: (sel) => (sel === '[data-map]' ? {} : null) } });
seen.push(root.dataset.pinned || '');
console.log(JSON.stringify(seen));
"""
)


def test_a_click_pins_a_map_nodes_focus_until_escape_or_the_canvas() -> None:
    """Hover is a glance; a click keeps it while the pointer moves on.
    Escape, or a click on the empty canvas, lets it go."""
    assert run(PIN_HARNESS, APP_JS=APP_JS) == ["database", "database", "", ""]
