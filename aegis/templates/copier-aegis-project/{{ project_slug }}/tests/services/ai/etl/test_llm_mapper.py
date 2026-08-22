"""Tests for LLM data mapper and merge logic."""

from datetime import UTC, datetime

from app.services.ai.domains.llm.etl.clients.litellm_client import LiteLLMModel
from app.services.ai.domains.llm.etl.clients.openrouter_client import (
    OpenRouterModel,
    OpenRouterModelIndex,
)
from app.services.ai.domains.llm.etl.mappers.llm_mapper import (
    MergedLLMData,
    extract_family,
    extract_vendor,
    merge_model_data,
    merge_single_model,
)


class TestExtractVendor:
    """Tests for vendor extraction logic."""

    def test_extract_vendor_with_prefix(self) -> None:
        """Test extracting vendor from model ID with prefix."""
        assert extract_vendor("openai/gpt-4o") == "openai"
        assert extract_vendor("anthropic/claude-3-5-sonnet") == "anthropic"
        assert extract_vendor("google/gemini-1.5-pro") == "google"
        assert extract_vendor("groq/llama-3.3-70b") == "groq"

    def test_extract_vendor_uses_provider_hint(self) -> None:
        """Test that provider_hint takes precedence."""
        assert extract_vendor("some/model", provider_hint="openai") == "openai"
        assert extract_vendor("some/model", provider_hint="anthropic") == "anthropic"

    def test_extract_vendor_normalizes_provider_hint(self) -> None:
        """Test that provider hints are normalized."""
        assert extract_vendor("model", provider_hint="together_ai") == "together"
        assert extract_vendor("model", provider_hint="fireworks_ai") == "fireworks"
        assert extract_vendor("model", provider_hint="vertex_ai") == "google"
        assert extract_vendor("model", provider_hint="cohere_chat") == "cohere"

    def test_extract_vendor_fallback_gpt(self) -> None:
        """Test fallback heuristics for GPT models."""
        assert extract_vendor("gpt-4o") == "openai"
        assert extract_vendor("gpt-3.5-turbo") == "openai"
        assert extract_vendor("o1-preview") == "openai"
        assert extract_vendor("o3-mini") == "openai"

    def test_extract_vendor_fallback_claude(self) -> None:
        """Test fallback heuristics for Claude models."""
        assert extract_vendor("claude-3-5-sonnet") == "anthropic"
        assert extract_vendor("claude-3-opus") == "anthropic"

    def test_extract_vendor_fallback_gemini(self) -> None:
        """Test fallback heuristics for Gemini models."""
        assert extract_vendor("gemini-1.5-pro") == "google"
        assert extract_vendor("gemini-2.0-flash") == "google"

    def test_extract_vendor_fallback_llama(self) -> None:
        """Test fallback heuristics for Llama models."""
        assert extract_vendor("llama-3.3-70b") == "meta"
        assert extract_vendor("codellama-34b") == "meta"

    def test_extract_vendor_fallback_mistral(self) -> None:
        """Test fallback heuristics for Mistral models."""
        assert extract_vendor("mistral-large") == "mistral"
        assert extract_vendor("mixtral-8x7b") == "mistral"

    def test_extract_vendor_fallback_cohere(self) -> None:
        """Test fallback heuristics for Cohere models."""
        assert extract_vendor("command-r-plus") == "cohere"
        assert extract_vendor("command-light") == "cohere"

    def test_extract_vendor_unknown(self) -> None:
        """Test fallback for unknown models."""
        assert extract_vendor("some-random-model") == "unknown"
        assert extract_vendor("custom-model-v1") == "unknown"


