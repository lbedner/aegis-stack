"""
Tests for AI service bracket syntax parser.

Tests the parsing of ai[framework, backend, providers...] syntax where:
- Frameworks: pydantic-ai, langchain
- Backends: memory, sqlite
- Providers: public, openai, anthropic, google, groq, mistral, cohere

Values are detected by type, order doesn't matter.
Defaults: pydantic-ai, memory, public
"""

import pytest

from aegis.core.ai_service_parser import (
    AIServiceConfig,
    is_ai_service_with_options,
    parse_ai_service_config,
)


class TestAIServiceParserDefaults:
    """Test default values when no options specified."""

    def test_bare_ai_returns_all_defaults(self) -> None:
        """ai → pydantic-ai, memory, public"""
        result = parse_ai_service_config("ai")
        assert result.framework == "pydantic-ai"
        assert result.backend == "memory"
        assert result.providers == ["public"]

    def test_empty_brackets_returns_defaults(self) -> None:
        """ai[] → same as ai"""
        result = parse_ai_service_config("ai[]")
        assert result.framework == "pydantic-ai"
        assert result.backend == "memory"
        assert result.providers == ["public"]


class TestAIServiceParserSingleOption:
    """Test with single option specified."""

    def test_backend_only(self) -> None:
        """ai[sqlite] → pydantic-ai, sqlite, public"""
        result = parse_ai_service_config("ai[sqlite]")
        assert result.framework == "pydantic-ai"
        assert result.backend == "sqlite"
        assert result.providers == ["public"]

    def test_framework_only_langchain(self) -> None:
        """ai[langchain] → langchain, memory, public"""
        result = parse_ai_service_config("ai[langchain]")
        assert result.framework == "langchain"
        assert result.backend == "memory"
        assert result.providers == ["public"]

    def test_framework_only_pydantic_ai(self) -> None:
        """ai[pydantic-ai] → pydantic-ai, memory, public"""
        result = parse_ai_service_config("ai[pydantic-ai]")
        assert result.framework == "pydantic-ai"
        assert result.backend == "memory"
        assert result.providers == ["public"]

    def test_single_provider_groq(self) -> None:
        """ai[groq] → pydantic-ai, memory, groq"""
        result = parse_ai_service_config("ai[groq]")
        assert result.framework == "pydantic-ai"
        assert result.backend == "memory"
        assert result.providers == ["groq"]

    def test_single_provider_openai(self) -> None:
        """ai[openai] → pydantic-ai, memory, openai"""
        result = parse_ai_service_config("ai[openai]")
        assert result.framework == "pydantic-ai"
        assert result.backend == "memory"
        assert result.providers == ["openai"]

    def test_single_provider_anthropic(self) -> None:
        """ai[anthropic] → pydantic-ai, memory, anthropic"""
        result = parse_ai_service_config("ai[anthropic]")
        assert result.framework == "pydantic-ai"
        assert result.backend == "memory"
        assert result.providers == ["anthropic"]

    def test_single_provider_google(self) -> None:
        """ai[google] → pydantic-ai, memory, google"""
        result = parse_ai_service_config("ai[google]")
        assert result.framework == "pydantic-ai"
        assert result.backend == "memory"
        assert result.providers == ["google"]

    def test_single_provider_mistral(self) -> None:
        """ai[mistral] → pydantic-ai, memory, mistral"""
        result = parse_ai_service_config("ai[mistral]")
        assert result.framework == "pydantic-ai"
        assert result.backend == "memory"
        assert result.providers == ["mistral"]

    def test_single_provider_cohere(self) -> None:
        """ai[cohere] → pydantic-ai, memory, cohere"""
        result = parse_ai_service_config("ai[cohere]")
        assert result.framework == "pydantic-ai"
        assert result.backend == "memory"
        assert result.providers == ["cohere"]

    def test_single_provider_public(self) -> None:
        """ai[public] → pydantic-ai, memory, public"""
        result = parse_ai_service_config("ai[public]")
        assert result.framework == "pydantic-ai"
        assert result.backend == "memory"
        assert result.providers == ["public"]

    def test_memory_backend_explicit(self) -> None:
        """ai[memory] → pydantic-ai, memory, public"""
        result = parse_ai_service_config("ai[memory]")
        assert result.framework == "pydantic-ai"
        assert result.backend == "memory"
        assert result.providers == ["public"]


