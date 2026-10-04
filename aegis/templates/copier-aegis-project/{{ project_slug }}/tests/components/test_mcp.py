"""An outside assistant (Claude Desktop, Claude Code, a local model) reads
the app through the same registered tools its own agents use."""

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from typing import Any

from fastmcp import Client
from mcp.types import Implementation
import pytest

from app.components.mcp.server import McpCall, build_server
from app.core.config import settings
from app.core.tools import load_tools, mcp_servable, register_tool

PROJECT = Path(__file__).resolve().parents[2]


async def lookup(order_id: str) -> dict[str, Any]:
    """Look up an order by id."""
    return {"order_id": order_id, "total_cents": 1250}


async def broken() -> str:
    """Always refuses."""
    raise ValueError("no such order")


async def save(note: str) -> str:
    """Save a note."""
    return note


@pytest.fixture
def tools(clean_registry: None) -> None:
    register_tool("lookup", lookup, effect="read")
    register_tool("broken", broken, effect="read")
    register_tool("save", save, effect="writes")


@pytest.mark.usefixtures("tools")
async def test_a_client_sees_exactly_the_granted_servable_tools() -> None:
    """A write never reaches an outside assistant, whatever the grant says,
    and an ungranted read does not exist to it."""
    server = build_server(["save", "lookup", "never-registered"])

    async with Client(server) as client:
        names = [tool.name for tool in await client.list_tools()]

    assert names == ["lookup"]


@pytest.mark.usefixtures("tools")
async def test_a_call_returns_what_the_tool_returns() -> None:
    """Same computation as a chat agent's call: the registered callable."""
    server = build_server(["lookup"])

    async with Client(server) as client:
        result = await client.call_tool("lookup", {"order_id": "A1"})

    assert result.data == await lookup("A1")


@pytest.mark.usefixtures("tools")
async def test_every_call_is_recorded_with_its_client() -> None:
    calls: list[McpCall] = []
    server = build_server(["lookup", "broken"], record=calls.append)
    claude = Implementation(name="claude-code", version="1.0")

    async with Client(server, client_info=claude) as client:
        await client.call_tool("lookup", {"order_id": "A1"})
        await client.call_tool("broken", {}, raise_on_error=False)

    assert [(c.tool, c.client, c.ok) for c in calls] == [
        ("lookup", "claude-code", True),
        ("broken", "claude-code", False),
    ]
    assert calls[0].result_bytes > 0


def test_the_default_grant_names_only_servable_tools() -> None:
    """``mcp_servable`` drops an unknown name without a word, so a renamed
    or removed tool must fail here instead of vanishing from every client."""
    load_tools()

    assert mcp_servable(settings.MCP_TOOLS) == settings.MCP_TOOLS


def test_stdout_carries_only_the_protocol() -> None:
    """The CLI speaks MCP over stdio: one stray log line on stdout and a
    client reads garbage, so every line it writes must be JSON-RPC."""
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    server = subprocess.Popen(
        [sys.executable, "-m", "app.cli.main", "mcp"],
        cwd=PROJECT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env={**os.environ, "MCP_TOOLS": "[]"},
    )
    assert server.stdin is not None and server.stdout is not None
    watchdog = threading.Timer(60, server.kill)
    watchdog.start()
    messages: list[dict[str, Any]] = []
    try:
        for request in requests:
            server.stdin.write(json.dumps(request) + "\n")
            server.stdin.flush()
        # Read until the listing answers; a log line here fails to parse.
        while not any(m.get("id") == 2 for m in messages):
            line = server.stdout.readline()
            if not line:
                break
            if line.strip():
                messages.append(json.loads(line))
    finally:
        watchdog.cancel()
        server.kill()
        server.wait()

    listed = next(m for m in messages if m.get("id") == 2)
    assert listed["result"]["tools"] == []
