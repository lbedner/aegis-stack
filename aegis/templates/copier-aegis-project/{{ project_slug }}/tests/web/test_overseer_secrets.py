"""The Overseer Secrets page: every credential the app declares, where it
is set and its last four characters, never the value; for one that is
missing, the ``.env`` line to add. Read-only until a writable store is
installed (the secrets component)."""

from collections.abc import Generator

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend import overseer_secrets
from app.core import secrets
from app.core.config import settings
from app.core.secrets import Secret
from app.services.system.models import ComponentStatus
from tests._secret_settings import FakeStore, use_store
from tests.web.dom import one, row_text, select, text
from tests.web.overseer import sign_in, status_with

KEY = "sk-test-0123456789wxyz"
# The component's health entry: with the component installed its page under
# Components is where the Secrets page lives.
SECRETS_ENTRY = ComponentStatus(name="secrets", message="")
DECLARED = (
    Secret("OPENAI_API_KEY", owner="AI"),
    Secret("ANTHROPIC_API_KEY", owner="AI"),
    Secret("RESEND_FROM_EMAIL", owner="Email", label="From address", secret=False),
)


@pytest.fixture
def page(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> Generator[str]:
    sign_in(app, monkeypatch, status_with(SECRETS_ENTRY))
    monkeypatch.setattr(secrets, "declared", lambda: DECLARED)
    monkeypatch.setitem(settings.__dict__, "OPENAI_API_KEY", KEY)
    monkeypatch.setitem(settings.__dict__, "ANTHROPIC_API_KEY", None)
    monkeypatch.setitem(settings.__dict__, "RESEND_FROM_EMAIL", "hi@example.com")
    response = TestClient(app).get("/overseer/secrets")
    assert response.status_code == 200, response.text
    yield response.text


def _row(html: str, name: str) -> str:
    return row_text(html, "#secrets tbody tr", name)


def test_the_sidebar_links_to_it(page: str) -> None:
    link = one(page, f'#overseer-sidebar a[href="{overseer_secrets.url()}"]')
    assert link.get("aria-current") == "page"


def test_with_the_component_secrets_live_on_its_page(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One home: the component's page under Components, not a second
    top-level page beside it. The old address forwards there."""
    sign_in(app, monkeypatch, status_with(SECRETS_ENTRY))
    monkeypatch.setattr(secrets, "declared", lambda: DECLARED)
    monkeypatch.setattr(overseer_secrets, "has_component", lambda: True)
    client = TestClient(app)
    moved = client.get("/overseer/secrets", follow_redirects=False)
    assert moved.status_code == 303
    assert moved.headers["location"] == "/overseer/components/secrets"
    html = client.get("/overseer/components/secrets").text
    assert one(html, "#secrets") is not None
    assert not select(html, '#overseer-sidebar a[href="/overseer/secrets"]')


def test_without_the_component_the_page_stays_at_the_top(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    sign_in(app, monkeypatch, status_with(SECRETS_ENTRY))
    monkeypatch.setattr(secrets, "declared", lambda: DECLARED)
    monkeypatch.setattr(overseer_secrets, "has_component", lambda: False)
    html = TestClient(app).get("/overseer/secrets").text
    assert one(html, '#overseer-sidebar a[href="/overseer/secrets"]') is not None


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
    assert "Not used" in row and "ANTHROPIC_API_KEY=" in row


def test_provider_config_shows_whole(page: str) -> None:
    assert "hi@example.com" in _row(page, "RESEND_FROM_EMAIL")


def test_it_says_how_values_change(page: str) -> None:
    """Read-only on the env backend: a restart is what changes a value."""
    assert "restart" in text(one(page, "#secrets-backend")).lower()


@pytest.fixture
def writable(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, FakeStore]:
    sign_in(app, monkeypatch, status_with(SECRETS_ENTRY))
    monkeypatch.setattr(secrets, "declared", lambda: DECLARED)
    monkeypatch.setitem(settings.__dict__, "OPENAI_API_KEY", KEY)
    monkeypatch.setitem(settings.__dict__, "ANTHROPIC_API_KEY", None)
    monkeypatch.setitem(settings.__dict__, "RESEND_FROM_EMAIL", None)
    return TestClient(app), use_store(monkeypatch)


PARTIALS = "/partials/overseer/secrets"


def test_a_settable_secret_offers_set_and_one_in_env_does_not(
    writable: tuple[TestClient, FakeStore],
) -> None:
    client, _ = writable
    html = client.get("/overseer/secrets").text
    assert (
        one(html, f'#secrets button[hx-get="{PARTIALS}/ANTHROPIC_API_KEY"]') is not None
    )
    assert not select(html, f'#secrets button[hx-get="{PARTIALS}/OPENAI_API_KEY"]')
    assert "change it in .env" in _row(html, "OPENAI_API_KEY").lower()


def test_the_dialog_never_shows_the_value(
    writable: tuple[TestClient, FakeStore],
) -> None:
    client, store = writable
    store.values["ANTHROPIC_API_KEY"] = "sk-ant-stored-0000wxyz"
    html = client.get(f"{PARTIALS}/ANTHROPIC_API_KEY").text
    field = one(html, 'input[name="value"]')
    assert field.get("type") == "password" and not field.get("value")
    assert "sk-ant-stored" not in html


def test_saving_stores_it_and_echoes_nothing(
    writable: tuple[TestClient, FakeStore],
) -> None:
    client, store = writable
    response = client.post(
        f"{PARTIALS}/ANTHROPIC_API_KEY", data={"value": "sk-ant-new-0000abcd"}
    )
    assert response.status_code == 200
    assert store.values["ANTHROPIC_API_KEY"] == "sk-ant-new-0000abcd"
    assert "sk-ant-new" not in response.text + str(response.headers)


def test_remove_clears_a_stored_value(writable: tuple[TestClient, FakeStore]) -> None:
    client, store = writable
    store.values["ANTHROPIC_API_KEY"] = "sk-ant-stored-0000wxyz"
    assert client.post(f"{PARTIALS}/ANTHROPIC_API_KEY/remove").status_code == 200
    assert "ANTHROPIC_API_KEY" not in store.values


def test_a_refused_write_says_why(writable: tuple[TestClient, FakeStore]) -> None:
    client, _ = writable
    response = client.post(
        f"{PARTIALS}/OPENAI_API_KEY", data={"value": "sk-other-000000"}
    )
    assert response.status_code == 422 and ".env" in response.text


def test_a_read_only_backend_names_where_to_change_it(
    writable: tuple[TestClient, FakeStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store = writable
    monkeypatch.setattr(store, "name", "vault")
    monkeypatch.setattr(store, "writable", False)
    html = client.get("/overseer/secrets").text
    assert not select(html, f'#secrets button[hx-get^="{PARTIALS}/"]')
    assert "vault" in text(one(html, "#secrets-backend")).lower()


async def _accepts(value: str) -> None:
    return None


async def _refuses(value: str) -> None:
    raise secrets.SecretRejectedError("api.example.com refused it (401).")


def _checked(monkeypatch: pytest.MonkeyPatch, verify: object) -> None:
    monkeypatch.setattr(
        secrets,
        "declared",
        lambda: (
            Secret("OPENAI_API_KEY", owner="AI", needed=True, verify=verify),
            Secret("ANTHROPIC_API_KEY", owner="AI", needed=True, verify=verify),
            Secret("RESEND_FROM_EMAIL", owner="Email", secret=False),
        ),
    )


def test_a_missing_needed_key_reads_apart_from_an_optional_one(
    writable: tuple[TestClient, FakeStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = writable
    _checked(monkeypatch, _accepts)
    html = client.get("/overseer/secrets").text
    assert "Missing" in _row(html, "ANTHROPIC_API_KEY")
    assert "Not used" in _row(html, "RESEND_FROM_EMAIL")
    assert "1 of 2 needed" in text(one(html, "#secrets-summary"))


def test_a_key_with_a_check_offers_test_wherever_it_is_set(
    writable: tuple[TestClient, FakeStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = writable
    _checked(monkeypatch, _accepts)
    html = client.get("/overseer/secrets").text
    assert (
        one(html, f'#secrets button[hx-post="{PARTIALS}/OPENAI_API_KEY/test"]')
        is not None
    )
    assert not select(
        html, f'#secrets button[hx-post="{PARTIALS}/ANTHROPIC_API_KEY/test"]'
    )
    response = client.post(f"{PARTIALS}/OPENAI_API_KEY/test")
    assert response.status_code == 200
    assert "works" in response.headers["HX-Trigger"] and KEY not in str(
        response.headers
    )


def test_a_key_the_provider_refuses_is_not_saved(
    writable: tuple[TestClient, FakeStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store = writable
    _checked(monkeypatch, _refuses)
    response = client.post(
        f"{PARTIALS}/ANTHROPIC_API_KEY", data={"value": "sk-ant-typo-000000"}
    )
    assert response.status_code == 422 and "refused" in response.text
    assert store.values == {}


def test_a_saved_key_says_it_was_verified(
    writable: tuple[TestClient, FakeStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = writable
    _checked(monkeypatch, _accepts)
    response = client.post(
        f"{PARTIALS}/ANTHROPIC_API_KEY", data={"value": "sk-ant-good-000000"}
    )
    assert "verified" in response.headers["HX-Trigger"]


def test_a_key_read_through_settings_is_listed_but_not_settable(
    writable: tuple[TestClient, FakeStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = writable
    monkeypatch.setattr(
        secrets,
        "declared",
        lambda: (Secret("ANTHROPIC_API_KEY", owner="App", live=False),),
    )
    html = client.get("/overseer/secrets").text
    assert not select(html, f'#secrets button[hx-get="{PARTIALS}/ANTHROPIC_API_KEY"]')
    assert "set it in .env" in _row(html, "ANTHROPIC_API_KEY").lower()


async def _domains() -> list[tuple[str, str]]:
    return [("hello@mail.example.com", "mail.example.com (verified in Resend)")]


def test_a_field_with_choices_offers_them_and_still_takes_typing(
    writable: tuple[TestClient, FakeStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = writable
    monkeypatch.setattr(
        secrets,
        "declared",
        lambda: (
            Secret("RESEND_FROM_EMAIL", owner="Email", secret=False, choices=_domains),
        ),
    )
    html = client.get(f"{PARTIALS}/RESEND_FROM_EMAIL").text
    field = one(html, 'input[name="value"]')
    options = select(html, f"datalist#{field.get('list')} option")
    assert [o.get("value") for o in options] == ["hello@mail.example.com"]
    assert "verified in Resend" in (options[0].get("label") or "")
