"""Tests for OpenRouter API client."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from app.services.ai.domains.llm.etl.clients.openrouter_client import (
    OpenRouterClient,
    OpenRouterModel,
    OpenRouterModelIndex,
)


class TestOpenRouterClient:
    """Tests for OpenRouterClient class."""

    @pytest.mark.asyncio
    async def test_fetch_models_success(self, mock_httpx_openrouter: MagicMock) -> None:
        """Test successful fetch and parsing of models."""
        client = OpenRouterClient()
        models = await client.fetch_models()

        assert len(models) == 2
        assert all(isinstance(m, OpenRouterModel) for m in models)

        # Verify first model
        gpt4o = models[0]
        assert gpt4o.model_id == "openai/gpt-4o"
        assert gpt4o.name == "GPT-4o"
        assert gpt4o.context_length == 128000

    @pytest.mark.asyncio
    async def test_fetch_models_http_error(self) -> None:
        """Test that HTTP errors are propagated."""
        with patch("app.services.ai.domains.llm.etl.clients.openrouter_client.httpx") as mock_httpx:
            mock_response = MagicMock()
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Server error",
                request=MagicMock(),
                response=MagicMock(status_code=500),
            )

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            mock_httpx.AsyncClient.return_value = mock_client

            client = OpenRouterClient()

            with pytest.raises(httpx.HTTPStatusError):
                await client.fetch_models()

    @pytest.mark.asyncio
    async def test_fetch_models_handles_parse_errors(self) -> None:
        """Test that invalid model entries are skipped with warning."""
        with patch("app.services.ai.domains.llm.etl.clients.openrouter_client.httpx") as mock_httpx:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "data": [
                    {"id": "valid/model", "context_length": 4096},
                    {},  # Invalid - missing required 'id' field
                ]
            }
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            mock_httpx.AsyncClient.return_value = mock_client

            client = OpenRouterClient()
            models = await client.fetch_models()

            # Should only have the valid model
            assert len(models) == 1
            assert models[0].model_id == "valid/model"


class TestOpenRouterClientParsing:
    """Tests for OpenRouterClient parsing logic."""

    def test_parse_model_complete(
        self, mock_openrouter_response: dict[str, Any]
    ) -> None:
        """Test parsing a complete model with all fields."""
        client = OpenRouterClient()
        raw = mock_openrouter_response["data"][0]
        model = client._parse_model(raw)

        assert model.model_id == "openai/gpt-4o"
        assert model.name == "GPT-4o"
        assert model.description == "OpenAI's most advanced multimodal model"
        assert model.context_length == 128000
        assert model.max_completion_tokens == 16384
        assert model.input_modalities == ["text", "image"]
        assert model.output_modalities == ["text"]
        assert model.tokenizer == "o200k_base"
        assert model.input_cost_per_token == 0.000005
        assert model.output_cost_per_token == 0.000015
        assert model.cache_read_cost_per_token == 0.0000025
        assert model.is_moderated is True

    def test_parse_model_minimal(
        self, mock_openrouter_response_minimal: dict[str, Any]
    ) -> None:
        """Test parsing a model with minimal/missing fields."""
        client = OpenRouterClient()
        raw = mock_openrouter_response_minimal["data"][0]
        model = client._parse_model(raw)

        assert model.model_id == "test/minimal-model"
        assert model.name == "test/minimal-model"  # Falls back to ID
        assert model.description == ""
        assert model.context_length == 4096  # Default
        assert model.max_completion_tokens is None
        assert model.input_modalities == ["text"]  # Default
        assert model.output_modalities == ["text"]  # Default
        assert model.input_cost_per_token == 0.0
        assert model.output_cost_per_token == 0.0

    def test_parse_price_string(self) -> None:
        """Test parsing price from string value."""
        client = OpenRouterClient()
        assert client._parse_price("0.000005") == 0.000005
        assert client._parse_price("0") == 0.0
        assert client._parse_price("1.5e-6") == 1.5e-6

    def test_parse_price_float(self) -> None:
        """Test parsing price from float value."""
        client = OpenRouterClient()
        assert client._parse_price(0.000005) == 0.000005
        assert client._parse_price(0.0) == 0.0

    def test_parse_price_none(self) -> None:
        """Test parsing None price value."""
        client = OpenRouterClient()
        assert client._parse_price(None) is None

    def test_parse_price_invalid(self) -> None:
        """Test parsing invalid price value."""
        client = OpenRouterClient()
        assert client._parse_price("invalid") is None
        assert client._parse_price({}) is None


class TestOpenRouterModelIndex:
    """Tests for OpenRouterModelIndex class."""

    def test_from_models_creates_index(
        self, sample_openrouter_model: OpenRouterModel
    ) -> None:
        """Test creating index from model list."""
        models = [sample_openrouter_model]
        index = OpenRouterModelIndex.from_models(models)

        assert len(index.models) == 2  # Full ID + short ID

    def test_get_by_full_id(self, sample_openrouter_model: OpenRouterModel) -> None:
        """Test lookup by full model ID."""
        index = OpenRouterModelIndex.from_models([sample_openrouter_model])

        result = index.get("openai/gpt-4o")
        assert result is not None
        assert result.model_id == "openai/gpt-4o"

    def test_get_by_short_id(self, sample_openrouter_model: OpenRouterModel) -> None:
        """Test lookup by short model ID (without vendor prefix)."""
        index = OpenRouterModelIndex.from_models([sample_openrouter_model])

        result = index.get("gpt-4o")
        assert result is not None
        assert result.model_id == "openai/gpt-4o"

    def test_get_not_found(self, sample_openrouter_model: OpenRouterModel) -> None:
        """Test lookup for non-existent model."""
        index = OpenRouterModelIndex.from_models([sample_openrouter_model])

        result = index.get("nonexistent/model")
        assert result is None

    def test_short_id_collision_prefers_first(self) -> None:
        """Test that first model wins when short IDs collide."""
        model1 = OpenRouterModel(
            model_id="vendor1/model",
            name="Model 1",
            description="",
            context_length=4096,
            max_completion_tokens=None,
            input_modalities=["text"],
            output_modalities=["text"],
            tokenizer=None,
            input_cost_per_token=0.0,
            output_cost_per_token=0.0,
            cache_read_cost_per_token=None,
            cache_write_cost_per_token=None,
            is_moderated=False,
        )
        model2 = OpenRouterModel(
            model_id="vendor2/model",
            name="Model 2",
            description="",
            context_length=8192,
            max_completion_tokens=None,
            input_modalities=["text"],
            output_modalities=["text"],
            tokenizer=None,
            input_cost_per_token=0.0,
            output_cost_per_token=0.0,
            cache_read_cost_per_token=None,
            cache_write_cost_per_token=None,
            is_moderated=False,
        )

        index = OpenRouterModelIndex.from_models([model1, model2])

        # Short ID "model" should resolve to first model
        result = index.get("model")
        assert result is not None
        assert result.model_id == "vendor1/model"

        # Full IDs should still work
        assert index.get("vendor1/model") is not None
        assert index.get("vendor2/model") is not None
