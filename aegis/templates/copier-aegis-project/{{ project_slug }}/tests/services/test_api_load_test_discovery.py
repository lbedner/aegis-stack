"""
Unit tests for FastAPI route discovery.

``list_routes(app, auth_dependency=None)`` walks ``app.routes`` and returns
one ``RouteInfo`` per (method, path) combination. Auth detection works by
inspecting the route's ``dependant.dependencies`` for the caller-supplied
auth callable — not by string matching, so the test exercises the real
mechanism.

Caller passes the auth dependency in explicitly rather than the discovery
module hard-coding a path into the project's auth service. This keeps the
discovery module agnostic about where auth lives.
"""

from fastapi import Depends, FastAPI
from app.services.load_test.api.discovery import list_routes
from app.services.load_test.api.models import RouteInfo


async def _auth_dep() -> dict:
    return {"user_id": 1}


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/health", tags=["system"])
    async def health():
        return {"ok": True}

    @app.get("/api/users", tags=["users"])
    async def list_users(_user=Depends(_auth_dep)):
        return []

    @app.post("/api/users", tags=["users"])
    async def create_user(_user=Depends(_auth_dep)):
        return {"id": 1}

    @app.post("/api/login")
    async def login():
        return {"token": "x"}

    @app.get("/api/users/{user_id}", tags=["users"])
    async def get_user(user_id: str, _user=Depends(_auth_dep)):
        return {"id": user_id}

    @app.get("/api/items/{item_id}/owner/{user_id}", tags=["items"])
    async def item_owner(item_id: str, user_id: str):
        return {"item": item_id, "user": user_id}

    return app


class TestListRoutes:
    def test_returns_one_entry_per_method_path(self):
        app = _build_app()
        routes = list_routes(app, auth_dependency=_auth_dep)
        # /health GET, /api/users GET, /api/users POST, /api/login POST = 4
        paths_methods = {(r.method, r.path) for r in routes}
        assert ("GET", "/health") in paths_methods
        assert ("GET", "/api/users") in paths_methods
        assert ("POST", "/api/users") in paths_methods
        assert ("POST", "/api/login") in paths_methods

    def test_returns_routeinfo_objects(self):
        app = _build_app()
        routes = list_routes(app, auth_dependency=_auth_dep)
        assert all(isinstance(r, RouteInfo) for r in routes)

    def test_requires_auth_true_when_dependency_present(self):
        app = _build_app()
        routes = list_routes(app, auth_dependency=_auth_dep)
        by_key = {(r.method, r.path): r for r in routes}
        assert by_key[("GET", "/api/users")].requires_auth is True
        assert by_key[("POST", "/api/users")].requires_auth is True

    def test_requires_auth_false_when_dependency_absent(self):
        app = _build_app()
        routes = list_routes(app, auth_dependency=_auth_dep)
        by_key = {(r.method, r.path): r for r in routes}
        assert by_key[("GET", "/health")].requires_auth is False
        assert by_key[("POST", "/api/login")].requires_auth is False

    def test_tags_forwarded(self):
        app = _build_app()
        routes = list_routes(app, auth_dependency=_auth_dep)
        by_key = {(r.method, r.path): r for r in routes}
        assert by_key[("GET", "/health")].tags == ["system"]
        assert by_key[("GET", "/api/users")].tags == ["users"]
        assert by_key[("POST", "/api/login")].tags == []

    def test_no_auth_dependency_argument_means_all_routes_unauthed(self):
        """If the caller doesn't pass an auth dependency, every route reads
        as ``requires_auth=False`` — discovery can't guess what auth means
        for this project."""
        app = _build_app()
        routes = list_routes(app)
        assert all(r.requires_auth is False for r in routes)

    def test_excludes_openapi_and_docs_routes(self):
        """FastAPI auto-registers ``/openapi.json``, ``/docs``, ``/redoc``.
        Load testing those is rarely useful; exclude them by default."""
        app = _build_app()
        routes = list_routes(app, auth_dependency=_auth_dep)
        paths = {r.path for r in routes}
        assert "/openapi.json" not in paths
        assert "/docs" not in paths
        assert "/redoc" not in paths

    def test_head_and_options_excluded(self):
        """FastAPI implicitly registers HEAD for GET routes. Load testing
        HEAD by default surprises users (and OPTIONS is preflight-only).
        Only user-declared verbs come back."""
        app = _build_app()
        routes = list_routes(app, auth_dependency=_auth_dep)
        methods = {r.method for r in routes}
        assert "HEAD" not in methods
        assert "OPTIONS" not in methods


class TestPathParamExtraction:
    """``RouteInfo.path_params`` carries the names of ``{...}`` placeholders.

    Same regex source as ``route_inspector.py`` so the CLI and dashboard
    see identical param lists for any route.
    """

    def test_no_params_for_static_path(self):
        app = _build_app()
        routes = list_routes(app, auth_dependency=_auth_dep)
        by_key = {(r.method, r.path): r for r in routes}
        assert by_key[("GET", "/health")].path_params == []
        assert by_key[("POST", "/api/login")].path_params == []

    def test_single_param_extracted(self):
        app = _build_app()
        routes = list_routes(app, auth_dependency=_auth_dep)
        by_key = {(r.method, r.path): r for r in routes}
        assert by_key[("GET", "/api/users/{user_id}")].path_params == ["user_id"]

    def test_multiple_params_extracted_in_order(self):
        """Order matters for users skimming the table: we preserve template order."""
        app = _build_app()
        routes = list_routes(app, auth_dependency=_auth_dep)
        by_key = {(r.method, r.path): r for r in routes}
        route = by_key[("GET", "/api/items/{item_id}/owner/{user_id}")]
        assert route.path_params == ["item_id", "user_id"]


def test_overseers_own_pages_are_not_loadable() -> None:
    """They answer a session cookie, never the bearer token a run sends."""
    app = _build_app()

    @app.get("/overseer/components/{name}")
    async def page(name: str) -> dict:
        return {}

    @app.post("/partials/overseer/server/load-tests")
    async def action() -> dict:
        return {}

    paths = {r.path for r in list_routes(app)}
    assert "/health" in paths
    assert not [p for p in paths if p.startswith(("/overseer", "/partials"))]
