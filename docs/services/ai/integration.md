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
| `chat(message, user_id, conversation_id)` | Send message, get response |
| `stream_chat(message, user_id, conversation_id)` | Stream response chunks |
| `get_conversation(conversation_id)` | Retrieve conversation with history |
| `list_conversations(user_id)` | List user's conversations |
| `calculate_cost(input_tokens, output_tokens)` | Calculate cost from catalog prices |
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

## Context Injection

Illiana receives live system data through context formatters that enrich her system prompt. This is what makes her system-aware rather than a generic chatbot.

### Health Context

**Location:** `app/services/ai/health_context.py`

Injects component health status so Illiana can answer "Is my database healthy?" or "What's the scheduler doing?"

```python
from app.services.ai.health_context import get_health_context

context = await get_health_context()
# Returns formatted markdown with component status, uptime, resource usage
```

### Usage Context

**Location:** `app/services/ai/usage_context.py`

Gives Illiana awareness of her own activity - token consumption, costs, success rates.

```python
from app.services.ai.usage_context import UsageContext

ctx = UsageContext(
    total_tokens=45230,
    total_requests=23,
    total_cost=0.47,
    success_rate=95.6,
    top_model="gpt-4o",
    top_model_percentage=65.2,
    recent_requests=10,
)
prompt_text = ctx.format_for_prompt()  # Compact markdown for injection
```

Supports `compact=True` for small models (Ollama) where context window is limited.

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

### RAG Stats Context

**Location:** `app/services/ai/rag_stats_context.py`

Provides collection-level awareness (how many collections, document counts, configuration):

```python
from app.services.ai.rag_stats_context import RAGStatsContext

ctx = RAGStatsContext(
    enabled=True,
    collection_count=2,
    collections=[("code", 1500), ("docs", 300)],
    embedding_model="all-MiniLM-L6-v2",
    chunk_size=1000,
    chunk_overlap=200,
    default_top_k=5,
)
```

### LLM Catalog Context

**Location:** `app/services/ai/llm_catalog_context.py`

Injects top models per vendor so Illiana can recommend alternatives:

- Featured vendors: OpenAI, Anthropic, Google, xAI, Mistral, Groq, DeepSeek
- Top 3 newest models per vendor (by release date)
- Includes pricing, context window, capabilities
- Filters out alias models (`-latest`, `:latest` suffixes)
- Optimized: ~3 SQL queries total with eager loading

### System Prompt Assembly

**Location:** `app/services/ai/prompts.py`

All contexts are assembled into Illiana's system prompt via `build_system_prompt()`:

```python
from app.services.ai.prompts import build_system_prompt

prompt = build_system_prompt(
    settings=settings,
    rag_context=rag_formatted,        # Code search results
    rag_stats_context=rag_stats,      # Collection info
    health_context=health_formatted,  # Component status (injected LAST for emphasis)
    usage_context=usage_formatted,    # Activity stats
    catalog_context=catalog_formatted, # Available models
    use_rag=True,
    current_model="gpt-4o",
    current_provider="openai",
)
```

!!! tip "Health Context Priority"
    Health context is injected **last** in the prompt so the LLM weights it more heavily when answering status questions. This ensures Illiana reports what **is** running, not what **could** run.

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
cost = await ai_service.calculate_cost(
    input_tokens=1500,
    output_tokens=800
)
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
