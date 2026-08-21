"""Tests for AIServiceConfig.validate_configuration keyless providers."""

import pytest

from app.services.ai.config import AIServiceConfig
from app.services.ai.models import AIProvider


class _NoKeysSettings:
    """Settings stand-in with no provider API keys configured."""


class TestKeylessProvidersValidate:
    @pytest.mark.parametrize(
        "provider",
        [AIProvider.PUBLIC, AIProvider.OLLAMA, AIProvider.POLLINATIONS],
    )
    def test_keyless_provider_validates_without_api_key(
        self, provider: AIProvider
    ) -> None:
        """Keyless providers must not be flagged as missing an API key."""
        config = AIServiceConfig(provider=provider)

        assert config.validate_configuration(_NoKeysSettings()) == []

    def test_keyed_provider_requires_api_key(self) -> None:
        config = AIServiceConfig(provider=AIProvider.OPENAI)

        errors = config.validate_configuration(_NoKeysSettings())

        assert errors, "keyed provider without a key must fail validation"
