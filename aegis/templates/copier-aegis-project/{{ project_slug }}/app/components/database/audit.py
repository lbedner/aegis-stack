"""The audit log: each ``AuditEmitter.emit`` (``app.core.audit``) kept as a
row, written off the caller in a session of its own (``keep``), and read
newest first by Overseer, the API and the CLI (``recent``).

``detail`` and the extra fields are redacted the way error tracking
redacts (``redact``): a credential named in either is never kept.
Nothing is pruned yet; retention is data protection's (DP-09).
"""

from datetime import datetime
from typing import Any

from pydantic_core import to_jsonable_python
from sqlmodel import col, or_, select

from app.core.db import get_async_session
from app.core.time import as_stored
from app.services.system.errors import redact

from .models.audit import AuditEvent

# The columns an event's fields fill by name; the rest go in ``context``.
COLUMNS = (
    "event_type",
    "actor_id",
    "actor_email",
    "target_type",
    "org_id",
    "ip_address",
)
MOST = 1000  # rows one read returns


async def keep(event: dict[str, Any]) -> None:
    """Keep ``event``, as ``AuditEmitter.emit`` made it."""
    fields = dict(event)
    at = datetime.fromisoformat(fields.pop("timestamp"))
    detail = fields.pop("detail", None)
    target = fields.pop("target_id", None)
    row = AuditEvent(
        at=as_stored(at),
        **{name: fields.pop(name) for name in COLUMNS if name in fields},
        target_id=None if target is None else str(target),
        detail=redact.text(str(detail)) if detail is not None else None,
        # Whatever the caller passed, as JSON can hold it.
        context=to_jsonable_python(redact.clean(fields), fallback=str),
    )
    async with get_async_session() as db:
        db.add(row)
        await db.commit()


async def recent(
    limit: int = 200, *, kind: str | None = None, actor: str | None = None
) -> list[AuditEvent]:
    """The newest ``limit`` rows (at most ``MOST``): of the event types
    starting ``kind`` (``auth.``), by the actor whose email or id is
    ``actor``."""
    query = select(AuditEvent)
    if kind:
        query = query.where(col(AuditEvent.event_type).startswith(kind))
    if actor:
        by_id = [AuditEvent.actor_id == int(actor)] if actor.isdigit() else []
        query = query.where(or_(AuditEvent.actor_email == actor, *by_id))
    query = query.order_by(col(AuditEvent.at).desc(), col(AuditEvent.id).desc())
    async with get_async_session(read_only=True) as db:
        return list((await db.exec(query.limit(min(limit, MOST)))).all())
