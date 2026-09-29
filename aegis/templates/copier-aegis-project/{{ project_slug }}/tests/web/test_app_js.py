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
