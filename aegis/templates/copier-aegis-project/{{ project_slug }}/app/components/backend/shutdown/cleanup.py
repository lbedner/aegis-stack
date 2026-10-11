# app/components/backend/shutdown/cleanup.py
"""
Auto-discovered cleanup shutdown hook.

This hook performs cleanup when the backend shuts down.
"""

from app.core.concurrency import drain
from app.core.log import logger


async def shutdown_hook() -> None:
    """
    Graceful shutdown cleanup.

    Releases resources when the backend stops:
    - Close database connections
    - Flush pending logs
    - Cancel background tasks
    """
    logger.info("Running backend cleanup...")
    await drain(timeout=5)
    logger.info("Backend shutdown cleanup complete")
