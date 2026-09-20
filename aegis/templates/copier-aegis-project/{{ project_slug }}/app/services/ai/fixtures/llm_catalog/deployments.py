"""Which vendors serve which models.

The many-to-many between ``vendors`` and ``models``, plus the per-vendor
speed / intelligence / reasoning scores, since the same model can behave
differently depending on who is serving it.
"""

from typing import Any

DEPLOYMENTS: dict[str, list[dict[str, Any]]] = {
    # OpenAI deploys their own models
    "openai": [
        {"model_id": "gpt-4o", "speed": 70, "intelligence": 90, "reasoning": 85},
        {"model_id": "gpt-4o-mini", "speed": 85, "intelligence": 75, "reasoning": 70},
        {"model_id": "gpt-4-turbo", "speed": 60, "intelligence": 88, "reasoning": 82},
        {"model_id": "o1-preview", "speed": 30, "intelligence": 95, "reasoning": 98},
        {"model_id": "o1-mini", "speed": 50, "intelligence": 85, "reasoning": 90},
    ],
    # Anthropic deploys their own models
    "anthropic": [
        {
            "model_id": "claude-3-5-sonnet-20241022",
            "speed": 75,
            "intelligence": 92,
            "reasoning": 90,
        },
        {
            "model_id": "claude-3-5-haiku-20241022",
            "speed": 95,
            "intelligence": 70,
            "reasoning": 65,
        },
        {
            "model_id": "claude-3-opus-20240229",
            "speed": 40,
            "intelligence": 95,
            "reasoning": 92,
        },
    ],
    # Google deploys their own models
    "google": [
        {
            "model_id": "gemini-1.5-pro",
            "speed": 65,
            "intelligence": 88,
            "reasoning": 85,
        },
        {
            "model_id": "gemini-1.5-flash",
            "speed": 90,
            "intelligence": 75,
            "reasoning": 70,
        },
        {
            "model_id": "gemini-2.0-flash-exp",
            "speed": 92,
            "intelligence": 80,
            "reasoning": 75,
        },
    ],
    # Groq deploys open-source models with fast inference
    "groq": [
        {
            "model_id": "llama-3.3-70b-versatile",
            "speed": 95,
            "intelligence": 82,
            "reasoning": 80,
        },
        {
            "model_id": "llama-3.1-8b-instant",
            "speed": 99,
            "intelligence": 60,
            "reasoning": 55,
        },
        {
            "model_id": "mixtral-8x7b-32768",
            "speed": 95,
            "intelligence": 75,
            "reasoning": 72,
        },
    ],
    # Mistral deploys their own models
    "mistral": [
        {
            "model_id": "mistral-large-latest",
            "speed": 60,
            "intelligence": 85,
            "reasoning": 82,
        },
        {
            "model_id": "mistral-small-latest",
            "speed": 85,
            "intelligence": 70,
            "reasoning": 65,
        },
        {
            "model_id": "codestral-latest",
            "speed": 80,
            "intelligence": 78,
            "reasoning": 75,
        },
    ],
    # Cohere deploys their own models
    "cohere": [
        {
            "model_id": "command-r-plus",
            "speed": 55,
            "intelligence": 82,
            "reasoning": 80,
        },
        {"model_id": "command-r", "speed": 75, "intelligence": 75, "reasoning": 72},
        {"model_id": "command-light", "speed": 90, "intelligence": 55, "reasoning": 50},
    ],
    # LLM7.io deploys models via proxy (free but slower, no streaming)
    "LLM7.io": [
        {"model_id": "gpt-4o-mini", "speed": 40, "intelligence": 75, "reasoning": 70},
        {"model_id": "auto", "speed": 40, "intelligence": 75, "reasoning": 70},
    ],
    "Pollinations": [
        {"model_id": "openai-fast", "speed": 55, "intelligence": 65, "reasoning": 75},
    ],
}
