"""Live streams survive an expired session (static/js/auth.js, run in node).

An EventSource cannot refresh a session: once the 15-minute access token
expires, every reconnect is refused and a live page silently stops
updating. auth.js answers a stream error by probing the session through
the refresh-on-401 wrapper, so the SSE extension's next retry connects.
"""

import json
from pathlib import Path

import pytest

from tests.web.node import run

AUTH_JS = Path("app/components/web_frontend/static/js/auth.js")
REFRESH = "/api/v1/auth/refresh"

HARNESS = """
const handlers = {};
global.window = { location: { pathname: '/overseer/components/worker' } };
global.document = { addEventListener: (name, fn) => { (handlers[name] ||= []).push(fn); } };
const calls = [];
let sessionValid = false;
global.fetch = async (path, opts) => {
  calls.push(path);
  if (path === '/api/v1/auth/refresh') { sessionValid = true; return { ok: true, status: 200 }; }
  return sessionValid ? { ok: true, status: 200 } : { ok: false, status: 401 };
};
require(%s);
(async () => {
  for (let i = 0; i < ERRORS; i++) {
    for (const fn of handlers['htmx:sseError'] || []) fn({});
  }
  await new Promise((r) => setTimeout(r, 50));
  console.log(JSON.stringify(calls));
})();
"""


def _stream_errors(count: int) -> list[str]:
    script = HARNESS.replace("ERRORS", str(count)) % json.dumps(str(AUTH_JS.resolve()))
    return run(script)


def test_a_stream_error_renews_an_expired_session() -> None:
    assert _stream_errors(1) == [
        "/api/v1/auth/me",
        "/api/v1/auth/refresh",
        "/api/v1/auth/me",
    ]


def test_a_burst_of_errors_probes_once() -> None:
    """Every retry fires an error; one probe covers the burst."""
    assert _stream_errors(5).count("/api/v1/auth/refresh") == 1


BOUNCE_HARNESS = """
const handlers = {};
global.window = { location: { pathname: PATH } };
global.document = { addEventListener: (name, fn) => { (handlers[name] ||= []).push(fn); } };
global.fetch = async () => ({ ok: false, status: 401 });
require(%s);
(async () => {
  for (const fn of handlers['htmx:responseError'] || []) fn({ detail: { xhr: { status: 401 } } });
  await new Promise((r) => setTimeout(r, 50));
  console.log(JSON.stringify(String(window.location)));
})();
"""


def _bounced_from(path: str) -> str:
    script = BOUNCE_HARNESS.replace("PATH", json.dumps(path))
    return run(script % json.dumps(str(AUTH_JS.resolve())))


def test_a_session_past_renewing_signs_in_where_the_page_does() -> None:
    """An htmx request refused for a dead session (no refresh to be had)
    goes to the sign-in its page uses, Overseer's own or the app's, and
    back to the page after."""
    assert (
        _bounced_from("/overseer/components/worker")
        == "/overseer/login?next=%2Foverseer%2Fcomponents%2Fworker"
    )
    assert _bounced_from("/notes") == "/login?next=%2Fnotes"


SIGN_IN_HARNESS = """
const handlers = {}, components = {}, calls = [];
const stored = STORED;
global.window = { location: { pathname: PATH, search: SEARCH } };
global.document = {
  addEventListener: (name, fn) => { (handlers[name] ||= []).push(fn); },
  // The page's hidden ``next``: the server has already kept it on the site.
  querySelector: (sel) => (sel === 'input[name=next]' && NEXT ? { value: NEXT } : null),
};
global.sessionStorage = {
  getItem: (k) => (k in stored ? stored[k] : null),
  setItem: (k, v) => { stored[k] = v; },
};
global.Alpine = { data: (name, make) => { components[name] = make; } };
global.fetch = async (path) => { calls.push(path); return { ok: RENEWS, status: RENEWS ? 200 : 401 }; };
require(%s);
(async () => {
  for (const fn of handlers['alpine:init'] || []) fn();
  components.loginForm().init();
  await new Promise((r) => setTimeout(r, 50));
  const where = typeof window.location === 'string' ? window.location : 'stayed';
  console.log(JSON.stringify([where, calls]));
})();
"""


def _signing_in(
    path: str,
    search: str = "",
    renews: bool = True,
    stored: str = "{}",
    next_: str = "",
) -> list:
    script = (
        SIGN_IN_HARNESS.replace("STORED", stored)
        .replace("NEXT", json.dumps(next_))
        .replace("PATH", json.dumps(path))
        .replace("SEARCH", json.dumps(search))
        .replace("RENEWS", "true" if renews else "false")
    )
    return run(script % json.dumps(str(AUTH_JS.resolve())))


@pytest.mark.parametrize(
    ("path", "next_", "lands"),
    [
        (
            "/overseer/login",
            "/overseer/components/worker",
            "/overseer/components/worker",
        ),
        ("/overseer/login", "", "/overseer"),
        ("/login", "/notes", "/notes"),
        ("/login", "", "/"),
    ],
)
def test_a_returning_viewer_whose_session_ran_out_is_renewed_not_asked(
    path: str, next_: str, lands: str
) -> None:
    """A full page load with an expired session lands on sign-in: it renews
    the session from the refresh cookie first and goes back to the page
    asked for (the form's ``next``, which the server keeps on the site), so
    only a dead refresh shows the form."""
    assert _signing_in(path, next_=next_) == [lands, [REFRESH]]


def test_a_refresh_that_fails_leaves_the_form() -> None:
    assert _signing_in("/login", renews=False) == ["stayed", [REFRESH]]


def test_a_refused_sign_in_does_not_try_to_renew() -> None:
    """The form came back with why it refused: nothing to renew."""
    assert _signing_in("/login", "?error=invalid") == ["stayed", []]


def test_a_renewal_the_server_then_refuses_is_not_tried_again_at_once() -> None:
    """Renewed, sent back, and bounced to sign-in again (a session the
    pages still refuse): the form, not a loop."""
    recent = json.dumps({"aegis.renewedAt": "9999999999999"})
    assert _signing_in("/login", stored=recent) == ["stayed", []]
