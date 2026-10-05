"""Credentials behind one interface (``app.core.secrets``).

``.env`` is the zero-setup backend: read-only, changed by a restart. A
writable store (the secrets component) plugs in behind the same calls, and
a value set in ``.env`` still wins over it. Nothing here ever hands back a
stored value except ``get`` to the code that uses it.
"""

import httpx
from pydantic import Field
from pydantic_settings import BaseSettings
import pytest

from app.core import secrets
from app.core.config import settings
from app.core.credential import Credential
from app.core.secrets import Secret
from tests._probe import answering
from tests._secret_settings import FakeStore

KEY = "sk-test-0123456789abcd"
DECLARED = (
    Secret("OPENAI_API_KEY", owner="AI"),
    Secret("RESEND_FROM_EMAIL", owner="Email", label="From address", secret=False),
)


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    # An explicit choice of store wins over discovering the component's.
    secrets.set_store(None)
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


async def test_get_many_reads_env_first_then_the_store_in_one_go(
    env: pytest.MonkeyPatch,
) -> None:
    store = FakeStore()
    store.values |= {"OPENAI_API_KEY": "sk-stored-zzzz", "RESEND_FROM_EMAIL": "a@b.co"}
    secrets.set_store(store)
    env.setitem(settings.__dict__, "OPENAI_API_KEY", KEY)
    assert await secrets.get_many("OPENAI_API_KEY", "RESEND_FROM_EMAIL", "NOPE") == {
        "OPENAI_API_KEY": KEY,
        "RESEND_FROM_EMAIL": "a@b.co",
        "NOPE": None,
    }


async def test_get_many_without_a_store_is_env_alone(env: pytest.MonkeyPatch) -> None:
    env.setitem(settings.__dict__, "OPENAI_API_KEY", KEY)
    assert await secrets.get_many("OPENAI_API_KEY", "RESEND_FROM_EMAIL") == {
        "OPENAI_API_KEY": KEY,
        "RESEND_FROM_EMAIL": None,
    }


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


async def test_core_computes_the_hint_the_store_keeps() -> None:
    """One rule for hints: the last four of a secret, all of plain config."""
    store = FakeStore()
    secrets.set_store(store)
    await secrets.put("OPENAI_API_KEY", KEY, actor="ops")
    await secrets.put("RESEND_FROM_EMAIL", "hi@example.com", actor="ops")
    assert store.hints == {
        "OPENAI_API_KEY": "abcd",
        "RESEND_FROM_EMAIL": "hi@example.com",
    }


async def test_delete_follows_the_same_rules(env: pytest.MonkeyPatch) -> None:
    with pytest.raises(secrets.SecretsReadOnlyError):
        await secrets.delete("OPENAI_API_KEY", actor="ops")
    store = FakeStore()
    store.values["OPENAI_API_KEY"] = KEY
    secrets.set_store(store)
    with pytest.raises(secrets.UnknownSecretError):
        await secrets.delete("PATH", actor="ops")
    await secrets.delete("OPENAI_API_KEY", actor="ops")
    assert await secrets.get("OPENAI_API_KEY") is None


class ReadOnlyStore(FakeStore):
    """An external manager the app may only read (a policy, not a bug)."""

    name = "vault"
    writable = False


async def test_a_stored_secret_says_which_backend_holds_it() -> None:
    store = ReadOnlyStore()
    store.values["OPENAI_API_KEY"] = KEY
    secrets.set_store(store)
    row = next(r for r in await secrets.status() if r.name == "OPENAI_API_KEY")
    assert row.source == "vault"


async def test_a_read_only_backend_refuses_writes_and_says_where() -> None:
    secrets.set_store(ReadOnlyStore())
    assert not secrets.writable()
    with pytest.raises(secrets.SecretsReadOnlyError, match="vault"):
        await secrets.put("OPENAI_API_KEY", KEY, actor="ops")
    with pytest.raises(secrets.SecretsReadOnlyError, match="vault"):
        await secrets.delete("OPENAI_API_KEY", actor="ops")


def test_owners_declare_what_they_read() -> None:
    """The real declarations: every name is a setting, and none repeats."""
    names = [s.name for s in secrets.collect()]
    assert len(names) == len(set(names))
    assert all(name in type(settings).model_fields for name in names)


# Needed or optional, and verified at the moment of paste.


async def _accepts(value: str) -> None:
    return None


async def _refuses(value: str) -> None:
    raise secrets.SecretRejectedError("api.example.com refused it (401).")


async def _unreachable(value: str) -> None:
    raise secrets.SecretUncheckedError("Could not reach api.example.com.")


def _declare(env: pytest.MonkeyPatch, *entries: Secret) -> None:
    env.setattr(secrets, "declared", lambda: entries)


