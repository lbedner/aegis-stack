"""Vendor presentation facts for the catalog sync.

Declaration data (descriptions, brand colors, API bases) kept out of the
sync logic module: a table nobody reads top-to-bottom, edited whenever a
vendor is added.
"""

# Default vendor metadata for known vendors
VENDOR_METADATA: dict[str, dict[str, str]] = {
    "openai": {
        "description": "OpenAI - Creator of GPT models and ChatGPT",
        "color": "#10A37F",
        "api_base": "https://api.openai.com/v1",
    },
    "anthropic": {
        "description": "Anthropic - Creator of Claude AI assistants",
        "color": "#D4A574",
        "api_base": "https://api.anthropic.com/v1",
    },
    "google": {
        "description": "Google AI - Creator of Gemini models",
        "color": "#4285F4",
        "api_base": "https://generativelanguage.googleapis.com",
    },
    "groq": {
        "description": "Groq - Ultra-fast LLM inference with custom LPU hardware",
        "color": "#F55036",
        "api_base": "https://api.groq.com/openai/v1",
    },
    "mistral": {
        "description": "Mistral AI - European AI company with efficient models",
        "color": "#FF7000",
        "api_base": "https://api.mistral.ai/v1",
    },
    "cohere": {
        "description": "Cohere - Enterprise-focused NLP and generation models",
        "color": "#39594D",
        "api_base": "https://api.cohere.ai/v1",
    },
    "together": {
        "description": "Together AI - Open-source model hosting platform",
        "color": "#6366F1",
        "api_base": "https://api.together.xyz/v1",
    },
    "fireworks": {
        "description": "Fireworks AI - Fast inference for open-source models",
        "color": "#FF6B35",
        "api_base": "https://api.fireworks.ai/inference/v1",
    },
    "deepinfra": {
        "description": "DeepInfra - Serverless AI inference platform",
        "color": "#7C3AED",
        "api_base": "https://api.deepinfra.com/v1/openai",
    },
    "perplexity": {
        "description": "Perplexity - AI-powered search and conversational models",
        "color": "#20808D",
        "api_base": "https://api.perplexity.ai",
    },
    "azure": {
        "description": "Azure OpenAI Service - Microsoft's hosted OpenAI models",
        "color": "#0078D4",
        "api_base": "",
    },
    "aws": {
        "description": "AWS Bedrock - Amazon's managed AI model service",
        "color": "#FF9900",
        "api_base": "",
    },
    "meta": {
        "description": "Meta AI - Creator of Llama open-source models",
        "color": "#0668E1",
        "api_base": "",
    },
    "xai": {
        "description": "xAI - Creator of Grok models",
        "color": "#1DA1F2",
        "api_base": "https://api.x.ai/v1",
    },
    "ollama": {
        "description": "Ollama - Run LLMs locally",
        "color": "#FFFFFF",
        "api_base": "http://localhost:11434/v1",
        "auth_method": "none",
    },
}
