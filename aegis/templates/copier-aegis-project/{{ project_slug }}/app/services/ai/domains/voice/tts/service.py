"""
Text-to-Speech service.

Provides a high-level interface for speech synthesis with provider abstraction,
configuration management, and streaming support.
"""

from collections.abc import AsyncIterator
import logging
import time
from typing import Any

from ..models import SpeechRequest, SpeechResult, TTSProvider
from .config import TTSConfig, get_tts_config
from .providers import BaseTTSProvider, get_tts_provider

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
        self._provider_key: str | None = None

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

    async def _get_api_key(self) -> str | None:
        """Get API key for the current provider."""
        if self._explicit_api_key:
            return self._explicit_api_key

        if self._settings:
            return await self._config.get_api_key(self._settings)

        return None

    async def _get_provider(self) -> BaseTTSProvider:
        """Get or create the TTS provider instance; rebuilt when the
        key changes, so one saved while the app runs takes effect."""
        api_key = await self._get_api_key()
        if self._provider_instance is None or api_key != self._provider_key:
            self._provider_key = api_key
            provider_type = self.provider_type
            model = self.model
            voice = self.voice

            logger.info(f"Initializing TTS provider: {provider_type.value}")

            self._provider_instance = get_tts_provider(
                provider=provider_type,
                api_key=api_key,
                model=model,
                voice=voice,
            )

        return self._provider_instance

    def _configured(self, request: SpeechRequest) -> SpeechRequest:
        """The request with what it leaves unset taken from the settings.
        The settings' speed and delivery instructions are sent unless the
        request names its own."""
        return request.model_copy(
            update={
                "speed": request.speed or self._config.speed,
                "instructions": request.instructions or self._config.instructions,
            }
        )

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
        provider = await self._get_provider()

        logger.debug(
            f"Synthesizing speech ({len(request.text)} chars, "
            f"voice={request.voice or self.voice}) with {provider.provider_type.value}"
        )

        start_time = time.perf_counter()
        result: SpeechResult | None = None
        error_message: str | None = None
        success = True

        try:
            result = await provider.synthesize(self._configured(request))

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
                output_duration_seconds=result.duration_seconds if result else None,
                latency_ms=latency_ms,
                user_id=user_id,
                success=success,
                error_message=error_message,
            )

    async def synthesize_stream(
        self, request: SpeechRequest, user_id: str | None = None
    ) -> AsyncIterator[bytes]:
        """Stream synthesized audio, recorded like ``synthesize`` once the
        last chunk has gone (or the stream failed).

        Args:
            request: SpeechRequest containing text and synthesis options.
            user_id: Optional user identifier for usage tracking.

        Yields:
            Audio data chunks as bytes.

        Raises:
            RuntimeError: If synthesis fails.
        """
        provider = await self._get_provider()

        logger.debug(
            f"Streaming speech synthesis ({len(request.text)} chars) "
            f"with {provider.provider_type.value}"
        )

        start_time = time.perf_counter()
        error_message: str | None = None
        try:
            async for chunk in provider.synthesize_stream(self._configured(request)):
                yield chunk
        except Exception as e:
            error_message = str(e)
            raise
        finally:
            await self._record_usage(
                input_characters=len(request.text),
                output_duration_seconds=None,
                latency_ms=int((time.perf_counter() - start_time) * 1000),
                user_id=user_id,
                success=error_message is None,
                error_message=error_message,
            )

    def reset_provider(self) -> None:
        """Reset the provider instance.

        Call this after changing configuration to force re-initialization.
        """
        self._provider_instance = None

    async def validate(self) -> list[str]:
        """Validate the TTS configuration.

        Returns:
            List of validation error messages (empty if valid).
        """
        if self._settings:
            return await self._config.validation_errors(self._settings)
        return []

    async def is_available(self) -> bool:
        """Check if the configured TTS provider is available.

        Returns:
            True if the provider is properly configured and available.
        """
        if self._settings:
            return await self._config.is_available(self._settings)
        # Without settings, assume available (will fail at runtime if not)
        return True

    async def get_status(self) -> dict[str, Any]:
        """Get TTS service status information.

        Returns:
            Dictionary with provider type, model, voice, availability, and validation info.
        """
        errors = await self.validate()
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
        output_duration_seconds: float | None,
        latency_ms: int,
        user_id: str | None,
        success: bool,
        error_message: str | None,
    ) -> None:
        """The spoken reply's row in the usage ledger, priced at the
        catalog's rates (by the character, or by the second of speech).
        Never fails the request."""
        try:
            from app.services.ai import usage_recording
        except ImportError:
            # A project generated without a database has no ledger (and no
            # app.core.db at all). The recording call stays in the path so
            # the code is one shape everywhere; there is simply nowhere to
            # write, and a warning per request would be worse than silence.
            return
        await usage_recording.record_speech(
            usage_recording.TTS_ACTION,
            self.model,
            cost=await usage_recording.speech_cost(
                self.model,
                characters=input_characters,
                output_seconds=output_duration_seconds,
            ),
            seconds=output_duration_seconds,
            duration_ms=latency_ms,
            user_id=user_id,
            success=success,
            error_message=error_message,
        )
