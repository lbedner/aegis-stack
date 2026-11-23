"""The database's API: its audit log, read behind ``get_admin_reader``
(``audit.recent``); and Overseer's write action, behind ``get_admin_actor``:
end one of its Postgres connections, rolling back the transaction it holds
(``db_transactions.end``). Every attempt is audited (who, which connection,
how it went), refused ones included. SQLite has no connection to end: its
holder's container restarts instead (``deploy.router``).
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from app.components.backend.api.utils import audit_admin_action
from app.components.database import audit as audit_log
from app.components.database.models.audit import AuditEvent
from app.core.audit import AuditEmitter, get_audit
from app.services.shared.deps import Actor, get_admin_actor, get_admin_reader
from app.services.system import db_transactions

router = APIRouter(prefix="/database", tags=["database"])


@router.get(
    "/audit",
    response_model=list[AuditEvent],
    dependencies=[Depends(get_admin_reader)],
)
async def audit_events(
    limit: int = Query(200, ge=1, le=audit_log.MOST),
    kind: str | None = Query(None, description="Event types starting with this"),
    actor: str | None = Query(None, description="The actor's email or user id"),
) -> list[AuditEvent]:
    """The newest audited actions."""
    return await audit_log.recent(limit, kind=kind, actor=actor)


class Ended(BaseModel):
    ended: int


@router.post("/connections/{pid}/end", response_model=Ended)
async def end_connection(
    pid: int,
    request: Request,
    actor: Actor = Depends(get_admin_actor),
    audit: AuditEmitter = Depends(get_audit),
) -> Ended:
    """End connection ``pid``: 409 on SQLite, 404 for one that is not this
    database's (or is the one asking)."""

    async def record(outcome: str, detail: str) -> None:
        await audit_admin_action(
            audit, actor, request, "database.connection_end", outcome, detail, pid=pid
        )

    if not db_transactions.is_postgres():
        await record("refused", "SQLite has no connection to end")
        raise HTTPException(status.HTTP_409_CONFLICT, "Only Postgres connections end")
    if not await db_transactions.end(pid):
        await record("refused", f"No connection {pid} to this database")
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No connection {pid}")
    await record("ended", f"Ended connection {pid}")
    return Ended(ended=pid)
