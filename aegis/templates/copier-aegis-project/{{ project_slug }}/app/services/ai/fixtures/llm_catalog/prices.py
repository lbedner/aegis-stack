"""Per vendor-model pricing, in cost per 1M tokens.

Keyed by ``(vendor, model_id)`` because price is a property of the
deployment, not the model: OpenAI charges for gpt-4o-mini and LLM7.io
gives it away.

Rates are as of Dec 2024.
"""

PRICES: dict[tuple[str, str], dict[str, float]] = {
    # OpenAI pricing (Dec 2024)
    ("openai", "gpt-4o"): {"input": 2.50, "output": 10.00},
    ("openai", "gpt-4o-mini"): {"input": 0.15, "output": 0.60},
    ("openai", "gpt-4-turbo"): {"input": 10.00, "output": 30.00},
    ("openai", "o1-preview"): {"input": 15.00, "output": 60.00},
    ("openai", "o1-mini"): {"input": 3.00, "output": 12.00},
    # Anthropic pricing (Dec 2024)
    ("anthropic", "claude-3-5-sonnet-20241022"): {"input": 3.00, "output": 15.00},
    ("anthropic", "claude-3-5-haiku-20241022"): {"input": 0.80, "output": 4.00},
    ("anthropic", "claude-3-opus-20240229"): {"input": 15.00, "output": 75.00},
    # Google pricing (Dec 2024)
    ("google", "gemini-1.5-pro"): {"input": 1.25, "output": 5.00},
    ("google", "gemini-1.5-flash"): {"input": 0.075, "output": 0.30},
    ("google", "gemini-2.0-flash-exp"): {"input": 0.00, "output": 0.00},  # Free preview
    # Groq pricing (Dec 2024) - very competitive
    ("groq", "llama-3.3-70b-versatile"): {"input": 0.59, "output": 0.79},
    ("groq", "llama-3.1-8b-instant"): {"input": 0.05, "output": 0.08},
    ("groq", "mixtral-8x7b-32768"): {"input": 0.24, "output": 0.24},
    # Mistral pricing (Dec 2024)
    ("mistral", "mistral-large-latest"): {"input": 2.00, "output": 6.00},
    ("mistral", "mistral-small-latest"): {"input": 0.20, "output": 0.60},
    ("mistral", "codestral-latest"): {"input": 0.20, "output": 0.60},
    # Cohere pricing (Dec 2024)
    ("cohere", "command-r-plus"): {"input": 2.50, "output": 10.00},
    ("cohere", "command-r"): {"input": 0.15, "output": 0.60},
    ("cohere", "command-light"): {"input": 0.03, "output": 0.06},
    # LLM7.io pricing (free)
    ("LLM7.io", "gpt-4o-mini"): {"input": 0.00, "output": 0.00},
    ("LLM7.io", "auto"): {"input": 0.00, "output": 0.00},
    # Pollinations pricing (free anonymous tier)
    ("Pollinations", "openai-fast"): {"input": 0.00, "output": 0.00},
}
