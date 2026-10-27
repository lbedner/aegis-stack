"""The MCP server: the app's granted tools, for an outside assistant.

Tools are the registry's own callables (``app.core.tools``), registered by
name: FastMCP builds each schema from the type hints and docstring the
chat agents already read, so a read over MCP and the same read by an agent
are one computation. Never ``FastMCP.from_fastapi``: that would turn every
API route into a tool, writes included, and give one question two answers.
"""

import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from contextvars import ContextVar
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AuthProvider
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import Tool
from fastmcp.tools.tool import ToolResult
from pydantic import BaseModel, ConfigDict

from app.core.config import settings
from app.core.log import logger
from app.core.tools import RUN_CODE, acting_as, get_tool, mcp_servable
from mcp import types


class McpStep(BaseModel):
    """A read ``run_code`` made inside its sandbox: the tool, its arguments
    (``trace.call_args_preview``), whether it returned, its size and what
    it returned (``TEXT_CAP``). The sandbox does not time them."""

    model_config = ConfigDict(frozen=True)

    tool: str
    args: str
    ok: bool
    result_bytes: int
    response: str | None = None


class McpCall(BaseModel):
    """One tool call, attributed to the client that made it. Measured the
    way the agents' tool-call ledger measures (``tool_telemetry``)."""

    model_config = ConfigDict(frozen=True)

    tool: str
    client: str
    effect: str
    duration_ms: int
    result_bytes: int
    ok: bool
    # The reads a run_code script made inside the sandbox, in order.
    steps: tuple[McpStep, ...] = ()
    # For debugging a client: how it reached the server ("stdio", "http"),
    # the version and session it gave, who the call acted for and with
    # which token (HTTP), what it sent and got back (``TEXT_CAP``) and the
    # error.
    transport: str | None = None
    client_version: str | None = None
    session: str | None = None
    user_id: int | None = None
    token: str | None = None
    args: str | None = None
    response: str | None = None
    error: str | None = None


# Where a running call gathers the reads its script makes inside the
# sandbox (``run_code``), for ``Attribution`` to record with it.
sandbox_steps: ContextVar[list[McpStep] | None] = ContextVar(
    "sandbox_steps", default=None
)


Recorder = Callable[[McpCall], Awaitable[None]]
# The most of a call's arguments or response kept: a run_code script
# whole, mostly, and the start of a long answer. ``result_bytes`` is
# always the whole answer's size, so a clipped one shows.
TEXT_CAP = 8_000


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
        transport=call.transport,
        error=call.error,
        steps=[f"{step.tool} {step.args}" for step in call.steps],
    )


def _client(context: MiddlewareContext[Any]) -> dict[str, Any]:
    """Who is calling, as it said at initialize (its name, ``unknown``
    without one, and version), and over what: the transport, any HTTP one
    as ``http``, and the session."""
    found = context.fastmcp_context
    if found is None:
        return {"client": "unknown"}
    params = found.session.client_params
    transport = found.transport
    return {
        "client": params.clientInfo.name if params is not None else "unknown",
        "client_version": params.clientInfo.version if params is not None else None,
        "transport": "stdio" if transport in (None, "stdio") else "http",
        "session": found.session_id,
    }


def _token_name() -> str | None:
    token = get_access_token()
    return token.claims.get("token") if token is not None else None


def _text(result: ToolResult) -> str:
    return "".join(
        block.text for block in result.content if isinstance(block, types.TextContent)
    )


def _reach() -> tuple[int | None, frozenset[str] | None, bool]:
    """Who a call acts for, the effects it may reach, and whether it may
    reach the admin tools: over HTTP, the token's owner, scope (its scopes
    are effects, ``tokens.SCOPES``) and admin claim; over stdio there is no
    token, so MCP_OWNER_USER_ID, the grant, and the operator's shell."""
    token = get_access_token()
    if token is None:
        return settings.MCP_OWNER_USER_ID, None, True
    return (
        token.claims["user_id"],
        frozenset(token.scopes),
        bool(token.claims.get("admin")),
    )


def _admin_only(name: str) -> bool:
    tool = get_tool(name)
    return tool is not None and tool.admin


def reachable(names: Iterable[str]) -> list[str]:
    """``names`` this call may reach: the admin tools only for an admin
    (``run_code`` runs its script against these)."""
    _, _, admin = _reach()
    return [name for name in names if admin or not _admin_only(name)]



