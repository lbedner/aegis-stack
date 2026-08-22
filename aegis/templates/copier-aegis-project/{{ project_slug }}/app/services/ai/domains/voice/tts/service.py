"""
Text-to-Speech service.

Provides a high-level interface for speech synthesis with provider abstraction,
configuration management, and streaming support.
"""

import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from app.core.db import get_async_session

from ..models import SpeechRequest, SpeechResult, TTSProvider
from .config import TTSConfig, get_tts_config
from .providers import BaseTTSProvider, get_tts_provider
from .usage import TTSUsage

logger = logging.getLogger(__name__)


class TTSService:
    """Text-to-Speech service with provider abstraction.

    Manages TTS provider lifecycle and provides a unified synthesis interface.
    Supports lazy-loading of providers and configuration from application settings.

    Example usage:
        ```python
        from app.services.ai.domains.voice.tts import TTSService, SpeechRequest

        # Initialize with settings
        tts = TTSService(settings)

        # Or with explicit configuration
        from app.services.ai.domains.voice.models import TTSProvider
        tts = TTSService(provider=TTSProvider.OPENAI, voice="nova")

        # Synthesize speech
        request = SpeechRequest(text="Hello, world!")
        result = await tts.synthesize(request)

        # Save audio
        with open("hello.mp3", "wb") as f:
            f.write(result.audio)
        ```
    """

    def __init__(
        self,
        settings: Any | None = None,
        provider: TTSProvider | None = None,
        model: str | None = None,
        voice: str | None = None,
        api_key: str | None = None,
    ) -> None:
        """Initialize TTS service.

        Args:
            settings: Application settings object (optional).
                If provided, reads TTS configuration from settings.
            provider: Explicit TTS provider to use (overrides settings).
            model: Explicit model name to use (overrides settings).
            voice: Explicit voice to use (overrides settings).
            api_key: Explicit API key for cloud providers (overrides settings).
        """
        self._settings = settings
        self._explicit_api_key = api_key
        self._provider_instance: BaseTTSProvider | None = None

        # Build config from settings or explicit values
        if provider or model or voice:
            # Explicit configuration overrides settings
            self._config = TTSConfig(
                provider=provider or TTSProvider.OPENAI,
                model=model,
                voice=voice,
            )
        elif settings:
            # Load from settings
            self._config = get_tts_config(settings)
        else:
            # Default configuration
            self._config = TTSConfig()

    @property
    def config(self) -> TTSConfig:
        """Get the current TTS configuration."""
        return self._config

    @property
    def provider_type(self) -> TTSProvider:
        """Get the configured TTS provider type."""
        return self._config.provider

    @property
    def model(self) -> str:
        """Get the configured model name (with provider default fallback)."""
        return self._config.get_model()

    @property
    def voice(self) -> str:
        """Get the configured voice (with provider default fallback)."""
        return self._config.get_voice()

    def _get_api_key(self) -> str | None:
        """Get API key for the current provider."""
        if self._explicit_api_key:
            return self._explicit_api_key

        if self._settings:
            return self._config.get_api_key(self._settings)

        return None

    def _get_provider(self) -> BaseTTSProvider:
        """Get or create the TTS provider instance."""
        if self._provider_instance is None:
            provider_type = self.provider_type
            model = self.model
            voice = self.voice
            api_key = self._get_api_key()

            logger.info(f"Initializing TTS provider: {provider_type.value}")

            self._provider_instance = get_tts_provider(
                provider=provider_type,
                api_key=api_key,
                model=model,
                voice=voice,
            )

        return self._provider_instance

    async def synthesize(
        self,
        request: SpeechRequest,
        user_id: str | None = None,
    ) -> SpeechResult:
        """Synthesize speech from text.

        Args:
            request: SpeechRequest containing text and synthesis options.
            user_id: Optional user identifier for usage tracking.

        Returns:
            SpeechResult with synthesized audio data and metadata.

        Raises:
            RuntimeError: If synthesis fails.
        """
        provider = self._get_provider()

        logger.debug(
            f"Synthesizing speech ({len(request.text)} chars, "
            f"voice={request.voice or self.voice}) with {provider.provider_type.value}"
        )

        start_time = time.perf_counter()
        result: SpeechResult | None = None
        error_message: str | None = None
        success = True

        try:
            result = await provider.synthesize(request)

            logger.debug(
                f"Synthesis complete: {len(result.audio)} bytes, "
                f"format={result.format.value}"
            )

            return result

        except Exception as e:
            success = False
            error_message = str(e)
            raise

        finally:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            await self._record_usage(
                input_characters=len(request.text),
                output_bytes=len(result.audio) if result else None,
                output_duration_seconds=result.duration_seconds if result else None,
                voice=request.voice or self.voice,
                latency_ms=latency_ms,
                user_id=user_id,
                success=success,
                error_message=error_message,
            )

    async def synthesize_stream(self, request: SpeechRequest) -> AsyncIterator[bytes]:
        """Stream synthesized audio.

        Args:
            request: SpeechRequest containing text and synthesis options.

        Yields:
            Audio data chunks as bytes.

        Raises:
            RuntimeError: If synthesis fails.
        """
        provider = self._get_provider()

        logger.debug(
            f"Streaming speech synthesis ({len(request.text)} chars) "
            f"with {provider.provider_type.value}"
        )

        async for chunk in provider.synthesize_stream(request):
            yield chunk

    def reset_provider(self) -> None:
        """Reset the provider instance.

        Call this after changing configuration to force re-initialization.
        """
        self._provider_instance = None

    def validate(self) -> list[str]:
        """Validate the TTS configuration.

        Returns:
            List of validation error messages (empty if valid).
        """
        if self._settings:
            return self._config.validate(self._settings)
        return []

    def is_available(self) -> bool:
        """Check if the configured TTS provider is available.

        Returns:
            True if the provider is properly configured and available.
        """
        if self._settings:
            return self._config.is_available(self._settings)
        # Without settings, assume available (will fail at runtime if not)
        return True

    def get_status(self) -> dict[str, Any]:
        """Get TTS service status information.

        Returns:
            Dictionary with provider type, model, voice, availability, and validation info.
        """
        errors = self.validate()
        return {
            "provider": self.provider_type.value,
            "model": self.model,
            "voice": self.voice,
            "speed": self._config.speed,
            "initialized": self._provider_instance is not None,
            "available": len(errors) == 0,
            "errors": errors if errors else None,
        }

    async def _record_usage(
        self,
        input_characters: int,
        output_bytes: int | None,
        output_duration_seconds: float | None,
        voice: str | None,
        latency_ms: int,
        user_id: str | None,
        success: bool,
        error_message: str | None,
    ) -> None:
        """Record TTS usage to database.

        Args:
            input_characters: Length of input text.
            output_bytes: Size of output audio in bytes.
            output_duration_seconds: Duration of output audio.
            voice: Voice ID used for synthesis.
            latency_ms: Request latency in milliseconds.
            user_id: Optional user identifier.
            success: Whether synthesis succeeded.
            error_message: Error message if synthesis failed.
        """
        try:
            async with get_async_session() as session:
                usage = TTSUsage(
                    provider=self.provider_type.value,
                    model=self.model,
                    voice=voice,
                    user_id=user_id,
                    timestamp=datetime.now(UTC),
                    input_characters=input_characters,
                    output_duration_seconds=output_duration_seconds,
                    output_bytes=output_bytes,
                    latency_ms=latency_ms,
                    total_cost=0.0,  # TODO: Calculate cost based on provider pricing
                    success=success,
                    error_message=error_message,
                )
                session.add(usage)

            logger.debug(
                f"TTS usage recorded: {input_characters} chars, "
                f"{latency_ms}ms, success={success}"
            )

        except Exception as e:
            # Don't fail the request if usage tracking fails
            logger.warning(f"Failed to record TTS usage: {e}")
