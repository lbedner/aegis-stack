"""
LiteLLM model cost map client.

LiteLLM maintains a comprehensive JSON file with pricing and capabilities
for 2000+ models across all major providers.
"""

from dataclasses import dataclass, field

import httpx
from app.core.log import logger


@dataclass
class LiteLLMModel:
    """Parsed model data from LiteLLM model cost map."""

    model_id: str
    provider: str
    mode: str  # chat, embedding, completion, image_generation, etc.
    max_tokens: int
    max_input_tokens: int | None
    max_output_tokens: int | None
    input_cost_per_token: float
    output_cost_per_token: float
    supports_function_calling: bool
    supports_parallel_function_calling: bool
    supports_vision: bool
    supports_audio_input: bool
    supports_audio_output: bool
    supports_reasoning: bool
    supports_response_schema: bool
    supports_system_messages: bool
    supports_prompt_caching: bool
    deprecation_date: str | None


class LiteLLMClient:
    """Client for fetching model data from LiteLLM's GitHub repository."""

    JSON_URL = (
        "https://raw.githubusercontent.com/BerriAI/litellm/main/"
        "model_prices_and_context_window.json"
    )
    TIMEOUT = 60.0  # Larger file, needs more time

    async def fetch_models(self) -> dict[str, LiteLLMModel]:
        """Fetch all models from LiteLLM model cost map.

        Returns:
            Dictionary of model_id -> LiteLLMModel.

        Raises:
            httpx.HTTPError: If the request fails.
        """
        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            response = await client.get(self.JSON_URL)
            response.raise_for_status()
            data = response.json()

        models: dict[str, LiteLLMModel] = {}

        # Skip the sample_spec entry
        entries = {k: v for k, v in data.items() if k != "sample_spec"}
        logger.info(f"Fetched {len(entries)} models from LiteLLM")

        for model_id, raw in entries.items():
            try:
                model = self._parse_model(model_id, raw)
                models[model_id] = model
            except (KeyError, ValueError, TypeError, AttributeError) as e:
                logger.warning(f"Failed to parse LiteLLM model {model_id}: {e}")
                continue

        return models

    def _parse_model(self, model_id: str, raw: dict) -> LiteLLMModel:
        """Parse raw model entry into LiteLLMModel.

        Args:
            model_id: The model identifier (dict key).
            raw: Raw model data from JSON.

        Returns:
            Parsed LiteLLMModel object.
        """
        # Extract provider from litellm_provider field or model_id
        provider = raw.get("litellm_provider", "")
        if not provider and "/" in model_id:
            provider = model_id.split("/")[0]

        # Token limits
        max_tokens = raw.get("max_tokens", 4096)
        max_input = raw.get("max_input_tokens")
        max_output = raw.get("max_output_tokens")

        # Pricing (already per-token in LiteLLM)
        input_cost = raw.get("input_cost_per_token", 0.0)
        output_cost = raw.get("output_cost_per_token", 0.0)

        return LiteLLMModel(
            model_id=model_id,
            provider=provider,
            mode=raw.get("mode", "chat"),
            max_tokens=max_tokens,
            max_input_tokens=max_input,
            max_output_tokens=max_output,
            input_cost_per_token=input_cost,
            output_cost_per_token=output_cost,
            supports_function_calling=raw.get("supports_function_calling", False),
            supports_parallel_function_calling=raw.get(
                "supports_parallel_function_calling", False
            ),
            supports_vision=raw.get("supports_vision", False),
            supports_audio_input=raw.get("supports_audio_input", False),
            supports_audio_output=raw.get("supports_audio_output", False),
            supports_reasoning=raw.get("supports_reasoning", False),
            supports_response_schema=raw.get("supports_response_schema", False),
            supports_system_messages=raw.get("supports_system_messages", True),
            supports_prompt_caching=raw.get("supports_prompt_caching", False),
            deprecation_date=raw.get("deprecation_date"),
        )


@dataclass
class LiteLLMModelIndex:
    """Index of LiteLLM models for fast lookup."""

    models: dict[str, LiteLLMModel] = field(default_factory=dict)
    by_provider: dict[str, list[LiteLLMModel]] = field(default_factory=dict)

    @classmethod
    def from_models(cls, models: dict[str, LiteLLMModel]) -> "LiteLLMModelIndex":
        """Create index from models dictionary.

        Args:
            models: Dictionary of model_id -> LiteLLMModel.

        Returns:
            LiteLLMModelIndex with models indexed by ID and provider.
        """
        index = cls()
        index.models = models.copy()

        # Build provider index
        for model in models.values():
            provider = model.provider.lower()
            if provider not in index.by_provider:
                index.by_provider[provider] = []
            index.by_provider[provider].append(model)

        return index

    def get(self, model_id: str) -> LiteLLMModel | None:
        """Get model by ID.

        Args:
            model_id: Model ID to look up.

        Returns:
            LiteLLMModel if found, None otherwise.
        """
        return self.models.get(model_id)

    def filter_by_mode(self, mode: str) -> list[LiteLLMModel]:
        """Filter models by mode.

        Args:
            mode: Mode to filter by (chat, embedding, etc.).

        Returns:
            List of models matching the mode.
        """
        return [m for m in self.models.values() if m.mode == mode]
