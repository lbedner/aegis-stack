# MCP

An outside assistant (Claude Desktop, Claude Code, a local model) reads your app through the [Model Context Protocol](https://modelcontextprotocol.io), using the same tools the app's own agents use.

```bash
aegis add mcp
aegis init my-app --components mcp --services finance
```

The server is [FastMCP](https://gofastmcp.com). It runs over stdio as a CLI command, so it adds no container and needs no token: whoever can run the CLI already owns the database. With the auth service it is also served over HTTP at `/mcp`, for a client elsewhere, signed in with a [token](#tokens).

## What a client sees

A client sees the tools listed in `MCP_TOOLS`, by registered name, and nothing else. A tool that writes is never served, whatever the list says (see [tool effects](../services/ai/agents.md#proposals-writes-the-user-approves)), and a name with no registered tool is dropped.

Every stack's default grant is Overseer's reads, the same ones its pages make:

| Tool | Answers |
|---|---|
| `health` | What is wrong now: every component's status and message, each check counted once and every one not healthy named with its message; name one for the details it reports that fit (a worker's queues, the scheduler's jobs), with `omitted` naming the rest |
| `errors` | What broke: retained errors grouped into issues; name one for its traceback |
| `logs` | What led up to it: container logs by service, level, text and window |
| `requests` | What a request did: the last ones the server answered (route, status, time, hop count), or one hop by hop: what each hop went through, named as the dry path names it, its real start and length, the tables a query touched and each line of code it was made through with the service piece it is in. The server's last 200, kept a day in the shared cache, so with Redis they outlive a restart and stdio reads them too |
| `ontology` | What the app is: its tables (fields, allowed values, links) and the changes an agent may propose to them; for an admin also its parts, routes, jobs, tools and Redis key families. A summary (the app, counts by kind, the tables by owner with their links, the changes to them, and an admin's parts and scheduled jobs); nodes by kind, category or text; one node with its edges and neighbours, and for an admin's part its live state (`now`: its health check, the errors it owns, the AI service's spend by window, when read) and what its code breaks of the service standard (`findings`: each rule, its severity, the file and line, what to do), and on the part what else it could be (`options`: each one's choices, the default, this stack's choice, what each means); the shortest paths between two (how a route reaches the database); and, for an admin, a route's dry path (`route="GET /api/v1/..."`): every hop it can take, read from the code, each at its file and line |

Health checks register when the webserver starts, so over stdio `health` asks the running webserver for its full walk, and says so when it can only see the CLI's own process. Over stdio `ontology` is built from what is on disk, without the routes, and says it is partial. The whole model (the ontology layer of the [Twin](../overseer/twin.md), the app's model of itself) is also `GET /api/v1/ontology` (admins only), as JSON. Every edge there, and in `ontology`'s answers, carries what the running app did along it this build (`observed`: count, errors, mean and max time) and a `state`: `both` (declared and seen), `observed_only` (seen but never declared: one service reaching another's table, say), `bypass` (a model provider reached around the AI service) or, after a day of traffic, `declared_only` (declared and never used). With the finance service, finance's read tools join the grant. Set it in `.env` as a JSON list to narrow it, for example `MCP_TOOLS=["ledger","accounts"]`; `MCP_TOOLS=[]` serves nothing.

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

## Running a script: run_code

With the AI service (pydantic-ai, with a database for its agents), a client also gets `run_code`: it writes a short Python script that calls the read tools as functions, and the app runs it next to the data, in the sandbox its own agents use in code mode. Only what the script returns crosses back, so a question that needs a dozen reads is one call, and the arithmetic happens in the script, not in the client's head.

```python
months = await ledger(months=12)
grew = sorted(months["months"], key=lambda m: m["spend_cents"])[-3:]
[m["month"] for m in grew]
```

The client's own model writes the script; it sees `run_code` like any tool, and its description lists the signature and docstring of every function inside. Only read tools are inside: proposals stay their own tools, and nothing that writes is ever reachable. The limits are the agents' (tool calls, time, memory, the size of what comes back), and each call starts fresh. It is granted by default where it can run, and counts as a read, so a read token reaches it.

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

For debugging a client, each call also keeps how it arrived (stdio or HTTP), the client's version and session, who it acted for and with which token, the arguments it sent, the response it got and the error when it failed. Arguments and responses are kept up to 8,000 characters each; the size column is always the whole answer's. A `run_code` call keeps each read its script made, with its arguments and response.

With the database component the record is kept, in the component's own `mcp_tool_call` table, apart from the chat agents' tool calls, for 30 days: older calls are deleted as new ones are written. Without one it is a log line (`mcp.call` on stderr).

Overseer shows it on its MCP page (htmx) and MCP card (Flet): the tools a client is served, each granted name it is not (and why), the commands that start the server, then each client's reads and proposals and the newest calls, each opening to its arguments, response, error and who made it how. Adding the database to a project later brings the record; removing it takes the record away.

A client's proposals are approved where every card is, and each one names the client that proposed it.

## Tokens

A client over HTTP needs a credential a person makes and can revoke. With the auth service, each person makes their own MCP tokens: on Overseer's MCP page (Tokens), from the CLI, or through the API.

```bash
my-app mcp-tokens create --email you@example.com --name laptop --scope read
my-app mcp-tokens list --email you@example.com
my-app mcp-tokens revoke --email you@example.com 3
```

A token's scope is its grant: `read` reaches the read tools in `MCP_TOOLS`, `propose` the proposals too. A client sees only the tools its scope reaches, and a call outside it is refused. There is no second permission system, and a token never reaches a write. People start read-only and grant proposals later.

`health`, `errors`, `logs` and `requests` are Overseer's reads, and Overseer shows them to admins only, so a token reaches them only when its owner is an admin (`ADMIN_USER_EMAILS`, or the admin role). Anyone else's token, and a script it runs with `run_code`, sees the other tools in its scope. `ontology` answers anyone with the app's tables and the changes to them, and only an admin with the rest. Chat holds an agent's admin tools to the same rule: granted to an agent everyone chats with, they answer only the admins.

Only a hash of the token is kept, so its value is shown once, when it is made. It works until it is revoked: each request checks it, so a revoked token fails on its next request, and each use is noted as its last use. Sessions in the browser are unaffected.

The API is the signed-in person's own: `GET /api/v1/mcp/tokens` lists them (never their values), `POST` makes one (its value in that answer only), and `DELETE /api/v1/mcp/tokens/{id}` revokes one.

## Tools without the AI service

MCP does not need the AI service: the [tool registry](../services/ai/agents.md#tools) is core, and `load_tools()` imports every service's `tools.py`, found on disk, in any process.
