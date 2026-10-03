"""After a direct API action, app.js reloads the page it was on
(static/js/app.js, run in node).

An action button with ``data-api-done`` gets JSON back, not HTML, so on
success the page's main area is re-requested. The page is the whole URL:
state such as the storage browser's open bucket and folder lives in the
query string, and dropping it sends the viewer back to the top.
"""

from pathlib import Path

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
                    querySelector: () => null,
                    body: { addEventListener: on, dispatchEvent: () => {} } };
global.htmx = { ajax: () => {} };
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
