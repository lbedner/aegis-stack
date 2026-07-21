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

Because the seeded `assistant` row is built from the same in-code default, the two sources cannot drift: a database-backed project and a memory-backed project produce identical default chat.

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
| `system_prompt` | The agent's persona. The seeded default is a marker meaning "use the service's built-in dynamic persona"; any edited text is used verbatim |
| `model_id` | Optional model pin. `NULL` means "use the service's active model", so the default agent tracks your configured provider |
| `temperature`, `max_tokens` | Sampling parameters applied to every request |
| `memory_modules` | Slugs of [memory modules](memory-modules.md) rendered into this agent's context |
| `knowledge_base_ids` | RAG collections this agent may search; empty means unrestricted |
| `is_active` | Inactive agents fall back to the code default |

Tools attach separately through the `tool` and `agent_tool` tables, and resolve at request time through the Python tool registry.

## Tools

The database decides WHICH tools an agent may call; Python decides WHAT each name executes. Register a tool once:

```python
from app.services.ai.tools import register_tool

async def lookup_order(order_id: str) -> str:
    """Fetch an order summary for the given order id."""
    ...

register_tool("lookup_order", lookup_order)
```

Then grant it to an agent by inserting a `tool` row named `lookup_order` and linking it via `agent_tool`. A row naming a tool with no registered callable is skipped with a warning, never an error: a stale grant degrades that one tool, not the agent.

## Per-User Memory

Agents can remember durable facts about a user across conversations. Two built-in tools are registered on every persistence-backed project:

- `save_memory(new_fact, category)`: remember one fact (categories: family, food, lifestyle, health, personal, program, general). Duplicate facts within a category are deduplicated by substring match.
- `replace_memory(memory_text)`: replace everything known about the user, one fact per line.

Saved facts are injected into later chats inside a `<user_memory>` guard block that explicitly frames them as data, not instructions. Facts are stored one JSON document per user in the `agent_user_memory` table.

## Knowledge Base Scoping

When RAG is enabled (`ai[...,rag]`), an agent's `knowledge_base_ids` lists the collections it may search. Retrieval merges results across the scope and ranks by similarity; an explicitly requested collection inside the scope narrows the search to just it, and a request outside the scope is refused with a log line. An empty scope keeps the unrestricted single-collection behavior. The `knowledge_base` and `knowledge_base_source` tables track collection metadata and per-source ingestion state, including the chunking preset (`paragraph`, `sentence`, `fixed`, `code`).

## Sentiment Analysis

Persistence-backed projects ship a batch job that scores each conversation with the configured model: user sentiment (positive, neutral, negative, frustrated), a score from -1.0 to 1.0, assistant performance, and detected issues. The job is registered on the scheduler but **off by default**, because every scored conversation costs model tokens:

```bash
AI_SENTIMENT_ENABLED=true    # enable scoring
AI_SENTIMENT_BATCH_LIMIT=20  # conversations per run
```

Results land in the `sentiment_analysis` table (one verdict per conversation) and surface in the CLI and the dashboard analytics tab:

```bash
my-app ai sentiment
```

## Managing Agents

**CLI**:

```bash
my-app agents list              # every agent with grants at a glance
my-app agents show assistant    # full definition including the prompt
my-app agents test assistant    # one live turn through the resolved config
my-app memory-modules list      # the module catalog
```

**Dashboard**: the AI service modal has an Agents tab listing every agent with an active toggle and a detail view.

**API**:

```bash
GET   /ai/agents          # list definitions with tool/module grants
PATCH /ai/agents/{slug}   # {"is_active": bool}
```

Edits through the API invalidate the loader's warm cache, so the next chat request sees the change immediately.

## Related Pages

- [Memory Modules](memory-modules.md): reusable context blocks agents opt into
- [RAG](rag.md): the retrieval pipeline agents scope over
- [Cost Tracking](cost-tracking.md): usage rows carry per-agent attribution (`chat:<slug>`)
