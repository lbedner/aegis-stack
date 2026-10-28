"""The dashboard's socket is the dashboard's own page's.

Flet's socket (under ``DASHBOARD_PATH``) checks no ``Origin``, and an open one
drives every control the dashboard has: without auth, a change made from
it is judged by the address the page was opened at (``refusal_at``), so a
page on another site, its socket sent to ``localhost``, would pass. A
socket whose ``Origin`` names another host than it was sent to is closed
before it opens, as a browser's form from another site is refused by the
API (``Origin`` in ``deps.operator_refusal``). A client that names no page (no
``Origin``) is not a browser led there, and connects.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import FastAPI
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocketClose

from app.core.constants import DASHBOARD_PATH


def _from_another_site(scope: Scope) -> bool:
    headers = Headers(scope=scope)
    origin = headers.get("origin")
    return origin is not None and urlsplit(origin).netloc != headers.get("host")


class DashboardOriginMiddleware:
    """Pure ASGI: only a socket under ``DASHBOARD_PATH`` is looked at."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "websocket"
            and scope["path"].startswith(DASHBOARD_PATH)
            and _from_another_site(scope)
        ):
            await WebSocketClose()(scope, receive, send)
            return
        await self.app(scope, receive, send)


def register_middleware(app: FastAPI) -> None:
    app.add_middleware(DashboardOriginMiddleware)
