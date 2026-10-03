"""Deploy history: one row per build that went live, keyed by build id.

Two writers fill the same row. The app records a new build as it starts
(``record_start``), which covers every way code reaches the server: ``aegis
deploy``, CI, a deploy from the Overseer. The deployer adds what only it
knows, who and from where, health, the backup and a rollback
(``record_deploy``, behind the ``deploy record`` command). A row the deployer
never touched has no ``finished_at``. What is live is the running
``BUILD_ID``, never the newest row.
"""

from sqlalchemy.exc import IntegrityError

from app.core.config import Settings, settings
from app.core.db import get_async_session
from app.core.log import logger
from app.core.time import utcnow

from .models import Deployment


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