class TestAIServiceParserMultipleOptions:
    """Test with multiple options specified."""

    def test_framework_and_backend(self) -> None:
        """ai[langchain, sqlite] → langchain, sqlite, public"""
        result = parse_ai_service_config("ai[langchain, sqlite]")
        assert result.framework == "langchain"
        assert result.backend == "sqlite"
        assert result.providers == ["public"]

    def test_framework_and_provider(self) -> None:
        """ai[langchain, anthropic] → langchain, memory, anthropic"""
        result = parse_ai_service_config("ai[langchain, anthropic]")
        assert result.framework == "langchain"
        assert result.backend == "memory"
        assert result.providers == ["anthropic"]

    def test_backend_and_provider(self) -> None:
        """ai[sqlite, groq] → pydantic-ai, sqlite, groq"""
        result = parse_ai_service_config("ai[sqlite, groq]")
        assert result.framework == "pydantic-ai"
        assert result.backend == "sqlite"
        assert result.providers == ["groq"]

    def test_backend_and_multiple_providers(self) -> None:
        """ai[sqlite, groq, google] → pydantic-ai, sqlite, [groq, google]"""
        result = parse_ai_service_config("ai[sqlite, groq, google]")
        assert result.framework == "pydantic-ai"
        assert result.backend == "sqlite"
        assert result.providers == ["groq", "google"]

    def test_multiple_providers(self) -> None:
        """ai[openai, anthropic, google] → pydantic-ai, memory, [openai, anthropic, google]"""
        result = parse_ai_service_config("ai[openai, anthropic, google]")
        assert result.framework == "pydantic-ai"
        assert result.backend == "memory"
        assert result.providers == ["openai", "anthropic", "google"]

    def test_all_options(self) -> None:
        """ai[langchain, sqlite, anthropic, groq] → langchain, sqlite, [anthropic, groq]"""
        result = parse_ai_service_config("ai[langchain, sqlite, anthropic, groq]")
        assert result.framework == "langchain"
        assert result.backend == "sqlite"
        assert result.providers == ["anthropic", "groq"]

    def test_all_providers(self) -> None:
        """ai[openai, anthropic, google, groq, mistral, cohere] → all providers"""
        result = parse_ai_service_config(
            "ai[openai, anthropic, google, groq, mistral, cohere]"
        )
        assert result.framework == "pydantic-ai"
        assert result.backend == "memory"
        assert set(result.providers) == {
            "openai",
            "anthropic",
            "google",
            "groq",
            "mistral",
            "cohere",
        }


class TestAIServiceParserOrderIndependent:
    """Test that order of options doesn't matter."""

    def test_order_variation_sqlite_langchain_groq(self) -> None:
        """ai[sqlite, langchain, groq] same as ai[langchain, sqlite, groq]"""
        result = parse_ai_service_config("ai[sqlite, langchain, groq]")
        assert result.framework == "langchain"
        assert result.backend == "sqlite"
        assert result.providers == ["groq"]

    def test_order_variation_groq_sqlite_langchain(self) -> None:
        """ai[groq, sqlite, langchain] same as above"""
        result = parse_ai_service_config("ai[groq, sqlite, langchain]")
        assert result.framework == "langchain"
        assert result.backend == "sqlite"
        assert result.providers == ["groq"]

    def test_order_variation_providers_first(self) -> None:
        """ai[anthropic, openai, langchain] → langchain with providers"""
        result = parse_ai_service_config("ai[anthropic, openai, langchain]")
        assert result.framework == "langchain"
        assert result.backend == "memory"
        assert set(result.providers) == {"anthropic", "openai"}

    def test_order_variation_all_mixed(self) -> None:
        """ai[groq, pydantic-ai, sqlite, google] → pydantic-ai, sqlite, [groq, google]"""
        result = parse_ai_service_config("ai[groq, pydantic-ai, sqlite, google]")
        assert result.framework == "pydantic-ai"
        assert result.backend == "sqlite"
        assert set(result.providers) == {"groq", "google"}


