"""The sign-in form says why it refused, as far as it safely can."""

from typing import Any

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from starlette.requests import Request

from app.components.web_frontend.routes import pages
from app.core.config import settings


@pytest.mark.parametrize(
    ("status_code", "reason"), [(403, "disabled"), (401, "invalid")]
)
def test_maps_the_api_refusal_to_a_reason(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, status_code: int, reason: str
) -> None:
    """A 403 comes only after a correct password (disabled account); every
    other refusal stays one generic message."""

    async def refuse(**_: Any) -> None:
        raise HTTPException(status_code=status_code, detail="refused")

    monkeypatch.setattr(pages, "api_login", refuse)
    response = client.post(
        "/login",
        data={"email": "a@example.com", "password": "whatever-long"},
        follow_redirects=False,
    )
    assert response.headers["location"] == f"/login?error={reason}"


@pytest.mark.parametrize(
    ("open_", "says"), [(True, "Create an account"), (False, "closed")]
)
def test_the_sign_in_page_reads_whether_signups_are_open_as_it_renders(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, open_: bool, says: str
) -> None:
    """``REGISTRATION_ENABLED`` saved in the Overseer applies once the process
    has booted, so the page reads it each time, not at import."""
    monkeypatch.setattr(settings, "REGISTRATION_ENABLED", open_)
    assert says in client.get("/login").text


def _asking(htmx: bool) -> Request:
    headers = [(b"hx-request", b"true")] if htmx else []
    return Request(
        {"type": "http", "method": "GET", "path": "/notes", "headers": headers}
    )


def test_a_page_signed_out_takes_the_whole_page_to_login() -> None:
    """A page that needs a user bounces a signed-out visitor to sign in;
    asked by htmx (a session that ran out mid-page), a plain 401, which
    auth.js renews the session on, or htmx swaps the login page into the
    shell."""
    plain = pages._current_user_or_redirect(_asking(htmx=False), None)
    assert plain is not None and plain.status_code == 303
    assert plain.headers["location"] == "/login?next=/notes"
    swapped = pages._current_user_or_redirect(_asking(htmx=True), None)
    assert swapped is not None and swapped.status_code == 401
    assert "hx-redirect" not in swapped.headers
