"""The MCP server: the app's granted tools, for an outside assistant.

Tools are the registry's own callables (``app.core.tools``), registered by
name: FastMCP builds each schema from the type hints and docstring the
chat agents already read, so a read over MCP and the same read by an agent
are one computation. Never ``FastMCP.from_fastapi``: that would turn every
API route into a tool, writes included, and give one question two answers.
"""

from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
import time
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AuthProvider
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import Tool
from fastmcp.tools.tool import ToolResult
from mcp import types

from app.core.config import settings
from app.core.log import logger
from app.core.tools import acting_as, get_tool, mcp_servable


@dataclass(frozen=True)
class McpCall:
    """One tool call, attributed to the client that made it. Measured the
    way the agents' tool-call ledger measures (``tool_telemetry``)."""

    tool: str
    client: str
    effect: str
    duration_ms: int
    result_bytes: int
    ok: bool


Recorder = Callable[[McpCall], Awaitable[None]]


async def log_call(call: McpCall) -> None:
    """The record where there is no database (``activity.record`` keeps it
    where there is one)."""
    logger.info(
        "mcp.call",
        tool=call.tool,
        client=call.client,
        effect=call.effect,
        duration_ms=call.duration_ms,
        result_bytes=call.result_bytes,
        ok=call.ok,
    )


def _client_name(context: MiddlewareContext[Any]) -> str:
    """The name the client gave at initialize, or ``unknown``."""
    if context.fastmcp_context is None:
        return "unknown"
    params = context.fastmcp_context.session.client_params
    return params.clientInfo.name if params is not None else "unknown"


def _result_bytes(result: ToolResult) -> int:
    return sum(
        len(block.text.encode())
        for block in result.content
        if isinstance(block, types.TextContent)
    )


def _reach() -> tuple[int | None, frozenset[str] | None]:
    """Who a call acts for, and the effects it may reach: over HTTP, the
    token's owner and scope (its scopes are effects, ``tokens.SCOPES``);
    over stdio there is no token, so MCP_OWNER_USER_ID and the grant."""
    token = get_access_token()
    if token is None:
        return settings.MCP_OWNER_USER_ID, None
    return token.claims["user_id"], frozenset(token.scopes)


def _within(name: str, effects: frozenset[str] | None) -> bool:
    tool = get_tool(name)
    return effects is None or (tool is not None and tool.effect in effects)


class Attribution(Middleware):
    """Who is calling, for every call, in one place, so no tool has to
    know it was reached over MCP: the call acts for its owner (``_reach``)
    as the agent ``mcp:<client>`` (``acting_as``), a token sees and calls
    only what its scope reaches, and each call is recorded - tool, client,
    duration, size, outcome."""

    def __init__(self, record: Recorder) -> None:
        self._record = record

    async def on_list_tools(
        self,
        context: MiddlewareContext[types.ListToolsRequest],
        call_next: CallNext[types.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        _, effects = _reach()
        return [tool for tool in await call_next(context) if _within(tool.name, effects)]

    async def on_call_tool(
        self,
        context: MiddlewareContext[types.CallToolRequestParams],
        call_next: CallNext[types.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        started = time.perf_counter()
        result: ToolResult | None = None
        client = _client_name(context)
        owner, effects = _reach()
        try:
            if not _within(context.message.name, effects):
                raise ToolError(f"{context.message.name} is outside this token's scope")
            with acting_as(owner, f"mcp:{client}"):
                result = await call_next(context)
            return result
        finally:
            tool = get_tool(context.message.name)
            await self._record(
                McpCall(
                    tool=context.message.name,
                    client=client,
                    effect=tool.effect if tool is not None else "unknown",
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    result_bytes=_result_bytes(result) if result else 0,
                    ok=result is not None,
                )
            )


def build_server(
    grant: Iterable[str],
    *,
    record: Recorder = log_call,
    auth: AuthProvider | None = None,
) -> FastMCP:
    """A server offering exactly the granted tools that MCP may serve:
    reads and proposals, never a write (``mcp_servable``). ``auth`` checks
    each HTTP request's token (``http``); stdio has none."""
    server = FastMCP(settings.PROJECT_NAME, middleware=[Attribution(record)], auth=auth)
    for name in mcp_servable(grant):
        tool = get_tool(name)
        if tool is not None:
            server.add_tool(Tool.from_function(tool.func, name=name))
    return server
