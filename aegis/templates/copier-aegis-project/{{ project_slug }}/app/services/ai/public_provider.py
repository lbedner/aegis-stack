"""LLM7.io (public provider) access helpers.

LLM7.io tiered its access in mid-2026:

- The **anonymous tier** still works with no key at all: open-weight
  models (tier "turbo" in their catalog) with strict per-IP rate
  limits. This is what keeps a freshly generated project chatting out
  of the box.
- **Premium models** (tier "pro": GPT-5.x, Claude, ...) require an
  account API key from https://dash.llm7.io and are billed per token.

These helpers keep both modes working across both chat frameworks:
``public_api_key`` supplies the key (or the anonymous placeholder with
a one-time log line), and ``resolve_public_model`` resolves
``AI_MODEL=auto`` against the live catalog tier-aware: keyless projects
get an anonymous-tier model, keyed projects get a premium default.
Results are cached per process with constant fallbacks when the
catalog is unreachable.
"""

import httpx

from app.core.log import logger

LLM7_BASE_URL = "https://api.llm7.io/v1"

# Anonymous (keyless) preferences: open-weight models LLM7 serves
# without a key. Order = preference.
ANONYMOUS_MODEL_PREFERENCES = (
    "gpt-oss:20b",
    "codestral-latest",
    "minimax-m2.7",
)
ANONYMOUS_FALLBACK_MODEL = "gpt-oss:20b"

# Keyed preferences: premium models billed to the LLM7 account.
KEYED_MODEL_PREFERENCES = (
    "gpt-5.4-mini",
    "gpt-5.4",
    "deepseek-v4-flash",
    "claude-sonnet-5",
)
KEYED_FALLBACK_MODEL = "gpt-5.4-mini"

# Catalog tier value that marks key-required premium models.
_PREMIUM_TIER = "pro"

_model_cache: dict[bool, str] = {}
_keyless_noted = False


def _configured_key() -> str | None:
    from app.core.config import settings

    key = getattr(settings, "LLM7_API_KEY", None)
    return str(key) if key else None


def public_api_key() -> str:
    """The LLM7.io API key, or the anonymous-tier placeholder."""
    global _keyless_noted
    key = _configured_key()
    if key:
        return key
    if not _keyless_noted:
        logger.info(
            "Using LLM7.io's free anonymous tier (open-weight models, "
            "strict rate limits). Set LLM7_API_KEY (free account at "
            "https://dash.llm7.io) to unlock premium models."
        )
        _keyless_noted = True
    return "unused"


def _fetch_catalog() -> list[dict[str, str]]:
    """(model_id, tier) pairs from the live catalog."""
    with httpx.Client(timeout=3.0) as client:
        response = client.get(f"{LLM7_BASE_URL}/models")
        response.raise_for_status()
        payload = response.json()
    return [
        {"id": entry["id"], "tier": str(entry.get("tier", ""))}
        for entry in payload.get("data", [])
        if isinstance(entry, dict) and entry.get("id")
    ]


def resolve_public_model(configured_model: str | None) -> str:
    """Resolve the model id to send to LLM7.io.

    An explicit model passes through untouched. ``auto`` (or empty)
    resolves against the live catalog once per process: keyless
    projects pick an anonymous-tier model, keyed projects a premium
    one, each with a constant fallback when the catalog is unreachable.
    """
    if configured_model and configured_model != "auto":
        return configured_model

    keyed = _configured_key() is not None
    cached = _model_cache.get(keyed)
    if cached:
        return cached

    preferences = KEYED_MODEL_PREFERENCES if keyed else ANONYMOUS_MODEL_PREFERENCES
    fallback = KEYED_FALLBACK_MODEL if keyed else ANONYMOUS_FALLBACK_MODEL

    try:
        catalog = _fetch_catalog()
        if keyed:
            candidates = [entry["id"] for entry in catalog]
        else:
            candidates = [
                entry["id"] for entry in catalog if entry["tier"] != _PREMIUM_TIER
            ]
        chosen = next((model for model in preferences if model in candidates), None)
        if chosen is None and candidates:
            chosen = sorted(candidates)[0]
        if chosen:
            _model_cache[keyed] = chosen
            return chosen
    except Exception as exc:
        logger.warning(
            "Could not read the LLM7.io model catalog; using fallback",
            error=str(exc),
            fallback=fallback,
        )

    _model_cache[keyed] = fallback
    return fallback


def reset_public_model_cache() -> None:
    """Forget resolved models (tests, or after a catalog change)."""
    _model_cache.clear()
