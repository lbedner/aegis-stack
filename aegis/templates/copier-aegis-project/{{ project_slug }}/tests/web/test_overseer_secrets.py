"""The Overseer Secrets page: every credential the app declares, where it
is set and its last four characters, never the value; for one that is
missing, the ``.env`` line to add. Read-only until a writable store is
installed (the secrets component)."""

from collections.abc import Generator

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.core import secrets
from app.core.config import settings
from app.core.secrets import Secret
from tests.web.dom import one, select, text
from tests.web.overseer import sign_in, status_with

KEY = "sk-test-0123456789wxyz"
DECLARED = (
    Secret("OPENAI_API_KEY", owner="AI"),
    Secret("ANTHROPIC_API_KEY", owner="AI"),
    Secret("RESEND_FROM_EMAIL", owner="Email", label="From address", secret=False),
)


@pytest.fixture
def page(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> Generator[str]:
    sign_in(app, monkeypatch, status_with())
    monkeypatch.setattr(secrets, "declared", lambda: DECLARED)
    monkeypatch.setitem(settings.__dict__, "OPENAI_API_KEY", KEY)
    monkeypatch.setitem(settings.__dict__, "ANTHROPIC_API_KEY", None)
    monkeypatch.setitem(settings.__dict__, "RESEND_FROM_EMAIL", "hi@example.com")
    response = TestClient(app).get("/overseer/secrets")
    assert response.status_code == 200, response.text
    yield response.text


def _row(html: str, name: str) -> str:
    return next(
        text(row) for row in select(html, "#secrets tbody tr") if name in text(row)
    )


def test_the_sidebar_links_to_it(page: str) -> None:
    link = one(page, '#overseer-sidebar a[href="/overseer/secrets"]')
    assert link.get("aria-current") == "page"


def test_secrets_are_grouped_by_who_reads_them(page: str) -> None:
    groups = [text(h) for h in select(page, "#secrets [data-owner]")]
    assert groups == ["AI", "Email"]


def test_a_set_secret_shows_its_source_and_last_four_never_the_value(
    page: str,
) -> None:
    row = _row(page, "OPENAI_API_KEY")
    assert ".env" in row and "wxyz" in row
    assert KEY not in page


def test_a_missing_secret_says_what_to_add(page: str) -> None:
    row = _row(page, "ANTHROPIC_API_KEY")
    assert "Not set" in row and "ANTHROPIC_API_KEY=" in row


def test_provider_config_shows_whole(page: str) -> None:
    assert "hi@example.com" in _row(page, "RESEND_FROM_EMAIL")


def test_it_says_how_values_change(page: str) -> None:
    """Read-only on the env backend: a restart is what changes a value."""
    assert "restart" in text(one(page, "#secrets-backend")).lower()