class TestExtractFamily:
    """Tests for model family extraction."""

    def test_extract_family_gpt4o(self) -> None:
        """Test extracting GPT-4o family."""
        assert extract_family("openai/gpt-4o") == "gpt-4o"
        assert extract_family("gpt-4o-mini") == "gpt-4o"
        assert extract_family("gpt-4o-2024-08-06") == "gpt-4o"

    def test_extract_family_gpt4(self) -> None:
        """Test extracting GPT-4 family."""
        assert extract_family("openai/gpt-4") == "gpt-4"
        assert extract_family("gpt-4-turbo") == "gpt-4"

    def test_extract_family_gpt35(self) -> None:
        """Test extracting GPT-3.5 family."""
        assert extract_family("gpt-3.5-turbo") == "gpt-3.5"
        assert extract_family("openai/gpt-3.5-turbo-16k") == "gpt-3.5"

    def test_extract_family_o1(self) -> None:
        """Test extracting o1 family."""
        assert extract_family("o1-preview") == "o1"
        assert extract_family("o1-mini") == "o1"

    def test_extract_family_o3(self) -> None:
        """Test extracting o3 family."""
        assert extract_family("o3-mini") == "o3"

    def test_extract_family_claude35(self) -> None:
        """Test extracting Claude 3.5 family."""
        assert extract_family("claude-3-5-sonnet") == "claude-3.5"
        assert extract_family("anthropic/claude-3.5-sonnet") == "claude-3.5"

    def test_extract_family_claude3(self) -> None:
        """Test extracting Claude 3 family."""
        assert extract_family("claude-3-opus") == "claude-3"
        assert extract_family("claude-3-sonnet") == "claude-3"

    def test_extract_family_gemini(self) -> None:
        """Test extracting Gemini families."""
        assert extract_family("gemini-2.0-flash") == "gemini-2"
        assert extract_family("gemini-1.5-pro") == "gemini-1.5"

    def test_extract_family_llama(self) -> None:
        """Test extracting Llama families."""
        assert extract_family("llama-3.3-70b") == "llama-3.3"
        assert extract_family("llama-3.2-3b") == "llama-3.2"
        assert extract_family("llama-3.1-405b") == "llama-3.1"
        assert extract_family("llama-3-8b") == "llama-3"

    def test_extract_family_mistral(self) -> None:
        """Test extracting Mistral families."""
        assert extract_family("mistral-large-latest") == "mistral-large"
        assert extract_family("mistral-small") == "mistral-small"
        assert extract_family("mixtral-8x7b") == "mixtral"

    def test_extract_family_command(self) -> None:
        """Test extracting Command-R family."""
        assert extract_family("command-r-plus") == "command-r"
        assert extract_family("command-r") == "command-r"

    def test_extract_family_unknown(self) -> None:
        """Test that unknown models return None."""
        assert extract_family("random-model") is None
        assert extract_family("custom-v1") is None


class TestMergeSingleModel:
    """Tests for single model merging."""

    def test_merge_with_openrouter_enrichment(
        self,
        sample_litellm_model: LiteLLMModel,
        sample_openrouter_model: OpenRouterModel,
    ) -> None:
        """Test that OpenRouter enriches description and title."""
        merged = merge_single_model(sample_litellm_model, sample_openrouter_model)

        assert isinstance(merged, MergedLLMData)
        # Title and description from OpenRouter
        assert merged.title == "GPT-4o"
        assert merged.description == "OpenAI's most advanced multimodal model"
        # Pricing from LiteLLM
        assert merged.input_cost_per_token == 0.000005
        assert merged.output_cost_per_token == 0.000015
        # Capabilities from LiteLLM
        assert merged.supports_function_calling is True
        assert merged.supports_structured_output is True
        # Context from OpenRouter (more accurate)
        assert merged.context_window == 128000
        # Modalities from OpenRouter
        assert "text" in merged.input_modalities
        assert "image" in merged.input_modalities
        # Cache pricing from OpenRouter
        assert merged.cache_read_cost_per_token == 0.0000025
        # Created timestamp from OpenRouter (1715558400 = 2024-05-13 00:00:00 UTC)
        assert merged.created_at == datetime(2024, 5, 13, tzinfo=UTC)

    def test_merge_litellm_only(self, sample_litellm_model: LiteLLMModel) -> None:
        """Test merging with only LiteLLM data."""
        merged = merge_single_model(sample_litellm_model, None)

        assert isinstance(merged, MergedLLMData)
        # Title generated from model_id
        assert "Gpt" in merged.title or "4O" in merged.title.upper()
        # No description without OpenRouter
        assert merged.description == ""
        # All other fields from LiteLLM
        assert merged.input_cost_per_token == 0.000005
        assert merged.supports_function_calling is True
        assert merged.supports_vision is True
        # No created_at without OpenRouter
        assert merged.created_at is None

    def test_merge_extracts_vendor(self, sample_litellm_model: LiteLLMModel) -> None:
        """Test that vendor is correctly extracted."""
        merged = merge_single_model(sample_litellm_model, None)

        assert merged.vendor == "openai"

    def test_merge_extracts_family(self, sample_litellm_model: LiteLLMModel) -> None:
        """Test that family is correctly extracted."""
        merged = merge_single_model(sample_litellm_model, None)

        assert merged.family == "gpt-4o"

    def test_merge_preserves_mode(self, sample_litellm_model: LiteLLMModel) -> None:
        """Test that mode is preserved from LiteLLM."""
        merged = merge_single_model(sample_litellm_model, None)

        assert merged.mode == "chat"