def code_tool_builder() -> Callable[[Sequence[str]], Awaitable[Tool]] | None:
    """``run_code.code_tool`` where the AI service's code mode is there to
    run a script (pydantic-ai, a persistent backend); None elsewhere."""
    try:
        from .run_code import code_tool
    except ImportError:
        return None
    return code_tool


def served_effects(grant: Iterable[str]) -> dict[str, str]:
    """Each granted tool a client is served, by its effect: the registry's
    reads and proposals (``mcp_servable``), and ``run_code`` (a read: only
    reads run inside it) where it can run."""
    names = list(grant)
    effects = {
        name: tool.effect for name in mcp_servable(names) if (tool := get_tool(name))
    }
    if RUN_CODE in names and code_tool_builder() is not None:
        effects[RUN_CODE] = "read"
    return effects


class Attribution(Middleware):
    """Who is calling, for every call, in one place, so no tool has to
    know it was reached over MCP: the call acts for its owner (``_reach``)
    as the agent ``mcp:<client>`` (``acting_as``), a token sees and calls
    only what its scope reaches, and each call is recorded - tool, client,
    duration, size, outcome."""

    def __init__(self, record: Recorder, effects: dict[str, str]) -> None:
        self._record = record
        self._effects = effects

    def _within(self, name: str, reach: frozenset[str] | None, admin: bool) -> bool:
        if reach is None:
            return True
        return self._effects.get(name) in reach and (admin or not _admin_only(name))

    async def on_list_tools(
        self,
        context: MiddlewareContext[types.ListToolsRequest],
        call_next: CallNext[types.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        _, reach, admin = _reach()
        return [
            tool
            for tool in await call_next(context)
            if self._within(tool.name, reach, admin)
        ]

    async def on_call_tool(
        self,
        context: MiddlewareContext[types.CallToolRequestParams],
        call_next: CallNext[types.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        started = time.perf_counter()
        result: ToolResult | None = None
        error: str | None = None
        caller = _client(context)
        owner, reach, admin = _reach()
        steps: list[McpStep] = []
        gathering = sandbox_steps.set(steps)
        try:
            if not self._within(context.message.name, reach, admin):
                raise ToolError(f"{context.message.name} is outside this token's scope")
            with acting_as(owner, f"mcp:{caller['client']}", admin=admin):
                result = await call_next(context)
            return result
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            sandbox_steps.reset(gathering)
            text = _text(result) if result else None
            await self._record(
                McpCall(
                    **caller,
                    tool=context.message.name,
                    effect=self._effects.get(context.message.name, "unknown"),
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    result_bytes=len(text.encode()) if text else 0,
                    ok=result is not None,
                    steps=tuple(steps),
                    user_id=owner,
                    token=_token_name(),
                    args=json.dumps(context.message.arguments or {})[:TEXT_CAP],
                    response=text[:TEXT_CAP] if text is not None else None,
                    error=error,
                )
            )


def build_server(
    grant: Iterable[str],
    *,
    record: Recorder = log_call,
    auth: AuthProvider | None = None,
) -> FastMCP:
    """A server offering exactly the granted tools that MCP may serve:
    reads and proposals, never a write (``served_effects``), ``run_code``
    among them where granted and able to run. ``auth`` checks each HTTP
    request's token (``http``); stdio has none."""
    names = list(grant)
    effects = served_effects(names)
    builder = code_tool_builder() if RUN_CODE in effects else None
    server = FastMCP(
        settings.PROJECT_NAME,
        middleware=[Attribution(record, effects)],
        auth=auth,
        lifespan=_adding(builder, mcp_servable(names, {"read"})) if builder else None,
    )
    for name in effects:
        tool = get_tool(name)
        if tool is not None:
            server.add_tool(Tool.from_function(tool.func, name=name))
    return server


def _adding(
    builder: Callable[[Sequence[str]], Awaitable[Tool]], reads: Sequence[str]
) -> Callable[[FastMCP], AbstractAsyncContextManager[dict[str, Any]]]:
    """A lifespan that adds ``run_code`` over ``reads`` when the server
    starts: its description comes from an agent run, which is async."""

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        server.add_tool(await builder(reads))
        yield {}

    return lifespan
