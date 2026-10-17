# AI Engines

The AI service supports two engine choices: **Pydantic AI** and **LangChain**. You select your engine at project generation time, and both provide the same user-facing API.

## Overview

An "engine" is the underlying AI framework that powers your chat functionality. Both engines:

- Support all [providers](providers.md)
- Provide identical CLI and REST API interfaces
- Handle conversation management the same way
- Support streaming responses
- Run an agent's granted tools: Pydantic AI natively, LangChain by binding them to the model and running what it calls between rounds (`app/services/ai/service/langchain_turn.py`)

The difference is internal implementation, how the engine communicates with the AI models. What matters for *you*, the builder, comes down to the following: Are you going to extend the service? If so, then pick the framework you're used to.

## Pydantic AI

[Pydantic AI](https://ai.pydantic.dev/) is built by the Pydantic team, providing a type-safe, validation-first approach to AI.

## LangChain

[LangChain](https://python.langchain.com/) is a comprehensive framework for building LLM applications with extensive tooling and integrations.

## Selecting Your Engine

Engine selection happens at project generation time using bracket notation:

```bash
# Generate with Pydantic AI (default)
aegis init my-app --services ai

# Generate with LangChain
aegis init my-app --services ai[langchain]

# LangChain with specific provider
aegis init my-app --services ai[langchain,openai]

# LangChain with SQLite persistence
aegis init my-app --services ai[langchain,sqlite,groq]
```

!!! note "Engine is Compile-Time"
    Unlike providers (which you can switch via environment variables), the engine choice is "baked in" at project generation. To switch engines, you'd need to regenerate the project.

## Dependencies

Each engine installs its own set of dependencies (depending on which providers you choose to use):

**Pydantic AI:**
```
pydantic-ai-slim[openai,anthropic,google,groq]
```

**LangChain:**
```
langchain-openai
langchain-anthropic
langchain-google-genai
langchain-groq
langchain-mistralai
langchain-cohere
```

---

**Next Steps:**

- **[Provider Setup](providers.md)** - Configure API keys for your chosen provider
- **[API Reference](api.md)** - REST API documentation
- **[CLI Commands](cli.md)** - Command-line interface
- **[Service Layer](integration.md)** - Using AIService in your code
