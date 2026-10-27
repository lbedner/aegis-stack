# Agent Registry

Agents are how the AI service works: every chat request resolves an **agent definition** (persona, sampling parameters, model pin, tool grants, memory modules, knowledge base scope) and runs through it. A freshly generated project ships one seeded agent, `assistant`, that behaves exactly like plain chat, so you never have to think about the registry until you want more than one agent, or want to customize the one you have.

## One Runtime, Two Config Sources

There is a single chat runtime. What changes with your storage backend is where the agent definition comes from:

```
                 +--------------------------------------+
 request  ---->  |  agent loader                        |
                 |  resolve(slug) -> AgentConfig        |
                 |    backend=memory : code default     |
                 |    backend=db     : agent row (cache)|
                 +------------------+-------------------+
                                    |
                 +------------------v-------------------+
                 |  context assembly                    |
                 |  memory modules (static + fetchers)  |
                 |  per-user memory (guarded injection) |
                 |  KB retrieval (scoped to the agent)  |
                 +------------------+-------------------+
                                    |
                 +------------------v-------------------+
                 |  chat runtime                        |
                 |  tools resolved via the registry     |
                 +--------------------------------------+
```

- **Persistence backend** (`ai[sqlite]` or `ai[postgres]`): definitions live in the `agent` table, cached warm per process. A missing or inactive row falls back to the code default, so a half-seeded database never breaks chat.
- **Memory backend** (the default `ai`): the code default is the only config source. Same shape, same behavior, no tables involved.

Because the seeded `assistant` row is built from the same in-code default, the two sources cannot drift. The one difference is the app map: with a persistence backend the `assistant` always has the `app_map` memory module (see [Memory Modules](memory-modules.md)), which needs the module tables a memory-backed project does not have.

### What each backend provides

| Capability | `memory` | `sqlite` / `postgres` |
|---|---|---|
| Agent config | code default | `agent` rows (seeded default) |
| Tools | code-registered only | code registry + per-agent grants |
| Memory modules | not available | full CRUD, hybrid modules |
| Per-user memory | not available | `save_memory` tool + guarded injection |
| Sentiment analysis | not available | batch job (off by default) |
| KB scoping | all collections | per-agent `knowledge_base_ids` |

## The Agent Definition

An `agent` row holds:

| Field | Meaning |
|---|---|
| `slug` | Unique identifier; chat resolves the `assistant` slug by default |
| `system_prompt` | The agent's persona, used verbatim. The `assistant` row is seeded with Illiana's whole persona, so what the row shows is what she runs on; the model in force and the live context are appended after it |
| `model_id` | Optional model pin. `NULL` means "use the service's active model", so the default agent tracks your configured provider. In the Overseer's agent editor it is picked from the models this install can call, grouped by vendor |
| `temperature`, `max_tokens` | Sampling parameters applied to every request |
| `memory_modules` | Slugs of [memory modules](memory-modules.md) rendered into this agent's context |
| `knowledge_base_ids` | RAG collections this agent may search; empty means unrestricted |
| `is_active` | Inactive agents fall back to the code default |

Tools attach separately through the `tool` and `agent_tool` tables, and resolve at request time through the Python tool registry.

## Tools

The database decides WHICH tools an agent may call; Python decides WHAT each name executes. Register a tool once, from any service: the registry lives in core (`app.core.tools`), not in the AI service. A service keeps its tools in its own `app/services/<service>/tools.py`; `load_tools()` finds every such module on disk, so a new service or a plugin adds tools without editing anything else.

```python
# app/services/orders/tools.py
from pydantic import BaseModel

from app.core.figures import FIGURES
from app.core.tools import register_tool

class OrderSummary(BaseModel):
    model_config = FIGURES

    order_id: str
    status: str
    total_cents: int

async def lookup_order(order_id: str) -> OrderSummary:
    """Fetch an order summary for the given order id."""
    ...

register_tool(
    "lookup_order", lookup_order, effect="read", doing="Looking up the order"
)
```

A tool hands back a typed model, never a `dict`: what an agent reads is that model's JSON, its schema types code mode's script and an MCP client's structured answer, and a renamed field fails a test instead of a conversation. A refusal the model can correct from is `Refused(error=...)` (`app.core.tools`), returned rather than raised. The service pattern's `returns-model` rule gates it.

`doing` is what a call of it is, as a person watching reads it: a meeting bot's card shows it under the question Illiana is answering (`app.core.steps`). Each call is heard where it runs, so a read inside a code-mode script is a step too. A tool without one shows as its name made readable ("Lookup order"), and code mode's `run_code` as its script's first comment.

Then grant it to an agent by inserting a `tool` row named `lookup_order` and linking it via `agent_tool`. A row naming a tool with no registered callable is skipped with a warning, never an error: a stale grant degrades that one tool, not the agent.

### What each part holds: `aggregate`

