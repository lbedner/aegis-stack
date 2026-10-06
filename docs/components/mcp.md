# MCP

An outside assistant (Claude Desktop, Claude Code, a local model) reads your app through the [Model Context Protocol](https://modelcontextprotocol.io), using the same tools the app's own agents use.

```bash
aegis add mcp
aegis init my-app --components mcp --services finance
```

The server is [FastMCP](https://gofastmcp.com). It runs over stdio as a CLI command, so it adds no container and needs no token: whoever can run the CLI already owns the database. With the auth service it is also served over HTTP at `/mcp`, for a client elsewhere, signed in with a [token](#tokens).

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

### Over HTTP

With the auth service, the webserver serves the same tools at `/mcp`. Every request carries an [MCP token](#tokens); without one the answer is 401 and no tools. The token's owner is who the calls act for (in place of `MCP_OWNER_USER_ID`), and its scope is what they reach.

```bash
claude mcp add --transport http my-app http://localhost:8000/mcp/ \
  --header "Authorization: Bearer mcp_..."
```

There is no CORS on it (desktop and coding clients are not browsers), and it is not reachable through the dev tunnel, whose guard admits only the Plaid webhook.

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

## Every call is on the record

One middleware records each call: the tool, the client that made it, its effect (a read or a proposal), the duration, the size of the result in bytes, and whether it succeeded. No tool has to know it was reached over MCP.

With the database component the record is kept, in the component's own `mcp_tool_call` table, apart from the chat agents' tool calls. Without one it is a log line (`mcp.call` on stderr).

Overseer shows it on its MCP page (htmx) and MCP card (Flet): the tools a client is served, each granted name it is not (and why), the commands that start the server, then each client's reads and proposals and the newest calls. Adding the database to a project later brings the record; removing it takes the record away.

A client's proposals are approved where every card is, and each one names the client that proposed it.

## Tokens

A client over HTTP needs a credential a person makes and can revoke. With the auth service, each person makes their own MCP tokens: on Overseer's MCP page (Tokens), from the CLI, or through the API.

```bash
my-app mcp-tokens create --email you@example.com --name laptop --scope read
my-app mcp-tokens list --email you@example.com
my-app mcp-tokens revoke --email you@example.com 3
```

A token's scope is its grant: `read` reaches the read tools in `MCP_TOOLS`, `propose` the proposals too. A client sees only the tools its scope reaches, and a call outside it is refused. There is no second permission system, and a token never reaches a write. People start read-only and grant proposals later.

Only a hash of the token is kept, so its value is shown once, when it is made. It works until it is revoked: each request checks it, so a revoked token fails on its next request, and each use is noted as its last use. Sessions in the browser are unaffected.

The API is the signed-in person's own: `GET /api/v1/mcp/tokens` lists them (never their values), `POST` makes one (its value in that answer only), and `DELETE /api/v1/mcp/tokens/{id}` revokes one.

## Tools without the AI service

MCP does not need the AI service: the [tool registry](../services/ai/agents.md#tools) is core, and `load_tools()` imports every service's `tools.py`, found on disk, in any process.
