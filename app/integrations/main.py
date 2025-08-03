from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import flet.fastapi as flet_fastapi
from fastapi import FastAPI

from app.backend.main import create_backend_app
from app.core.discovery import auto_discover_services
from app.core.lifecycle import SHUTDOWN_TASKS, STARTUP_TASKS
from app.core.log import logger
from app.frontend.main import create_frontend_app


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    A generic, registry-driven lifespan manager.
    It executes registered startup and shutdown tasks in the correct order.
    """
    # --- STARTUP ---
    logger.info("--- Running application startup tasks ---")

    # Auto-discover services (allows them to register lifecycle tasks)
    auto_discover_services()

    await flet_fastapi.app_manager.start()
    for task in STARTUP_TASKS:
        await task()
    logger.info("--- Startup complete ---")

    yield

    # --- SHUTDOWN ---
    logger.info("--- Running application shutdown tasks ---")
    # Execute shutdown tasks in reverse order
    for task in reversed(SHUTDOWN_TASKS):
        await task()
    await flet_fastapi.app_manager.shutdown()
    logger.info("--- Shutdown complete ---")


def create_integrated_app() -> FastAPI:
    """
    Creates the integrated Flet+FastAPI application using the officially
    recommended pattern and a composable lifecycle registry.
    """
    app = FastAPI(lifespan=lifespan)
    create_backend_app(app)
    # Create and mount the Flet app using the flet.fastapi module
    # First, get the actual session handler function from the factory
    session_handler = create_frontend_app()
    flet_app = flet_fastapi.app(session_handler)
    app.mount("/", flet_app)
    return app
