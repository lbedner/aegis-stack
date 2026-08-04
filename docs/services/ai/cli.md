# AI CLI Commands

**Part of the Generated Project CLI** - See [CLI Reference](../../cli-reference.md#service-clis) for complete overview.

The AI service provides three command groups: `ai` (chat and status), `llm` (model catalog), and `rag` (document indexing and search).

## Command Overview

```bash
# AI Chat & Status
my-app ai status          # Show configuration and validation
my-app ai providers       # List all providers
my-app ai chat "message"  # Send single message
my-app ai chat            # Interactive chat session (Illiana)
my-app ai conversations   # List conversations
my-app ai history <id>    # View conversation history
my-app ai usage           # Token usage and cost statistics
my-app ai sentiment       # Conversation sentiment statistics

# Agent Registry
my-app agents list             # All agents with their grants
my-app agents show <slug>      # One agent's full definition
my-app agents test <slug>      # One live turn through the agent
my-app memory-modules list     # Memory module catalog
my-app memory-modules show <slug>  # One module's definition

# LLM Catalog
my-app llm sync           # Sync ~2000 models from cloud/Ollama
my-app llm status         # Catalog statistics
my-app llm vendors        # List vendors
my-app llm modalities     # List modalities
my-app llm list <pattern> # Search models
my-app llm current        # Show current model config
my-app llm use <model>    # Switch active model
my-app llm info <model>   # Detailed model info

# RAG
my-app rag index <path>   # Index documents
my-app rag add <file>     # Add/update single file
my-app rag remove <path>  # Remove file from index
my-app rag files          # List indexed files
my-app rag search <query> # Semantic search
my-app rag list           # List collections
my-app rag delete <name>  # Delete collection
my-app rag status         # RAG configuration
my-app rag install-model  # Pre-download embedding model
```

---

## AI Commands

### ai status

Show AI service status, configuration, and validation:

```bash
my-app ai status
```

```
AI Service Status
========================================
Engine: pydantic-ai
Status: Enabled
Provider: groq
Model: llama-3.1-70b-versatile
Temperature: 0.7
Max Tokens: 1000
API Key: Set

✓ Configuration valid
  Free tier
  Streaming supported

Available providers: 3 (run 'ai providers' to list)
```

### ai providers

List all available AI providers and their status:

```bash
my-app ai providers
```

```
           AI Providers
┏━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ Provider ┃ Status                   ┃ Free ┃ Features         ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ public   │ Available (current)      │ Yes  │ Basic            │
│ groq     │ Need GROQ_API_KEY        │ Yes  │ Stream           │
│ openai   │ Need OPENAI_API_KEY      │ No   │ Stream, Functions│
│ anthropic│ Need ANTHROPIC_API_KEY   │ No   │ Stream, Vision   │
│ google   │ Need GOOGLE_API_KEY      │ Yes  │ Stream           │
│ mistral  │ Need MISTRAL_API_KEY     │ No   │ Stream           │
│ cohere   │ Need COHERE_API_KEY      │ No   │ Stream           │
└──────────┴──────────────────────────┴──────┴──────────────────┘
```

### ai chat

Send messages to Illiana or start interactive sessions.

**Single Message:**

```bash
my-app ai chat "Explain async/await in Python"
```

**Options:**

| Flag | Description |
|------|-------------|
| `--stream / --no-stream` | Enable/disable streaming (default: enabled) |
| `--conversation-id, -c` | Continue an existing conversation |
| `--user-id, -u` | User identifier (default: cli-user) |
| `--verbose, -v` | Show conversation metadata |
| `--rag` | Enable RAG context |
| `--collection` | RAG collection to search |
| `--top-k` | Number of RAG results (default: 5) |
| `--sources` | Show source file references |

**Examples:**

```bash
# Simple message
my-app ai chat "What is this project's architecture?"

# Continue a conversation
my-app ai chat -c abc123 "Tell me more about that"

# Chat with codebase context (RAG)
my-app ai chat --rag --collection code --top-k 20 --sources \
  "How does the auth service work?"
```

**Interactive Mode** (no message argument):

```bash
$ my-app ai chat
Illiana v0.6.3
Provider: groq | Model: llama-3.1-70b-versatile

You: What is FastAPI?
Illiana: FastAPI is a modern Python web framework...

You: /model gpt-4o
✓ Switched to OpenAI/gpt-4o

You: /rag code
✓ RAG enabled with collection: code

You: /status
Provider: openai
Model: gpt-4o
RAG: ON (code)

You: /exit
Goodbye!
```

### Slash Commands (Interactive Mode)

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/model [name]` | Show current model or switch |
| `/status` | Show current configuration |
| `/new` | Start a new conversation |
| `/rag [off\|collection]` | Toggle RAG or select collection |
| `/sources [enable\|disable]` | Toggle source references |
| `/clear` | Clear the screen |
| `/exit` | Exit the chat session |

### ai conversations

List conversations for a user:

```bash
my-app ai conversations
my-app ai conversations -u "user-456" -l 20
```

### ai history

View message history of a conversation:

```bash
my-app ai history <conversation-id>
```

---

### ai usage

Aggregated token usage and cost statistics, fetched from the running API server.

```bash
my-app ai usage             # Summary, token breakdown, model usage
my-app ai usage --json      # Raw JSON
my-app ai usage --recent 20 # More recent-activity rows
```

Requires a database backend (`ai[sqlite]` / `ai[postgres]`) and a running server.

### ai sentiment

Conversation sentiment statistics from the batch analysis job: distribution, average score, assistant performance, and recent negative conversations.

```bash
my-app ai sentiment         # Rendered distribution
my-app ai sentiment --json  # Raw JSON
```

Scoring is off by default; enable it with `AI_SENTIMENT_ENABLED=true`. See [Agents](agents.md) for details.

---

## Agent Registry Commands

Inspect and smoke-test the database-driven [agent registry](agents.md). Requires a database backend.

### agents list

```bash
my-app agents list
```

Every agent with its model, active state, and tool/module counts.

### agents show

```bash
my-app agents show assistant
```

One agent's full definition: sampling, tools, memory modules, knowledge base scope, and the system prompt.

### agents test

```bash
my-app agents test assistant
my-app agents test support -m "What are your hours?"
```

Runs one live turn through the agent's resolved configuration against the configured model and prints the reply.

### memory-modules list / show

```bash
my-app memory-modules list
my-app memory-modules show <slug>
```

The [memory module](memory-modules.md) catalog: kind (static, dynamic, hybrid), priority, active state, and per-module detail.

---

## LLM Catalog Commands

Manage the local model catalog. See [LLM Catalog](llm-catalog.md) for full documentation.

### llm sync

Sync model data from cloud APIs or local Ollama:

```bash
# Default: sync chat models from cloud (OpenRouter + LiteLLM)
my-app llm sync

# Sync only Ollama models
my-app llm sync --source ollama

# Sync everything (cloud + Ollama)
my-app llm sync --source all --mode all

# Preview without saving
my-app llm sync --dry-run

# Full refresh (truncate + re-sync)
my-app llm sync --refresh
```

**Options:**

| Flag | Values | Default | Description |
|------|--------|---------|-------------|
| `--mode, -m` | `chat`, `embedding`, `all` | `chat` | Model type filter |
| `--source, -s` | `cloud`, `ollama`, `all` | `cloud` | Data source |
| `--dry-run, -n` | flag | off | Preview without saving |
| `--refresh, -r` | flag | off | Truncate tables first |

```
Sync Results
┏━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┓
┃ Metric              ┃ Count ┃
┡━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━┩
│ Vendors Added       │ 32    │
│ Models Added        │ 1847  │
│ Deployments Synced  │ 2103  │
│ Prices Synced       │ 1952  │
│ Modalities Synced   │ 3891  │
│ Duration            │ 12.4s │
└─────────────────────┴───────┘
```

### llm status

Show catalog statistics:

```bash
my-app llm status
```

```
LLM Catalog Summary
┏━━━━━━━━━━━━━┳━━━━━━━┓
┃ Metric      ┃ Count ┃
┡━━━━━━━━━━━━━╇━━━━━━━┩
│ Vendors     │ 32    │
│ Models      │ 1847  │
│ Deployments │ 2103  │
│ Prices      │ 1952  │
└─────────────┴───────┘
```

### llm vendors

List all vendors:

```bash
my-app llm vendors
```

### llm modalities

List all modalities (text, image, audio, video) with model counts:

```bash
my-app llm modalities
```

### llm list

Search and filter models:

```bash
# Search by pattern
my-app llm list claude

# Filter by vendor
my-app llm list gpt-4 --vendor openai

# Filter by modality
my-app llm list --vendor anthropic --modality image

# Include disabled models
my-app llm list --vendor openai --all

# Limit results
my-app llm list --vendor google --limit 10
```

```
LLM Models (5 results)
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ Model ID                    ┃ Vendor    ┃ Context  ┃ Input $/1M┃ Output $/1M┃ Released   ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ claude-sonnet-4-20250514    │ Anthropic │ 200,000  │ $3.00     │ $15.00     │ 2025-05-14 │
│ claude-haiku-4-5-20251001   │ Anthropic │ 200,000  │ $0.80     │ $4.00      │ 2025-10-01 │
│ claude-opus-4-6             │ Anthropic │ 200,000  │ $15.00    │ $75.00     │ 2025-06-01 │
└─────────────────────────────┴───────────┴──────────┴───────────┴────────────┴────────────┘
```

### llm current

Show current LLM configuration from `.env`, enriched with catalog data:

```bash
my-app llm current
```

```
Current LLM Configuration
├── Provider: openai
├── Model: gpt-4o
├── Temperature: 0.7
└── Max Tokens: 1,000

Model Details (from catalog)
├── Context Window: 128,000
├── Input Price: $2.50 / 1M tokens
├── Output Price: $10.00 / 1M tokens
└── Modalities: text, image
```

### llm use

Switch to a different model:

```bash
# Auto-detects vendor and updates AI_PROVIDER in .env
my-app llm use gpt-4o
my-app llm use claude-sonnet-4-20250514

# Force any model string (skip catalog validation)
my-app llm use my-custom-model --force
```

### llm info

Show detailed model information:

```bash
my-app llm info gpt-4o
```

```
╭─────────────── gpt-4o ───────────────╮
│ GPT-4o                               │
│                                       │
│ Model ID: gpt-4o                     │
│ Vendor: OpenAI                       │
│                                       │
│ Context Window: 128,000 tokens       │
│ Streamable: Yes                      │
│ Enabled: Yes                         │
│ Released: 2024-05-13                 │
│                                       │
│ Pricing (per 1M tokens)             │
│   Input: $2.50                       │
│   Output: $10.00                     │
│                                       │
│ Modalities: text, image              │
╰───────────────────────────────────────╯
```

---

## RAG Commands

Manage document indexing and search. See [RAG](rag.md) for full documentation.

### rag index

Index documents from a path into a collection:

```bash
# Index current directory
my-app rag index . --collection my-codebase

# Index specific directory with extensions
my-app rag index ./app --collection code --extensions .py,.ts
```

```
╭──────── Collection: code ─────────╮
│ Successfully indexed 1,523 chunks │
│ from 87 files                     │
│                                    │
│ Extensions: .py                   │
│ Duration: 8.3s                    │
│   Loading:  1.2s (14%)            │
│   Chunking: 0.8s (10%)           │
│   Indexing: 6.3s (76%)           │
│ Throughput: 183.5 chunks/sec     │
│ Collection size: 1,523 chunks    │
╰────────────────────────────────────╯
```

### rag add

Add or update a single file (upsert semantics):

```bash
my-app rag add app/services/auth.py --collection code
my-app rag add app/services/auth.py -c code --show-ids
```

### rag remove

Remove a file's chunks from the collection:

```bash
my-app rag remove /path/to/file.py --collection code
my-app rag remove /path/to/file.py -c code --force
```

### rag files

List indexed files in a collection:

```bash
my-app rag files --collection code
```

```
Indexed Files: code
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ File                                  ┃ Chunks ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ app/services/ai/service.py            │ 45     │
│ app/services/auth/service.py          │ 23     │
│ app/components/backend/api/v1/ai/router… │ 12     │
└───────────────────────────────────────┴────────┘

Total: 87 files, 1,523 chunks
```

### rag search

Semantic search across indexed documents:

```bash
# Basic search
my-app rag search "how does authentication work" --collection code

# Show full content
my-app rag search "database connection" -c code --content

# More results
my-app rag search "error handling" -c code --top-k 10
```

### rag list

List all collections:

```bash
my-app rag list
```

```
RAG Collections
┏━━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ Collection  ┃ Documents ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━━━┩
│ code        │ 1,523     │
│ docs        │ 342       │
└─────────────┴───────────┘
```

### rag delete

Delete a collection:

```bash
my-app rag delete code
my-app rag delete code --force
```

### rag status

Show RAG service status and configuration:

```bash
my-app rag status
```

```
╭──────── RAG Service Status ────────╮
│ Enabled: Yes                       │
│ Persist Directory: .chromadb       │
│ Embedding Model: all-MiniLM-L6-v2 │
│ Model Status: Installed            │
│ Chunk Size: 1000                   │
│ Chunk Overlap: 200                 │
│ Default Top K: 5                   │
│ Collections: 2                     │
╰────────────────────────────────────╯
```

### rag install-model

Pre-download the embedding model for offline use:

```bash
# Download to default location
my-app rag install-model

# Custom cache directory
my-app rag install-model --cache-dir /path/to/models

# Specific model
my-app rag install-model --model sentence-transformers/all-MiniLM-L6-v2
```

!!! note
    Not needed for OpenAI embeddings - only for local sentence-transformers models (~400MB download).

---

## See Also

- **[CLI Reference](../../cli-reference.md)** - Complete CLI overview and all commands
- **[LLM Catalog](llm-catalog.md)** - Full catalog documentation
- **[RAG](rag.md)** - Full RAG documentation
- **[AI Service](index.md)** - Main AI service documentation
- **[Providers Guide](providers.md)** - Provider setup and configuration
- **[API Reference](api.md)** - REST API documentation
