"""The record of MCP activity: what each outside assistant looked at and
what it proposed (``McpToolCall``), kept where there is a database; a
``run_code`` call's reads are kept under it.

``record`` is the server's recorder (``build_server(record=...)``): it logs
the call like every MCP server does, then keeps it. A record that fails to
keep is logged as an error and the client still gets its answer.
"""

from datetime import datetime, timedelta
import time

from pydantic import BaseModel, ConfigDict
from sqlalchemy import case
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import defer, selectinload
from sqlmodel import col, delete, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_async_session
from app.core.log import logger
from app.core.time import utcnow

from .models.calls import McpToolCall
from .server import McpCall, log_call


class ClientActivity(BaseModel):
    """One client's calls, summed: how much it read and proposed. The reads
    a script made count once, as its run_code call."""

    model_config = ConfigDict(frozen=True)

    client: str
    calls: int
    reads: int
    proposals: int
    failed: int
    last_at: datetime


# How long a call is kept: older ones go on a write, with the reads under
# them. ponytail: a constant, and pruned at most hourly per process on a
# write; a setting and a scheduled job if a quiet app must shed rows too.
KEEP = timedelta(days=30)
PRUNE_EVERY = 3600.0
# When this process last pruned (``time.monotonic``, which starts at boot,
# not at zero); None until it first does.
_pruned_at: float | None = None


async def record(call: McpCall) -> None:
    await log_call(call)
    try:
        async with get_async_session() as db:
            # The call's fields are the row's columns, by name.
            parent = McpToolCall(**call.model_dump(exclude={"steps"}))
            parent.steps = [
                McpToolCall(
                    client=call.client, effect="read", duration_ms=None, **step.model_dump()
                )
                for step in call.steps
            ]
            db.add(parent)
            await _prune(db)
    except SQLAlchemyError:
        logger.exception("mcp.record_failed", tool=call.tool, client=call.client)


async def _prune(db: AsyncSession) -> None:
    """Delete calls older than ``KEEP``, the reads under them first (each
    points at its run), at most once every ``PRUNE_EVERY`` seconds."""
    global _pruned_at
    now = time.monotonic()
    if _pruned_at is not None and now - _pruned_at < PRUNE_EVERY:
        return
    _pruned_at = now
    old = select(McpToolCall.id).where(
        col(McpToolCall.parent_id).is_(None), col(McpToolCall.called_at) < utcnow() - KEEP
    )
    await db.exec(delete(McpToolCall).where(col(McpToolCall.parent_id).in_(old)))
    await db.exec(delete(McpToolCall).where(col(McpToolCall.id).in_(old)))


# A call's text, up to ``server.TEXT_CAP`` each: read with ``one`` when its
# row is opened, never for the list (a step's args are its short preview,
# its name in the list).
_TEXT = (defer(McpToolCall.response), defer(McpToolCall.error))  # type: ignore[arg-type]


async def recent(*, limit: int = 50) -> list[McpToolCall]:
    """The newest calls the clients made first, every client, each with the
    reads its script made (``steps``, loaded in one more query), without
    their text (``one``)."""
    query = (
        select(McpToolCall)
        .where(col(McpToolCall.parent_id).is_(None))
        .options(
            defer(McpToolCall.args),  # type: ignore[arg-type]
            *_TEXT,
            selectinload(McpToolCall.steps).options(*_TEXT),  # type: ignore[arg-type]
        )
        .order_by(col(McpToolCall.id).desc())
        .limit(limit)
    )
    async with get_async_session() as db:
        return list((await db.exec(query)).all())


async def one(call_id: int) -> McpToolCall | None:
    """One call, text and all (read afresh, over any copy ``recent`` left
    in the session without it)."""
    query = (
        select(McpToolCall)
        .where(col(McpToolCall.id) == call_id)
        .execution_options(populate_existing=True)
    )
    async with get_async_session() as db:
        return (await db.exec(query)).first()


async def by_client() -> list[ClientActivity]:
    """Each client's calls, most recently active first, in one query."""
    query = (
        select(
            McpToolCall.client,
            func.count(),
            func.sum(case((McpToolCall.effect == "read", 1), else_=0)),
            func.sum(case((McpToolCall.effect == "proposes", 1), else_=0)),
            func.sum(case((col(McpToolCall.ok).is_(False), 1), else_=0)),
            func.max(McpToolCall.called_at),
        )
        .where(col(McpToolCall.parent_id).is_(None))
        .group_by(McpToolCall.client)
        .order_by(func.max(McpToolCall.called_at).desc())
    )
    async with get_async_session() as db:
        rows = (await db.exec(query)).all()
    return [
        ClientActivity(
            client=client,
            calls=calls,
            reads=reads,
            proposals=proposals,
            failed=failed,
            last_at=last_at,
        )
        for client, calls, reads, proposals, failed, last_at in rows
    ]
