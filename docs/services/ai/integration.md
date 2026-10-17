# AI Service Layer

How the AI service works internally and how to use it in your code.

!!! info "Engine-Agnostic API"
    All code examples on this page work identically whether you chose Pydantic AI or LangChain as your engine. The `AIService` class provides a unified interface. See [Engines](engines.md) for implementation details.

## AIService Class

**Location:** `app/services/ai/service.py`

The central class that orchestrates chat, voice, RAG, conversation management, and usage tracking.

```python
import asyncio
from app.core.config import settings
from app.services.ai.service import AIService

async def main():
    ai_service = AIService(settings)

    # Send message (creates new conversation)
    response = await ai_service.chat(
        message="Explain FastAPI",
        user_id="my-user"
    )
    print(response.content)

    # Continue conversation
    conversation_id = response.metadata["conversation_id"]
    response2 = await ai_service.chat(
        message="Show me an example",
        conversation_id=conversation_id,
        user_id="my-user"
    )

    # Stream response
    async for chunk in ai_service.stream_chat(message="Hello", user_id="my-user"):
        print(chunk.content, end='', flush=True)

    # List conversations
    conversations = ai_service.list_conversations(user_id="my-user")

asyncio.run(main())
```

### Key Methods

| Method | Description |
|--------|-------------|
| `chat(message, user_id, conversation_id)` | Send message, get response: `stream_chat` run to its end, so the reply keeps its steps, model and cost |
| `stream_chat(message, user_id, conversation_id)` | Stream response chunks |
| `get_conversation(conversation_id)` | Retrieve conversation with history |
| `list_conversations(user_id)` | List user's conversations |
| `get_usage_stats(user_id, start_time, end_time)` | Get usage analytics |
| `refresh_config()` | Reload configuration from .env |

## Configuration

**Location:** `app/services/ai/domains/llm/config.py`

```python
from app.services.ai.domains.llm.config import get_ai_config

config = get_ai_config(settings)

# Check configuration
errors = config.validate_configuration(settings)
if errors:
    print(f"Config issues: {errors}")

# Get available providers
available = config.get_available_providers(settings)
```

## Conversation Management

**Location:** `app/services/ai/conversation.py`

Conversations are stored based on your backend choice:

| Backend | Storage | Persistence | Use Case |
|---------|---------|-------------|----------|
| `memory` | In-memory dict | Lost on restart | Development, testing |
| `sqlite` | SQLite database | Persistent | Single-server production |
| `postgres` | PostgreSQL | Persistent | Multi-server production |

Select your backend at project generation:

```bash
# In-memory (default)
aegis init my-app --services ai

# SQLite persistence
aegis init my-app --services "ai[sqlite]"

# PostgreSQL persistence
aegis init my-app --services "ai[postgres]"
```

```python
# Conversations are created automatically by AIService
conversation = ai_service.get_conversation(conv_id)
conversations = ai_service.list_conversations(user_id="user-123")
```

### Database Models

When using `sqlite` or `postgres` backend, conversations are stored in two tables:

```
Conversation
├── id: UUID
├── user_id: str (indexed)
├── title: str | None
├── created_at, updated_at: datetime
├── meta_data: dict (flexible JSON)
└── messages: list[ConversationMessage]

ConversationMessage
├── id: UUID
├── conversation_id: UUID (FK)
├── role: "user" | "assistant" | "system"
├── content: str
├── timestamp: datetime (indexed)
└── meta_data: dict
```

## Context and Live Data

Illiana's system prompt holds nothing live, so a provider's prompt cache serves it turn to turn. Live data reaches her two ways: tools she calls when asked, and one line on her current message while something is wrong.

### A part's live state

**Location:** `app/services/system/node_now.py`

The `ontology` tool's answer for one part carries `now`, a frozen Pydantic model:

```python
from app.services.system.node_now import NodeNow, now_of

now: NodeNow | None = await now_of(node)  # None for a table, route or sub-part
now.health        # the part's ComponentStatus, or None where it has no check
now.errors        # the ErrorIssues it owns, latest first (up to 5)
now.errors_total  # how many it owns
now.spend         # the AI service's UsageWindows: today, last 7 days, all time
now.read_at       # when all of it was read
```

