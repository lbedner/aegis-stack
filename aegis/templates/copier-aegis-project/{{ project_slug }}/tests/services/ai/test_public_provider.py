"""Tests for LLM7.io public-provider access helpers."""

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock

import pytest

import app.services.ai.public_provider as public_provider_module
from app.services.ai.public_provider import (
    ANONYMOUS_FALLBACK_MODEL,
    KEYED_FALLBACK_MODEL,
    public_api_key,
    reset_public_model_cache,
    resolve_public_model,
)


@pytest.fixture(autouse=True)
def clean_state(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM7_API_KEY", None, raising=False)
    reset_public_model_cache()
    yield
    reset_public_model_cache()


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    def __init__(self, payload: dict[str, Any] | Exception) -> None:
        self._payload = payload

    def __call__(self, *args: Any, **kwargs: Any) -> "_FakeClient":
        return self

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def get(self, url: str) -> _FakeResponse:
        if isinstance(self._payload, Exception):
            raise self._payload
        return _FakeResponse(self._payload)


def _catalog(*entries: tuple[str, str]) -> dict[str, Any]:
    return {"data": [{"id": mid, "tier": tier} for mid, tier in entries]}


def _use_catalog(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any] | Exception
) -> None:
    fake_httpx = MagicMock()
    fake_httpx.Client = _FakeClient(payload)
    monkeypatch.setattr(public_provider_module, "httpx", fake_httpx)


def _set_key(monkeypatch: pytest.MonkeyPatch, key: str | None) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM7_API_KEY", key, raising=False)


class TestResolvePublicModel:
    def test_explicit_model_passes_through(self) -> None:
        assert resolve_public_model("deepseek-v4-flash") == "deepseek-v4-flash"

    def test_keyless_auto_prefers_anonymous_tier(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without a key, premium (pro) models are never picked."""
        _use_catalog(
            monkeypatch,
            _catalog(
                ("gpt-5.4-mini", "pro"),
                ("claude-sonnet-5", "pro"),
                ("gpt-oss:20b", "turbo"),
            ),
        )

        assert resolve_public_model("auto") == "gpt-oss:20b"

    def test_keyed_auto_prefers_premium_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_key(monkeypatch, "llm7-key")
        _use_catalog(
            monkeypatch,
            _catalog(
                ("gpt-oss:20b", "turbo"),
                ("gpt-5.4-mini", "pro"),
            ),
        )

        assert resolve_public_model("auto") == "gpt-5.4-mini"

    def test_keyless_falls_back_to_any_non_premium_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No preferred anonymous model served: pick a deterministic one."""
        _use_catalog(
            monkeypatch,
            _catalog(("some-open-model", "turbo"), ("gpt-5.4", "pro")),
        )

        assert resolve_public_model(None) == "some-open-model"

    def test_unreachable_catalog_uses_mode_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_catalog(monkeypatch, ConnectionError("no network"))
        assert resolve_public_model("auto") == ANONYMOUS_FALLBACK_MODEL

        reset_public_model_cache()
        _set_key(monkeypatch, "llm7-key")
        _use_catalog(monkeypatch, ConnectionError("no network"))
        assert resolve_public_model("auto") == KEYED_FALLBACK_MODEL

    def test_resolution_is_cached_per_process(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = {"count": 0}

        class CountingClient(_FakeClient):
            def get(self, url: str) -> _FakeResponse:
                calls["count"] += 1
                return super().get(url)

        fake_httpx = MagicMock()
        fake_httpx.Client = CountingClient(_catalog(("gpt-oss:20b", "turbo")))
        monkeypatch.setattr(public_provider_module, "httpx", fake_httpx)

        resolve_public_model("auto")
        resolve_public_model("auto")

        assert calls["count"] == 1


class TestPublicApiKey:
    def test_configured_key_is_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_key(monkeypatch, "llm7-real-key")

        assert public_api_key() == "llm7-real-key"

    def test_keyless_uses_anonymous_tier_with_one_note(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        noted = MagicMock()
        monkeypatch.setattr(public_provider_module.logger, "info", noted)
        monkeypatch.setattr(public_provider_module, "_keyless_noted", False)

        assert public_api_key() == "unused"
        noted.assert_called_once()
        # Note once per process, not once per request.
        assert public_api_key() == "unused"
        noted.assert_called_once()