An agent asks the app's data what it holds through one tool, not SQL. Each service declares its own aggregates beside its data, in `app/services/<service>/aggregates.py`, as `AGGREGATES`: each an `Aggregate` from `app.core.aggregates` with a name, what it counts, and a read returning a typed model of figures (counts and sums by label, never a row). `aggregate()` lists them and the windows they take (the app's range chips, in days); `aggregate("scheduler.runs", days=7)` reads one. The same window read again within a minute is served from the shared cache, so a burst of questions costs one query. The figures are app-wide (never one owner's) and an operator's: the tool is an admin's. Each read takes the session it is given and the window's days:

```python
# app/services/orders/aggregates.py
from app.core.aggregates import Aggregate

async def orders_by_status(session: AsyncSession, days: int | None) -> OrderCounts:
    ...  # one GROUP BY since ranges.start(days); an OrderCounts of FIGURES

AGGREGATES = (Aggregate("by_status", "Orders by status", orders_by_status),)
```

## Proposals: Writes the User Approves

A tool that changes something should not change it. It files a **pending change** instead: a card in the chat with **Approve** and **Reject**, and nothing runs until the user decides. The queue ships with every persistence-backed project (and with finance), and it knows nothing about any one service. A service makes a change proposable by registering a change type at import:

```python
from pydantic import BaseModel
from app.services.change_queue import ChangeDisplayRow, ChangeExecutor, register

class ReschedulePayload(BaseModel):
    post_id: int
    publish_at: str

class Rescheduled(BaseModel):
    model_config = FIGURES  # app.core.figures

    post_id: int

async def execute(db, payload, owner_user_id) -> Rescheduled:
    ...  # the real mutation; runs only on approval
    return Rescheduled(post_id=payload.post_id)

async def describe(db, payloads, owner_user_id) -> list[list[ChangeDisplayRow]]:
    return [[ChangeDisplayRow(label="Publish at", value=p.publish_at)] for p in payloads]

register(ChangeExecutor(
    change_type="post.reschedule",
    title="Reschedule a post",
    payload_model=ReschedulePayload,
    execute=execute,
    describe=describe,
))
```

The payload model validates when the change is proposed and again when it is approved; `describe` renders the card from the database, never from the model's own words. It takes a list of payloads and returns one card body per payload, in order, so a page of cards can load what they show in one query instead of one per card. Agents reach the queue through built-in tools: `propose` and `propose_many` (one card for a batch, with a per-row veto), and `pending`, `withdraw` and `withdraw_batch` for an agent's own open cards. The card's buttons call `/api/v1/changes` (`POST /changes/{id}/approve`, `/reject`, and the batch forms), and every resolution keeps its row as the audit trail.

A tool declares what a call does with `effect`: `read` changes nothing, `proposes` files a change the user approves before it lands, and `writes` changes state at once. A tool that declares nothing is treated as `writes`, with a warning in the log, and re-registering a tool cannot change its effect. Any tool that is not `read` stays a visible native call in code mode instead of running inside the sandbox, and only `read` and `proposes` tools can ever be served to an outside assistant:

```python
register_tool("save_note", save_note, effect="writes")
```

## Per-User Memory

Agents can remember durable facts about a user across conversations. Two built-in tools are registered on every persistence-backed project:

- `save_memory(new_fact, category)`: remember one fact (categories: family, food, lifestyle, health, personal, program, general). Duplicate facts within a category are deduplicated by substring match.
- `replace_memory(memory_text)`: replace everything known about the user, one fact per line.

Saved facts are injected into later chats inside a `<user_memory>` guard block that explicitly frames them as data, not instructions. Facts are stored one JSON document per user in the `agent_user_memory` table.

## Knowledge Base Scoping

When RAG is enabled (`ai[...,rag]`), an agent's `knowledge_base_ids` lists the collections it may search. Retrieval merges results across the scope and ranks by similarity; an explicitly requested collection inside the scope narrows the search to just it, and a request outside the scope is refused with a log line. An empty scope keeps the unrestricted single-collection behavior. The `knowledge_base` and `knowledge_base_source` tables track collection metadata and per-source ingestion state, including the chunking preset (`paragraph`, `sentence`, `fixed`, `code`).

## Sentiment Analysis

Persistence-backed projects ship a batch job that scores each conversation: user sentiment (positive, neutral, negative, frustrated), a score from -1.0 to 1.0, assistant performance, and detected issues. The job is registered on the scheduler but **off by default**, because every scored conversation costs model tokens:

```bash
AI_SENTIMENT_ENABLED=true    # enable scoring
AI_SENTIMENT_BATCH_LIMIT=20  # conversations per run
```

The job runs as the built-in `sentiment` agent, seeded beside the default one: its model, temperature, max tokens and prompt are edited like any agent's. It starts on the service's active model; scoring is a short, structured task, so a small fast model is usually the better pick, especially when the active model is a large local one whose cold start can outlast `AI_TIMEOUT_SECONDS`. With the agent removed or inactive, the job uses the built-in prompt on the active model. The job reads its batch, ends that database transaction, and only then calls the model, so a slow model never holds the database.

Results land in the `sentiment_analysis` table (one verdict per conversation) and surface in the CLI and the dashboard analytics tab:

```bash
my-app ai sentiment
```

## Managing Agents

**CLI**:

```bash
my-app agents list              # every agent with grants at a glance
my-app agents show assistant    # full definition including the prompt
my-app agents test assistant    # one chat turn as the agent
my-app memory-modules list      # the module catalog
```

**Dashboard**: the AI service modal has an Agents tab listing every agent with an active toggle and a detail view.

**API**:

```bash
GET   /api/v1/ai/agents          # list definitions with tool/module grants
PATCH /api/v1/ai/agents/{slug}   # {"is_active": bool}
```

Edits through the API invalidate the loader's warm cache, so the next chat request sees the change immediately.

## Related Pages

- [Memory Modules](memory-modules.md): reusable context blocks agents opt into
- [RAG](rag.md): the retrieval pipeline agents scope over
- [Cost Tracking](cost-tracking.md): usage rows carry per-agent attribution (`chat:<slug>`)
- [Finance Chat](../finance/chat.md): a service-owned agent whose tools read
  the ledger and whose only write files a proposal for the user to approve
