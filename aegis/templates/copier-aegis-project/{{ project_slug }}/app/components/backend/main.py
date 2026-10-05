from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.components.backend.api.routing import include_routers
from app.components.backend.hooks import backend_hooks
from app.core.runtime import RuntimeUnavailableError, UnknownInstanceError

# Store the configured FastAPI app instance for introspection
_configured_app: FastAPI | None = None


def create_backend_app(app: FastAPI) -> FastAPI:
    """Configure FastAPI app with all backend concerns"""
    global _configured_app

    # Store the app instance for later introspection
    _configured_app = app

    # Auto-discover and register middleware
    backend_hooks.discover_and_register_middleware(app)

    # Include all routes
    include_routers(app)

    # The runtime's errors, from any route that reaches it: a container not
    # this app's is a 404, a runtime that does not answer a 503.
    app.add_exception_handler(UnknownInstanceError, _runtime_error)
    app.add_exception_handler(RuntimeUnavailableError, _runtime_error)

    return app


async def _runtime_error(request: Request, exc: Exception) -> JSONResponse:
    code = (
        status.HTTP_404_NOT_FOUND
        if isinstance(exc, UnknownInstanceError)
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return JSONResponse({"detail": str(exc)}, status_code=code)


def get_configured_app() -> FastAPI | None:
    """
    Get the configured backend FastAPI app instance.
    Returns:
        The configured FastAPI app instance, or None if not yet configured.
    """
    return _configured_app
