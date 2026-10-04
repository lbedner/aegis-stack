"""Without the auth service Overseer is open: no page, partial or action
refuses anyone. With auth it is admins only, and
tests/web/test_overseer_admin_gate.py walks the same routes as a member."""

from importlib.util import find_spec

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from tests.web.dom import select
from tests.web.overseer import overseer_calls, sign_in, status_with

pytestmark = pytest.mark.skipif(
    find_spec("app.services.auth") is not None,
    reason="with auth, Overseer is admins only (test_overseer_admin_gate.py)",
)


def test_nothing_refuses_anyone(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in(app, monkeypatch, status_with())
    # A 500 is not a refusal; this walk asks only who may get in.
    client = TestClient(app, raise_server_exceptions=False)
    calls = [(m, p) for m, p in overseer_calls(app) if "/events" not in p]
    assert ("GET", "/overseer") in calls
    refused = []
    for method, path in calls:
        response = client.request(method, path, follow_redirects=False)
        to_login = "login" in response.headers.get("location", "")
        if response.status_code in (401, 403) or to_login:
            refused.append((method, path, response.status_code))
    assert not refused, f"refused without auth: {refused}"


def test_the_home_page_opens(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in(app, monkeypatch, status_with())
    response = TestClient(app).get("/overseer")
    assert response.status_code == 200
    assert not select(response.text, 'a[href="/logout"]')  # nobody to sign out
