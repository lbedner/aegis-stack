"""Tests for Pollinations (keyless provider) access helpers."""

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

import app.services.ai.pollinations_provider as pollinations_provider_module
from app.services.ai.pollinations_provider import (
    POLLINATIONS_FALLBACK_MODEL,
    anonymous_async_http_client,
    pollinations_api_key,
    reset_pollinations_model_cache,
    resolve_pollinations_model,
)


@pytest.fixture(autouse=True)
def clean_state(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    from app.core.config import settings

    monkeypatch.setattr(settings, "POLLINATIONS_API_KEY", None, raising=False)
    reset_pollinations_model_cache()
    yield
    reset_pollinations_model_cache()


class _FakeResponse:
    def __init__(self, payload: list[dict[str, Any]]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> list[dict[str, Any]]:
        return self._payload


class _FakeClient:
    def __init__(self, payload: list[dict[str, Any]] | Exception) -> None:
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


def _catalog(*entries: tuple[str, str]) -> list[dict[str, Any]]:
    return [{"name": name, "tier": tier} for name, tier in entries]


def _use_catalog(
    monkeypatch: pytest.MonkeyPatch, payload: list[dict[str, Any]] | Exception
) -> None:
    fake_httpx = MagicMock()
    fake_httpx.Client = _FakeClient(payload)
    monkeypatch.setattr(pollinations_provider_module, "httpx", fake_httpx)


def _set_key(monkeypatch: pytest.MonkeyPatch, key: str | None) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "POLLINATIONS_API_KEY", key, raising=False)


class TestResolvePollinationsModel:
    def test_explicit_model_passes_through(self) -> None:
        assert resolve_pollinations_model("openai-fast") == "openai-fast"

    def test_keyless_auto_prefers_anonymous_tier(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without a key, models above the anonymous tier are never picked."""
        _use_catalog(
            monkeypatch,
            _catalog(("gpt-5.4", "flower"), ("openai-fast", "anonymous")),
        )

        assert resolve_pollinations_model("auto") == "openai-fast"

    def test_keyed_auto_may_use_any_tier(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A key opens the whole catalog; unknown models resolve deterministically."""
        _set_key(monkeypatch, "pollinations-key")
        _use_catalog(
            monkeypatch,
            _catalog(("aria-large", "flower"), ("zephyr", "seed")),
        )

        assert resolve_pollinations_model("auto") == "aria-large"

    def test_keyless_falls_back_to_any_anonymous_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No preferred model served: pick a deterministic anonymous one."""
        _use_catalog(
            monkeypatch,
            _catalog(("some-open-model", "anonymous"), ("gpt-5.4", "flower")),
        )

        assert resolve_pollinations_model(None) == "some-open-model"

    def test_unreachable_catalog_uses_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_catalog(monkeypatch, ConnectionError("no network"))

        assert resolve_pollinations_model("auto") == POLLINATIONS_FALLBACK_MODEL

    def test_resolution_is_cached_per_process(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = {"count": 0}

        class CountingClient(_FakeClient):
            def get(self, url: str) -> _FakeResponse:
                calls["count"] += 1
                return super().get(url)

        fake_httpx = MagicMock()
        fake_httpx.Client = CountingClient(_catalog(("openai-fast", "anonymous")))
        monkeypatch.setattr(pollinations_provider_module, "httpx", fake_httpx)

        resolve_pollinations_model("auto")
        resolve_pollinations_model("auto")

        assert calls["count"] == 1


class TestPollinationsApiKey:
    def test_configured_key_is_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_key(monkeypatch, "pollinations-real-key")

        assert pollinations_api_key() == "pollinations-real-key"

    def test_keyless_returns_none_with_one_note(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        noted = MagicMock()
        monkeypatch.setattr(pollinations_provider_module.logger, "info", noted)
        monkeypatch.setattr(pollinations_provider_module, "_keyless_noted", False)

        assert pollinations_api_key() is None
        noted.assert_called_once()
        # Note once per process, not once per request.
        assert pollinations_api_key() is None
        noted.assert_called_once()


class TestAnonymousHttpClient:
    async def test_authorization_header_is_stripped(self) -> None:
        """Anonymous requests must carry NO auth header.

        Pollinations treats any Bearer value (including the OpenAI SDK's
        required placeholder) as an account key and rejects it with a 402,
        so the placeholder must never reach the wire.
        """
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["has_auth"] = "authorization" in request.headers
            return httpx.Response(200, json={})

        client = anonymous_async_http_client(transport=httpx.MockTransport(handler))
        await client.post(
            "https://text.pollinations.ai/openai/chat/completions",
            headers={"Authorization": "Bearer unused"},
        )
        await client.aclose()

        assert seen["has_auth"] is False