class TestAIServiceParserWhitespace:
    """Test whitespace handling."""

    def test_no_spaces(self) -> None:
        """ai[langchain,sqlite,groq] parses correctly"""
        result = parse_ai_service_config("ai[langchain,sqlite,groq]")
        assert result.framework == "langchain"
        assert result.backend == "sqlite"
        assert result.providers == ["groq"]

    def test_extra_spaces(self) -> None:
        """ai[  langchain  ,  sqlite  ,  groq  ] parses correctly"""
        result = parse_ai_service_config("ai[  langchain  ,  sqlite  ,  groq  ]")
        assert result.framework == "langchain"
        assert result.backend == "sqlite"
        assert result.providers == ["groq"]

    def test_tabs(self) -> None:
        """ai[langchain\t,\tsqlite] parses correctly"""
        result = parse_ai_service_config("ai[langchain\t,\tsqlite]")
        assert result.framework == "langchain"
        assert result.backend == "sqlite"
        assert result.providers == ["public"]

    def test_leading_trailing_whitespace(self) -> None:
        """Whitespace around whole string handled"""
        result = parse_ai_service_config("  ai[langchain]  ")
        assert result.framework == "langchain"
        assert result.backend == "memory"
        assert result.providers == ["public"]


class TestAIServiceParserErrors:
    """Test error cases."""

    def test_unknown_value_raises_error(self) -> None:
        """Unknown value should raise ValueError with helpful message."""
        with pytest.raises(ValueError) as exc_info:
            parse_ai_service_config("ai[invalid]")
        error_msg = str(exc_info.value)
        assert "Unknown value 'invalid'" in error_msg or "invalid" in error_msg

    def test_multiple_frameworks_raises_error(self) -> None:
        """Can't specify both frameworks."""
        with pytest.raises(ValueError) as exc_info:
            parse_ai_service_config("ai[langchain, pydantic-ai]")
        error_msg = str(exc_info.value).lower()
        assert "multiple" in error_msg or "framework" in error_msg

    def test_multiple_backends_raises_error(self) -> None:
        """Can't specify both backends."""
        with pytest.raises(ValueError) as exc_info:
            parse_ai_service_config("ai[memory, sqlite]")
        error_msg = str(exc_info.value).lower()
        assert "multiple" in error_msg or "backend" in error_msg

    def test_invalid_service_name_raises_error(self) -> None:
        """Non-ai service should raise error."""
        with pytest.raises(ValueError) as exc_info:
            parse_ai_service_config("auth[sqlite]")
        error_msg = str(exc_info.value).lower()
        assert "ai" in error_msg

    def test_malformed_brackets_raises_error(self) -> None:
        """Malformed brackets should raise error."""
        with pytest.raises(ValueError):
            parse_ai_service_config("ai[langchain")

    def test_gibberish_raises_error(self) -> None:
        """Completely invalid input raises error."""
        with pytest.raises(ValueError):
            parse_ai_service_config("not_a_service")


class TestAIServiceConfigDataclass:
    """Test the AIServiceConfig dataclass."""

    def test_config_attributes(self) -> None:
        """AIServiceConfig has expected attributes."""
        config = AIServiceConfig(
            framework="langchain", backend="sqlite", providers=["openai", "anthropic"]
        )
        assert config.framework == "langchain"
        assert config.backend == "sqlite"
        assert config.providers == ["openai", "anthropic"]

    def test_config_equality(self) -> None:
        """AIServiceConfig instances with same values are equal."""
        config1 = AIServiceConfig(
            framework="pydantic-ai", backend="memory", providers=["public"]
        )
        config2 = AIServiceConfig(
            framework="pydantic-ai", backend="memory", providers=["public"]
        )
        assert config1 == config2


