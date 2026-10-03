"""Record the build this webserver starts, once per build (deploy history)."""

from sqlalchemy.exc import SQLAlchemyError

from app.components.deploy.history import record_start
from app.core.config import settings
from app.core.log import logger


async def startup_hook() -> None:
    try:
        await record_start(settings.BUILD_ID)
    except SQLAlchemyError as e:
        # A build that adds the table starts before ``aegis deploy`` migrates;
        # the deployer's record creates the row then. Never block startup.
        logger.warning(f"Deploy history not recorded for {settings.BUILD_ID}: {e}")
