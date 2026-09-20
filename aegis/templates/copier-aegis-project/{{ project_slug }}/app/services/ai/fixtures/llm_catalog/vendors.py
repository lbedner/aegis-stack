"""The API providers the catalog seeds with.

An ``LLMOrg`` is who you call, not who built the model: OpenAI owns
gpt-4o-mini and also serves it, while LLM7.io serves it by proxy.
Which vendor serves which model is ``deployments``.
"""

from typing import Any

VENDORS: list[dict[str, Any]] = [
    {
        "name": "openai",
        "description": "OpenAI - Creator of GPT models and ChatGPT",
        "color": "#10A37F",
        "api_base": "https://api.openai.com/v1",
        "auth_method": "api-key",
    },
    {
        "name": "anthropic",
        "description": "Anthropic - Creator of Claude AI assistants",
        "color": "#D4A574",
        "api_base": "https://api.anthropic.com/v1",
        "auth_method": "api-key",
    },
    {
        "name": "google",
        "description": "Google AI - Creator of Gemini models",
        "color": "#4285F4",
        "api_base": "https://generativelanguage.googleapis.com",
        "auth_method": "api-key",
    },
    {
        "name": "groq",
        "description": "Groq - Ultra-fast LLM inference with custom LPU hardware",
        "color": "#F55036",
        "api_base": "https://api.groq.com/openai/v1",
        "auth_method": "api-key",
    },
    {
        "name": "mistral",
        "description": "Mistral AI - European AI company with efficient models",
        "color": "#FF7000",
        "api_base": "https://api.mistral.ai/v1",
        "auth_method": "api-key",
    },
    {
        "name": "cohere",
        "description": "Cohere - Enterprise-focused NLP and generation models",
        "color": "#39594D",
        "api_base": "https://api.cohere.ai/v1",
        "auth_method": "api-key",
    },
    {
        "name": "LLM7.io",
        "description": "LLM7.io public endpoints (free anonymous tier; LLM7_API_KEY unlocks premium models)",
        "color": "#00D4AA",
        "api_base": "https://api.llm7.io/v1",
        "auth_method": "none",
    },
    {
        "name": "Pollinations",
        "description": "Pollinations public endpoints (free anonymous tier, open-weight models)",
        "color": "#F59E0B",
        "api_base": "https://text.pollinations.ai/openai",
        "auth_method": "none",
    },
]
