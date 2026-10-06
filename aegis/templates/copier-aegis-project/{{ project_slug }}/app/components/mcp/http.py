"""MCP over HTTP: the stdio server's tools, mounted in the webserver at
``/mcp`` for a client elsewhere. Every request carries an MCP token
(``Authorization: Bearer mcp_...``); no token, no tools. Its owner is who
the calls act for and its scope what they reach (``server.Attribution``).

No CORS: desktop and coding clients are not browsers. Not through the dev
tunnel, whose guard admits only the Plaid webhook.
"""

from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.http import StarletteWithLifespan

from app.core.config import settings
from app.core.db import get_async_session
from app.core.tools import load_tools

from . import tokens
from .activity import record
from .server import build_server

PATH = "/mcp"


class McpTokens(TokenVerifier):
    """A request's bearer token, resolved to its owner and the effects its
    scope reaches. A revoked or unknown token is refused (401)."""

    async def verify_token(self, token: str) -> AccessToken | None:
        async with get_async_session() as db:
            row = await tokens.resolve(db, token)
        if row is None:
            return None
        return AccessToken(
            token=token,
            client_id=f"mcp-token-{row.id}",
            scopes=sorted(tokens.SCOPES[row.scope]),
            claims={"user_id": row.user_id},
        )


def build_http_app() -> StarletteWithLifespan:
    """The app to mount at ``PATH``. Its lifespan must run inside the root
    app's (``app/integrations/main.py``): a mounted app's does not run on
    its own, and without it no session starts."""
    load_tools()
    server = build_server(settings.MCP_TOOLS, record=record, auth=McpTokens())
    return server.http_app(path="/", json_response=True)
