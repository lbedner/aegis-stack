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
    async def test_keyless_provider_validates_without_api_key(
        self, provider: AIProvider
    ) -> None:
        """Keyless providers must not be flagged as missing an API key."""
        config = AIServiceConfig(provider=provider)

        assert await config.validate_configuration(_NoKeysSettings()) == []

    async def test_keyed_provider_requires_api_key(self) -> None:
        config = AIServiceConfig(provider=AIProvider.OPENAI)

        errors = await config.validate_configuration(_NoKeysSettings())

        assert errors, "keyed provider without a key must fail validation"


def test_an_agent_overlays_its_sampling_and_any_model_it_pins() -> None:
    """One overlay for every runner: sampling always, the model only when
    the agent pins one (``None`` follows the active model)."""
    from types import SimpleNamespace

    config = AIServiceConfig(
        provider=AIProvider.OLLAMA, model="active", temperature=0.7
    )
    assert config.for_agent(None) == config
    follows = config.for_agent(
        SimpleNamespace(temperature=0.1, max_tokens=300, model_id=None)
    )
    assert (follows.model, follows.temperature, follows.max_tokens) == (
        "active",
        0.1,
        300,
    )
    pinned = config.for_agent(
        SimpleNamespace(temperature=0.1, max_tokens=300, model_id="qwen3:4b")
    )
    assert pinned.model == "qwen3:4b"
