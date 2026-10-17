"""Deploy history: one row per build that went live, keyed by build id.

Two writers fill the same row. The app records a new build as it starts
(``record_start``), which covers every way code reaches the server: ``aegis
deploy``, CI, a deploy from the Overseer. The deployer adds what only it
knows, who and from where, health, the backup and a rollback
(``record_deploy``, behind the ``deploy record`` command). A row the deployer
never touched has no ``finished_at``. What is live is the running
``BUILD_ID``, never the newest row. Overseer reads it (``recent``, ``get``).

Everything else done to the server is an event (``record_event``): ``aegis``
writes one per command through ``deploy event``, a job in the app directly.
"""

from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from app.core.config import Settings, settings
from app.core.db import get_async_session
from app.core.log import logger
from app.core.time import as_stored, utcnow

from .models import DeployEvent, Deployment


async def record_start(build_id: str) -> None:
    """Record ``build_id`` the first time it starts; a restart writes nothing."""
    if build_id == Settings.model_fields["BUILD_ID"].default:
        return
    async with get_async_session() as db:
        if await db.get(Deployment, build_id) is not None:
            return
        db.add(Deployment(build_id=build_id))
        try:
            await db.commit()
        except IntegrityError:
            # Another replica of the same build recorded it first.
            await db.rollback()
            logger.debug(f"Build {build_id} already recorded by another process")


async def record_deploy(
    build_id: str,
    *,
    deployed_by: str | None = None,
    deployed_from: str | None = None,
    health: str | None = None,
    backup: str | None = None,
    rolled_back: bool = False,
) -> None:
    """Fill in the deployer's side of ``build_id``'s row, creating it when the
    build never got as far as starting. After a rollback the restored build
    is the one running, so it is named from this process's ``BUILD_ID``."""
    async with get_async_session() as db:
        row = await db.get(Deployment, build_id) or Deployment(build_id=build_id)
        row.deployed_by = deployed_by
        row.deployed_from = deployed_from
        row.health = health
        row.backup = backup
        row.rolled_back_to = settings.BUILD_ID if rolled_back else None
        row.finished_at = utcnow()
        db.add(row)
        await db.commit()


async def recent(limit: int = 50) -> list[Deployment]:
    """The last ``limit`` builds that went live, newest first."""
    async with get_async_session() as db:
        query = select(Deployment).order_by(col(Deployment.started_at).desc())
        return list((await db.exec(query.limit(limit))).all())


async def get(build_id: str) -> Deployment | None:
    """``build_id``'s row, if it went live here."""
    async with get_async_session() as db:
        return await db.get(Deployment, build_id)


async def record_event(
    kind: str,
    outcome: str,
    *,
    summary: str = "",
    actor: str | None = None,
    origin: str | None = None,
    started_at: datetime | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Keep one thing done to the server, as it finishes."""
    now = utcnow()
    event = DeployEvent(
        kind=kind,
        outcome=outcome,
        summary=summary,
        actor=actor,
        origin=origin,
        started_at=as_stored(started_at) if started_at else now,
        finished_at=now,
        detail=detail or {},
    )
    async with get_async_session() as db:
        db.add(event)
        await db.commit()


async def recent_events(limit: int = 50) -> list[DeployEvent]:
    """The last ``limit`` events, newest first."""
    async with get_async_session() as db:
        query = select(DeployEvent).order_by(col(DeployEvent.finished_at).desc())
        return list((await db.exec(query.limit(limit))).all())


async def latest_event(kind: str) -> DeployEvent | None:
    """The newest event of ``kind``, if there was one."""
    async with get_async_session() as db:
        query = (
            select(DeployEvent)
            .where(DeployEvent.kind == kind)
            .order_by(col(DeployEvent.finished_at).desc())
        )
        return (await db.exec(query.limit(1))).first()
