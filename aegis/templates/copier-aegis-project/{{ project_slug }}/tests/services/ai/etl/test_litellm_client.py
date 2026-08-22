"""Tests for LiteLLM model cost map client."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from app.services.ai.domains.llm.etl.clients.litellm_client import (
    LiteLLMClient,
    LiteLLMModel,
    LiteLLMModelIndex,
)


class TestLiteLLMClient:
    """Tests for LiteLLMClient class."""

    @pytest.mark.asyncio
    async def test_fetch_models_success(self, mock_httpx_litellm: MagicMock) -> None:
        """Test successful fetch and parsing of models."""
        client = LiteLLMClient()
        models = await client.fetch_models()

        # Should skip sample_spec entry
        assert len(models) == 3
        assert all(isinstance(m, LiteLLMModel) for m in models.values())

        # Verify gpt-4o
        gpt4o = models.get("openai/gpt-4o")
        assert gpt4o is not None
        assert gpt4o.provider == "openai"
        assert gpt4o.mode == "chat"
        assert gpt4o.max_tokens == 128000

    @pytest.mark.asyncio
    async def test_fetch_models_skips_sample_spec(
        self, mock_httpx_litellm: MagicMock
    ) -> None:
        """Test that sample_spec entry is skipped."""
        client = LiteLLMClient()
        models = await client.fetch_models()

        assert "sample_spec" not in models

    @pytest.mark.asyncio
    async def test_fetch_models_http_error(self) -> None:
        """Test that HTTP errors are propagated."""
        with patch("app.services.ai.domains.llm.etl.clients.litellm_client.httpx") as mock_httpx:
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

            client = LiteLLMClient()

            with pytest.raises(httpx.HTTPStatusError):
                await client.fetch_models()

    @pytest.mark.asyncio
    async def test_fetch_models_handles_parse_errors(self) -> None:
        """Test that invalid model entries are skipped with warning."""
        with patch("app.services.ai.domains.llm.etl.clients.litellm_client.httpx") as mock_httpx:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "valid/model": {"mode": "chat", "max_tokens": 4096},
                "invalid/model": "not a dict",  # Invalid format
            }
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            mock_httpx.AsyncClient.return_value = mock_client

            client = LiteLLMClient()
            models = await client.fetch_models()

            # Should only have the valid model
            assert len(models) == 1
            assert "valid/model" in models


class TestLiteLLMClientParsing:
    """Tests for LiteLLMClient parsing logic."""

    def test_parse_model_complete(self, mock_litellm_response: dict[str, Any]) -> None:
        """Test parsing a complete model with all fields."""
        client = LiteLLMClient()
        raw = mock_litellm_response["openai/gpt-4o"]
        model = client._parse_model("openai/gpt-4o", raw)

        assert model.model_id == "openai/gpt-4o"
        assert model.provider == "openai"
        assert model.mode == "chat"
        assert model.max_tokens == 128000
        assert model.max_input_tokens == 128000
        assert model.max_output_tokens == 16384
        assert model.input_cost_per_token == 0.000005
        assert model.output_cost_per_token == 0.000015
        assert model.supports_function_calling is True
        assert model.supports_parallel_function_calling is True
        assert model.supports_vision is True
        assert model.supports_audio_input is False
        assert model.supports_audio_output is False
        assert model.supports_reasoning is False
        assert model.supports_response_schema is True
        assert model.supports_system_messages is True
        assert model.supports_prompt_caching is True
        assert model.deprecation_date is None

    def test_parse_model_minimal(
        self, mock_litellm_response_minimal: dict[str, Any]
    ) -> None:
        """Test parsing a model with minimal/missing fields."""
        client = LiteLLMClient()
        raw = mock_litellm_response_minimal["test/minimal-model"]
        model = client._parse_model("test/minimal-model", raw)

        assert model.model_id == "test/minimal-model"
        assert model.provider == "test"  # Extracted from model_id
        assert model.mode == "chat"
        assert model.max_tokens == 4096  # Default
        assert model.max_input_tokens is None
        assert model.max_output_tokens is None
        assert model.input_cost_per_token == 0.0
        assert model.output_cost_per_token == 0.0
        assert model.supports_function_calling is False
        assert model.supports_vision is False
        assert model.supports_system_messages is True  # Default

    def test_parse_model_extracts_provider_from_id(self) -> None:
        """Test provider extraction from model_id when not in data."""
        client = LiteLLMClient()
        raw = {"mode": "chat"}
        model = client._parse_model("anthropic/claude-3-opus", raw)

        assert model.provider == "anthropic"

    def test_parse_model_uses_litellm_provider(self) -> None:
        """Test that litellm_provider field takes precedence."""
        client = LiteLLMClient()
        raw = {"mode": "chat", "litellm_provider": "vertex_ai"}
        model = client._parse_model("google/gemini-pro", raw)

        assert model.provider == "vertex_ai"


class TestLiteLLMModelIndex:
    """Tests for LiteLLMModelIndex class."""

    def test_from_models_creates_index(
        self, sample_litellm_model: LiteLLMModel
    ) -> None:
        """Test creating index from models dict."""
        models = {"openai/gpt-4o": sample_litellm_model}
        index = LiteLLMModelIndex.from_models(models)

        assert len(index.models) == 1
        assert "openai" in index.by_provider
        assert len(index.by_provider["openai"]) == 1

    def test_get_by_id(self, sample_litellm_model: LiteLLMModel) -> None:
        """Test lookup by model ID."""
        models = {"openai/gpt-4o": sample_litellm_model}
        index = LiteLLMModelIndex.from_models(models)

        result = index.get("openai/gpt-4o")
        assert result is not None
        assert result.model_id == "openai/gpt-4o"

    def test_get_not_found(self, sample_litellm_model: LiteLLMModel) -> None:
        """Test lookup for non-existent model."""
        models = {"openai/gpt-4o": sample_litellm_model}
        index = LiteLLMModelIndex.from_models(models)

        result = index.get("nonexistent/model")
        assert result is None

    def test_filter_by_mode_chat(self, mock_litellm_response: dict[str, Any]) -> None:
        """Test filtering models by chat mode."""
        client = LiteLLMClient()
        models = {}
        for model_id, raw in mock_litellm_response.items():
            if model_id != "sample_spec":
                models[model_id] = client._parse_model(model_id, raw)

        index = LiteLLMModelIndex.from_models(models)
        chat_models = index.filter_by_mode("chat")

        assert len(chat_models) == 2
        assert all(m.mode == "chat" for m in chat_models)

    def test_filter_by_mode_embedding(
        self, mock_litellm_response: dict[str, Any]
    ) -> None:
        """Test filtering models by embedding mode."""
        client = LiteLLMClient()
        models = {}
        for model_id, raw in mock_litellm_response.items():
            if model_id != "sample_spec":
                models[model_id] = client._parse_model(model_id, raw)

        index = LiteLLMModelIndex.from_models(models)
        embedding_models = index.filter_by_mode("embedding")

        assert len(embedding_models) == 1
        assert embedding_models[0].model_id == "text-embedding-3-small"

    def test_provider_grouping(self, mock_litellm_response: dict[str, Any]) -> None:
        """Test that models are grouped by provider."""
        client = LiteLLMClient()
        models = {}
        for model_id, raw in mock_litellm_response.items():
            if model_id != "sample_spec":
                models[model_id] = client._parse_model(model_id, raw)

        index = LiteLLMModelIndex.from_models(models)

        assert "openai" in index.by_provider
        assert "anthropic" in index.by_provider
        assert len(index.by_provider["openai"]) == 2  # gpt-4o and embedding
        assert len(index.by_provider["anthropic"]) == 1
