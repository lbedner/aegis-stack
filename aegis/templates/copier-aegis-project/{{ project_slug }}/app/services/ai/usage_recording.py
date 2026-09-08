"""LLM usage extraction, pricing, and ledger writes — module-level.

Extracted from ``AIService`` so non-chat callers (the insight generation
pipeline, future one-shot agents) can price and record LLM calls without
instantiating the chat service (whose ``ConversationManager`` runs
``init_database()`` on construction — a ``create_all`` that must never race
Alembic in worker processes). ``AIService`` delegates here; the price
lookup lives in exactly one place.
"""

from datetime import UTC, datetime
from typing import Any

from app.core.db import db_session
from app.core.log import logger
from app.services.ai.domains.llm import queries as llm_queries

from .models.llm import LLMUsage


def _bare_model_name(model_name: str) -> str:
    """Strip a vendor prefix ("openai/gpt-4o" → "gpt-4o")."""
    if "/" in model_name:
        return model_name.split("/", 1)[1]
    return model_name


def _token_count(usage: Any, *names: str) -> int:
    """First integer attribute among ``names``, else 0 (mock-safe)."""
    for name in names:
        value = getattr(usage, name, None)
        if isinstance(value, int):
            return value
    return 0


def extract_usage(result: Any) -> dict[str, int]:
    """Token usage from a pydantic-ai run result.

    Handles every shape pydantic-ai has shipped: ``result.usage`` as a
    data attribute (legacy ``Usage`` with request/response_tokens) or as
    a method returning ``RunUsage`` (input/output_tokens). Anything
    unreadable degrades to zeros rather than raising — usage tracking
    must never fail the request.

    Cache accounting: pydantic-ai's ``input_tokens`` AGGREGATES uncached +
    cache-read + cache-write tokens, so the cache splits ride along for
    pricing (cached reads bill at ~0.1x, writes at ~1.25x on Anthropic).
    Zero on providers/runs without caching, which prices identically to
    the pre-cache behavior.
    """
    usage = getattr(result, "usage", None)
    if callable(usage):
        try:
            usage = usage()
        except Exception:
            return {"input_tokens": 0, "output_tokens": 0}
    if usage is None:
        return {"input_tokens": 0, "output_tokens": 0}
    return {
        "input_tokens": _token_count(usage, "input_tokens", "request_tokens"),
        "output_tokens": _token_count(usage, "output_tokens", "response_tokens"),
        "cache_read_tokens": _token_count(usage, "cache_read_tokens"),
        "cache_write_tokens": _token_count(usage, "cache_write_tokens"),
    }


def calculate_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    """Full-rate cost estimate in USD, 0.0 when model/price is uncataloged.

    This charges every input token at the base rate; it takes aggregate counts
    and has no cache split to price reads/writes differently. It's a display
    estimate (e.g. a live status line). ``record_usage`` is the authoritative,
    cache-aware path that writes the ledger, so for cached runs the ledgered
    cost is lower than this estimate.
    """
    bare = _bare_model_name(model_name)
    try:
        with db_session() as session:
            price = llm_queries.latest_price_for_model(session, bare)
            if not price:
                return 0.0
            return (
                input_tokens * price.input_cost_per_token
                + output_tokens * price.output_cost_per_token
            )
    except Exception as e:
        logger.warning("Failed to calculate cost", error=str(e), model=bare)
        return 0.0


# Anthropic's cache multipliers on the input price: reads bill at ~0.1x,
# writes (5m TTL) at 1.25x. Other providers differ, but cache token counts
# only flow for runs where pydantic-ai reports them; zero = old pricing.
_CACHE_READ_MULT = 0.1
_CACHE_WRITE_MULT = 1.25


def _priced_input_cost(usage: dict[str, int], input_price: float) -> float:
    """Input-side cost with cache-aware pricing.

    ``input_tokens`` arrives as pydantic-ai's AGGREGATE (uncached + cache
    reads + cache writes), so the cached share is re-priced at its own
    multiplier instead of full rate. Without cache counts this reduces to
    ``input_tokens * price`` exactly as before.
    """
    total = usage.get("input_tokens", 0)
    reads = usage.get("cache_read_tokens", 0)
    writes = usage.get("cache_write_tokens", 0)
    uncached = max(0, total - reads - writes)
    return (
        uncached * input_price
        + reads * input_price * _CACHE_READ_MULT
        + writes * input_price * _CACHE_WRITE_MULT
    )


def record_usage(
    action: str,
    model_name: str,
    usage: dict[str, int],
    user_id: str | None,
    success: bool = True,
    error_message: str | None = None,
    duration_ms: int | None = None,
) -> float:
    """Write one ``llm_usage`` ledger row; returns the calculated cost.

    Unknown models are still recorded (at zero cost) so the ledger stays
    complete; a failed write is logged and swallowed — usage tracking must
    never fail the calling request. The returned cost lets callers
    denormalize it onto their own artifacts without a second price lookup.
    """
    bare = _bare_model_name(model_name)
    total_cost = 0.0
    try:
        with db_session() as session:
            price = llm_queries.latest_price_for_model(session, bare)
            if price:
                total_cost = (
                    _priced_input_cost(usage, price.input_cost_per_token)
                    + usage.get("output_tokens", 0) * price.output_cost_per_token
                )
            else:
                logger.warning(
                    "LLM not priced in catalog - usage recorded without cost",
                    model_id=bare,
                )
            session.add(
                LLMUsage(
                    action=action,
                    model_id=bare,
                    user_id=user_id,
                    timestamp=datetime.now(UTC),
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    total_cost=total_cost,
                    success=success,
                    error_message=error_message,
                    duration_ms=duration_ms,
                )
            )
        logger.info(
            "Usage committed to database",
            model=bare,
            tokens=usage,
            cost=total_cost,
        )
    except Exception as e:
        logger.error("Failed to record LLM usage", error=str(e))
    return total_cost
