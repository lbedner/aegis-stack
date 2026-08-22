"""
OpenRouter API client for fetching LLM model data.

OpenRouter provides a unified API for accessing multiple LLM providers
with rich model metadata including descriptions and architecture info.
"""

from dataclasses import dataclass, field

import httpx
from app.core.log import logger


@dataclass
class OpenRouterModel:
    """Parsed model data from OpenRouter API."""

    model_id: str
    name: str
    description: str
    context_length: int
    max_completion_tokens: int | None
    input_modalities: list[str]
    output_modalities: list[str]
    tokenizer: str | None
    input_cost_per_token: float
    output_cost_per_token: float
    cache_read_cost_per_token: float | None
    cache_write_cost_per_token: float | None
    is_moderated: bool
    created: int | None = None  # Unix timestamp of when model was added (optional)


class OpenRouterClient:
    """Client for fetching model data from OpenRouter API."""

    BASE_URL = "https://openrouter.ai/api/v1/models"
    TIMEOUT = 30.0

    async def fetch_models(self) -> list[OpenRouterModel]:
        """Fetch all models from OpenRouter API.

        Returns:
            List of parsed OpenRouterModel objects.

        Raises:
            httpx.HTTPError: If the API request fails.
        """
        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            response = await client.get(self.BASE_URL)
            response.raise_for_status()
            data = response.json()

        models: list[OpenRouterModel] = []
        raw_models = data.get("data", [])
        logger.info(f"Fetched {len(raw_models)} models from OpenRouter")

        for raw in raw_models:
            try:
                model = self._parse_model(raw)
                models.append(model)
            except (KeyError, ValueError, TypeError) as e:
                model_id = raw.get("id", "unknown")
                logger.warning(f"Failed to parse OpenRouter model {model_id}: {e}")
                continue

        return models

    def _parse_model(self, raw: dict) -> OpenRouterModel:
        """Parse raw API response into OpenRouterModel.

        Args:
            raw: Raw model data from API response.

        Returns:
            Parsed OpenRouterModel object.
        """
        # Extract pricing (stored as string or float, cost per token)
        pricing = raw.get("pricing", {})
        input_cost = self._parse_price(pricing.get("prompt", "0"))
        output_cost = self._parse_price(pricing.get("completion", "0"))
        cache_read = self._parse_price(pricing.get("input_cache_read"))
        cache_write = self._parse_price(pricing.get("input_cache_write"))

        # Extract architecture info
        architecture = raw.get("architecture", {})
        input_modalities = architecture.get("input_modalities", ["text"])
        output_modalities = architecture.get("output_modalities", ["text"])
        tokenizer = architecture.get("tokenizer")

        # Extract top provider info
        top_provider = raw.get("top_provider", {})
        max_completion = top_provider.get("max_completion_tokens")
        is_moderated = top_provider.get("is_moderated", False)

        return OpenRouterModel(
            model_id=raw["id"],
            name=raw.get("name", raw["id"]),
            description=raw.get("description", ""),
            context_length=raw.get("context_length", 4096),
            max_completion_tokens=max_completion,
            input_modalities=input_modalities,
            output_modalities=output_modalities,
            tokenizer=tokenizer,
            input_cost_per_token=input_cost,
            output_cost_per_token=output_cost,
            cache_read_cost_per_token=cache_read,
            cache_write_cost_per_token=cache_write,
            is_moderated=is_moderated,
            created=raw.get("created"),
        )

    def _parse_price(self, value: str | float | None) -> float | None:
        """Parse price value from API (may be string or float).

        Args:
            value: Price value from API.

        Returns:
            Parsed float price or None if not available.
        """
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None


@dataclass
class OpenRouterModelIndex:
    """Index of OpenRouter models for fast lookup by model ID."""

    models: dict[str, OpenRouterModel] = field(default_factory=dict)

    @classmethod
    def from_models(cls, models: list[OpenRouterModel]) -> "OpenRouterModelIndex":
        """Create index from list of models.

        Args:
            models: List of OpenRouterModel objects.

        Returns:
            OpenRouterModelIndex with models indexed by ID.
        """
        index = cls()
        for model in models:
            # Index by full ID (e.g., "openai/gpt-4o")
            index.models[model.model_id] = model
            # Also index by short ID if it has a prefix
            if "/" in model.model_id:
                short_id = model.model_id.split("/", 1)[1]
                # Don't overwrite if short ID already exists
                if short_id not in index.models:
                    index.models[short_id] = model
        return index

    def get(self, model_id: str) -> OpenRouterModel | None:
        """Get model by ID (supports both full and short IDs).

        Args:
            model_id: Model ID to look up.

        Returns:
            OpenRouterModel if found, None otherwise.
        """
        return self.models.get(model_id)