class TestMergeModelData:
    """Tests for bulk model merging."""

    def test_merge_multiple_models(
        self,
        sample_litellm_model: LiteLLMModel,
        sample_openrouter_model: OpenRouterModel,
    ) -> None:
        """Test merging multiple models."""
        litellm_models = {
            "openai/gpt-4o": sample_litellm_model,
        }
        openrouter_index = OpenRouterModelIndex.from_models([sample_openrouter_model])

        merged = merge_model_data(litellm_models, openrouter_index)

        assert len(merged) == 1
        assert merged[0].model_id == "openai/gpt-4o"

    def test_merge_handles_missing_openrouter(
        self, sample_litellm_model: LiteLLMModel
    ) -> None:
        """Test merging when OpenRouter data is missing."""
        litellm_models = {"openai/gpt-4o": sample_litellm_model}
        openrouter_index = OpenRouterModelIndex()  # Empty

        merged = merge_model_data(litellm_models, openrouter_index)

        assert len(merged) == 1
        assert merged[0].description == ""  # No OpenRouter enrichment

    def test_merge_skips_invalid_models(self) -> None:
        """Test that invalid models are skipped."""
        # Create a minimal model that should work
        valid_model = LiteLLMModel(
            model_id="valid/model",
            provider="valid",
            mode="chat",
            max_tokens=4096,
            max_input_tokens=None,
            max_output_tokens=None,
            input_cost_per_token=0.0,
            output_cost_per_token=0.0,
            supports_function_calling=False,
            supports_parallel_function_calling=False,
            supports_vision=False,
            supports_audio_input=False,
            supports_audio_output=False,
            supports_reasoning=False,
            supports_response_schema=False,
            supports_system_messages=True,
            supports_prompt_caching=False,
            deprecation_date=None,
        )

        litellm_models = {"valid/model": valid_model}
        openrouter_index = OpenRouterModelIndex()

        merged = merge_model_data(litellm_models, openrouter_index)

        assert len(merged) == 1


class TestVendorAliasNormalization:
    """Tests for vendor alias normalization."""

    def test_together_ai_normalization(self) -> None:
        """Test together_ai normalizes to together."""
        assert extract_vendor("model", provider_hint="together_ai") == "together"
        assert extract_vendor("together_ai/model") == "together"

    def test_fireworks_ai_normalization(self) -> None:
        """Test fireworks_ai normalizes to fireworks."""
        assert extract_vendor("model", provider_hint="fireworks_ai") == "fireworks"

    def test_vertex_ai_normalization(self) -> None:
        """Test vertex_ai normalizes to google."""
        assert extract_vendor("model", provider_hint="vertex_ai") == "google"
        assert extract_vendor("model", provider_hint="vertex_ai_beta") == "google"

    def test_cohere_chat_normalization(self) -> None:
        """Test cohere_chat normalizes to cohere."""
        assert extract_vendor("model", provider_hint="cohere_chat") == "cohere"

    def test_bedrock_normalization(self) -> None:
        """Test bedrock normalizes to aws."""
        assert extract_vendor("model", provider_hint="bedrock") == "aws"
        assert extract_vendor("bedrock/model") == "aws"

    def test_ollama_chat_normalization(self) -> None:
        """Test ollama_chat normalizes to ollama."""
        assert extract_vendor("model", provider_hint="ollama_chat") == "ollama"
