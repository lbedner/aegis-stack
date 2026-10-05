# MCP

An outside assistant (Claude Desktop, Claude Code, a local model) reads your app through the [Model Context Protocol](https://modelcontextprotocol.io), using the same tools the app's own agents use.

```bash
aegis add mcp
aegis init my-app --components mcp --services finance
```

The server is [FastMCP](https://gofastmcp.com). It runs over stdio as a CLI command, so it adds no container and needs no token: whoever can run the CLI already owns the database.

## What a client sees

A client sees the tools listed in `MCP_TOOLS`, by registered name, and nothing else. A tool that writes is never served, whatever the list says (see [tool effects](../services/ai/agents.md#proposals-writes-the-user-approves)), and a name with no registered tool is dropped. With the finance service, the default grant is finance's read tools. Set it in `.env` as a JSON list to narrow it, for example `MCP_TOOLS=["ledger","accounts"]`; `MCP_TOOLS=[]` serves nothing.

The tools are the registry's own functions, registered by name. FastMCP builds each tool's schema from the type hints and docstring the app's agents already read, so a read over MCP and the same read by a chat agent are one computation. The server is never built with `FastMCP.from_fastapi`, which would turn every API route into a tool, writes included.

## Connecting a client

Run it from the project:

```bash
uv run my-app mcp
```

In Docker, through the running webserver container. `-T` matters: a TTY would corrupt the stream.

```bash
docker compose exec -T webserver my-app mcp
```

Claude Code:

```bash
claude mcp add my-app -- uv run --directory /path/to/my-app my-app mcp
```

Claude Desktop, in `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "my-app": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/my-app", "my-app", "mcp"]
    }
  }
}
```

stdout carries the protocol and nothing else; the command sends every log line to stderr before it starts.

## Proposing changes

Any assistant can suggest; only you can change. Grant the queue's tools and a client can file changes, never make them:

```bash
MCP_TOOLS=["ledger","accounts","categories","propose","propose_many","pending","withdraw","withdraw_batch","change_types"]
```

A proposal is a card in the app's own approval queue, filed under the client as `mcp:<client>` (`mcp:claude-code`). Nothing changes until a person approves it in Review, row by row. The client sees only its own cards with `pending` (pending, approved, rejected, withdrawn) and can withdraw only its own; another client's cards do not exist to it.

## Whose data

Over stdio there is no signed-in user. `MCP_OWNER_USER_ID` says who a client acts for: whose rows it reads and whose cards it files. Unset, it reads every row, the same as a single-tenant app; with the auth service, proposing needs it.

```bash
MCP_OWNER_USER_ID=1
```

## Every call is recorded

One middleware records each call: the tool, the client that made it, the duration, the size of the result in bytes, and whether it succeeded. Today the record is a log line (`mcp.call`) on stderr. No tool has to know it was reached over MCP.

## Tools without the AI service

MCP does not need the AI service: the [tool registry](../services/ai/agents.md#tools) is core, and `load_tools()` imports every module that registers tools, in any process.
