"""The Overseer Settings page: every ``Configurable`` setting, grouped by
what reads it, with its value, where it comes from and its default. With a
writable store (the secrets component) one not set in ``.env`` is saved
here, through the Secrets page's own dialog, and applies on restart."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.core import saved_settings, secrets
from tests._secret_settings import FakeStore, settings_at_default, use_store
from tests.web.dom import location, one, row_text, select, text, triggers
from tests.web.overseer import sign_in, status_with

NAME = "MEMORY_THRESHOLD_PERCENT"
PARTIALS = "/partials/overseer/secrets"


@pytest.fixture
def client(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, FakeStore]:
    sign_in(app, monkeypatch, status_with())
    settings_at_default(monkeypatch)
    return TestClient(app), use_store(monkeypatch)


def _page(client: tuple[TestClient, FakeStore]) -> str:
    response = client[0].get("/overseer/settings")
    assert response.status_code == 200, response.text
    return response.text


def _row(html: str, name: str = NAME) -> str:
    return row_text(html, "#settings tbody tr", name)


def test_the_sidebar_links_to_it(client: tuple[TestClient, FakeStore]) -> None:
    link = one(_page(client), '#overseer-sidebar a[href="/overseer/settings"]')
    assert link.get("aria-current") == "page"


def test_settings_show_their_value_source_and_default(
    client: tuple[TestClient, FakeStore],
) -> None:
    html = _page(client)
    assert "Health" in [text(h) for h in select(html, "#settings [data-owner]")]
    row = _row(html)
    assert "Default" in row and "90.0" in row


def test_settings_stay_off_the_secrets_page(
    client: tuple[TestClient, FakeStore],
) -> None:
    assert NAME not in client[0].get("/overseer/secrets").text


def test_saving_one_says_it_applies_on_restart(
    client: tuple[TestClient, FakeStore],
) -> None:
    http, store = client
    assert (
        one(_page(client), f'#settings button[hx-get="{PARTIALS}/{NAME}"]') is not None
    )
    response = http.post(f"{PARTIALS}/{NAME}", data={"value": "75"})
    assert store.values[NAME] == "75.0"  # one spelling: the float's
    assert location(response) == "/overseer/settings"
    assert "restart" in str(triggers(response)).lower()


def test_a_value_that_does_not_fit_is_refused(
    client: tuple[TestClient, FakeStore],
) -> None:
    http, store = client
    response = http.post(f"{PARTIALS}/{NAME}", data={"value": "lots"})
    assert response.status_code == 422 and NAME not in store.values


def test_one_set_in_env_is_changed_there(
    client: tuple[TestClient, FakeStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(saved_settings, "IN_ENV", frozenset({NAME}))
    html = _page(client)
    assert not select(html, f'#settings button[hx-get="{PARTIALS}/{NAME}"]')
    assert "change it in .env" in _row(html).lower()


def test_without_a_store_it_says_values_come_from_env(
    client: tuple[TestClient, FakeStore],
) -> None:
    secrets.set_store(None)
    html = _page(client)
    assert not select(html, f'#settings button[hx-get^="{PARTIALS}/"]')
    assert ".env" in text(one(html, "#settings-backend"))


def test_a_setting_with_choices_is_picked_from_a_list(
    client: tuple[TestClient, FakeStore],
) -> None:
    """A closed set of values (a bool here) is a select, not a text field,
    with the value in effect already chosen."""
    html = client[0].get(f"{PARTIALS}/TRAFFIC_MONITOR_ENABLED").text
    picker = one(html, 'select[name="value"]')
    assert [o.get("value") for o in picker.findall(".//option")] == ["True", "False"]
    assert one(html, "option[selected]").get("value") == "True"
