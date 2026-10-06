"""The Server's figures as both UIs and its health check show them
(``ui_backend``)."""

from app.services.system import ui_backend


def test_endpoints_are_shown_only_apart_from_routes() -> None:
    """Endpoints count each route's methods: with one method a route they
    would repeat the routes, so they show only where a route has more."""
    assert ui_backend.endpoints_apart(routes=280, endpoints=280) is None
    assert ui_backend.endpoints_apart(routes=280, endpoints=284) == 284
