"""Live streams survive an expired session (static/js/auth.js, run in node).

An EventSource cannot refresh a session: once the 15-minute access token
expires, every reconnect is refused and a live page silently stops
updating. auth.js answers a stream error by probing the session through
the refresh-on-401 wrapper, so the SSE extension's next retry connects.
"""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

AUTH_JS = Path("app/components/web_frontend/static/js/auth.js")

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
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    script = HARNESS.replace("ERRORS", str(count)) % json.dumps(str(AUTH_JS.resolve()))
    out = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, check=True
    ).stdout
    return json.loads(out)


def test_a_stream_error_renews_an_expired_session() -> None:
    assert _stream_errors(1) == [
        "/api/v1/auth/me",
        "/api/v1/auth/refresh",
        "/api/v1/auth/me",
    ]


def test_a_burst_of_errors_probes_once() -> None:
    """Every retry fires an error; one probe covers the burst."""
    assert _stream_errors(5).count("/api/v1/auth/refresh") == 1
