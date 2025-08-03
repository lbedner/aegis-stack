import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backend.main import create_backend_app
from app.integrations.main import create_integrated_app


@pytest.fixture
def backend_app() -> FastAPI:
    """Create a FastAPI app with backend configuration only"""
    app = FastAPI()
    return create_backend_app(app)


@pytest.fixture
def backend_client(backend_app: FastAPI) -> TestClient:
    """Create a test client for the backend-only app"""
    return TestClient(backend_app)


@pytest.fixture
def integrated_app() -> FastAPI:
    """Create the full integrated Flet+FastAPI app"""
    return create_integrated_app()


@pytest.fixture
def integrated_client(integrated_app: FastAPI) -> TestClient:
    """Create a test client for the integrated app"""
    return TestClient(integrated_app)
