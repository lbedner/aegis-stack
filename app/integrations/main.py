from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import flet.fastapi as flet_fastapi
from fastapi import FastAPI

from app.backend.main import create_backend_app
from app.core.discovery import discover_and_import_services
from app.core.lifecycle import SHUTDOWN_TASKS, STARTUP_TASKS
from app.core.log import logger, setup_logging
from app.frontend.main import create_frontend_app

# --- DYNAMIC SERVICE DISCOVERY ---
# This block runs once when the module is first imported.
# It automatically finds and imports all modules in the 'app/services' directory,
# allowing them to self-register their lifecycle tasks.
SERVICES_DIR = Path(__file__).parent.parent / "services"
discover_and_import_services(SERVICES_DIR)
# ---------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    A generic, registry-driven lifespan manager.
    It executes registered startup and shutdown tasks in the correct order.
    """
    # --- STARTUP ---
    setup_logging()
    logger.info("--- Running application startup tasks ---")
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