async def test_needed_is_decided_by_config_not_a_flag(env: pytest.MonkeyPatch) -> None:
    provider = {"active": "openai"}
    _declare(
        env,
        Secret(
            "OPENAI_API_KEY", owner="AI", needed=lambda: provider["active"] == "openai"
        ),
        Secret("RESEND_FROM_EMAIL", owner="Email", secret=False),
    )
    rows = {row.name: row for row in await secrets.status()}
    assert rows["OPENAI_API_KEY"].needed and not rows["RESEND_FROM_EMAIL"].needed
    provider["active"] = "ollama"
    rows = {row.name: row for row in await secrets.status()}
    assert not rows["OPENAI_API_KEY"].needed


async def test_a_value_the_provider_refuses_is_never_stored(
    env: pytest.MonkeyPatch,
) -> None:
    _declare(env, Secret("OPENAI_API_KEY", owner="AI", verify=_refuses))
    store = FakeStore()
    secrets.set_store(store)
    with pytest.raises(secrets.SecretRejectedError, match="refused"):
        await secrets.put("OPENAI_API_KEY", KEY, actor="ops")
    assert store.values == {}


async def test_a_verified_value_is_stored_and_says_so(env: pytest.MonkeyPatch) -> None:
    _declare(env, Secret("OPENAI_API_KEY", owner="AI", verify=_accepts))
    store = FakeStore()
    secrets.set_store(store)
    verdict = await secrets.put("OPENAI_API_KEY", KEY, actor="ops")
    assert verdict is not None and verdict.result == secrets.VERIFIED
    assert store.values == {"OPENAI_API_KEY": KEY}


async def test_an_unreachable_provider_stores_it_unverified(
    env: pytest.MonkeyPatch,
) -> None:
    """A network blip must not block a correct key."""
    _declare(env, Secret("OPENAI_API_KEY", owner="AI", verify=_unreachable))
    store = FakeStore()
    secrets.set_store(store)
    verdict = await secrets.put("OPENAI_API_KEY", KEY, actor="ops")
    assert verdict is not None and verdict.result == secrets.UNVERIFIED
    assert store.values == {"OPENAI_API_KEY": KEY}


async def test_without_a_check_there_is_no_verdict() -> None:
    secrets.set_store(FakeStore())
    assert await secrets.put("OPENAI_API_KEY", KEY, actor="ops") is None


