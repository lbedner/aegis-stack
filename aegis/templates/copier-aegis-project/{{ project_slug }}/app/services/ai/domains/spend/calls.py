"""What a live call costs (``realtime_calls``): its ledger row, opened with
the call and billed as it runs, at the model's per-second rate or by its
tokens (``recording.realtime_cost``), and the call a turn run mid-call is
handed off from."""

import asyncio
from contextvars import ContextVar
from typing import Any

from sqlalchemy import update
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import release_lock
from app.core.log import logger
from app.services.ai.domains.llm import queries as llm_queries
from app.services.ai.domains.spend.recording import (
    REALTIME_ACTION,
    _rates,
    _token_count,
    realtime_cost,
    stamped,
)
from app.services.ai.models.llm import LLMUsage

# The live call a turn run now is handed off from (a picture looked at
# mid-call): the write of the call's ledger row, started beside its audio
# (``realtime_calls.drive``). The turn's reply names the row (``call``), so
# the call's thinking is read from those replies, live and in the report.
# ponytail: on the reply, not the ledger row - ``llm_usage`` has no column
# for it; a ``call_id`` column would put it on the row itself.
handing_off: ContextVar[asyncio.Task[int | None] | None] = ContextVar(
    "handing_off", default=None
)


async def handed_off_call() -> int | None:
    """The ledger row of the call this turn is handed off from, or None."""
    opening = handing_off.get()
    return await opening if opening is not None else None


async def realtime_price(model: str) -> llm_queries.Rates | None:
    """A realtime model's rates, read once when its call opens; None when it
    cannot be priced (the call goes on either way)."""
    return await _rates(model)


def per_second(rates: llm_queries.Rates | None) -> float | None:
    """USD a second when a realtime model bills its call by time (the
    catalog's per-minute price, kept per second); None when its tokens
    price it."""
    return (rates or {}).get("input_cost_per_second") or None


def call_cost(rates: llm_queries.Rates | None, usage: Any, seconds: float) -> float:
    """What a live call has cost so far, its one home: its ``seconds`` at
    the model's per-second rate where it bills by time, else its tokens
    (``realtime_cost``)."""
    rate = per_second(rates)
    return seconds * rate if rate else realtime_cost(rates, usage)


async def open_realtime(
    session: AsyncSession,
    model: str,
    *,
    conversation_id: str | None,
    user_id: str | None = None,
) -> int | None:
    """A live call's row, opened with the call and billed as it runs
    (``bill_realtime``), so a call cut off by a killed process still has
    what it cost to its last turn. Its id; None when it could not be
    written (the call goes on either way). Committed at once, like each
    bill: a call that lasts an hour holds no transaction (``release_lock``)."""
    row = stamped(
        LLMUsage(
            action=REALTIME_ACTION,
            model_id=model,
            user_id=user_id,
            input_tokens=0,
            output_tokens=0,
            total_cost=0.0,
            audio_seconds=0.0,
            conversation_id=conversation_id,
        )
    )
    try:
        session.add(row)
        await session.flush()
        row_id = row.id
        await release_lock(session)
    except Exception as e:
        await session.rollback()
        logger.error("Failed to record a realtime call's usage", error=str(e))
        return None
    return row_id


async def bill_realtime(
    session: AsyncSession,
    row_id: int | None,
    usage: Any,
    *,
    seconds: float,
    rates: llm_queries.Rates | None,
    success: bool = True,
) -> float:
    """The call's row at what it has cost so far (``call_cost``), with its
    running usage and length; the cost. ``rates`` are read once, when the
    call opened (``realtime_price``)."""
    cost = call_cost(rates, usage, seconds)
    if row_id is None:
        return cost
    try:
        await session.execute(
            update(LLMUsage)
            .where(col(LLMUsage.id) == row_id)
            .values(
                input_tokens=_token_count(usage, "input_tokens"),
                output_tokens=_token_count(usage, "output_tokens"),
                total_cost=cost,
                audio_seconds=seconds,
                duration_ms=seconds * 1000,
                tool_calls=getattr(usage, "tool_calls", None),
                success=success,
            )
        )
        await release_lock(session)
    except Exception as e:
        await session.rollback()
        logger.error("Failed to bill a realtime call", error=str(e))
    return cost
