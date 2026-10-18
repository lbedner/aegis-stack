"""Tests for the operator paths' HTTP Basic auth gate: docs, redoc,
openapi.json and the detailed health tree.

The gate lives in ``app.components.backend.security.operator_auth`` and
reads ``settings.DOCS_USERNAME``/``DOCS_PASSWORD``/``APP_ENV`` at request
time, so each test can mutate ``settings`` with ``monkeypatch`` without
rebuilding the app.
"""

from collections.abc import Generator

import pytest
from app.core.config import settings
from app.integrations.main import create_integrated_app
from fastapi.testclient import TestClient

DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")
GATED = (*DOCS_PATHS, "/health/detailed", "/health/dashboard")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    """Fresh client with creds cleared; tests opt into setting them."""
    monkeypatch.setattr(settings, "DOCS_USERNAME", "")
    monkeypatch.setattr(settings, "DOCS_PASSWORD", "")
    app = create_integrated_app()
    with TestClient(app) as test_client:
        yield test_client


def test_dev_unset_creds_opens_docs(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """APP_ENV=dev with no creds: docs endpoints serve without auth."""
    monkeypatch.setattr(settings, "APP_ENV", "dev")
    for path in GATED:
        response = client.get(path)
        assert response.status_code == 200, path


def test_prod_unset_creds_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """APP_ENV != dev with no creds: docs endpoints fail closed with 404."""
    monkeypatch.setattr(settings, "APP_ENV", "prod")
    for path in GATED:
        response = client.get(path)
        assert response.status_code == 404, path


def test_creds_set_no_auth_header_returns_401(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "prod")
    monkeypatch.setattr(settings, "DOCS_USERNAME", "admin")
    monkeypatch.setattr(settings, "DOCS_PASSWORD", "secret")
    for path in GATED:
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.headers.get("WWW-Authenticate") == "Basic", path


def test_creds_set_wrong_creds_returns_401(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "prod")
    monkeypatch.setattr(settings, "DOCS_USERNAME", "admin")
    monkeypatch.setattr(settings, "DOCS_PASSWORD", "secret")
    for path in GATED:
        response = client.get(path, auth=("admin", "wrong"))
        assert response.status_code == 401, path


def test_creds_set_correct_creds_serves_docs(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "prod")
    monkeypatch.setattr(settings, "DOCS_USERNAME", "admin")
    monkeypatch.setattr(settings, "DOCS_PASSWORD", "secret")

    swagger = client.get("/docs", auth=("admin", "secret"))
    assert swagger.status_code == 200
    assert "swagger" in swagger.text.lower()

    redoc = client.get("/redoc", auth=("admin", "secret"))
    assert redoc.status_code == 200
    assert "redoc" in redoc.text.lower()

    openapi = client.get("/openapi.json", auth=("admin", "secret"))
    assert openapi.status_code == 200
    payload = openapi.json()
    assert payload["openapi"].startswith("3.")
    assert "paths" in payload


def test_the_detailed_health_tree_serves_with_creds(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "prod")
    monkeypatch.setattr(settings, "DOCS_USERNAME", "admin")
    monkeypatch.setattr(settings, "DOCS_PASSWORD", "secret")

    response = client.get("/health/detailed", auth=("admin", "secret"))

    assert response.status_code == 200
    assert "components" in response.json()


@pytest.fixture
def local(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    """A client calling from loopback, as one inside the container does."""
    monkeypatch.setattr(settings, "APP_ENV", "prod")
    monkeypatch.setattr(settings, "DOCS_USERNAME", "admin")
    monkeypatch.setattr(settings, "DOCS_PASSWORD", "secret")
    app = create_integrated_app()
    with TestClient(app, client=("127.0.0.1", 50000)) as test_client:
        yield test_client


def test_a_caller_inside_the_container_needs_no_creds(local: TestClient) -> None:
    """The CLI's ``health``, ``live_status`` and the dashboard ask the
    webserver over loopback, from inside its container; Traefik and a
    published port never arrive as loopback."""
    assert local.get("/health/detailed").status_code == 200
