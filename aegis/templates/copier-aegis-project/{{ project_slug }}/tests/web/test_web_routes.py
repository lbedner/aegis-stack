"""The web frontend's routes: tagged, out of the API schema, never shadowed."""

from collections import Counter

from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.components.web_frontend.main import create_web_frontend_app


def _web_routes() -> list[APIRoute]:
    return [r for r in create_web_frontend_app().routes if isinstance(r, APIRoute)]


def test_overseer_routes_are_tagged_overseer_and_the_rest_web() -> None:
    for route in _web_routes():
        expected = "overseer" if "/overseer" in route.path else "web"
        assert route.tags == [expected], route.path


def test_no_web_route_is_published_in_the_api_schema() -> None:
    published = [r.path for r in _web_routes() if r.include_in_schema]
    assert published == []


def test_no_two_routes_share_a_method_and_path(app: FastAPI) -> None:
    pairs = Counter(
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    )
    assert [pair for pair, n in pairs.items() if n > 1] == []
