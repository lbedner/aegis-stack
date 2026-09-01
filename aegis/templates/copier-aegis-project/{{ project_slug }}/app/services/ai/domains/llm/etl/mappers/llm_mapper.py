"""
Data mapper for merging LLM model data from multiple sources.

Combines data from LiteLLM (primary catalog) and OpenRouter (enrichment)
into a unified format for database insertion.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.core.log import logger
from app.services.ai.domains.llm.etl.clients.litellm_client import LiteLLMModel
from app.services.ai.domains.llm.etl.clients.openrouter_client import (
    OpenRouterModel,
    OpenRouterModelIndex,
)


@dataclass
class MergedLLMData:
    """Unified LLM model data merged from multiple sources."""

    model_id: str
    vendor: str
    title: str
    description: str
    context_window: int
    max_output_tokens: int | None
    input_cost_per_token: float
    output_cost_per_token: float
    cache_read_cost_per_token: float | None
    input_modalities: list[str] = field(default_factory=lambda: ["text"])
    output_modalities: list[str] = field(default_factory=lambda: ["text"])
    supports_function_calling: bool = False
    supports_structured_output: bool = False
    supports_vision: bool = False
    supports_audio_input: bool = False
    supports_audio_output: bool = False
    supports_reasoning: bool = False
    supports_prompt_caching: bool = False
    streamable: bool = True
    mode: str = "chat"
    family: str | None = None
    deprecation_date: str | None = None
    created_at: datetime | None = None  # When model was released/added


# Vendor name normalization mapping
VENDOR_ALIASES: dict[str, str] = {
    "openai": "openai",
    "azure": "azure",
    "azure_ai": "azure",
    "anthropic": "anthropic",
    "google": "google",
    "vertex_ai": "google",
    "vertex_ai_beta": "google",
    "gemini": "google",
    "groq": "groq",
    "mistral": "mistral",
    "cohere": "cohere",
    "cohere_chat": "cohere",
    "together_ai": "together",
    "together": "together",
    "anyscale": "anyscale",
    "fireworks_ai": "fireworks",
    "fireworks": "fireworks",
    "deepinfra": "deepinfra",
    "perplexity": "perplexity",
    "replicate": "replicate",
    "huggingface": "huggingface",
    "ollama": "ollama",
    "ollama_chat": "ollama",
    "bedrock": "aws",
    "sagemaker": "aws",
    "ai21": "ai21",
    "nlp_cloud": "nlp_cloud",
    "aleph_alpha": "aleph_alpha",
    "palm": "google",
    "xai": "xai",
    "cerebras": "cerebras",
    "sambanova": "sambanova",
    "databricks": "databricks",
    "cloudflare": "cloudflare",
    "voyage": "voyage",
    "jina_ai": "jina",
    "text-embedding-inference": "huggingface",
}


def extract_vendor(model_id: str, provider_hint: str | None = None) -> str:
    """Extract normalized vendor name from model ID or provider hint.

    Args:
        model_id: The model identifier (e.g., "openai/gpt-4o").
        provider_hint: Optional provider name from API response.

    Returns:
        Normalized vendor name.
    """
    # Try provider hint first
    if provider_hint:
        normalized = provider_hint.lower().replace("-", "_")
        if normalized in VENDOR_ALIASES:
            return VENDOR_ALIASES[normalized]

    # Extract from model_id prefix
    if "/" in model_id:
        prefix = model_id.split("/")[0].lower().replace("-", "_")
        if prefix in VENDOR_ALIASES:
            return VENDOR_ALIASES[prefix]
        return prefix

    # Fallback heuristics for models without prefix
    model_lower = model_id.lower()

    if model_lower.startswith(("gpt-", "o1", "o3", "text-embedding", "dall-e")):
        return "openai"
    if model_lower.startswith("claude"):
        return "anthropic"
    if model_lower.startswith(("gemini", "palm")):
        return "google"
    if model_lower.startswith(("llama", "codellama")):
        return "meta"
    if model_lower.startswith("mistral"):
        return "mistral"
    if model_lower.startswith("mixtral"):
        return "mistral"
    if model_lower.startswith("command"):
        return "cohere"

    return "unknown"


# Vendors the CLOUD catalog describes but this install cannot answer
# from it. LiteLLM lists ``ollama/...`` as a RUNNER prefix - models you
# could pull - not as a callable vendor; the local sync owns that
# vendor's rows, and only what the local server actually serves belongs
# in a picker that promises callable models. (It also carries Ollama
# Cloud's ``-cloud`` variants, which need a key this install has no
# concept of.)
_LOCAL_ONLY_VENDORS = frozenset({"ollama"})


def is_cloud_syncable(model_id: str, provider_hint: str | None = None) -> bool:
    """Whether a cloud-catalog row belongs in the catalog at all."""
    return extract_vendor(model_id, provider_hint) not in _LOCAL_ONLY_VENDORS


def extract_family(model_id: str) -> str | None:
    """Extract model family from model ID.

    Args:
        model_id: The model identifier.

    Returns:
        Model family name or None.
    """
    # Remove vendor prefix if present
    name = model_id.split("/")[-1].lower()

    # Common family patterns
    if name.startswith("gpt-4o"):
        return "gpt-4o"
    if name.startswith("gpt-4"):
        return "gpt-4"
    if name.startswith("gpt-3.5"):
        return "gpt-3.5"
    if name.startswith("o1"):
        return "o1"
    if name.startswith("o3"):
        return "o3"
    if name.startswith("claude-3.5") or name.startswith("claude-3-5"):
        return "claude-3.5"
    if name.startswith("claude-3"):
        return "claude-3"
    if name.startswith("gemini-2"):
        return "gemini-2"
    if name.startswith("gemini-1.5"):
        return "gemini-1.5"
    if name.startswith("llama-3.3"):
        return "llama-3.3"
    if name.startswith("llama-3.2"):
        return "llama-3.2"
    if name.startswith("llama-3.1"):
        return "llama-3.1"
    if name.startswith("llama-3"):
        return "llama-3"
    if name.startswith("mistral-large"):
        return "mistral-large"
    if name.startswith("mistral-small"):
        return "mistral-small"
    if name.startswith("mixtral"):
        return "mixtral"
    if name.startswith("command-r"):
        return "command-r"

    return None


def _generate_title(model_id: str) -> str:
    """Generate a human-readable title from model ID.

    Args:
        model_id: The model identifier.

    Returns:
        Human-readable title.
    """
    # Remove vendor prefix
    name = model_id.split("/")[-1]

    # Capitalize and clean up
    parts = name.replace("-", " ").replace("_", " ").split()
    title_parts = []

    for part in parts:
        # Handle version numbers and common abbreviations
        if part.isdigit() or part.replace(".", "").isdigit():
            title_parts.append(part)
        elif part.lower() in ("ai", "llm", "xl", "xxl"):
            title_parts.append(part.upper())
        else:
            title_parts.append(part.capitalize())

    return " ".join(title_parts)


def _modalities_from_litellm(model: LiteLLMModel) -> tuple[list[str], list[str]]:
    """Extract modalities from LiteLLM capability flags.

    Args:
        model: LiteLLM model data.

    Returns:
        Tuple of (input_modalities, output_modalities).
    """
    input_mods = ["text"]
    output_mods = ["text"]

    if model.supports_vision:
        input_mods.append("image")
    if model.supports_audio_input:
        input_mods.append("audio")
    if model.supports_audio_output:
        output_mods.append("audio")

    # Image generation models
    if model.mode == "image_generation":
        output_mods = ["image"]

    return input_mods, output_mods


def merge_single_model(
    litellm_model: LiteLLMModel,
    openrouter_model: OpenRouterModel | None = None,
) -> MergedLLMData:
    """Merge data from LiteLLM and OpenRouter for a single model.

    LiteLLM is the primary source, OpenRouter provides enrichment.

    Args:
        litellm_model: Required LiteLLM model data.
        openrouter_model: Optional OpenRouter model data for enrichment.

    Returns:
        Merged model data.
    """
    model_id = litellm_model.model_id
    vendor = extract_vendor(model_id, litellm_model.provider)

    # Use OpenRouter for rich descriptions and titles if available
    if openrouter_model:
        title = openrouter_model.name or _generate_title(model_id)
        description = openrouter_model.description or ""
        context_window = openrouter_model.context_length
        max_output = openrouter_model.max_completion_tokens
        input_modalities = openrouter_model.input_modalities
        output_modalities = openrouter_model.output_modalities
        cache_read_cost = openrouter_model.cache_read_cost_per_token
        # Convert Unix timestamp to datetime
        created_at = (
            datetime.fromtimestamp(openrouter_model.created, tz=UTC)
            if openrouter_model.created
            else None
        )
    else:
        title = _generate_title(model_id)
        description = ""
        context_window = litellm_model.max_tokens
        max_output = litellm_model.max_output_tokens
        input_modalities, output_modalities = _modalities_from_litellm(litellm_model)
        cache_read_cost = None
        created_at = None

    return MergedLLMData(
        model_id=model_id,
        vendor=vendor,
        title=title,
        description=description,
        context_window=context_window,
        max_output_tokens=max_output,
        input_cost_per_token=litellm_model.input_cost_per_token,
        output_cost_per_token=litellm_model.output_cost_per_token,
        cache_read_cost_per_token=cache_read_cost,
        input_modalities=input_modalities,
        output_modalities=output_modalities,
        supports_function_calling=litellm_model.supports_function_calling,
        supports_structured_output=litellm_model.supports_response_schema,
        supports_vision=litellm_model.supports_vision,
        supports_audio_input=litellm_model.supports_audio_input,
        supports_audio_output=litellm_model.supports_audio_output,
        supports_reasoning=litellm_model.supports_reasoning,
        supports_prompt_caching=litellm_model.supports_prompt_caching,
        streamable=litellm_model.mode == "chat",
        mode=litellm_model.mode,
        family=extract_family(model_id),
        deprecation_date=litellm_model.deprecation_date,
        created_at=created_at,
    )


def merge_model_data(
    litellm_models: dict[str, LiteLLMModel],
    openrouter_index: OpenRouterModelIndex,
) -> list[MergedLLMData]:
    """Merge model data from LiteLLM and OpenRouter.

    LiteLLM is the primary source (more models). OpenRouter data
    is used for enrichment (descriptions, architecture info).

    Args:
        litellm_models: Dictionary of model_id -> LiteLLMModel.
        openrouter_index: Index of OpenRouter models for lookup.

    Returns:
        List of merged model data.
    """
    merged: list[MergedLLMData] = []
    enriched_count = 0

    for model_id, litellm_model in litellm_models.items():
        # Try to find matching OpenRouter model
        openrouter_model = openrouter_index.get(model_id)
        if openrouter_model:
            enriched_count += 1

        try:
            merged_data = merge_single_model(litellm_model, openrouter_model)
            merged.append(merged_data)
        except Exception as e:
            logger.warning(f"Failed to merge model {model_id}: {e}")
            continue

    logger.info(
        f"Merged {len(merged)} models, {enriched_count} enriched with OpenRouter data"
    )
    return merged
