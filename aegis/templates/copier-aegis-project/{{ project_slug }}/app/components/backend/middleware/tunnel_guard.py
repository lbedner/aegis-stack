"""Only Plaid's webhook comes in through the dev tunnel.

The dev overlay's ``plaid-tunnel`` sidecar is a cloudflared quick tunnel to
the whole webserver, so its public ``*.trycloudflare.com`` address would
open every page of an app that has no login. Cloudflare marks each request
it forwards with ``cf-ray``: a marked request gets 404 unless it is Plaid's
webhook. Local and LAN requests carry no mark and pass untouched.
"""

from __future__ import annotations

from fastapi import FastAPI
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocketClose

from app.components.backend.startup.finance_webhook_tunnel import (
    PLAID_WEBHOOK_PATH,
    tunnel_metrics_url,
)


def _through_the_tunnel(scope: Scope) -> bool:
    return any(name == b"cf-ray" for name, _value in scope.get("headers") or ())


def _is_the_webhook(scope: Scope) -> bool:
    return (
        scope["type"] == "http"
        and scope["method"] == "POST"
        and scope["path"] == PLAID_WEBHOOK_PATH
    )


class TunnelGuardMiddleware:
    """Pure ASGI, so a live-call websocket is refused as well as a page."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] in ("http", "websocket")
            and _through_the_tunnel(scope)
            and not _is_the_webhook(scope)
        ):
            refusal = (
                WebSocketClose()
                if scope["type"] == "websocket"
                else PlainTextResponse("Not Found", status_code=404)
            )
            await refusal(scope, receive, send)
            return
        await self.app(scope, receive, send)


def register_middleware(app: FastAPI) -> None:
    """Installed only where the dev overlay runs the tunnel."""
    if tunnel_metrics_url():
        app.add_middleware(TunnelGuardMiddleware)
