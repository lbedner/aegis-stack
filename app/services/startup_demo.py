# app/services/startup_demo.py
"""
A demonstration service to show how to register lifecycle events.
"""

import asyncio

from app.core.lifecycle import SHUTDOWN_TASKS, STARTUP_TASKS
from app.core.log import logger


async def start_demo_service() -> None:
    """A sample startup task."""
    logger.info("Lifecycle: Starting demo service...")
    await asyncio.sleep(0.1)  # Simulate async work
    logger.info("Lifecycle: Demo service started.")


async def shutdown_demo_service() -> None:
    """A sample shutdown task."""
    logger.info("Lifecycle: Shutting down demo service...")
    await asyncio.sleep(0.1)  # Simulate async work
    logger.info("Lifecycle: Demo service shut down.")


# Register the functions with the application lifecycle
STARTUP_TASKS.append(start_demo_service)
SHUTDOWN_TASKS.append(shutdown_demo_service)
