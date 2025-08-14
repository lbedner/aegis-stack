from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
import flet.fastapi as flet_fastapi

from app.components.backend.hooks import backend_hooks
from app.components.backend.main import create_backend_app
from app.components.frontend.main import create_frontend_app
from app.core.log import logger


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.
    Handles startup/shutdown concerns using component-specific hooks.
    """
    # --- STARTUP ---
    logger.info("--- Running application startup ---")

    # Discover startup and shutdown hooks
    await backend_hooks.discover_lifespan_hooks()

    # Start Flet app manager
    await flet_fastapi.app_manager.start()

    # Execute backend startup hooks
    await backend_hooks.execute_startup_hooks()

    logger.info("--- Application startup complete ---")

    yield

    # --- SHUTDOWN ---
    logger.info("--- Running application shutdown ---")

    # Execute backend shutdown hooks
    await backend_hooks.execute_shutdown_hooks()

    # Stop Flet app manager
    await flet_fastapi.app_manager.shutdown()

    logger.info("--- Application shutdown complete ---")


def create_integrated_app() -> FastAPI:
    """
    Creates the integrated Flet+FastAPI application using the officially
    recommended pattern and component-specific hooks.
    """
    app = FastAPI(lifespan=lifespan)

    create_backend_app(app)
    # Create and mount the Flet app using the flet.fastapi module
    # First, get the actual session handler function from the factory
    session_handler = create_frontend_app()
    flet_app = flet_fastapi.app(session_handler)
    # Mount Flet at /dashboard to avoid intercepting FastAPI routes like /health
    app.mount("/dashboard", flet_app)
    return app