async def test_test_checks_the_value_in_effect_wherever_it_lives(
    env: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    async def record(value: str) -> None:
        seen.append(value)

    _declare(env, Secret("OPENAI_API_KEY", owner="AI", verify=record))
    env.setitem(settings.__dict__, "OPENAI_API_KEY", KEY)
    verdict = await secrets.test("OPENAI_API_KEY")
    assert verdict.result == secrets.VERIFIED and seen == [KEY]
    assert KEY not in verdict.message


async def test_test_reports_a_refusal_and_an_unset_key(env: pytest.MonkeyPatch) -> None:
    _declare(env, Secret("OPENAI_API_KEY", owner="AI", verify=_refuses))
    assert (await secrets.test("OPENAI_API_KEY")).result == secrets.UNVERIFIED
    env.setitem(settings.__dict__, "OPENAI_API_KEY", KEY)
    assert (await secrets.test("OPENAI_API_KEY")).result == secrets.REJECTED


async def test_status_says_which_can_be_checked(env: pytest.MonkeyPatch) -> None:
    _declare(
        env,
        Secret("OPENAI_API_KEY", owner="AI", verify=_accepts),
        Secret("RESEND_FROM_EMAIL", owner="Email", secret=False),
    )
    rows = {row.name: row for row in await secrets.status()}
    assert (
        rows["OPENAI_API_KEY"].verifiable and not rows["RESEND_FROM_EMAIL"].verifiable
    )


async def test_probe_passes_on_success(env: pytest.MonkeyPatch) -> None:
    sent = answering(env, 200)
    await secrets.probe(
        "https://api.example.com/models", headers={"Authorization": "Bearer k"}
    )
    assert sent[0].headers["Authorization"] == "Bearer k"


async def test_probe_rejects_on_a_refusal_without_echoing_the_body(
    env: pytest.MonkeyPatch,
) -> None:
    """Providers echo part of a bad key in their 401 body; never repeat it."""
    answering(env, 401, "Incorrect API key provided: sk-abc***wxyz")
    with pytest.raises(secrets.SecretRejectedError) as raised:
        await secrets.probe("https://api.example.com/models")
    assert "api.example.com" in str(raised.value) and "wxyz" not in str(raised.value)


async def test_probe_cannot_tell_on_a_server_error(env: pytest.MonkeyPatch) -> None:
    answering(env, 503)
    with pytest.raises(secrets.SecretUncheckedError):
        await secrets.probe("https://api.example.com/models")


async def test_probe_lets_an_owner_accept_a_restricted_key(
    env: pytest.MonkeyPatch,
) -> None:
    answering(env, 401, '{"name": "restricted_api_key"}')
    await secrets.probe(
        "https://api.example.com/domains",
        passes=lambda r: r.is_success or "restricted_api_key" in r.text,
    )


async def test_probe_cannot_tell_when_the_network_fails(
    env: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    env.setattr(
        secrets,
        "_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(secrets.SecretUncheckedError, match="api.example.com"):
        await secrets.probe("https://api.example.com/models")


# A setting typed ``Credential`` is listed with no other declaration.


class _AppSettings(BaseSettings):
    SENDGRID_API_KEY: Credential = Field(None, description="SendGrid API key")
    PLAIN_SETTING: str | None = None


def test_a_credential_typed_setting_is_listed_without_declaring_it(
    env: pytest.MonkeyPatch,
) -> None:
    env.setattr(secrets, "settings", _AppSettings())
    found = {s.name: s for s in secrets.collect()}
    assert "SENDGRID_API_KEY" in found and "PLAIN_SETTING" not in found
    assert found["SENDGRID_API_KEY"].label == "SendGrid API key"
    assert not found["SENDGRID_API_KEY"].live


async def test_a_setting_read_through_settings_cannot_be_set_here(
    env: pytest.MonkeyPatch,
) -> None:
    """``settings`` only sees ``.env``: a stored value would never reach it."""
    env.setattr(
        secrets,
        "declared",
        lambda: (Secret("SENDGRID_API_KEY", owner="App", live=False),),
    )
    secrets.set_store(FakeStore())
    with pytest.raises(secrets.SecretsReadOnlyError, match=".env"):
        await secrets.put("SENDGRID_API_KEY", KEY, actor="ops")
    (row,) = await secrets.status()
    assert not row.live


# Choices: values the provider itself offers, picked instead of typed.


async def _two_numbers() -> list[tuple[str, str]]:
    return [("+15550001111", "Main line"), ("+15550002222", "Support")]


async def _unreachable_choices() -> list[tuple[str, str]]:
    raise secrets.SecretUncheckedError("could not reach api.example.com.")


async def test_choices_come_from_the_declaration(env: pytest.MonkeyPatch) -> None:
    _declare(
        env,
        Secret(
            "TWILIO_PHONE_NUMBER", owner="Twilio", secret=False, choices=_two_numbers
        ),
        Secret("OPENAI_API_KEY", owner="AI"),
    )
    assert await secrets.choices("TWILIO_PHONE_NUMBER") == await _two_numbers()
    assert await secrets.choices("OPENAI_API_KEY") == []
    rows = {row.name: row for row in await secrets.status()}
    assert (
        rows["TWILIO_PHONE_NUMBER"].choosable and not rows["OPENAI_API_KEY"].choosable
    )


async def test_a_provider_that_cannot_answer_offers_no_choices(
    env: pytest.MonkeyPatch,
) -> None:
    """Typing the value still works; the picker is a convenience."""
    _declare(
        env,
        Secret(
            "TWILIO_PHONE_NUMBER",
            owner="Twilio",
            secret=False,
            choices=_unreachable_choices,
        ),
    )
    assert await secrets.choices("TWILIO_PHONE_NUMBER") == []


async def test_choices_for_an_undeclared_name_refuse(env: pytest.MonkeyPatch) -> None:
    with pytest.raises(secrets.UnknownSecretError):
        await secrets.choices("PATH")


# The app's own credentials, which no ``SECRETS`` declares.
APP_CREDENTIALS = {"SECRET_KEY", "ENCRYPTION_KEY", "DOCS_PASSWORD"}


def test_a_settings_repr_shows_no_credential() -> None:
    """A log line, a traceback or a failing assert that shows ``settings``
    never carries a credential: any one declared, or the app's own."""
    declared = {e.name for e in secrets.collect() if e.secret and not e.setting}
    names = (declared | APP_CREDENTIALS) & set(type(settings).model_fields)
    shown = settings.model_copy(update={name: f"{name}-value" for name in names})
    for text in (repr(shown), str(shown)):
        assert not [name for name in names if f"{name}-value" in text]


@pytest.mark.parametrize(
    ("url", "masked"),
    [
        ("postgresql://app:hunter2@db:5432/app", "postgresql://app:***@db:5432/app"),
        ("redis://:hunter2@redis:6379/0", "redis://:***@redis:6379/0"),  # no user
        ("postgresql://app:hun/ter2@db/app", "postgresql://app:***@db/app"),
        ("https://example.com/a?b=c", "https://example.com/a?b=c"),
    ],
)
def test_a_settings_repr_hides_a_urls_password(url: str, masked: str) -> None:
    shown = repr(settings.model_copy(update={"PUBLIC_BASE_URL": url}))
    assert "hunter2" not in shown and "hun/ter2" not in shown
    assert masked in shown
