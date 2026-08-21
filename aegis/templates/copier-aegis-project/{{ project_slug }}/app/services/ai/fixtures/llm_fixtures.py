"""LLM fixture data and loading functions.

Contains seed data for LLM vendors, models, deployments, and pricing (Dec 2024 rates).

Architecture:
- LLMVendor: API providers (OpenAI, Anthropic, LLM7.io, etc.)
- LargeLanguageModel: Unique models (gpt-4o-mini exists ONCE, owned by OpenAI)
- LLMDeployment: Which vendors offer which models (LLM7.io deploys
  gpt-4o-mini via proxy)
- LLMPrice: Per vendor-model pricing (OpenAI charges $0.15, LLM7.io charges $0.00)
"""

from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app.core.log import logger
from app.services.ai.models.llm import (
    LargeLanguageModel,
    LLMDeployment,
    LLMPrice,
    LLMVendor,
)

# =============================================================================
# Vendor Data (7 providers)
# =============================================================================

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

# =============================================================================
# Model Data (keyed by OWNER vendor - each model exists once)
# =============================================================================

MODELS: dict[str, list[dict[str, Any]]] = {
    "openai": [
        {
            "model_id": "gpt-4o",
            "title": "GPT-4o",
            "description": "OpenAI's most advanced multimodal model",
            "context_window": 128000,
            "streamable": True,
            "enabled": True,
            "color": "#10A37F",
            "family": "gpt-4",
        },
        {
            "model_id": "gpt-4o-mini",
            "title": "GPT-4o Mini",
            "description": "Affordable small model for fast, lightweight tasks",
            "context_window": 128000,
            "streamable": True,
            "enabled": True,
            "color": "#10A37F",
            "family": "gpt-4",
        },
        {
            "model_id": "gpt-4-turbo",
            "title": "GPT-4 Turbo",
            "description": "GPT-4 Turbo with vision capabilities",
            "context_window": 128000,
            "streamable": True,
            "enabled": True,
            "color": "#10A37F",
            "family": "gpt-4",
        },
        {
            "model_id": "o1-preview",
            "title": "o1 Preview",
            "description": "Reasoning model for complex tasks",
            "context_window": 128000,
            "streamable": False,
            "enabled": True,
            "color": "#10A37F",
            "family": "o1",
        },
        {
            "model_id": "o1-mini",
            "title": "o1 Mini",
            "description": "Smaller reasoning model, faster and cheaper",
            "context_window": 128000,
            "streamable": False,
            "enabled": True,
            "color": "#10A37F",
            "family": "o1",
        },
    ],
    "anthropic": [
        {
            "model_id": "claude-3-5-sonnet-20241022",
            "title": "Claude 3.5 Sonnet",
            "description": "Most intelligent Claude model, best for complex tasks",
            "context_window": 200000,
            "streamable": True,
            "enabled": True,
            "color": "#D4A574",
            "family": "claude-3.5",
        },
        {
            "model_id": "claude-3-5-haiku-20241022",
            "title": "Claude 3.5 Haiku",
            "description": "Fastest Claude model, great for quick responses",
            "context_window": 200000,
            "streamable": True,
            "enabled": True,
            "color": "#D4A574",
            "family": "claude-3.5",
        },
        {
            "model_id": "claude-3-opus-20240229",
            "title": "Claude 3 Opus",
            "description": "Powerful model for highly complex tasks",
            "context_window": 200000,
            "streamable": True,
            "enabled": True,
            "color": "#D4A574",
            "family": "claude-3",
        },
    ],
    "google": [
        {
            "model_id": "gemini-1.5-pro",
            "title": "Gemini 1.5 Pro",
            "description": "Google's most capable model with 2M context window",
            "context_window": 2097152,
            "streamable": True,
            "enabled": True,
            "color": "#4285F4",
            "family": "gemini-1.5",
        },
        {
            "model_id": "gemini-1.5-flash",
            "title": "Gemini 1.5 Flash",
            "description": "Fast and versatile multimodal model",
            "context_window": 1048576,
            "streamable": True,
            "enabled": True,
            "color": "#4285F4",
            "family": "gemini-1.5",
        },
        {
            "model_id": "gemini-2.0-flash-exp",
            "title": "Gemini 2.0 Flash (Experimental)",
            "description": "Next-gen features with low latency",
            "context_window": 1048576,
            "streamable": True,
            "enabled": True,
            "color": "#4285F4",
            "family": "gemini-2.0",
        },
    ],
    "groq": [
        {
            "model_id": "llama-3.3-70b-versatile",
            "title": "Llama 3.3 70B Versatile",
            "description": "Meta's latest Llama model on Groq's fast infrastructure",
            "context_window": 128000,
            "streamable": True,
            "enabled": True,
            "color": "#F55036",
            "family": "llama-3.3",
        },
        {
            "model_id": "llama-3.1-8b-instant",
            "title": "Llama 3.1 8B Instant",
            "description": "Ultra-fast smaller Llama model",
            "context_window": 128000,
            "streamable": True,
            "enabled": True,
            "color": "#F55036",
            "family": "llama-3.1",
        },
        {
            "model_id": "mixtral-8x7b-32768",
            "title": "Mixtral 8x7B",
            "description": "Mistral's mixture-of-experts model on Groq",
            "context_window": 32768,
            "streamable": True,
            "enabled": True,
            "color": "#F55036",
            "family": "mixtral",
        },
    ],
    "mistral": [
        {
            "model_id": "mistral-large-latest",
            "title": "Mistral Large",
            "description": "Mistral's flagship model for complex tasks",
            "context_window": 128000,
            "streamable": True,
            "enabled": True,
            "color": "#FF7000",
            "family": "mistral-large",
        },
        {
            "model_id": "mistral-small-latest",
            "title": "Mistral Small",
            "description": "Cost-efficient model for simple tasks",
            "context_window": 32000,
            "streamable": True,
            "enabled": True,
            "color": "#FF7000",
            "family": "mistral-small",
        },
        {
            "model_id": "codestral-latest",
            "title": "Codestral",
            "description": "Specialized model for code generation",
            "context_window": 32000,
            "streamable": True,
            "enabled": True,
            "color": "#FF7000",
            "family": "codestral",
        },
    ],
    "cohere": [
        {
            "model_id": "command-r-plus",
            "title": "Command R+",
            "description": "Cohere's most powerful model for enterprise RAG",
            "context_window": 128000,
            "streamable": True,
            "enabled": True,
            "color": "#39594D",
            "family": "command-r",
        },
        {
            "model_id": "command-r",
            "title": "Command R",
            "description": "Balanced model for RAG and tool use",
            "context_window": 128000,
            "streamable": True,
            "enabled": True,
            "color": "#39594D",
            "family": "command-r",
        },
        {
            "model_id": "command-light",
            "title": "Command Light",
            "description": "Lightweight model for simple tasks",
            "context_window": 4096,
            "streamable": True,
            "enabled": True,
            "color": "#39594D",
            "family": "command",
        },
    ],
    # LLM7.io's "auto" model - represents dynamic model selection
    "LLM7.io": [
        {
            "model_id": "auto",
            "title": "Auto (LLM7.io)",
            "description": "Automatic model selection via LLM7.io public endpoint",
            "context_window": 128000,
            "streamable": False,
            "enabled": True,
            "color": "#6B7280",
            "family": "auto",
        },
    ],
    # Pollinations' anonymous-tier open-weight model
    "Pollinations": [
        {
            "model_id": "openai-fast",
            "title": "GPT-OSS 20B (Pollinations)",
            "description": "Open-weight reasoning model via Pollinations anonymous tier",
            "context_window": 128000,
            "streamable": False,
            "enabled": True,
            "color": "#F59E0B",
            "family": "gpt-oss",
        },
    ],
}

