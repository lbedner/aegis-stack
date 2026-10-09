"""The Overseer Web Frontend page: its status, and its own routes."""

from collections.abc import Generator

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.services.system.models import ComponentStatus
from tests.web.dom import one, select, text
from tests.web.overseer import sign_in, status_with

WEB_FRONTEND = ComponentStatus(
    name="web_frontend",
    message="htmx web frontend component available",
    metadata={"framework": "Jinja2 + htmx", "routes": 3},
)
BACKEND = ComponentStatus(
    name="backend",
    message="Running",
    metadata={
        "routes": [
            {"path": "/", "methods": ["GET"], "tags": ["web"]},
            {"path": "/overseer", "methods": ["GET"], "tags": ["overseer"]},
            {"path": "/overseer/events", "methods": ["GET"], "tags": ["overseer"]},
            {"path": "/health/", "methods": ["GET"], "tags": ["health"]},
        ]
    },
)


@pytest.fixture
def client(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    sign_in(app, monkeypatch, status_with(BACKEND, WEB_FRONTEND))
    with TestClient(app) as client:
        yield client


def _get(client: TestClient, section: str = "") -> str:
    url = "/overseer/components/web_frontend" + (f"/{section}" if section else "")
    response = client.get(url)
    assert response.status_code == 200
    return response.text


def test_sections_are_overview_routes_and_its_settings(client: TestClient) -> None:
    """Settings: whether Overseer > Code is on outside dev."""
    assert [text(a) for a in select(_get(client), "#overseer-subnav nav a")] == [
        "Overview",
        "Routes",
        "Settings",
    ]


def test_overview_keeps_the_status_and_details(client: TestClient) -> None:
    assert "Jinja2 + htmx" in text(one(_get(client), "#card-details"))


def test_routes_are_the_web_and_overseer_ones_only(client: TestClient) -> None:
    groups = select(_get(client, "routes"), "[data-route-group]")
    assert {text(one(g, "h2")): len(select(g, "tbody tr:not([data-detail])")) for g in groups} == {
        "overseer": 2,
        "web": 1,
    }
