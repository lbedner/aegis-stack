"""Without the auth service Overseer is open: no page or partial refuses
anyone, and the operator's changes are the local dev build's
(``operator_refusal``; tests/api/test_operator_refusal.py walks them). With
auth it is admins only, and tests/web/test_overseer_admin_gate.py walks the
same routes as a member."""

from importlib.util import find_spec
from pathlib import Path
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.services.shared.deps import NO_AUTH_REFUSAL
from tests.web.dom import none, one, select, text
from tests.web.overseer import overseer_calls, sign_in, status_with

pytestmark = pytest.mark.skipif(
    find_spec("app.services.auth") is not None,
    reason="with auth, Overseer is admins only (test_overseer_admin_gate.py)",
)


def test_nothing_refuses_the_local_dev_build(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its writes included: at localhost the real rule (nothing overridden)
    lets every page, partial and action through."""
    sign_in(app, monkeypatch, status_with(), admin=False)
    # A 500 is not a refusal; this walk asks only who may get in.
    client = TestClient(
        app, base_url="http://localhost:8000", raise_server_exceptions=False
    )
    calls = [(m, p) for m, p in overseer_calls(app) if "/events" not in p]
    assert ("GET", "/overseer") in calls
    refused = []
    for method, path in calls:
        response = client.request(method, path, follow_redirects=False)
        to_login = "login" in response.headers.get("location", "")
        if response.status_code in (401, 403) or to_login:
            refused.append((method, path, response.status_code))
    assert not refused, f"refused without auth: {refused}"


def test_nothing_fails_for_a_missing_component(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A component's partials are there only when it is, so none crashes
    (500) in a stack without it; an unreachable runtime is a 503."""
    sign_in(app, monkeypatch, status_with())
    client = TestClient(app, raise_server_exceptions=False)
    calls = [(m, p) for m, p in overseer_calls(app) if "/events" not in p]
    failed = [
        (method, path)
        for method, path in calls
        if client.request(method, path, follow_redirects=False).status_code == 500
    ]
    assert not failed


def test_the_home_page_opens(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in(app, monkeypatch, status_with())
    response = TestClient(app).get("/overseer")
    assert response.status_code == 200
    assert not select(response.text, 'a[href="/logout"]')  # nobody to sign out


def test_another_host_sees_why_the_write_controls_are_hidden(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``testserver`` is not the local dev build: the shell says why, and
    marks itself so every write control (``data-write``) is hidden."""
    sign_in(app, monkeypatch, status_with(), admin=False)
    html = TestClient(app).get("/overseer").text
    one(html, "[data-read-only]")
    assert text(one(html, "[data-operator-refusal]")) == NO_AUTH_REFUSAL


def test_the_local_dev_build_keeps_them(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    sign_in(app, monkeypatch, status_with())
    html = TestClient(app, base_url="http://localhost:8000").get("/overseer").text
    none(html, "[data-read-only]")
    none(html, "[data-operator-refusal]")


def test_a_read_only_shell_hides_every_write_control() -> None:
    """Anywhere on the page, a dialog or drawer included."""
    css = Path("app/components/web_frontend/static/input.css").read_text()
    assert re.search(
        r"body:has\(\[data-read-only\]\) \[data-write\]\s*\{\s*display:\s*none",
        css,
    )