# =============================================================================
# Deployment Data (which vendors offer which models)
# Format: {vendor_name: [list of model_ids they deploy]}
# =============================================================================

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

# =============================================================================
# Pricing Data (Dec 2024 rates - cost per 1M tokens)
# Format: {(vendor_name, model_id): {"input": X, "output": Y}}
# =============================================================================

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


# =============================================================================
# Loading Functions
# =============================================================================


def _load_vendors(session: Session) -> int:
    """Load vendor fixtures, skipping existing."""
    count = 0
    for vendor_data in VENDORS:
        existing = session.exec(
            select(LLMVendor).where(LLMVendor.name == vendor_data["name"])
        ).first()
        if not existing:
            vendor = LLMVendor(**vendor_data)
            session.add(vendor)
            count += 1
            logger.debug(f"Added vendor: {vendor_data['name']}")
    session.commit()
    return count


def _load_models(session: Session) -> int:
    """Load model fixtures, skipping existing."""
    count = 0

    # Get vendor ID mapping
    vendors = session.exec(select(LLMVendor)).all()
    vendor_map = {v.name: v.id for v in vendors}

    for vendor_name, models in MODELS.items():
        vendor_id = vendor_map.get(vendor_name)
        if not vendor_id:
            logger.warning(f"Vendor not found for models: {vendor_name}")
            continue

        for model_data in models:
            existing = session.exec(
                select(LargeLanguageModel).where(
                    LargeLanguageModel.model_id == model_data["model_id"]
                )
            ).first()

            if not existing:
                model = LargeLanguageModel(
                    llm_vendor_id=vendor_id,
                    **model_data,
                )
                session.add(model)
                count += 1
                logger.debug(f"Added model: {model_data['model_id']}")

    session.commit()
    return count


