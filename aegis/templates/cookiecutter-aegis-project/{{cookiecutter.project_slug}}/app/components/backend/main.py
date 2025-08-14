from fastapi import FastAPI

from app.components.backend.api.routing import include_routers
from app.components.backend.hooks import backend_hooks


def create_backend_app(app: FastAPI) -> FastAPI:
    """Configure FastAPI app with all backend concerns"""

    # Auto-discover and register middleware
    backend_hooks.discover_and_register_middleware(app)

    # Include all routes
    include_routers(app)

    return app
