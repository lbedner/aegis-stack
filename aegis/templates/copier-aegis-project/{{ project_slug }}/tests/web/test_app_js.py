"""After a direct API action, app.js reloads the page it was on
(static/js/app.js, run in node).

An action button with ``data-api-done`` gets JSON back, not HTML, so on
success the page's main area is re-requested. The page is the whole URL:
state such as the storage browser's open bucket and folder lives in the
query string, and dropping it sends the viewer back to the top.
"""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

APP_JS = Path("app/components/web_frontend/static/js/app.js")

HARNESS = """
const handlers = {};
const on = (name, fn) => { (handlers[name] ||= []).push(fn); };
global.window = { location: { pathname: '/overseer/components/storage/browse',
                              search: '?bucket=demo-files&prefix=invoices%2F' },
                  dispatchEvent: () => {} };
global.Event = class { constructor(name) { this.type = name; } };
global.CustomEvent = class extends global.Event {};
global.document = { addEventListener: on, body: { addEventListener: on, dispatchEvent: () => {} } };
const requested = [];
global.htmx = { ajax: (verb, url) => requested.push(url) };
require(APP_JS);
for (const fn of handlers['htmx:afterRequest']) {
  fn({ detail: { elt: { dataset: { apiDone: 'File deleted' } }, successful: true } });
}
console.log(JSON.stringify(requested));
"""


def test_a_finished_action_reloads_the_same_url_query_and_all() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    script = HARNESS.replace("APP_JS", json.dumps(str(APP_JS.resolve())))
    out = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, check=True
    )
    assert json.loads(out.stdout) == [
        "/overseer/components/storage/browse?bucket=demo-files&prefix=invoices%2F"
    ]


DISMISS_HARNESS = """
const toasts = [];
global.window = { location: { pathname: '/', search: '' },
                  dispatchEvent: (e) => toasts.push(e.detail && e.detail.text) };
global.Event = class { constructor(name) { this.type = name; } };
global.CustomEvent = class extends global.Event {
  constructor(name, init) { super(name); this.detail = init && init.detail; } };
global.document = { addEventListener: () => {},
                    body: { addEventListener: () => {}, dispatchEvent: () => {} } };
global.htmx = { ajax: () => Promise.resolve() };
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


def test_clicking_off_closes_unless_something_is_unsaved() -> None:
    """Light dismiss: a click outside (or Escape) closes a panel, a row
    click switches to that item, and typed-but-unsaved work holds it open
    with a toast; the X still closes on purpose."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    script = DISMISS_HARNESS.replace("APP_JS", json.dumps(str(APP_JS.resolve())))
    out = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, check=True
    )
    assert json.loads(out.stdout) == {
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
