from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_health_check(backend_client: TestClient) -> None:
    """Test the basic health check endpoint"""
    response = backend_client.get("/health/")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_detailed_health_check(backend_client: TestClient) -> None:
    """Test the detailed health check endpoint"""
    response = backend_client.get("/health/detailed")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "healthy"
    assert data["service"] == "aegis-stack"
    assert data["version"] == "0.1.0"


def test_health_check_response_format(backend_client: TestClient) -> None:
    """Test that health check returns proper JSON content type"""
    response = backend_client.get("/health/")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"


def test_health_endpoints_are_available(backend_app: FastAPI) -> None:
    """Test that health endpoints are properly registered"""
    routes = [getattr(route, "path", "") for route in backend_app.routes]

    assert "/health/" in routes
    assert "/health/detailed" in routes
