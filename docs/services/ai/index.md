# AI Service

The **AI Service** brings a complete AI platform to your Aegis Stack project: multi-provider chat with **Illiana** (your system-aware AI assistant), an **LLM Catalog** with ~2000 models, **RAG** for codebase-aware conversations, **cost tracking** with usage analytics, and optional **voice** (TTS/STT).

![AI Service Demo](../../images/aegis-ai-demo.gif)

!!! info "Start Chatting in 30 Seconds"
    Generate a project with AI service and start chatting with Illiana immediately:

    ```bash
    uvx aegis-stack init my-app --services ai
    cd my-app
    uv sync && source .venv/bin/activate
    my-app ai chat "Hello! What can you tell me about my system?"
    ```

    No API key required with the PUBLIC provider - perfect for testing!

    *Requires [uv](https://docs.astral.sh/uv/getting-started/installation/) installed. See [Installation](../../installation.md) for other options.*

## What You Get

<div class="grid cards" markdown>

-   :material-robot: **Illiana - System-Aware AI**

    ---

    Conversational assistant with live awareness of your system health, usage stats, and codebase context

    [:octicons-arrow-right-24: Illiana](illiana.md)

-   :material-account-group: **Agent Registry**

    ---

    Database-driven agents with tool grants, memory modules, per-user memory, and knowledge base scoping

    [:octicons-arrow-right-24: Agents](agents.md)

-   :material-database-search: **LLM Catalog**

    ---

    ~2000 models from OpenRouter, LiteLLM, and Ollama with pricing, capabilities, and one-command switching

    [:octicons-arrow-right-24: LLM Catalog](llm-catalog.md)

-   :material-file-search: **RAG**

    ---

    Index your codebase into ChromaDB and let Illiana answer questions with file-level precision

    [:octicons-arrow-right-24: RAG](rag.md)

-   :material-chart-line: **Cost Tracking**

    ---

    Automatic per-request usage recording with cost calculation, analytics dashboard, and usage API

    [:octicons-arrow-right-24: Cost Tracking](cost-tracking.md)

-   :material-microphone: **Voice (TTS/STT)**

    ---

    Text-to-speech and speech-to-text with OpenAI, Groq Whisper, and local providers

    [:octicons-arrow-right-24: Voice](voice.md)

-   :material-swap-horizontal: **Multi-Provider**

    ---

    OpenAI, Anthropic, Google, Groq, Mistral, Cohere, Ollama, and free public endpoints

    [:octicons-arrow-right-24: Provider Setup](providers.md)

</div>

**Also included:**

- **Streaming Responses** - Real-time SSE streaming for interactive UX
- **Conversation Management** - In-memory or database-backed (SQLite/PostgreSQL) persistence
- **Slash Commands** - In-chat commands (`/model`, `/rag`, `/status`, `/new`)
- **Health Monitoring** - Service health checks with validation
- **Context Injection** - Live system health, usage stats, RAG results, and catalog data injected into Illiana's prompts

## Quick Start

### 1. Generate Project with AI Service

```bash
# Basic AI (in-memory conversations)
aegis init my-app --services ai

# AI with database persistence + RAG
aegis init my-app --services "ai[sqlite,rag]"

# AI with everything
aegis init my-app --services "ai[sqlite,rag,voice]"
```

```bash
cd my-app
uv sync && source .venv/bin/activate
```

### 2. Chat with Illiana

```bash
# Interactive chat session
my-app ai chat

# Single message
my-app ai chat "Explain the architecture of this project"

# Chat with RAG (codebase-aware)
my-app rag index ./app --collection code
my-app ai chat --rag --collection code "How does authentication work?"
```

### 3. Explore the LLM Catalog

```bash
# Sync ~2000 models from cloud APIs
my-app llm sync

# Browse models
my-app llm list claude --vendor anthropic
my-app llm info gpt-4o

# Switch models
my-app llm use claude-sonnet-4-20250514
```

### 4. API Usage

```bash
# Start server
make serve

# Chat endpoint
curl -X POST http://localhost:8000/ai/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello from the API!"}'

# Browse LLM catalog
curl http://localhost:8000/llm/models?pattern=gpt-4

# Check usage stats
curl http://localhost:8000/ai/usage/stats
```

## Configuration

### Basic Configuration

```bash
# .env - Default configuration (PUBLIC provider)
AI_ENABLED=true
AI_PROVIDER=public
AI_MODEL=auto
```

### Service Options

Configure AI features at project generation:

```bash
aegis init my-app --services "ai[pydantic-ai,sqlite,openai,rag,voice]"
```

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| Framework | `pydantic-ai`, `langchain` | `pydantic-ai` | AI engine |
| Backend | `memory`, `sqlite`, `postgres` | `memory` | Conversation storage |
| Providers | `openai`, `anthropic`, `google`, `groq`, `mistral`, `cohere`, `ollama`, `public` | `public` | LLM providers |
| RAG | flag | disabled | Enable RAG support |
| Voice | flag | disabled | Enable TTS/STT |

### Switching Providers

```bash
# Via environment variables
AI_PROVIDER=groq
GROQ_API_KEY=your-key-here
AI_MODEL=llama-3.1-8b-instant
```

```bash
# Via CLI (with LLM catalog)
my-app llm use gpt-4o           # Auto-detects OpenAI
my-app llm use claude-sonnet-4-20250514  # Auto-detects Anthropic
```

**Available providers:** OpenAI, Anthropic, Google Gemini, Groq, Mistral, Cohere, Ollama, PUBLIC

**-> [Complete Provider Setup Guide](providers.md)**

---

**Next Steps:**

- **[Illiana](illiana.md)** - System-aware AI assistant with context injection
- **[LLM Catalog](llm-catalog.md)** - Browse and manage ~2000 AI models
- **[RAG](rag.md)** - Index your codebase for AI-powered search
- **[Cost Tracking](cost-tracking.md)** - Monitor usage and costs
- **[Voice](voice.md)** - Add speech capabilities
- **[Engines](engines.md)** - Choose between Pydantic AI and LangChain
- **[Provider Setup](providers.md)** - Configure your AI provider
- **[API Reference](api.md)** - Complete REST API documentation
- **[Service Layer](integration.md)** - Integration patterns and architecture
- **[CLI Commands](cli.md)** - Command-line interface reference
- **[Examples](examples.md)** - Real-world usage patterns