class TestAIServiceParserProviderOrder:
    """Test that provider order is preserved."""

    def test_provider_order_preserved(self) -> None:
        """Providers should be in the order specified."""
        result = parse_ai_service_config("ai[openai, anthropic, google]")
        assert result.providers == ["openai", "anthropic", "google"]

    def test_provider_order_preserved_reversed(self) -> None:
        """Providers should be in the order specified (reversed)."""
        result = parse_ai_service_config("ai[google, anthropic, openai]")
        assert result.providers == ["google", "anthropic", "openai"]


class TestIsAIServiceWithOptions:
    """Test the is_ai_service_with_options helper function.

    This function determines if bracket syntax is used, which affects
    whether auto-detection of AI backend should run.
    """

    def test_plain_ai_returns_false(self) -> None:
        """Plain 'ai' without brackets should return False.

        This is critical for auto-detection: when user specifies just 'ai',
        the system should auto-detect backend based on available components
        (e.g., use sqlite if database component exists).
        """
        assert is_ai_service_with_options("ai") is False

    def test_ai_with_empty_brackets_returns_true(self) -> None:
        """ai[] should return True (explicit but empty options)."""
        assert is_ai_service_with_options("ai[]") is True

    def test_ai_with_backend_returns_true(self) -> None:
        """ai[sqlite] should return True."""
        assert is_ai_service_with_options("ai[sqlite]") is True

    def test_ai_with_framework_returns_true(self) -> None:
        """ai[langchain] should return True."""
        assert is_ai_service_with_options("ai[langchain]") is True

    def test_ai_with_multiple_options_returns_true(self) -> None:
        """ai[langchain, sqlite, openai] should return True."""
        assert is_ai_service_with_options("ai[langchain, sqlite, openai]") is True

    def test_ai_with_spaces_returns_false(self) -> None:
        """'ai' with surrounding spaces should return False."""
        assert is_ai_service_with_options("  ai  ") is False

    def test_ai_bracket_with_spaces_returns_true(self) -> None:
        """'ai[sqlite]' with surrounding spaces should return True."""
        assert is_ai_service_with_options("  ai[sqlite]  ") is True

    def test_non_ai_service_returns_false(self) -> None:
        """Non-AI services should return False."""
        assert is_ai_service_with_options("auth") is False
        assert is_ai_service_with_options("comms") is False

    def test_partial_ai_name_returns_false(self) -> None:
        """Partial matches like 'ai_test' should return False."""
        assert is_ai_service_with_options("ai_test") is False
        assert is_ai_service_with_options("my_ai") is False


class TestAIServiceParserVoiceFeature:
    """Test voice feature flag in AI service configuration.

    The voice feature flag enables TTS (Text-to-Speech) and STT (Speech-to-Text)
    capabilities in the AI service.
    """

    def test_voice_enabled_defaults_to_false(self) -> None:
        """Voice should be disabled by default."""
        result = parse_ai_service_config("ai")
        assert result.voice_enabled is False

    def test_voice_enabled_with_empty_brackets(self) -> None:
        """ai[] should have voice disabled."""
        result = parse_ai_service_config("ai[]")
        assert result.voice_enabled is False

    def test_voice_feature_flag(self) -> None:
        """ai[voice] should enable voice."""
        result = parse_ai_service_config("ai[voice]")
        assert result.voice_enabled is True
        # Other defaults should remain unchanged
        assert result.framework == "pydantic-ai"
        assert result.backend == "memory"
        assert result.providers == ["public"]

    def test_voice_with_backend(self) -> None:
        """ai[sqlite, voice] should enable voice and set backend."""
        result = parse_ai_service_config("ai[sqlite, voice]")
        assert result.voice_enabled is True
        assert result.backend == "sqlite"

    def test_voice_with_framework(self) -> None:
        """ai[langchain, voice] should enable voice and set framework."""
        result = parse_ai_service_config("ai[langchain, voice]")
        assert result.voice_enabled is True
        assert result.framework == "langchain"

    def test_voice_with_provider(self) -> None:
        """ai[openai, voice] should enable voice and set provider."""
        result = parse_ai_service_config("ai[openai, voice]")
        assert result.voice_enabled is True
        assert result.providers == ["openai"]

    def test_voice_with_all_options(self) -> None:
        """ai[langchain, sqlite, anthropic, voice] should work with all options."""
        result = parse_ai_service_config("ai[langchain, sqlite, anthropic, voice]")
        assert result.voice_enabled is True
        assert result.framework == "langchain"
        assert result.backend == "sqlite"
        assert result.providers == ["anthropic"]

    def test_voice_order_independent(self) -> None:
        """Voice flag should work regardless of position."""
        result1 = parse_ai_service_config("ai[voice, sqlite]")
        result2 = parse_ai_service_config("ai[sqlite, voice]")
        assert result1.voice_enabled is True
        assert result2.voice_enabled is True
        assert result1.backend == result2.backend == "sqlite"


