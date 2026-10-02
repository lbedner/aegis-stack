"""Each owner's ``needed`` and ``verify``: which keys the enabled config
reads, and the one cheap call that tells a working key from a typo.
Owners this stack does not have are skipped."""

from importlib import import_module
from types import ModuleType

import pytest

from app.core import secrets
from app.core.config import settings
from tests._probe import answering

KEY = "key-0123456789abcd"


def _owner(path: str) -> ModuleType:
    try:
        return import_module(path)
    except ImportError:
        pytest.skip(f"{path} is not in this stack")


def _entry(module: ModuleType, name: str) -> secrets.Secret:
    return next(s for s in module.SECRETS if s.name == name)


def test_only_the_active_ai_providers_key_is_needed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _owner("app.services.ai.domains.llm.provider_management")
    monkeypatch.setitem(settings.__dict__, "AI_PROVIDER", "openai")
    needed = {s.name for s in module.SECRETS if s.is_needed()}
    assert needed == {"OPENAI_API_KEY"}
    monkeypatch.setitem(settings.__dict__, "AI_PROVIDER", "ollama")
    assert not any(s.is_needed() for s in module.SECRETS)


async def test_an_ai_key_is_checked_against_its_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _owner("app.services.ai.domains.llm.provider_management")
    entry = _entry(module, "ANTHROPIC_API_KEY")
    assert entry.verify is not None
    sent = answering(monkeypatch, 200)
    await entry.verify(KEY)
    assert sent[0].url.host == "api.anthropic.com"
    assert sent[0].headers["x-api-key"] == KEY
    answering(monkeypatch, 401)
    with pytest.raises(secrets.SecretRejectedError):
        await entry.verify(KEY)


async def test_a_send_only_resend_key_counts_as_working(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _owner("app.services.comms.email")
    entry = _entry(module, "RESEND_API_KEY")
    assert entry.is_needed() and entry.verify is not None
    answering(monkeypatch, 401, '{"name": "restricted_api_key"}')
    await entry.verify(KEY)
    answering(monkeypatch, 401, '{"name": "validation_error"}')
    with pytest.raises(secrets.SecretRejectedError):
        await entry.verify(KEY)


async def test_a_twilio_token_is_checked_with_its_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _owner("app.services.comms.twilio")
    entry = _entry(module, "TWILIO_AUTH_TOKEN")
    assert entry.verify is not None
    monkeypatch.setitem(settings.__dict__, "TWILIO_ACCOUNT_SID", None)
    with pytest.raises(secrets.SecretUncheckedError, match="TWILIO_ACCOUNT_SID"):
        await entry.verify(KEY)
    monkeypatch.setitem(settings.__dict__, "TWILIO_ACCOUNT_SID", "AC123")
    sent = answering(monkeypatch, 200)
    await entry.verify(KEY)
    assert "/Accounts/AC123.json" in sent[0].url.path


async def test_a_restricted_stripe_key_counts_as_working(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _owner("app.services.payment.providers.stripe")
    entry = _entry(module, "STRIPE_SECRET_KEY")
    assert entry.is_needed() and entry.verify is not None
    answering(monkeypatch, 403)
    await entry.verify(KEY)
    answering(monkeypatch, 401)
    with pytest.raises(secrets.SecretRejectedError):
        await entry.verify(KEY)


async def test_a_porkbun_key_is_checked_with_its_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _owner("app.services.ops.adapters.porkbun_keys")
    entry = _entry(module, "PORKBUN_API_KEY")
    assert entry.verify is not None and not entry.is_needed()
    monkeypatch.setitem(settings.__dict__, "PORKBUN_SECRET_KEY", None)
    with pytest.raises(secrets.SecretUncheckedError, match="PORKBUN_SECRET_KEY"):
        await entry.verify(KEY)
    monkeypatch.setitem(settings.__dict__, "PORKBUN_SECRET_KEY", "sk1_pair")
    sent = answering(monkeypatch, 200, '{"status": "SUCCESS"}')
    await entry.verify(KEY)
    assert sent[0].method == "POST" and sent[0].url.path.endswith("/ping")
    assert b'"apikey"' in sent[0].content and b"sk1_pair" in sent[0].content
    answering(monkeypatch, 400, '{"status": "ERROR"}')
    with pytest.raises(secrets.SecretRejectedError):
        await entry.verify(KEY)


async def test_a_hugging_face_token_is_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _owner("app.services.rag.config")
    entry = _entry(module, "HF_TOKEN")
    assert entry.verify is not None and not entry.is_needed()
    sent = answering(monkeypatch, 200)
    await entry.verify(KEY)
    assert sent[0].url.host == "huggingface.co"
    assert sent[0].headers["Authorization"] == f"Bearer {KEY}"
    answering(monkeypatch, 401)
    with pytest.raises(secrets.SecretRejectedError):
        await entry.verify(KEY)


def test_s3_credentials_are_listed_read_only() -> None:
    """Storage connects at startup from settings: listed, never set here."""
    module = _owner("app.components.storage.s3")
    for name in ("S3_ACCESS_KEY", "S3_SECRET_KEY"):
        assert not _entry(module, name).live


def test_every_owner_is_registered() -> None:
    for path in (
        "app.services.ops.adapters.porkbun_keys",
        "app.services.rag.config",
        "app.components.storage.s3",
    ):
        assert path in secrets.OWNERS
