"""Per vendor-model pricing, in cost per 1M tokens.

Keyed by ``(vendor, model_id)`` because price is a property of the
deployment, not the model: OpenAI charges for gpt-4o-mini and LLM7.io
gives it away.

Rates are as of Dec 2024. Voice rates (``VOICE_PRICE_FIELDS``) are
given as the source catalog gives them, per unit, not per 1M; a model
lists only the measures it bills by. As of Sep 2026.
"""

PRICES: dict[tuple[str, str], dict[str, float]] = {
    # Google voice (Sep 2026)
    ("google", "gemini-3.8-live"): {
        "input": 0.75,
        "output": 4.50,
        "input_cost_per_audio_token": 3 / 1_000_000,
        "output_cost_per_audio_token": 12 / 1_000_000,
    },
    # OpenAI voice (Sep 2026)
    ("openai", "gpt-live-1"): {
        "input": 0,
        "output": 0,
        "input_cost_per_second": 0.05 / 60,
    },
    ("openai", "gpt-realtime-2.1"): {
        "input": 4.00,
        "output": 24.00,
        "cache": 0.40,
        "input_cost_per_audio_token": 32 / 1_000_000,
        "output_cost_per_audio_token": 64 / 1_000_000,
    },
    ("openai", "gpt-realtime-2.1-mini"): {
        "input": 0.60,
        "output": 2.40,
        "cache": 0.06,
        "input_cost_per_audio_token": 10 / 1_000_000,
        "output_cost_per_audio_token": 20 / 1_000_000,
    },
    ("openai", "gpt-transcribe"): {
        "input": 0,
        "output": 0,
        "input_cost_per_second": 0.0045 / 60,
    },
    ("openai", "gpt-4o-transcribe"): {
        "input": 2.50,
        "output": 10.00,
        "input_cost_per_second": 0.006 / 60,
    },
    ("openai", "gpt-4o-mini-transcribe"): {
        "input": 1.25,
        "output": 5.00,
        "input_cost_per_second": 0.003 / 60,
    },
    ("openai", "whisper-1"): {
        "input": 0,
        "output": 0,
        "input_cost_per_second": 0.006 / 60,
    },
    ("openai", "tts-1"): {
        "input": 0,
        "output": 0,
        "input_cost_per_character": 15 / 1_000_000,
    },
    ("openai", "tts-1-hd"): {
        "input": 0,
        "output": 0,
        "input_cost_per_character": 30 / 1_000_000,
    },
    ("openai", "gpt-4o-mini-tts"): {
        "input": 0.60,
        "output": 10.00,
        "output_cost_per_second": 0.015 / 60,
    },
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