class TestAIServiceParserRagAndVoice:
    """Test RAG and voice feature flags together."""

    def test_rag_defaults_to_false(self) -> None:
        """RAG should be disabled by default."""
        result = parse_ai_service_config("ai")
        assert result.rag_enabled is False

    def test_rag_feature_flag(self) -> None:
        """ai[rag] should enable RAG."""
        result = parse_ai_service_config("ai[rag]")
        assert result.rag_enabled is True
        assert result.voice_enabled is False

    def test_both_features_enabled(self) -> None:
        """ai[rag, voice] should enable both features."""
        result = parse_ai_service_config("ai[rag, voice]")
        assert result.rag_enabled is True
        assert result.voice_enabled is True

    def test_all_features_with_options(self) -> None:
        """ai[langchain, sqlite, openai, rag, voice] should work."""
        result = parse_ai_service_config("ai[langchain, sqlite, openai, rag, voice]")
        assert result.rag_enabled is True
        assert result.voice_enabled is True
        assert result.framework == "langchain"
        assert result.backend == "sqlite"
        assert result.providers == ["openai"]


class TestAIServiceParserEvals:
    """``ai[evals]``: the eval harness, an option like rag and voice."""

    def test_evals_is_off_unless_named(self) -> None:
        assert parse_ai_service_config("ai").evals_enabled is False
        assert parse_ai_service_config("ai[sqlite, voice]").evals_enabled is False

    def test_evals_flag_turns_it_on_beside_the_others(self) -> None:
        result = parse_ai_service_config("ai[sqlite, rag, evals]")
        assert result.evals_enabled is True
        assert result.rag_enabled is True
        assert result.backend == "sqlite"


class TestAIServiceConfigVoiceAttribute:
    """Test the AIServiceConfig dataclass voice_enabled attribute."""

    def test_config_has_voice_enabled_attribute(self) -> None:
        """AIServiceConfig should have voice_enabled attribute."""
        config = AIServiceConfig(
            framework="pydantic-ai",
            backend="memory",
            providers=["public"],
            voice_enabled=True,
        )
        assert config.voice_enabled is True

    def test_config_voice_enabled_defaults_false(self) -> None:
        """AIServiceConfig voice_enabled should default to False."""
        config = AIServiceConfig(
            framework="pydantic-ai",
            backend="memory",
            providers=["public"],
        )
        assert config.voice_enabled is False

    def test_config_equality_with_voice(self) -> None:
        """AIServiceConfig instances with different voice_enabled are not equal."""
        config1 = AIServiceConfig(
            framework="pydantic-ai",
            backend="memory",
            providers=["public"],
            voice_enabled=False,
        )
        config2 = AIServiceConfig(
            framework="pydantic-ai",
            backend="memory",
            providers=["public"],
            voice_enabled=True,
        )
        assert config1 != config2