### What is wrong right now

```python
from app.services.system.node_now import right_now

line = (await right_now()).line()  # None while every check is healthy
```

The default assistant's turn puts the line ahead of the current message, for typed turns and calls alike; a custom agent never gets it.

### The model catalog

**Location:** `app/services/ai/domains/llm/catalog.py`

The `catalog` tool lists the models this install could use, filtered by text, vendor or modality, each a `CatalogModel` (id, title, vendor, lab, context window, prices per million tokens, release date). The default agent is granted it with `ontology` and, for admins, `health`.

### RAG Context

**Location:** `app/services/ai/rag_context.py`

When RAG is enabled, search results are formatted for prompt injection with file references:

```python
from app.services.ai.rag_context import RAGContext

ctx = RAGContext(results=search_results)
prompt_text = ctx.format_for_prompt()     # Markdown with file names, line numbers, syntax highlighting
sources = ctx.format_sources_footer()      # Citation-style source references
metadata = ctx.to_metadata()               # Storage-friendly format
```

### System Prompt Assembly

**Location:** `app/services/ai/domains/chat/prompts.py`

```python
from app.services.ai.domains.chat.prompts import build_system_prompt

prompt = build_system_prompt(
    rag_context=rag_formatted,  # Code search results
    current_model="gpt-4o",
    current_provider="openai",
    persona=agent_row_prompt,   # None: the seeded default
    memory_context=memory,      # Saved user memory
)
```

## Cost Calculation

**Location:** `app/services/ai/service.py`

Every AI request automatically:

1. Extracts token counts from the provider response
2. Looks up the model in the LLM Catalog
3. Fetches the latest price (by `effective_date`)
4. Calculates: `(input_tokens * input_cost) + (output_tokens * output_cost)`
5. Records to `LLMUsage` table (non-blocking - won't crash the request on failure)

```python
# Manual cost calculation
from app.services.ai.domains.spend import recording

cost = await recording.calculate_cost("gpt-4o", 1500, 800)
```

See [Cost Tracking](cost-tracking.md) for the full analytics system.

## Provider Capabilities

**Location:** `app/services/ai/models.py`

```python
from app.services.ai.models import (
    AIProvider,
    get_provider_capabilities,
    get_free_providers
)

# Check what a provider supports
caps = get_provider_capabilities(AIProvider.GROQ)
print(f"Streaming: {caps.supports_streaming}")
print(f"Free tier: {caps.free_tier_available}")

# Get free providers
free = get_free_providers()
# [AIProvider.PUBLIC, AIProvider.GROQ, AIProvider.GOOGLE, AIProvider.COHERE]
```

## Provider Management

**Location:** `app/services/ai/provider_management.py`

Runtime provider detection, dependency checking, and API key management:

```python
from app.services.ai.provider_management import (
    check_provider_dependency_installed,
    install_provider_dependency,
    get_existing_api_key,
    validate_provider_name,
    mask_api_key,
)

# Check if provider SDK is installed
if not check_provider_dependency_installed("anthropic"):
    install_provider_dependency("anthropic")  # Auto-installs via uv/pip

# Check for API key
key = get_existing_api_key("openai")  # Checks env vars and .env
masked = mask_api_key(key)  # "sk-a...xyz"
```

## Health Monitoring

**Location:** `app/services/ai/health.py`

```python
from app.services.ai.health import check_ai_service_health

status = await check_ai_service_health()
print(f"Status: {status.status}")  # HEALTHY, DEGRADED, or UNHEALTHY
```

---

**Next Steps:**

- **[LLM Catalog](llm-catalog.md)** - Model registry and management
- **[RAG](rag.md)** - Codebase indexing and search
- **[Cost Tracking](cost-tracking.md)** - Usage analytics
- **[Engines](engines.md)** - Pydantic AI vs LangChain internals
- **[API Reference](api.md)** - REST API endpoints
- **[CLI Commands](cli.md)** - Command-line interface
- **[Examples](examples.md)** - Usage examples
