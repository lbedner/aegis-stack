"""The record of MCP activity: what each outside assistant looked at and
what it proposed (``McpToolCall``), kept where there is a database.

``record`` is the server's recorder (``build_server(record=...)``): it logs
the call like every MCP server does, then keeps it. A record that fails to
keep is logged as an error and the client still gets its answer.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import col, func, select

from app.core.db import get_async_session
from app.core.log import logger

from .models.calls import McpToolCall
from .server import McpCall, log_call


@dataclass(frozen=True)
class ClientActivity:
    """One client's calls, summed: how much it read and proposed."""

    client: str
    calls: int
    reads: int
    proposals: int
    failed: int
    last_at: datetime


async def record(call: McpCall) -> None:
    await log_call(call)
    try:
        async with get_async_session() as db:
            db.add(
                McpToolCall(
                    client=call.client,
                    tool=call.tool,
                    effect=call.effect,
                    ok=call.ok,
                    duration_ms=call.duration_ms,
                    result_bytes=call.result_bytes,
                )
            )
    except SQLAlchemyError:
        logger.exception("mcp.record_failed", tool=call.tool, client=call.client)


async def recent(*, limit: int = 50) -> list[McpToolCall]:
    """The newest calls first, every client."""
    query = select(McpToolCall).order_by(col(McpToolCall.id).desc()).limit(limit)
    async with get_async_session() as db:
        return list((await db.exec(query)).all())


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
        .group_by(McpToolCall.client)
        .order_by(func.max(McpToolCall.called_at).desc())
    )
    async with get_async_session() as db:
        rows = (await db.exec(query)).all()
    return [
        ClientActivity(client, calls, reads, proposals, failed, last_at)
        for client, calls, reads, proposals, failed, last_at in rows
    ]
