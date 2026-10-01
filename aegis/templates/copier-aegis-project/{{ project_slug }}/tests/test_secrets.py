"""Credentials behind one interface (``app.core.secrets``).

``.env`` is the zero-setup backend: read-only, changed by a restart. A
writable store (the secrets component) plugs in behind the same calls, and
a value set in ``.env`` still wins over it. Nothing here ever hands back a
stored value except ``get`` to the code that uses it.
"""

from datetime import UTC, datetime

import pytest

from app.core import secrets
from app.core.config import settings
from app.core.secrets import Secret, StoredSecret

KEY = "sk-test-0123456789abcd"
DECLARED = (
    Secret("OPENAI_API_KEY", owner="AI"),
    Secret("RESEND_FROM_EMAIL", owner="Email", label="From address", secret=False),
)


class FakeStore:
    """A writable backend, the shape the secrets component implements."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, name: str) -> str | None:
        return self.values.get(name)

    async def put(self, name: str, value: str, actor: str) -> None:
        self.values[name] = value

    async def stored(self) -> dict[str, StoredSecret]:
        return {
            name: StoredSecret(
                hint=value[-4:], set_at=datetime(2026, 10, 1, tzinfo=UTC), set_by="ops"
            )
            for name, value in self.values.items()
        }


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.setattr(secrets, "declared", lambda: DECLARED)
    monkeypatch.setitem(settings.__dict__, "OPENAI_API_KEY", None)
    monkeypatch.setitem(settings.__dict__, "RESEND_FROM_EMAIL", None)
    yield monkeypatch
    secrets.set_store(None)


async def test_a_value_in_env_resolves(env: pytest.MonkeyPatch) -> None:
    env.setitem(settings.__dict__, "OPENAI_API_KEY", KEY)
    assert await secrets.get("OPENAI_API_KEY") == KEY


async def test_unset_and_blank_are_none(env: pytest.MonkeyPatch) -> None:
    assert await secrets.get("OPENAI_API_KEY") is None
    env.setitem(settings.__dict__, "OPENAI_API_KEY", "  ")
    assert await secrets.get("OPENAI_API_KEY") is None


async def test_env_wins_over_a_stored_value(env: pytest.MonkeyPatch) -> None:
    store = FakeStore()
    store.values["OPENAI_API_KEY"] = "sk-stored-zzzz"
    secrets.set_store(store)
    assert await secrets.get("OPENAI_API_KEY") == "sk-stored-zzzz"
    env.setitem(settings.__dict__, "OPENAI_API_KEY", KEY)
    assert await secrets.get("OPENAI_API_KEY") == KEY


async def test_without_a_store_writes_refuse_and_say_why() -> None:
    with pytest.raises(secrets.SecretsReadOnlyError, match="OPENAI_API_KEY in .env"):
        await secrets.put("OPENAI_API_KEY", KEY, actor="ops")


async def test_a_name_set_in_env_refuses_writes(env: pytest.MonkeyPatch) -> None:
    secrets.set_store(FakeStore())
    env.setitem(settings.__dict__, "OPENAI_API_KEY", KEY)
    with pytest.raises(secrets.SecretsReadOnlyError, match="set in .env"):
        await secrets.put("OPENAI_API_KEY", "sk-other", actor="ops")


async def test_only_declared_names_are_written() -> None:
    secrets.set_store(FakeStore())
    with pytest.raises(secrets.UnknownSecretError):
        await secrets.put("PATH", "x", actor="ops")


async def test_status_says_where_each_comes_from_never_the_value(
    env: pytest.MonkeyPatch,
) -> None:
    env.setitem(settings.__dict__, "OPENAI_API_KEY", KEY)
    env.setitem(settings.__dict__, "RESEND_FROM_EMAIL", "hi@example.com")
    rows = {row.name: row for row in await secrets.status()}
    assert rows["OPENAI_API_KEY"].source == "env"
    assert rows["OPENAI_API_KEY"].hint == "abcd"
    assert KEY not in repr(rows["OPENAI_API_KEY"])
    # Provider config is safe to show whole: a from address, not a secret.
    assert rows["RESEND_FROM_EMAIL"].hint == "hi@example.com"


async def test_status_reports_a_stored_secret_with_who_and_when() -> None:
    store = FakeStore()
    store.values["OPENAI_API_KEY"] = KEY
    secrets.set_store(store)
    row = next(r for r in await secrets.status() if r.name == "OPENAI_API_KEY")
    assert (row.source, row.hint, row.set_by) == ("database", "abcd", "ops")


async def test_a_missing_secret_is_unset() -> None:
    row = next(r for r in await secrets.status() if r.name == "OPENAI_API_KEY")
    assert row.source is None and row.hint is None and not row.is_set


async def test_a_short_secret_shows_no_hint(env: pytest.MonkeyPatch) -> None:
    """Four characters of a six-character value is most of it."""
    env.setitem(settings.__dict__, "OPENAI_API_KEY", "abc123")
    row = next(r for r in await secrets.status() if r.name == "OPENAI_API_KEY")
    assert row.is_set and row.hint is None


def test_owners_declare_what_they_read() -> None:
    """The real declarations: every name is a setting, and none repeats."""
    names = [s.name for s in secrets.collect()]
    assert len(names) == len(set(names))
    assert all(name in type(settings).model_fields for name in names)
