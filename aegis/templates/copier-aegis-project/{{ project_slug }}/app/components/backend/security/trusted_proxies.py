"""The client's address behind a proxy, settled once for the whole app.

``X-Forwarded-For`` is believed only when it arrives from a sender in
``TRUSTED_PROXIES``: a caller that reaches the app's port directly sends a
header too, and a rule about which entry to read can't tell the two apart.
Uvicorn's ``ProxyHeadersMiddleware`` does the walk (right to left, skipping
trusted hops, so a CDN in front of Traefik works) and rewrites the scope's
client and scheme, so every reader of the address agrees: rate limits,
sessions, audit, traffic and the open connections.

The settings are read per request, not at build, so a test can turn trust
on against the session-scoped app.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.core.config import settings


class TrustedProxyMiddleware:
    """Pure ASGI, so a websocket's client is rewritten as well as a page's."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._proxied: dict[tuple[str, ...], ProxyHeadersMiddleware] = {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if settings.TRUST_PROXY_HEADERS and scope["type"] in ("http", "websocket"):
            await self._behind(tuple(settings.TRUSTED_PROXIES))(scope, receive, send)
            return
        await self.app(scope, receive, send)

    def _behind(self, trusted: tuple[str, ...]) -> ProxyHeadersMiddleware:
        """Uvicorn's middleware for these senders, built once per list. Never
        ``"*"``: trusting every sender, it reads the left-most entry, the
        one the caller wrote."""
        if trusted not in self._proxied:
            self._proxied[trusted] = ProxyHeadersMiddleware(
                self.app, trusted_hosts=list(trusted)
            )
        return self._proxied[trusted]
