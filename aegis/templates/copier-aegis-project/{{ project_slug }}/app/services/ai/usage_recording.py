"""LLM usage extraction, pricing, and ledger writes — module-level.

Extracted from ``AIService`` so non-chat callers (the insight generation
pipeline, future one-shot agents) can price and record LLM calls without
instantiating the chat service (whose ``ConversationManager`` runs
``init_database()`` on construction — a ``create_all`` that must never race
Alembic in worker processes). ``AIService`` delegates here; the price
lookup lives in exactly one place.
"""

from typing import Any

from app.core import series
from app.core.db import get_async_session
from app.core.log import logger
from app.core.time import utcnow
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


def _optional_token_count(usage: Any, *names: str) -> int | None:
    """Like ``_token_count`` but None when the provider never said.

    A provider that supports caching and got no hits reports 0, which is
    a measurement worth keeping. A provider or client version that has
    no such attribute reported nothing at all, and folding that to 0
    would claim a cache was offered and missed on every call.
    """
    for name in names:
        value = getattr(usage, name, None)
        if isinstance(value, int):
            return value
    return None


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
    Absent on providers/clients that report no cache counts at all,
    which prices identically to the pre-cache behavior.
    """
    usage = getattr(result, "usage", None)
    if callable(usage):
        try:
            usage = usage()
        except Exception:
            return {"input_tokens": 0, "output_tokens": 0}
    if usage is None:
        return {"input_tokens": 0, "output_tokens": 0}
    counts = {
        "input_tokens": _token_count(usage, "input_tokens", "request_tokens"),
        "output_tokens": _token_count(usage, "output_tokens", "response_tokens"),
    }
    # Present only when the provider actually reported them, so the
    # ledger can tell "no cache hits" from "no cache at all".
    for key in ("cache_read_tokens", "cache_write_tokens"):
        reported = _optional_token_count(usage, key)
        if reported is not None:
            counts[key] = reported
    return counts


async def _rates(model: str) -> llm_queries.Rates | None:
    """A model's catalog rates (memoized, ``price_for_model``), or None
    when it is not priced or the read fails: a cost is never worth failing
    the call it describes."""
    bare = _bare_model_name(model)
    try:
        async with get_async_session() as session:
            return await llm_queries.price_for_model(session, bare)
    except Exception as e:
        logger.warning("Failed to read a model's price", error=str(e), model=bare)
        return None


def _rate(rates: llm_queries.Rates, name: str) -> float:
    """One rate; a measure the model does not bill by costs nothing."""
    return rates.get(name) or 0.0


async def calculate_cost(
    model_name: str, input_tokens: int, output_tokens: int
) -> float:
    """Full-rate cost estimate in USD, 0.0 when model/price is uncataloged.

    This charges every input token at the base rate; it takes aggregate counts
    and has no cache split to price reads/writes differently. It's a display
    estimate (e.g. a live status line). ``record_usage`` is the authoritative,
    cache-aware path that writes the ledger, so for cached runs the ledgered
    cost is lower than this estimate.
    """
    rates = await _rates(model_name)
    if not rates:
        return 0.0
    return input_tokens * _rate(rates, "input_cost_per_token") + (
        output_tokens * _rate(rates, "output_cost_per_token")
    )


# Anthropic's cache multipliers on the input price: reads bill at ~0.1x,
# writes (5m TTL) at 1.25x. A model the catalog gives its own cached-read
# rate is priced at that; the multipliers cover the rest. Cache token
# counts only flow for runs where the provider reports them.
_CACHE_READ_MULT = 0.1
_CACHE_WRITE_MULT = 1.25


def _cached_read_rate(rates: llm_queries.Rates) -> float:
    """What a cached input token costs: the catalog's rate, else the
    multiplier on the input rate."""
    input_rate = _rate(rates, "input_cost_per_token")
    return rates.get("cache_input_cost_per_token") or input_rate * _CACHE_READ_MULT


def _priced_input_cost(usage: dict[str, int], rates: llm_queries.Rates) -> float:
    """Input-side cost with cache-aware pricing.

    ``input_tokens`` arrives as pydantic-ai's AGGREGATE (uncached + cache
    reads + cache writes), so the cached share is re-priced at its own
    rate instead of full rate. Without cache counts this reduces to
    ``input_tokens * price`` exactly as before.
    """
    input_rate = _rate(rates, "input_cost_per_token")
    total = usage.get("input_tokens", 0)
    reads = usage.get("cache_read_tokens", 0)
    writes = usage.get("cache_write_tokens", 0)
    uncached = max(0, total - reads - writes)
    return (
        uncached * input_rate
        + reads * _cached_read_rate(rates)
        + writes * input_rate * _CACHE_WRITE_MULT
    )


async def _write(row: LLMUsage, what: str) -> None:
    """One ledger row, its model named bare like every other; a failed
    write is logged and swallowed - usage tracking must never fail the
    calling request."""
    row.model_id = _bare_model_name(row.model_id)
    # Naive UTC: asyncpg rejects an aware value for a ``timestamp without
    # time zone`` column, and the except below would swallow that as a
    # lost row.
    row.timestamp = utcnow()
    try:
        async with get_async_session() as session:
            session.add(row)
    except Exception as e:
        logger.error(f"Failed to record {what}", error=str(e))


async def _chart(model: str, usage: dict[str, int], duration_ms: float | None) -> None:
    """The call as points on the live charts (``app.core.series``), pushed as
    it happens: seconds taken, and output tokens a second."""
    if not duration_ms:
        return
    seconds = duration_ms / 1000
    points = {f"{series.LLM}:{model}:{series.LATENCY}": seconds}
    if output := usage.get("output_tokens", 0):
        points[f"{series.LLM}:{model}:{series.TOKENS_PER_SECOND}"] = output / seconds
    await series.record(points)


async def record_usage(
    action: str,
    model_name: str,
    usage: dict[str, int],
    user_id: str | None,
    success: bool = True,
    error_message: str | None = None,
    duration_ms: float | None = None,
    tool_calls: int | None = None,
    conversation_id: str | None = None,
) -> float:
    """Write one ``llm_usage`` ledger row; returns the calculated cost.

    Unknown models are still recorded (at zero cost) so the ledger stays
    complete. The returned cost lets callers denormalize it onto their own
    artifacts without a second price lookup.
    """
    bare = _bare_model_name(model_name)
    rates = await _rates(bare)
    total_cost = 0.0
    if rates:
        total_cost = _priced_input_cost(usage, rates) + usage.get(
            "output_tokens", 0
        ) * _rate(rates, "output_cost_per_token")
    else:
        logger.warning(
            "LLM not priced in catalog - usage recorded without cost", model_id=bare
        )
    await _write(
        LLMUsage(
            action=action,
            model_id=bare,
            user_id=user_id,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            total_cost=total_cost,
            success=success,
            error_message=error_message,
            duration_ms=duration_ms,
            # ``.get`` with no default, so a provider that reports no cache
            # records None rather than claiming it offered one and missed
            # every time.
            cache_read_tokens=usage.get("cache_read_tokens"),
            cache_write_tokens=usage.get("cache_write_tokens"),
            tool_calls=tool_calls,
            conversation_id=conversation_id,
        ),
        "LLM usage",
    )
    logger.info("Usage recorded", model=bare, tokens=usage, cost=total_cost)
    await _chart(bare, usage, duration_ms)
    return total_cost


# --- voice -------------------------------------------------------------------
# Voice bills by the second (a transcription), by the character or second
# of speech, or by audio tokens (a realtime call). Every rate is the
# catalog's (``llm_price``, synced with the model), so a voice cost is
# priced exactly where a chat turn's is, and lands in the same ledger.

STT_ACTION = "stt"
TTS_ACTION = "tts"
REALTIME_ACTION = "realtime"
# The ledger's voice actions, as the spend report names them.
VOICE_ACTIONS: dict[str, str] = {
    STT_ACTION: "Transcription",
    TTS_ACTION: "Speech",
    REALTIME_ACTION: "Live calls",
}


async def speech_cost(
    model: str,
    *,
    input_seconds: float | None = None,
    output_seconds: float | None = None,
    characters: int | None = None,
) -> float:
    """What a transcription or a spoken reply cost: each measure times the
    rate the model lists for it (a model lists only the measures it bills
    by); 0 for a model the catalog does not price."""
    rates = await _rates(model)
    if not rates:
        return 0.0
    return (
        (input_seconds or 0) * _rate(rates, "input_cost_per_second")
        + (output_seconds or 0) * _rate(rates, "output_cost_per_second")
        + (characters or 0) * _rate(rates, "input_cost_per_character")
    )


async def record_speech(
    action: str,
    model: str,
    *,
    cost: float,
    seconds: float | None = None,
    duration_ms: float | None = None,
    user_id: str | None = None,
    success: bool = True,
    error_message: str | None = None,
) -> None:
    """One ledger row for a transcription (``stt``) or spoken reply
    (``tts``), beside the model calls. Tokens are 0: speech reports none."""
    await _write(
        LLMUsage(
            action=action,
            model_id=model,
            user_id=user_id,
            input_tokens=0,
            output_tokens=0,
            total_cost=cost,
            audio_seconds=seconds,
            duration_ms=duration_ms,
            success=success,
            error_message=error_message,
        ),
        "speech usage",
    )


async def realtime_price(model: str) -> llm_queries.Rates | None:
    """A realtime model's rates, read once when its call opens; None when it
    cannot be priced (the call goes on either way)."""
    return await _rates(model)


def realtime_cost(rates: llm_queries.Rates | None, usage: Any) -> float:
    """A realtime call's tokens at the catalog's text, audio and cached
    rates. The totals include the audio and the cached share, so each is
    taken out and priced at its own rate."""
    if not rates:
        return 0.0
    audio_in = _token_count(usage, "input_audio_tokens")
    audio_out = _token_count(usage, "output_audio_tokens")
    cached = _token_count(usage, "cache_read_tokens")
    cached_audio = _token_count(usage, "cache_audio_read_tokens")
    text_in = max(
        0, _token_count(usage, "input_tokens") - audio_in - (cached - cached_audio)
    )
    text_out = max(0, _token_count(usage, "output_tokens") - audio_out)
    input_rate = _rate(rates, "input_cost_per_token")
    output_rate = _rate(rates, "output_cost_per_token")
    return (
        text_in * input_rate
        + max(0, audio_in - cached_audio)
        * (rates.get("input_cost_per_audio_token") or input_rate)
        + cached * _cached_read_rate(rates)
        + text_out * output_rate
        + audio_out * (rates.get("output_cost_per_audio_token") or output_rate)
    )


async def record_realtime(
    model: str,
    usage: Any,
    *,
    seconds: float,
    conversation_id: str | None,
    rates: llm_queries.Rates | None,
    user_id: str | None = None,
) -> None:
    """A realtime call's row: its tokens, priced at the catalog's rates like
    every other model call (``rates``, read once when the call opened)."""
    await _write(
        LLMUsage(
            action=REALTIME_ACTION,
            model_id=model,
            user_id=user_id,
            input_tokens=_token_count(usage, "input_tokens"),
            output_tokens=_token_count(usage, "output_tokens"),
            total_cost=realtime_cost(rates, usage),
            audio_seconds=seconds,
            duration_ms=seconds * 1000,
            tool_calls=getattr(usage, "tool_calls", None),
            conversation_id=conversation_id,
        ),
        "a realtime call's usage",
    )