def _load_deployments(session: Session) -> int:
    """Load deployment fixtures, skipping existing."""
    count = 0

    # Get vendor and model mappings
    vendors = session.exec(select(LLMVendor)).all()
    vendor_map = {v.name: v.id for v in vendors}

    models = session.exec(select(LargeLanguageModel)).all()
    model_map = {m.model_id: m.id for m in models}

    for vendor_name, deployments in DEPLOYMENTS.items():
        vendor_id = vendor_map.get(vendor_name)
        if not vendor_id:
            logger.warning(f"Vendor not found for deployments: {vendor_name}")
            continue

        for deployment_data in deployments:
            model_id = model_map.get(deployment_data["model_id"])
            if not model_id:
                logger.warning(
                    f"Model not found for deployment: {deployment_data['model_id']}"
                )
                continue

            # Check if deployment already exists
            existing = session.exec(
                select(LLMDeployment).where(
                    LLMDeployment.llm_vendor_id == vendor_id,
                    LLMDeployment.llm_id == model_id,
                )
            ).first()

            if not existing:
                deployment = LLMDeployment(
                    llm_vendor_id=vendor_id,
                    llm_id=model_id,
                    speed=deployment_data.get("speed", 50),
                    intelligence=deployment_data.get("intelligence", 50),
                    reasoning=deployment_data.get("reasoning", 50),
                )
                session.add(deployment)
                count += 1
                logger.debug(
                    f"Added deployment: {vendor_name} -> {deployment_data['model_id']}"
                )

    session.commit()
    return count


def _load_prices(session: Session) -> int:
    """Load price fixtures, skipping existing."""
    count = 0
    effective_date = datetime.now(UTC)

    # Get vendor and model mappings
    vendors = session.exec(select(LLMVendor)).all()
    vendor_map = {v.name: v.id for v in vendors}

    models = session.exec(select(LargeLanguageModel)).all()
    model_map = {m.model_id: m.id for m in models}

    for (vendor_name, model_id), price_data in PRICES.items():
        vendor_id = vendor_map.get(vendor_name)
        llm_id = model_map.get(model_id)

        if not vendor_id:
            logger.warning(f"Vendor not found for price: {vendor_name}")
            continue
        if not llm_id:
            logger.warning(f"Model not found for price: {model_id}")
            continue

        # Check if price already exists for this vendor-model pair
        existing = session.exec(
            select(LLMPrice).where(
                LLMPrice.llm_vendor_id == vendor_id,
                LLMPrice.llm_id == llm_id,
            )
        ).first()

        if not existing:
            # Convert from per-1M-tokens to per-token
            price = LLMPrice(
                llm_vendor_id=vendor_id,
                llm_id=llm_id,
                input_cost_per_token=price_data["input"] / 1_000_000,
                output_cost_per_token=price_data["output"] / 1_000_000,
                effective_date=effective_date,
            )
            session.add(price)
            count += 1
            logger.debug(f"Added price: {vendor_name} + {model_id}")

    session.commit()
    return count


def load_all_llm_fixtures(session: Session) -> dict[str, int]:
    """Load all LLM fixtures in correct order.

    Loading order matters due to foreign key dependencies:
    1. Vendors (no dependencies)
    2. Models (depends on vendors for ownership)
    3. Deployments (depends on vendors and models)
    4. Prices (depends on vendors and models)

    Skips any records that already exist (duplicate detection).

    Args:
        session: Database session

    Returns:
        dict with counts: {"vendors": N, "models": N, "deployments": N, "prices": N}
    """
    logger.info("Loading LLM fixtures...")

    vendors_added = _load_vendors(session)
    models_added = _load_models(session)
    deployments_added = _load_deployments(session)
    prices_added = _load_prices(session)

    result = {
        "vendors": vendors_added,
        "models": models_added,
        "deployments": deployments_added,
        "prices": prices_added,
    }

    logger.info(
        f"LLM fixtures loaded: {vendors_added} vendors, {models_added} models, "
        f"{deployments_added} deployments, {prices_added} prices"
    )

    return result
