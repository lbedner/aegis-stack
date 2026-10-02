"""``secrets``: list, set, delete and test declared credentials from the
terminal. A value comes in through a hidden prompt or stdin, never argv,
and nothing prints it back."""

from collections.abc import Iterator
from typing import Any

import pytest

from app.core import secrets
from app.core.config import settings
from app.core.secrets import Secret, StoredSecret
from tests._cli import invoke

KEY = "sk-live-0123456789abcdWXYZ"


class FakeStore:
    name = "database"
    writable = True

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.actors: list[str] = []

    async def get(self, name: str) -> str | None:
        return self.values.get(name)

    async def get_many(self, names: list[str]) -> dict[str, str | None]:
        return {name: self.values.get(name) for name in names}

    async def put(self, name: str, value: str, hint: str | None, actor: str) -> None:
        self.values[name] = value
        self.actors.append(actor)

    async def delete(self, name: str, actor: str) -> None:
        self.values.pop(name, None)

    async def stored(self) -> dict[str, StoredSecret]:
        return {n: StoredSecret(hint=v[-4:]) for n, v in self.values.items()}


async def _accepts(value: str) -> None:
    return None


async def _refuses(value: str) -> None:
    raise secrets.SecretRejectedError("api.example.com refused it (401).")


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeStore]:
    fake = FakeStore()
    secrets.set_store(fake)
    monkeypatch.setitem(settings.__dict__, "TEST_API_KEY", None)
    monkeypatch.setitem(settings.__dict__, "TEST_OTHER_KEY", None)
    _declare(monkeypatch, _accepts)
    yield fake
    secrets.set_store(None)


def _declare(monkeypatch: pytest.MonkeyPatch, verify: Any) -> None:
    monkeypatch.setattr(
        secrets,
        "declared",
        lambda: (
            Secret("TEST_API_KEY", owner="Test", needed=True, verify=verify),
            Secret("TEST_OTHER_KEY", owner="Test"),
        ),
    )


def test_set_reads_stdin_stores_and_never_echoes(store: FakeStore) -> None:
    result = invoke(["secrets", "set", "TEST_API_KEY"], input=KEY + "\n")
    assert result.exit_code == 0, result.output
    assert store.values == {"TEST_API_KEY": KEY}
    assert store.actors[0].startswith("cli:")
    assert "verified" in result.output and KEY not in result.output


def test_a_refused_key_fails_and_is_not_stored(
    store: FakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _declare(monkeypatch, _refuses)
    result = invoke(["secrets", "set", "TEST_API_KEY"], input=KEY)
    assert result.exit_code == 1 and "refused" in result.output
    assert store.values == {}


def test_list_shows_needed_apart_from_optional_never_a_value(store: FakeStore) -> None:
    store.values["TEST_OTHER_KEY"] = KEY
    result = invoke(["secrets", "list"])
    assert result.exit_code == 0, result.output
    assert "Missing" in result.output and "WXYZ" in result.output
    assert KEY not in result.output


def test_delete_and_test(store: FakeStore) -> None:
    store.values["TEST_API_KEY"] = KEY
    tested = invoke(["secrets", "test", "TEST_API_KEY"])
    assert tested.exit_code == 0 and "works" in tested.output
    assert invoke(["secrets", "delete", "TEST_API_KEY"]).exit_code == 0
    assert store.values == {}


def test_an_unknown_name_fails(store: FakeStore) -> None:
    result = invoke(["secrets", "set", "PATH"], input="x")
    assert result.exit_code == 1 and "not a declared secret" in result.output
