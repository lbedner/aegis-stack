# AI Providers

Complete setup guide for all supported AI providers.

## Overview

The AI service supports multiple providers through either [Pydantic AI](https://ai.pydantic.dev/) or [LangChain](https://python.langchain.com/) (see [Engines](engines.md)), giving you flexibility to choose based on your needs: cost, speed, features, or specific model capabilities.

!!! tip "All Providers Work with Both Engines"
    Whether you chose Pydantic AI or LangChain as your engine, every provider below is fully supported with identical configuration.

**Quick comparison:**

| Provider | API Key Required | Speed | Best For |
|----------|------------------|-------|----------|
| **PUBLIC** | Optional (anonymous tier) | Basic | Instant testing, zero setup |
| **Pollinations** | Optional (anonymous tier) | Basic | Keyless fallback, open-weight models |
| **Ollama** | No (local) | Varies | Privacy, offline, no API costs |
| **Google Gemini** | Yes (free tier) | Good | Development, prototyping |
| **Groq** | Yes (free tier) | Very fast | Production, low cost |
| **OpenAI** | Yes | Good | Production, familiar API |
| **Anthropic** | Yes | Good | Claude models |
| **Mistral** | Yes | Good | Open models |
| **Cohere** | Yes (free tier) | Good | Command models |

!!! tip "Recommendation"
    **Start:** PUBLIC (keyless anonymous tier) → **Develop:** Google Gemini (free tier) → **Production:** Groq (very fast, low cost)

## Configuration

All providers are configured through environment variables in your `.env` file:

```bash
# Core AI Service Settings
AI_ENABLED=true                    # Enable/disable service
AI_PROVIDER=public                 # Provider: openai, anthropic, google, groq, mistral, cohere, ollama, public, pollinations
AI_MODEL=auto                      # Model name (varies by provider, "auto" for PUBLIC and Pollinations)
AI_TEMPERATURE=0.7                 # Response creativity (0.0-2.0)
AI_MAX_TOKENS=1000                 # Maximum response length
AI_TIMEOUT_SECONDS=30.0            # Request timeout

# Provider API Keys
LLM7_API_KEY=...                   # Optional: unlocks LLM7 premium models (dash.llm7.io)
POLLINATIONS_API_KEY=...           # Optional: Pollinations account tier
OPENAI_API_KEY=sk-...              # OpenAI API key
ANTHROPIC_API_KEY=sk-ant-...       # Anthropic API key
GOOGLE_API_KEY=...                 # Google API key
GROQ_API_KEY=gsk_...               # Groq API key
MISTRAL_API_KEY=...                # Mistral API key
COHERE_API_KEY=...                 # Cohere API key
```

## Provider Setup Guides

=== "PUBLIC (Free)"

    Free access through LLM7.io. The anonymous tier works with **no key at
    all**: open-weight models (GPT-OSS, Codestral, ...) with strict per-IP
    rate limits. An optional free account key unlocks their premium models
    (GPT-5.x, Claude, billed per token) and higher limits.

    **Setup (anonymous):**

    ```bash
    # Nothing to configure - just start chatting
    my-app ai chat "Hello! Can you help me?"
    ```

    **Setup (premium models):**

    1. Create a free account key at [dash.llm7.io](https://dash.llm7.io)
    2. Set it in your environment:

    ```bash
    # .env
    LLM7_API_KEY=your-key
    ```

    `AI_MODEL=auto` resolves against LLM7's live catalog and is tier-aware:
    keyless projects pick an anonymous-tier model, keyed projects a premium
    one - you never chase their model rotation.

    **Best for:** Instant testing, demos, getting started with zero setup

=== "Pollinations (Free)"

    A second keyless option with an active community, served through an
    OpenAI-compatible API. The anonymous tier needs **no key at all**:
    open-weight models (GPT-OSS 20B) with per-IP rate limits and
    non-streaming responses.

    **Setup (anonymous):**

    ```bash
    # .env
    AI_PROVIDER=pollinations

    my-app ai chat "Hello! Can you help me?"
    ```

    `AI_MODEL=auto` resolves against Pollinations' live catalog: keyless
    projects only pick anonymous-tier models. Anonymous requests must not
    carry a key; the service handles that automatically.

    **Best for:** A drop-in keyless fallback when the PUBLIC provider is
    unavailable, or trying open-weight models with zero setup

=== "Groq (Production)"

    Blazing fast inference with very generous free tier.

    **Setup:**

    1. Sign up at [console.groq.com](https://console.groq.com/)
    2. Create an API key (free tier available)
    3. Configure your environment:

    ```bash
    export AI_PROVIDER=groq
    export GROQ_API_KEY=gsk_your_key_here
    export AI_MODEL=llama-3.1-8b-instant  # Fastest model
    ```

    **Available Models:** See [Groq's model documentation](https://console.groq.com/docs/models) for the latest available models.

    **Best for:** Production use (very fast, extremely low cost)

=== "Google Gemini (Free Tier)"

    Generous free tier with daily rate limits. Great for development.

    **Setup:**

    1. Get free API key from [aistudio.google.com](https://aistudio.google.com/apikey)
    2. Configure your environment:

    ```bash
    export AI_PROVIDER=google
    export GOOGLE_API_KEY=your_key_here
    export AI_MODEL=gemini-2.0-flash-exp
    ```

    **Available Models:** See [Google's model documentation](https://ai.google.dev/gemini-api/docs/models/gemini) for the latest available models.

    **Best for:** Development and prototyping within rate limits

=== "OpenAI"

    Industry-standard GPT models. Most widely used and documented.

    **Setup:**

    1. Get API key from [platform.openai.com](https://platform.openai.com/)
    2. Add payment method (required for API access)
    3. Configure your environment:

    ```bash
    export AI_PROVIDER=openai
    export OPENAI_API_KEY=sk-your_key_here
    export AI_MODEL=gpt-3.5-turbo
    ```

    **Available Models:** See [OpenAI's model documentation](https://platform.openai.com/docs/models) for the latest available models.

    **Best for:** Production with familiar API, extensive ecosystem

=== "Anthropic"

    Claude models from Anthropic. Known for safety and reasoning.

    **Setup:**

    1. Get API key from [console.anthropic.com](https://console.anthropic.com/)
    2. Add payment method
    3. Configure your environment:

    ```bash
    export AI_PROVIDER=anthropic
    export ANTHROPIC_API_KEY=sk-ant-your_key_here
    export AI_MODEL=claude-3-5-sonnet-20241022
    ```

    **Available Models:** See [Anthropic's model documentation](https://docs.anthropic.com/en/docs/models-overview) for the latest available models.

    **Best for:** High-quality responses, safety-critical applications

=== "Mistral"

    Open-source Mistral models with European data residency.

    **Setup:**

    1. Get API key from [console.mistral.ai](https://console.mistral.ai/)
    2. Configure your environment:

    ```bash
    export AI_PROVIDER=mistral
    export MISTRAL_API_KEY=your_key_here
    export AI_MODEL=mistral-small-latest
    ```

    **Available Models:** See [Mistral's model documentation](https://docs.mistral.ai/getting-started/models/) for the latest available models.

    **Best for:** Open-source preference, European compliance requirements

=== "Cohere"

    Command models optimized for enterprise and RAG use cases.

    **Setup:**

    1. Get API key from [dashboard.cohere.com](https://dashboard.cohere.com/)
    2. Configure your environment:

    ```bash
    export AI_PROVIDER=cohere
    export COHERE_API_KEY=your_key_here
    export AI_MODEL=command-r-plus
    ```

    **Available Models:** See [Cohere's model documentation](https://docs.cohere.com/docs/models) for the latest available models.

    **Best for:** Enterprise features, RAG applications

## Ollama (Local)

Run models locally with zero API costs. Supports hundreds of open-source models.

### Setup

1. Install Ollama from [ollama.ai](https://ollama.ai/)
2. Pull a model:

```bash
ollama pull llama3.1
```

3. Configure your environment:

```bash
AI_PROVIDER=ollama
AI_MODEL=llama3.1
```

### Ollama Deployment Modes

Configure at project generation:

```bash
# Host mode: Ollama runs on your machine (default)
aegis init my-app --services ai

# Docker mode: Ollama runs in a Docker container
# (select during aegis init interactive prompts)
```

| Mode | Description | Use Case |
|------|-------------|----------|
| `host` | Ollama on localhost:11434 | Development, GPU on host |
| `docker` | Ollama in Docker container | Portable, CI/CD |
| `none` | No Ollama support | Cloud-only providers |

### Switching Models via CLI

With the LLM Catalog, you can discover and switch Ollama models:

```bash
# Sync Ollama models into catalog
my-app llm sync --source ollama

# List available Ollama models
my-app llm list --vendor ollama

# Switch to an Ollama model
my-app llm use llama3.1

# Or use /model in interactive chat
my-app ai chat
> /model llama3.1
```

!!! tip "Cost Tracking with Ollama"
    Ollama models show $0.00 cost in usage stats - this is expected and normal since all processing happens locally. Illiana is aware of this and won't flag it as an issue.

## Switching Providers

You can switch providers at any time by changing your `.env` file or using the CLI:

```bash
# Switch from PUBLIC to Groq
AI_PROVIDER=groq
GROQ_API_KEY=your-key-here
AI_MODEL=llama-3.1-8b-instant
```

### Via .env

Edit `.env` and restart:

```bash
make stop && make serve
```

### Via CLI (with LLM Catalog)

Update `.env` from the catalog (takes effect on next CLI invocation or server restart):

```bash
# Auto-detects provider from model name and updates .env
my-app llm use gpt-4o              # → sets AI_PROVIDER=openai
my-app llm use claude-sonnet-4-20250514  # → sets AI_PROVIDER=anthropic
my-app llm use llama3.1            # → sets AI_PROVIDER=ollama
```

Switch instantly within an interactive chat session (refreshes in-process, no restart needed):

```bash
my-app ai chat
> /model gpt-4o
✓ Switched to OpenAI/gpt-4o
```

**Verify the switch:**

```bash
my-app ai status
my-app llm current
```

## Troubleshooting

### "Missing API key" Error

```bash
❌ Missing API key for groq provider. Set GROQ_API_KEY environment variable.
```

**Solution:** Add the API key to your `.env` file:

```bash
GROQ_API_KEY=your-actual-key-here
```

### "Provider not available" Error

**Check configuration:**

```bash
my-app ai status
```

**Verify provider is installed:**

```bash
my-app ai providers
```

---

**Next Steps:**

- **[LLM Catalog](llm-catalog.md)** - Browse and switch between ~2000 models
- **[CLI Commands](cli.md)** - Using the AI service from command line
- **[API Reference](api.md)** - Using the AI service via REST API
- **[Service Layer](integration.md)** - Using the AI service in your code
- **[Examples](examples.md)** - Real-world usage patterns
