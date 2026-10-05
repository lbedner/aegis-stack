"""The sign-in form says why it refused, as far as it safely can."""

from typing import Any

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend.routes import pages
from app.core.config import settings


@pytest.mark.parametrize(("status_code", "reason"), [(403, "disabled"), (401, "invalid")])
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


@pytest.mark.parametrize(("open_", "says"), [(True, "Create an account"), (False, "closed")])
def test_the_sign_in_page_reads_whether_signups_are_open_as_it_renders(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, open_: bool, says: str
) -> None:
    """``REGISTRATION_ENABLED`` saved in the Overseer applies once the process
    has booted, so the page reads it each time, not at import."""
    monkeypatch.setattr(settings, "REGISTRATION_ENABLED", open_)
    assert says in client.get("/login").text
