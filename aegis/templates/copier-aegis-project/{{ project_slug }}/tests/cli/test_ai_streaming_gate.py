"""Tests for the CLI chat streaming gate.

The gate must follow the provider capabilities matrix, not a hardcoded
provider list: any provider whose anonymous/free endpoint rejects
``stream=true`` (public/LLM7.io, pollinations) declares
``supports_streaming=False`` and must fall back to non-streaming chat.
"""

from app.cli.ai import _use_streaming
from app.services.ai.models import (
    PROVIDER_CAPABILITIES,
    AIProvider,
)


class TestUseStreaming:
    def test_follows_capabilities_for_every_provider(self) -> None:
        for provider, caps in PROVIDER_CAPABILITIES.items():
            assert _use_streaming(provider) is caps.supports_streaming

    def test_public_never_streams(self) -> None:
        assert _use_streaming(AIProvider.PUBLIC) is False

    def test_pollinations_never_streams(self) -> None:
        """The anonymous tier 402s on stream=true; the CLI must not send it."""
        assert _use_streaming(AIProvider.POLLINATIONS) is False

    def test_streaming_provider_streams(self) -> None:
        assert _use_streaming(AIProvider.OPENAI) is True

    def test_caller_can_opt_out(self) -> None:
        assert _use_streaming(AIProvider.OPENAI, requested=False) is False
