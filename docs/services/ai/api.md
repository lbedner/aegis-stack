# AI Service API Reference

Complete REST API documentation for AI service endpoints.

## Base URL

All AI endpoints are prefixed with `/ai`:

```
http://localhost:8000/ai
```

## Endpoints Overview

<div class="grid cards" markdown>

-   :material-message-text: **POST `/api/v1/ai/chat`**

    ---

    Send chat message and receive AI response

    [:octicons-arrow-right-24: Details](#post-apiv1aichat)

-   :material-broadcast: **POST `/api/v1/ai/chat/stream`**

    ---

    Stream AI responses with Server-Sent Events

    [:octicons-arrow-right-24: Details](#post-apiv1aichatstream)

-   :material-format-list-bulleted: **GET `/api/v1/ai/conversations`**

    ---

    List user conversations with metadata

    [:octicons-arrow-right-24: Details](#get-apiv1aiconversations)

-   :material-message-reply-text: **GET `/api/v1/ai/conversations/{id}`**

    ---

    Get conversation with full message history

    [:octicons-arrow-right-24: Details](#get-apiv1aiconversationsconversation_id)

-   :material-heart-pulse: **GET `/api/v1/ai/health`**

    ---

    Check AI service health status

    [:octicons-arrow-right-24: Details](#get-apiv1aihealth)

-   :material-account-group: **GET `/api/v1/ai/agents`**

    ---

    List agent definitions with tool and module grants

-   :material-pencil: **PATCH `/api/v1/ai/agents/{slug}`**

    ---

    Update an agent's editable fields

-   :material-chart-bar: **GET `/api/v1/ai/usage/stats`**

    ---

    Aggregated token usage and cost statistics

-   :material-emoticon-outline: **GET `/api/v1/ai/sentiment/stats`**

    ---

    Conversation sentiment distribution and recent negatives

-   :material-information: **GET `/ai/version`**

    ---

    Get service version and capabilities

    [:octicons-arrow-right-24: Details](#get-aiversion)

</div>

## Chat Endpoints

### POST `/api/v1/ai/chat`

Send a chat message and receive AI response.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message` | string | ✅ Yes | User's chat message |
| `conversation_id` | string \| null | ❌ No | Existing conversation ID (creates new if null) |
| `user_id` | string | ❌ No | User identifier (default: "api-user") |

**Response:**

```json title="Response Schema"
{
  "message_id": "uuid",
  "content": "AI response text",
  "conversation_id": "uuid",
  "response_time_ms": 1234.5
}
```

**Examples:**

=== "cURL"

    ```bash
    curl -X POST http://localhost:8000/api/v1/ai/chat \
      -H "Content-Type: application/json" \
      -d '{
        "message": "Explain FastAPI in one sentence",
        "user_id": "my-user"
      }'
    ```

=== "Python"

    ```python title="Basic Chat Request" hl_lines="3-8"
    import httpx

    response = httpx.post(  # (1)!
        "http://localhost:8000/api/v1/ai/chat",
        json={
            "message": "What is async/await in Python?",  # (2)!
            "user_id": "my-user"  # (3)!
        }
    )

    data = response.json()
    print(f"AI: {data['content']}")  # (4)!
    print(f"Conversation: {data['conversation_id']}")  # (5)!
    ```

    1.  POST request to the chat endpoint
    2.  The user's message - this is what gets sent to the AI
    3.  User identifier for conversation tracking (optional, defaults to "api-user")
    4.  Extract and print the AI's response text
    5.  Save this conversation_id to continue the conversation in future requests

=== "JavaScript"

    ```javascript title="Fetch API Example"
    const response = await fetch('http://localhost:8000/api/v1/ai/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: 'How do I handle errors in async functions?',
        user_id: 'web-user'
      })
    });

    const data = await response.json();
    console.log(`AI: ${data.content}`);
    ```

**Continue Conversation:**

```bash
# First message
curl -X POST http://localhost:8000/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is FastAPI?"}' \
  | jq -r '.conversation_id' > conv_id.txt

# Follow-up message (maintains context)
curl -X POST http://localhost:8000/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -d "{
    \"message\": \"Can you show me an example?\",
    \"conversation_id\": \"$(cat conv_id.txt)\"
  }"
```

### POST `/api/v1/ai/chat/stream`

Stream chat response with Server-Sent Events (SSE).

**Request Body:**

Same as `/api/v1/ai/chat`:

```json
{
  "message": "string",
  "conversation_id": "string | null",
  "user_id": "string"
}
```

**Response:**

Server-Sent Events stream with the following event types:

**Event: `connect`**
```
event: connect
data: {"status": "connected", "message": "Streaming started"}
```

**Event: `chunk`** (repeated for each content chunk)
```
event: chunk
data: {
  "content": "text delta",
  "is_final": false,
  "is_delta": true,
  "message_id": "uuid",
  "conversation_id": "uuid",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

**Event: `final`**
```
event: final
data: {
  "content": "complete response",
  "is_final": true,
  "is_delta": false,
  "message_id": "uuid",
  "conversation_id": "uuid",
  "timestamp": "2024-01-15T10:30:05Z",
  "response_time_ms": 1234.5,
  "provider": "groq",
  "model": "llama-3.1-70b-versatile"
}
```

**Event: `complete`**
```
event: complete
data: {"status": "completed", "message": "Stream finished"}
```

**Event: `error`** (on error)
```
event: error
data: {"error": "AI service error", "detail": "error message"}
```

**Examples:**

=== "cURL"

    ```bash
    curl -X POST http://localhost:8000/api/v1/ai/chat/stream \
      -H "Content-Type: application/json" \
      -d '{"message": "Write a Python hello world"}' \
      --no-buffer
    ```

=== "JavaScript"

    ```javascript title="SSE Streaming Client" hl_lines="10-13"
    const eventSource = new EventSource(  // (1)!
      '/api/v1/ai/chat/stream?' + new URLSearchParams({
        message: 'Explain async programming',
        user_id: 'web-user'
      })
    );

    let fullResponse = '';

    eventSource.addEventListener('chunk', (e) => {  // (2)!
      const data = JSON.parse(e.data);
      fullResponse += data.content;
      updateUI(fullResponse);  // (3)!
    });

    eventSource.addEventListener('final', (e) => {  // (4)!
      const data = JSON.parse(e.data);
      console.log('Complete response:', data.content);
      console.log('Response time:', data.response_time_ms);
    });

    eventSource.addEventListener('error', (e) => {  // (5)!
      const data = JSON.parse(e.data);
      console.error('Error:', data.detail);
      eventSource.close();
    });

    eventSource.addEventListener('complete', (e) => {  // (6)!
      console.log('Stream complete');
      eventSource.close();
    });
    ```

    1.  Create EventSource connection to the streaming endpoint
    2.  Handle each streamed chunk as it arrives
    3.  Update UI in real-time as tokens stream in
    4.  Handle final event with complete response and timing
    5.  Handle errors and close connection
    6.  Clean up connection when stream completes

=== "Python"

    ```python title="httpx Streaming" hl_lines="6-9"
    import httpx
    import json

    url = "http://localhost:8000/api/v1/ai/chat/stream"
    data = {"message": "Explain decorators in Python", "user_id": "my-user"}

    with httpx.stream("POST", url, json=data) as response:  # (1)!
        for line in response.iter_lines():  # (2)!
            if line.startswith('event:'):
                event_type = line.split(':')[1].strip()
            elif line.startswith('data:'):
                data = json.loads(line.split('data:')[1])

                if event_type == 'chunk':  # (3)!
                    print(data['content'], end='', flush=True)
                elif event_type == 'final':  # (4)!
                    print(f"\n\nResponse time: {data['response_time_ms']}ms")
    ```

    1.  Open streaming connection with context manager
    2.  Iterate through Server-Sent Events line by line
    3.  Print each chunk as it arrives for real-time output
    4.  Show final response metadata when stream completes

## Conversation Management

### GET `/api/v1/ai/conversations`

List conversations for a user.

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `user_id` | string | ❌ No | "api-user" | User identifier |
| `limit` | integer | ❌ No | 50 | Maximum conversations to return |

**Response:**

```json
[
  {
    "id": "uuid",
    "title": "Conversation title",
    "message_count": 5,
    "last_activity": "2024-01-15T10:30:00Z",
    "provider": "groq",
    "model": "llama-3.1-70b-versatile"
  }
]
```

**Example:**

```bash
# List conversations
curl "http://localhost:8000/api/v1/ai/conversations?user_id=my-user&limit=10"

# With Python
import httpx

response = httpx.get(
    "http://localhost:8000/api/v1/ai/conversations",
    params={"user_id": "my-user", "limit": 10}
)

conversations = response.json()
for conv in conversations:
    print(f"{conv['id']}: {conv['title']} ({conv['message_count']} messages)")
```

### GET `/api/v1/ai/conversations/{conversation_id}`

Get a specific conversation with full message history.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `conversation_id` | string | Conversation UUID |

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `user_id` | string | ❌ No | "api-user" | User identifier for access control |

**Response:**

```json
{
  "id": "uuid",
  "title": "Conversation title",
  "provider": "groq",
  "model": "llama-3.1-70b-versatile",
  "created_at": "2024-01-15T10:00:00Z",
  "updated_at": "2024-01-15T10:30:00Z",
  "message_count": 5,
  "messages": [
    {
      "id": "msg-uuid-1",
      "role": "user",
      "content": "What is FastAPI?",
      "timestamp": "2024-01-15T10:00:00Z"
    },
    {
      "id": "msg-uuid-2",
      "role": "assistant",
      "content": "FastAPI is a modern web framework...",
      "timestamp": "2024-01-15T10:00:02Z"
    }
  ],
  "metadata": {
    "user_id": "my-user",
    "last_response_time_ms": 1234.5
  }
}
```

**Example:**

```bash
curl "http://localhost:8000/api/v1/ai/conversations/CONVERSATION_ID?user_id=my-user"
```

## Agent Registry

Requires a database backend (`ai[sqlite]` / `ai[postgres]`). See [Agents](agents.md).

### GET `/api/v1/ai/agents`

List every agent definition, including tool and memory-module grants.

```bash
curl http://localhost:8000/api/v1/ai/agents
```

```json
[
  {
    "slug": "assistant",
    "name": "Illiana",
    "model_id": null,
    "temperature": 0.7,
    "max_tokens": 1000,
    "system_prompt": "...",
    "is_active": true,
    "tools": [],
    "memory_modules": [],
    "knowledge_base_ids": []
  }
]
```

### PATCH `/api/v1/ai/agents/{slug}`

Partial update of an agent's editable fields (`name`, `description`, `category`, `model_id`, `temperature`, `max_tokens`, `system_prompt`, `is_active`). The agent's cached configuration is invalidated, so the next chat request uses the new definition. Unknown slugs return 404; invalid values (temperature outside 0-2, empty prompt) return 400.

```bash
curl -X PATCH http://localhost:8000/api/v1/ai/agents/assistant \
  -H "Content-Type: application/json" \
  -d '{"temperature": 0.3, "is_active": true}'
```

## Analytics

### GET `/api/v1/ai/usage/stats`

Aggregated token usage and cost statistics, with optional `user_id`, `start_time`, `end_time`, and `recent_limit` query parameters.

```bash
curl "http://localhost:8000/api/v1/ai/usage/stats?recent_limit=10"
```

### GET `/api/v1/ai/sentiment/stats`

Sentiment and performance distributions, average score, and recent negative conversations. Zero-filled until the (off-by-default) scoring job runs; the `enabled` field reports whether `AI_SENTIMENT_ENABLED` is set.

```bash
curl http://localhost:8000/api/v1/ai/sentiment/stats
```

## Service Status

### GET `/api/v1/ai/health`

AI service health status and configuration.

**Response:**

```json
{
  "service": "ai",
  "status": "healthy",
  "enabled": true,
  "provider": "groq",
  "model": "llama-3.1-70b-versatile",
  "agent_ready": true,
  "total_conversations": 42,
  "configuration_valid": true,
  "validation_errors": []
}
```

**Status Values:**
- `healthy` - Service operational and properly configured
- `unhealthy` - Configuration issues or service errors
- `error` - Critical service failure

**Example:**

```bash
curl http://localhost:8000/api/v1/ai/health | jq
```

### GET `/ai/version`

Service version and feature information.

**Response:**

```json
{
  "service": "ai",
  "engine": "pydantic-ai",
  "version": "1.0",
  "features": [
    "chat",
    "conversation_management",
    "multi_provider_support",
    "health_monitoring",
    "api_endpoints",
    "cli_commands"
  ],
  "providers_supported": [
    "openai",
    "anthropic",
    "google",
    "groq",
    "mistral",
    "cohere"
  ]
}
```

**Example:**

```bash
curl http://localhost:8000/api/v1/ai/version | jq
```

## Error Handling

### HTTP Status Codes

| Status | Description |
|--------|-------------|
| 200 | Success |
| 400 | Bad request (invalid conversation_id, missing required fields) |
| 403 | Forbidden (conversation access denied) |
| 404 | Not found (conversation doesn't exist) |
| 502 | Bad gateway (AI provider error) |
| 503 | Service unavailable (AI service disabled or misconfigured) |
| 500 | Internal server error |

### Error Response Format

```json
{
  "detail": "Error message description"
}
```

### Common Errors

**AI Service Disabled:**
```json
{
  "detail": "AI service error: AI service is disabled"
}
```

**Missing API Key:**
```json
{
  "detail": "AI service error: Missing API key for openai provider. Set OPENAI_API_KEY environment variable."
}
```

**Provider Error:**
```json
{
  "detail": "AI provider error: Rate limit exceeded"
}
```

**Conversation Not Found:**
```json
{
  "detail": "Conversation error: Conversation abc-123 not found"
}
```

**Access Denied:**
```json
{
  "detail": "Access denied"
}
```

## Usage Analytics

### GET `/api/v1/ai/usage/stats`

!!! note
    Requires database backend (`ai[sqlite]` or `ai[postgres]`). Not available with in-memory backend.

Get usage statistics with token counts, costs, and model breakdown.

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `user_id` | string | No | all users | Filter by user |
| `start_time` | datetime | No | all time | Start of time range |
| `end_time` | datetime | No | now | End of time range |
| `recent_limit` | integer | No | 10 | Number of recent activities |

**Response:**

```json
{
  "total_tokens": 45230,
  "input_tokens": 32100,
  "output_tokens": 13130,
  "total_cost": 0.47,
  "total_requests": 23,
  "success_rate": 95.6,
  "models": [
    {
      "model_id": "gpt-4o",
      "vendor": "OpenAI",
      "requests": 15,
      "tokens": 30000,
      "cost": 0.35,
      "percentage": 65.2
    }
  ],
  "recent_activity": [
    {
      "timestamp": "2024-01-15T10:30:00Z",
      "model": "gpt-4o",
      "input_tokens": 1500,
      "output_tokens": 800,
      "cost": 0.02,
      "success": true,
      "action": "chat"
    }
  ]
}
```

**Example:**

```bash
# All-time stats
curl http://localhost:8000/api/v1/ai/usage/stats | jq

# Per-user stats
curl "http://localhost:8000/api/v1/ai/usage/stats?user_id=my-user"

# Time-range query
curl "http://localhost:8000/api/v1/ai/usage/stats?start_time=2024-01-01T00:00:00Z&recent_limit=20"
```

---

## LLM Catalog Endpoints

All LLM catalog endpoints are prefixed with `/llm`. See [LLM Catalog](llm-catalog.md) for full documentation.

### GET `/llm/status`

Get catalog statistics.

```json
{
  "vendor_count": 32,
  "model_count": 1847,
  "deployment_count": 2103,
  "price_count": 1952,
  "top_vendors": [
    {"name": "OpenAI", "model_count": 156},
    {"name": "Google", "model_count": 89}
  ]
}
```

### GET `/llm/vendors`

List all vendors with model counts.

```bash
curl http://localhost:8000/llm/vendors | jq
```

### GET `/llm/modalities`

List modalities (text, image, audio, video) with model counts.

### GET `/llm/models`

Search and filter models.

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `pattern` | string | null | Search pattern for model ID/title |
| `vendor` | string | null | Filter by vendor name |
| `modality` | string | null | Filter by modality |
| `limit` | integer | 50 | Max results (1-200) |
| `include_disabled` | boolean | false | Include disabled models |

```bash
# Search models
curl "http://localhost:8000/llm/models?pattern=gpt-4&vendor=openai"

# Filter by modality
curl "http://localhost:8000/llm/models?modality=image&limit=20"
```

**Response:**

```json
[
  {
    "model_id": "gpt-4o",
    "vendor": "OpenAI",
    "context_window": 128000,
    "input_price": 2.50,
    "output_price": 10.00,
    "released_on": "2024-05-13"
  }
]
```

### GET `/llm/current`

Get current active LLM configuration enriched with catalog data.

```json
{
  "provider": "openai",
  "model": "gpt-4o",
  "temperature": 0.7,
  "max_tokens": 1000,
  "context_window": 128000,
  "input_price": 2.50,
  "output_price": 10.00,
  "modalities": ["text", "image"]
}
```

---

## RAG Endpoints

All RAG endpoints are prefixed with `/rag`. See [RAG](rag.md) for full documentation.

### POST `/rag/index`

Index documents from a path.

**Request:**

```json
{
  "path": "./app",
  "collection_name": "code",
  "extensions": [".py", ".ts"],
  "exclude_patterns": ["**/test_*"]
}
```

**Response:**

```json
{
  "collection_name": "code",
  "documents_added": 1523,
  "total_documents": 1523,
  "duration_ms": 8300.5
}
```

### POST `/rag/search`

Semantic search across indexed documents.

**Request:**

```json
{
  "query": "how does authentication work",
  "collection_name": "code",
  "top_k": 5,
  "filter_metadata": null
}
```

**Response:**

```json
{
  "query": "how does authentication work",
  "collection_name": "code",
  "results": [
    {
      "content": "class AuthService:\n    ...",
      "metadata": {"source": "app/services/auth/service.py", "file_name": "service.py"},
      "score": 0.8932,
      "rank": 1
    }
  ],
  "result_count": 5
}
```

### GET `/rag/collections`

List all collection names.

### GET `/rag/collections/{name}`

Get collection info (name, document count, metadata).

### GET `/rag/collections/{name}/files`

List indexed files with chunk counts.

```json
{
  "collection_name": "code",
  "files": [
    {"source": "app/services/ai/service.py", "chunks": 45},
    {"source": "app/services/auth/service.py", "chunks": 23}
  ],
  "total_files": 87,
  "total_chunks": 1523
}
```

### DELETE `/rag/collections/{name}`

Delete a collection and all its documents.

### GET `/rag/health`

RAG service health status including configuration and validation.

---

## Voice Endpoints

All voice endpoints are prefixed with `/voice`. See [Voice](voice.md) for full documentation.

### TTS Catalog

| Endpoint | Description |
|----------|-------------|
| `GET /voice/catalog/tts/providers` | List TTS providers |
| `GET /voice/catalog/tts/{provider_id}/models` | List models for provider |
| `GET /voice/catalog/tts/{provider_id}/voices` | List voices for provider |

### STT Catalog

| Endpoint | Description |
|----------|-------------|
| `GET /voice/catalog/stt/providers` | List STT providers |
| `GET /voice/catalog/stt/{provider_id}/models` | List STT models |

### Settings & Preview

| Endpoint | Description |
|----------|-------------|
| `GET /voice/settings` | Get current voice settings |
| `POST /voice/settings` | Update voice settings |
| `POST /voice/preview` | Generate voice preview (returns audio/mpeg) |
| `GET /voice/preview/{voice_id}` | Browser-friendly voice preview |
| `GET /voice/catalog/summary` | Full catalog summary |

---

## Error Handling

### HTTP Status Codes

| Status | Description |
|--------|-------------|
| 200 | Success |
| 400 | Bad request (invalid conversation_id, missing required fields) |
| 403 | Forbidden (conversation access denied) |
| 404 | Not found (conversation/collection doesn't exist) |
| 502 | Bad gateway (AI provider error) |
| 503 | Service unavailable (AI service disabled or misconfigured) |
| 500 | Internal server error |

### Error Response Format

```json
{
  "detail": "Error message description"
}
```

### Common Errors

**AI Service Disabled:**
```json
{
  "detail": "AI service error: AI service is disabled"
}
```

**Missing API Key:**
```json
{
  "detail": "AI service error: Missing API key for openai provider. Set OPENAI_API_KEY environment variable."
}
```

**Provider Error:**
```json
{
  "detail": "AI provider error: Rate limit exceeded"
}
```

**Conversation Not Found:**
```json
{
  "detail": "Conversation error: Conversation abc-123 not found"
}
```

**Collection Not Found:**
```json
{
  "detail": "Collection 'my-collection' not found"
}
```

---

**Next Steps:**

- **[LLM Catalog](llm-catalog.md)** - Full catalog documentation
- **[RAG](rag.md)** - Full RAG documentation
- **[Cost Tracking](cost-tracking.md)** - Usage analytics
- **[Voice](voice.md)** - Voice capabilities
- **[Service Layer](integration.md)** - Integration patterns and architecture
- **[CLI Commands](cli.md)** - Command-line interface reference
- **[Examples](examples.md)** - Real-world usage patterns
