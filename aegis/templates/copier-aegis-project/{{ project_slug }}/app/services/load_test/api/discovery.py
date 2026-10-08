"""FastAPI route discovery for HTTP load testing.

``list_routes`` walks ``app.routes`` and returns one ``RouteInfo`` per
user-declared (method, path) combination. Auth detection works by
inspecting each route's dependant tree for a caller-supplied auth
callable, so this module stays agnostic about where auth lives in the
project.
"""

from collections.abc import Callable, Sequence
import re

from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.routing import BaseRoute

from app.core.route_auth import route_requires_auth
from app.services.load_test.api.models import RouteInfo

_EXCLUDED_PATHS = frozenset(
    {"/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"}
)
_EXCLUDED_METHODS = frozenset({"HEAD", "OPTIONS"})
# Overseer's pages and fragments answer a session cookie, never the bearer
# token a load test sends.
_EXCLUDED_PREFIXES = ("/overseer", "/partials")
# Same regex used by ``route_inspector.py`` — kept in sync so the CLI and the
# dashboard always see identical path-param names for a given route.
_PATH_PARAM_RE = re.compile(r"\{([^}]+)\}")


def extract_path_params(path: str) -> list[str]:
    """Names of ``{...}`` placeholders in a FastAPI route template, in order."""
    return _PATH_PARAM_RE.findall(path)


def list_routes(
    app: FastAPI, auth_dependency: Callable | None = None
) -> list[RouteInfo]:
    """Enumerate loadable routes.

    Pass ``auth_dependency`` (e.g. the project's ``get_current_user``) to
    populate ``RouteInfo.requires_auth``. Without it, every route reads as
    unauthenticated — discovery can't infer what auth means for a given
    project.
    """
    return describe_routes(app.routes, auth_dependency)


def describe_routes(
    routes: Sequence[BaseRoute], auth_dependency: Callable | None = None
) -> list[RouteInfo]:
    """``list_routes`` over a route list rather than an app."""
    results: list[RouteInfo] = []
    for route in routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path in _EXCLUDED_PATHS or route.path.startswith(_EXCLUDED_PREFIXES):
            continue
        requires_auth = _route_requires_auth(route, auth_dependency)
        tags = list(route.tags) if route.tags else []
        path_params = extract_path_params(route.path)
        for method in route.methods or ():
            if method in _EXCLUDED_METHODS:
                continue
            results.append(
                RouteInfo(
                    method=method,
                    path=route.path,
                    requires_auth=requires_auth,
                    tags=tags,
                    path_params=path_params,
                )
            )
    return results


def _route_requires_auth(route: APIRoute, auth_dependency: Callable | None) -> bool:
    """Whether a route is auth-protected.

    Primary signal: any security scheme in the route's dependant tree (see
    ``app.core.route_auth``), which catches direct, role-based, and
    router-level auth uniformly. The explicit ``auth_dependency`` callable, if
    given, is kept as a fallback for cookie-only deps that use no scheme.
    """
    return route_requires_auth(route) or (
        auth_dependency is not None
        and _route_uses_dependency(route, auth_dependency)
    )


def _route_uses_dependency(route: APIRoute, target: Callable) -> bool:
    """Walk a route's dependant tree looking for ``target``."""

    def _walk(dependant) -> bool:
        for sub in dependant.dependencies:
            if sub.call is target:
                return True
            if _walk(sub):
                return True
        return False

    return _walk(route.dependant)
