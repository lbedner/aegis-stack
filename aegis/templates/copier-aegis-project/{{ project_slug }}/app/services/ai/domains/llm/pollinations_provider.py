"""Pollinations (keyless provider) access helpers.

Pollinations serves an OpenAI-compatible endpoint whose **anonymous
tier needs no key at all**: open-weight models tagged ``tier:
"anonymous"`` in their catalog, rate-limited per IP, non-streaming
only. Higher tiers use account keys, and their keyed traffic is
migrating to a newer gateway, so this integration is anonymous-first.

Two wire-level rules make anonymous access work:

- Requests must carry **no** ``Authorization`` header. Pollinations
  treats any Bearer value (including the placeholder the OpenAI SDK
  insists on) as an account key and rejects it, so
  ``anonymous_async_http_client``/``anonymous_sync_http_client`` strip
  the header before it reaches the wire.
- ``AI_MODEL=auto`` resolves against the live catalog
  (``resolve_pollinations_model``): keyless projects only pick
  anonymous-tier models, with a constant fallback when the catalog is
  unreachable. Results are cached per process.
"""

from typing import Any

import httpx

from app.core.log import logger

POLLINATIONS_BASE_URL = "https://text.pollinations.ai/openai"

# The richer catalog (with tier metadata) lives outside the
# OpenAI-compatible prefix.
_CATALOG_URL = "https://text.pollinations.ai/models"

# Catalog tier value served without a key.
_ANONYMOUS_TIER = "anonymous"

# Preferred models, in order. The anonymous catalog is small (often a
# single open-weight model), so the fallback doubles as the usual pick.
POLLINATIONS_MODEL_PREFERENCES = ("openai-fast",)
POLLINATIONS_FALLBACK_MODEL = "openai-fast"

_model_cache: dict[bool, str] = {}
_keyless_noted = False


def _configured_key() -> str | None:
    from app.core.config import settings

    key = getattr(settings, "POLLINATIONS_API_KEY", None)
    return str(key) if key else None


def pollinations_api_key() -> str | None:
    """The Pollinations API key, or ``None`` for the anonymous tier."""
    global _keyless_noted
    key = _configured_key()
    if key:
        return key
    if not _keyless_noted:
        logger.info(
            "Using Pollinations' free anonymous tier (open-weight models, "
            "per-IP rate limits, no streaming). Set POLLINATIONS_API_KEY "
            "to use an account tier."
        )
        _keyless_noted = True
    return None


class _StripAuthAsyncClient(httpx.AsyncClient):
    """Async client that drops the ``Authorization`` header."""

    async def send(self, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        request.headers.pop("Authorization", None)
        return await super().send(request, **kwargs)


class _StripAuthSyncClient(httpx.Client):
    """Sync client that drops the ``Authorization`` header."""

    def send(self, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        request.headers.pop("Authorization", None)
        return super().send(request, **kwargs)


def anonymous_async_http_client(**kwargs: Any) -> httpx.AsyncClient:
    """HTTP client for keyless requests (no auth header ever sent)."""
    return _StripAuthAsyncClient(**kwargs)


def anonymous_sync_http_client(**kwargs: Any) -> httpx.Client:
    """Sync variant of ``anonymous_async_http_client``."""
    return _StripAuthSyncClient(**kwargs)


def _fetch_catalog() -> list[dict[str, str]]:
    """(model name, tier) pairs from the live catalog."""
    with httpx.Client(timeout=3.0) as client:
        response = client.get(_CATALOG_URL)
        response.raise_for_status()
        payload = response.json()
    return [
        {"name": entry["name"], "tier": str(entry.get("tier", ""))}
        for entry in payload
        if isinstance(entry, dict) and entry.get("name")
    ]


def resolve_pollinations_model(configured_model: str | None) -> str:
    """Resolve the model name to send to Pollinations.

    An explicit model passes through untouched. ``auto`` (or empty)
    resolves against the live catalog once per process: keyless
    projects only consider anonymous-tier models, keyed projects the
    whole catalog, with a constant fallback when the catalog is
    unreachable.
    """
    if configured_model and configured_model != "auto":
        return configured_model

    keyed = _configured_key() is not None
    cached = _model_cache.get(keyed)
    if cached:
        return cached

    try:
        catalog = _fetch_catalog()
        if keyed:
            candidates = [entry["name"] for entry in catalog]
        else:
            candidates = [
                entry["name"] for entry in catalog if entry["tier"] == _ANONYMOUS_TIER
            ]
        chosen = next(
            (model for model in POLLINATIONS_MODEL_PREFERENCES if model in candidates),
            None,
        )
        if chosen is None and candidates:
            chosen = sorted(candidates)[0]
        if chosen:
            _model_cache[keyed] = chosen
            return chosen
    except Exception as exc:
        logger.warning(
            "Could not read the Pollinations model catalog; using fallback",
            error=str(exc),
            fallback=POLLINATIONS_FALLBACK_MODEL,
        )

    _model_cache[keyed] = POLLINATIONS_FALLBACK_MODEL
    return POLLINATIONS_FALLBACK_MODEL


def reset_pollinations_model_cache() -> None:
    """Forget resolved models (tests, or after a catalog change)."""
    _model_cache.clear()
