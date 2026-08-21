"""Tests for AI service models and provider functions."""

from app.services.ai.models import (
    AIProvider,
    ProviderCapabilities,
    get_free_providers,
    get_provider_capabilities,
)


class TestProviderFunctions:
    """Test provider utility functions."""

    def test_get_free_providers_returns_enum_list(self) -> None:
        """Ensure get_free_providers returns list of AIProvider enums, not strings."""
        providers = get_free_providers()

        assert isinstance(providers, list)
        assert len(providers) > 0
        # CRITICAL: Must return AIProvider enums, not strings
        assert all(isinstance(p, AIProvider) for p in providers)

    def test_free_providers_enum_membership(self) -> None:
        """Test that AIProvider enum membership checks work correctly.

        This test would have caught the bug where get_free_providers
        returned list[str] instead of list[AIProvider].
        """
        free_providers = get_free_providers()

        # These comparisons must work (enum in list[enum]).
        # Only OLLAMA (local) and PUBLIC (no API key) are free-tier in
        # ``PROVIDER_CAPABILITIES``. GROQ/GOOGLE/COHERE previously advertised
        # free tiers but the capability flags were tightened — their free
        # offerings are rate-limited or behind signup, so the catalog marks
        # them paid and we test what's actually shipped.
        assert AIProvider.PUBLIC in free_providers
        assert AIProvider.OLLAMA in free_providers

        # These should NOT be free (paid / API-key required)
        assert AIProvider.OPENAI not in free_providers
        assert AIProvider.ANTHROPIC not in free_providers
        assert AIProvider.MISTRAL not in free_providers
        assert AIProvider.GROQ not in free_providers
        assert AIProvider.GOOGLE not in free_providers
        assert AIProvider.COHERE not in free_providers

    def test_free_providers_string_join(self) -> None:
        """Test that free providers can be joined as strings for display."""
        free_providers = get_free_providers()

        # This is what the CLI does - must work with .value
        providers_list = ", ".join(p.value for p in free_providers)

        assert isinstance(providers_list, str)
        assert "public" in providers_list
        assert "ollama" in providers_list

    def test_pollinations_is_free_provider(self) -> None:
        """Pollinations advertises a genuinely keyless anonymous tier."""
        free_providers = get_free_providers()
        assert AIProvider.POLLINATIONS in free_providers

    def test_get_provider_capabilities_pollinations(self) -> None:
        """Test capabilities for POLLINATIONS provider."""
        caps = get_provider_capabilities(AIProvider.POLLINATIONS)

        assert caps.provider == AIProvider.POLLINATIONS
        assert caps.free_tier_available is True
        # The anonymous tier rejects stream=true.
        assert caps.supports_streaming is False

    def test_get_provider_capabilities_public(self) -> None:
        """Test capabilities for PUBLIC provider."""
        caps = get_provider_capabilities(AIProvider.PUBLIC)

        assert isinstance(caps, ProviderCapabilities)
        assert caps.provider == AIProvider.PUBLIC
        assert caps.free_tier_available is True
        assert caps.supports_streaming is False
        assert caps.supports_function_calling is False
        assert caps.supports_vision is False

    def test_get_provider_capabilities_openai(self) -> None:
        """Test capabilities for OpenAI provider."""
        caps = get_provider_capabilities(AIProvider.OPENAI)

        assert caps.provider == AIProvider.OPENAI
        assert caps.free_tier_available is False
        assert caps.supports_streaming is True
        assert caps.supports_function_calling is True
        assert caps.supports_vision is True

    def test_get_provider_capabilities_groq(self) -> None:
        """Test capabilities for Groq provider.

        Groq's free tier is rate-limited/signup-gated, so ``PROVIDER_CAPABILITIES``
        marks it paid. This test pins that intent so a casual flag flip
        doesn't drift the catalog silently.
        """
        caps = get_provider_capabilities(AIProvider.GROQ)

        assert caps.provider == AIProvider.GROQ
        assert caps.free_tier_available is False
        assert caps.supports_streaming is True

    def test_all_providers_have_capabilities(self) -> None:
        """Ensure all providers have defined capabilities."""
        for provider in AIProvider:
            caps = get_provider_capabilities(provider)
            assert isinstance(caps, ProviderCapabilities)
            assert caps.provider == provider

    def test_free_tier_consistency(self) -> None:
        """Ensure free_tier_available matches get_free_providers result."""
        free_providers = get_free_providers()

        for provider in AIProvider:
            caps = get_provider_capabilities(provider)

            if provider in free_providers:
                assert caps.free_tier_available is True, (
                    f"{provider} should have free_tier_available=True"
                )
            else:
                assert caps.free_tier_available is False, (
                    f"{provider} should have free_tier_available=False"
                )


class TestAIProviderEnum:
    """Test AIProvider enum behavior."""

    def test_provider_enum_values(self) -> None:
        """Test that provider enums have correct string values."""
        assert AIProvider.OPENAI.value == "openai"
        assert AIProvider.ANTHROPIC.value == "anthropic"
        assert AIProvider.GOOGLE.value == "google"
        assert AIProvider.GROQ.value == "groq"
        assert AIProvider.MISTRAL.value == "mistral"
        assert AIProvider.COHERE.value == "cohere"
        assert AIProvider.PUBLIC.value == "public"

    def test_provider_enum_from_string(self) -> None:
        """Test creating provider from string value."""
        assert AIProvider("openai") == AIProvider.OPENAI
        assert AIProvider("public") == AIProvider.PUBLIC

    def test_provider_enum_comparison(self) -> None:
        """Test that provider enum comparisons work correctly."""
        provider = AIProvider.PUBLIC

        # Enum equality
        assert provider == AIProvider.PUBLIC
        assert provider != AIProvider.OPENAI

        # String comparison should work (due to str inheritance)
        assert provider == "public"
        assert provider != "openai"


class TestProviderCapabilitiesModel:
    """Test ProviderCapabilities Pydantic model."""

    def test_provider_capabilities_creation(self) -> None:
        """Test creating ProviderCapabilities instance."""
        caps = ProviderCapabilities(
            provider=AIProvider.OPENAI,
            supports_streaming=True,
            supports_function_calling=True,
            supports_vision=True,
            free_tier_available=False,
        )

        assert caps.provider == AIProvider.OPENAI
        assert caps.supports_streaming is True
        assert caps.supports_function_calling is True
        assert caps.supports_vision is True
        assert caps.free_tier_available is False

    def test_provider_capabilities_defaults(self) -> None:
        """Test default values for ProviderCapabilities."""
        caps = ProviderCapabilities(provider=AIProvider.PUBLIC)

        # Defaults from model definition
        assert caps.supports_streaming is True
        assert caps.supports_function_calling is False
        assert caps.supports_vision is False
        assert caps.free_tier_available is False
