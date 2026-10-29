"""The dashboard's socket is the dashboard's own page's, never another
site's: Flet checks no ``Origin``, and an open socket can drive every
control the dashboard has, a change with no auth service included."""

from __future__ import annotations

from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from app.components.backend.middleware.dashboard_origin import (
    DashboardOriginMiddleware,
)


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()

    async def hello(socket: WebSocket) -> None:
        await socket.accept()
        await socket.send_text("hello")
        await socket.close()

    app.add_api_websocket_route("/dashboard/ws", hello)
    app.add_api_websocket_route("/live", hello)
    app.add_middleware(DashboardOriginMiddleware)
    return TestClient(app)  # its sockets are sent to ``testserver``


def _says(client: TestClient, path: str, origin: str | None = None) -> str:
    headers = {"origin": origin} if origin else {}
    with client.websocket_connect(path, headers=headers) as socket:
        return socket.receive_text()


def test_its_own_page_connects(client: TestClient) -> None:
    assert _says(client, "/dashboard/ws", "http://testserver") == "hello"


def test_another_sites_page_is_refused(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect):
        _says(client, "/dashboard/ws", "https://evil.example")


def test_a_client_that_names_no_page_connects(client: TestClient) -> None:
    """Only a browser sends ``Origin``, and only a browser can be led to
    another site's page."""
    assert _says(client, "/dashboard/ws") == "hello"


def test_other_sockets_are_left_alone(client: TestClient) -> None:
    assert _says(client, "/live", "https://evil.example") == "hello"
