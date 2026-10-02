"""``settings``: the settings marked ``Configurable`` from the terminal.
A value goes in as an argument (these are not secrets), is checked against
the setting's type, and applies when the app restarts."""

import pytest

from tests._cli import invoke
from tests._secret_settings import FakeStore, settings_at_default, use_store

NAME = "MEMORY_THRESHOLD_PERCENT"


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    settings_at_default(monkeypatch)
    return use_store(monkeypatch)


def test_list_shows_the_value_source_and_default(store: FakeStore) -> None:
    result = invoke(["settings", "list"])
    assert result.exit_code == 0, result.output
    assert NAME in result.output and "Default" in result.output
    assert "90.0" in result.output


def test_set_saves_it_and_says_when_it_applies(store: FakeStore) -> None:
    result = invoke(["settings", "set", NAME, "75"])
    assert result.exit_code == 0, result.output
    assert store.values[NAME] == "75.0" and "restart" in result.output


def test_a_value_that_does_not_fit_is_refused(store: FakeStore) -> None:
    result = invoke(["settings", "set", NAME, "lots"])
    assert result.exit_code == 1 and NAME not in store.values


def test_reset_goes_back_to_the_default(store: FakeStore) -> None:
    store.values[NAME] = "75"
    assert invoke(["settings", "reset", NAME]).exit_code == 0
    assert NAME not in store.values


def test_a_credential_is_not_a_setting(store: FakeStore) -> None:
    result = invoke(["settings", "set", "OPENAI_API_KEY", "sk-x"])
    assert result.exit_code == 1 and "secrets" in result.output
