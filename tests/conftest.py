from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.components.backend.main import create_backend_app
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


def pytest_addoption(parser: Any) -> None:
    """Add custom pytest options."""
    parser.addoption(
        "--runslow",
        action="store_true",
        default=False,
        help="run slow tests (CLI integration tests with project generation)",
    )


@pytest.fixture
def skip_slow_tests(request: Any) -> None:
    """Skip tests marked as slow unless --runslow is passed."""
    if request.config.getoption("--runslow"):
        return
    pytest.skip("need --runslow option to run")
