"""What the backend health check knows about itself, cached once.

Route, middleware and lifecycle metadata are all derived by walking the
configured FastAPI app, which is far too expensive to redo on every
health poll. The startup hook primes these; the accessors below fill
them lazily as a fallback, because a health check can run before the
hook does (tests do exactly that).
"""

import importlib
from pathlib import Path
from typing import Any

from app.components.backend.main import get_configured_app
from app.core.log import logger
from app.services.backend.middleware_inspector import (
    MiddlewareMetadata,
    get_fastapi_middleware_metadata,
)
from app.services.backend.route_inspector import (
    RouteMetadata,
    get_fastapi_route_metadata,
)

# Cache for route metadata - initialized once at startup
_cached_route_metadata: RouteMetadata | None = None
# Cache for middleware metadata - initialized once at startup
_cached_middleware_metadata: MiddlewareMetadata | None = None
# Cache for lifecycle metadata - initialized once at startup
_cached_lifecycle_metadata: dict[str, Any] | None = None

_EMPTY_LIFECYCLE: dict[str, Any] = {"startup_hooks": [], "shutdown_hooks": []}


def initialize_route_metadata_cache() -> None:
    """
    Initialize route and middleware metadata caches using the configured FastAPI app.
    Called once during startup to avoid recreating the app on every health check.
    """
    global _cached_route_metadata, _cached_middleware_metadata

    if _cached_route_metadata is not None and _cached_middleware_metadata is not None:
        return  # Already initialized

    try:
        app = get_configured_app()
        if app is None:
            logger.warning(
                "FastAPI app not yet configured - route and middleware metadata "
                "cache will be initialized later"
            )
            return

        # Cache route metadata
        if _cached_route_metadata is None:
            _cached_route_metadata = get_fastapi_route_metadata(app)
            logger.info(
                f"Route metadata cached: "
                f"{_cached_route_metadata.total_routes} routes, "
                f"{_cached_route_metadata.total_endpoints} endpoints"
            )

        # Cache middleware metadata
        if _cached_middleware_metadata is None:
            _cached_middleware_metadata = get_fastapi_middleware_metadata(app)
            logger.info(
                f"Middleware metadata cached: "
                f"{_cached_middleware_metadata.total_middleware} middleware, "
                f"{_cached_middleware_metadata.security_count} security layers"
            )
    except Exception as e:
        logger.error(f"Failed to initialize route and middleware metadata cache: {e}")


def route_and_middleware(
    *, warn_when_cold: bool = False
) -> tuple[RouteMetadata | None, MiddlewareMetadata | None]:
    """The cached pair, filling it on the way out if nobody has yet.

    Still returns ``None`` for either half when the app cannot be
    introspected at all - callers report that as "introspection
    unavailable" rather than as a failure. ``warn_when_cold`` is for the
    production path, where arriving here cold means the startup hook did
    not run and that is worth saying out loud.
    """
    if _cached_route_metadata is None or _cached_middleware_metadata is None:
        if warn_when_cold:
            logger.warning(
                "Route and middleware metadata cache not initialized at startup, "
                "initializing now..."
            )
        initialize_route_metadata_cache()
    return _cached_route_metadata, _cached_middleware_metadata


def _discover_lifecycle_hooks() -> dict[str, Any]:
    """
    Discover startup and shutdown hooks from the backend directories.

    Returns a dict with startup_hooks and shutdown_hooks lists,
    each containing hook info with name and description.
    """
    backend_dir = Path(__file__).parent.parent

    def get_hooks_from_dir(hook_dir: Path) -> list[dict[str, str]]:
        """Get hook info from a directory by importing modules
        and reading docstrings."""
        hooks = []
        if not hook_dir.exists():
            return hooks

        for hook_file in sorted(hook_dir.glob("*.py")):
            if hook_file.name.startswith("_"):
                continue

            module_name = f"app.components.backend.{hook_dir.name}.{hook_file.stem}"
            try:
                module = importlib.import_module(module_name)
                # Check if it has a startup_hook or shutdown_hook function
                hook_func = getattr(module, "startup_hook", None) or getattr(
                    module, "shutdown_hook", None
                )
                if hook_func:
                    # Get description from function docstring (full text)
                    doc = hook_func.__doc__ or ""
                    description = doc.strip() if doc else f"{hook_file.stem} hook"

                    hooks.append({
                        "name": hook_file.stem,
                        "description": description,
                        "module": module_name,
                    })
            except Exception as e:
                logger.debug(f"Could not load hook module {module_name}: {e}")
                # Still include it as discovered
                hooks.append({
                    "name": hook_file.stem,
                    "description": f"{hook_file.stem} hook",
                    "module": module_name,
                })

        return hooks

    startup_hooks = get_hooks_from_dir(backend_dir / "startup")
    shutdown_hooks = get_hooks_from_dir(backend_dir / "shutdown")

    return {
        "startup_hooks": startup_hooks,
        "shutdown_hooks": shutdown_hooks,
    }


def initialize_lifecycle_metadata_cache() -> None:
    """Initialize lifecycle metadata cache."""
    global _cached_lifecycle_metadata

    if _cached_lifecycle_metadata is not None:
        return

    try:
        _cached_lifecycle_metadata = _discover_lifecycle_hooks()
        startup_count = len(_cached_lifecycle_metadata.get("startup_hooks", []))
        shutdown_count = len(_cached_lifecycle_metadata.get("shutdown_hooks", []))
        logger.info(
            f"Lifecycle metadata cached: {startup_count} startup hooks, "
            f"{shutdown_count} shutdown hooks"
        )
    except Exception as e:
        logger.error(f"Failed to initialize lifecycle metadata cache: {e}")
        _cached_lifecycle_metadata = dict(_EMPTY_LIFECYCLE)


def lifecycle() -> dict[str, Any]:
    """The discovered startup/shutdown hooks, or an empty pair of lists."""
    if _cached_lifecycle_metadata is None:
        initialize_lifecycle_metadata_cache()
    return _cached_lifecycle_metadata or dict(_EMPTY_LIFECYCLE)
