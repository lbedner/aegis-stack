"""
Speech-to-Text service.

Provides a high-level interface for transcription with provider abstraction,
configuration management, and optional caching.
"""

import logging
import time
from datetime import UTC, datetime
from typing import Any

from app.core.db import get_async_session

from ..models import AudioInput, STTProvider, TranscriptionResult
from .config import STTConfig, get_stt_config
from .providers import BaseSTTProvider, get_stt_provider
from .usage import STTUsage

logger = logging.getLogger(__name__)


class STTService:
    """Speech-to-Text service with provider abstraction.

    Manages STT provider lifecycle and provides a unified transcription interface.
    Supports lazy-loading of providers and configuration from application settings.

    Example usage:
        ```python
        from app.services.ai.domains.voice.stt import STTService
        from app.services.ai.domains.voice.models import AudioInput, STTProvider

        # Initialize with settings
        stt = STTService(settings)

        # Or with explicit configuration
        stt = STTService(provider=STTProvider.OPENAI_WHISPER, model="whisper-1")

        # Transcribe audio
        audio = AudioInput(content=audio_bytes, format="wav")
        result = await stt.transcribe(audio)
        print(result.text)
        ```
    """

    def __init__(
        self,
        settings: Any | None = None,
        provider: STTProvider | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        """Initialize STT service.

        Args:
            settings: Application settings object (optional).
                If provided, reads STT configuration from settings.
            provider: Explicit STT provider to use (overrides settings).
            model: Explicit model name/size to use (overrides settings).
            api_key: Explicit API key for cloud providers (overrides settings).
        """
        self._settings = settings
        self._explicit_api_key = api_key
        self._provider_instance: BaseSTTProvider | None = None

        # Build config from settings or explicit values
        if provider or model:
            # Explicit configuration overrides settings
            self._config = STTConfig(
                provider=provider or STTProvider.OPENAI_WHISPER,
                model=model,
            )
        elif settings:
            # Load from settings
            self._config = get_stt_config(settings)
        else:
            # Default configuration
            self._config = STTConfig()

    @property
    def config(self) -> STTConfig:
        """Get the current STT configuration."""
        return self._config

    @property
    def provider_type(self) -> STTProvider:
        """Get the configured STT provider type."""
        return self._config.provider

    @property
    def model(self) -> str:
        """Get the configured model name/size (with provider default fallback)."""
        return self._config.get_model()

    def _get_api_key(self) -> str | None:
        """Get API key for the current provider."""
        if self._explicit_api_key:
            return self._explicit_api_key

        if self._settings:
            return self._config.get_api_key(self._settings)

        return None

    def _get_provider(self) -> BaseSTTProvider:
        """Get or create the STT provider instance."""
        if self._provider_instance is None:
            provider_type = self.provider_type
            model = self.model
            api_key = self._get_api_key()

            logger.info(f"Initializing STT provider: {provider_type.value}")

            # Build provider-specific kwargs
            kwargs: dict[str, Any] = {}

            # Add device for local providers if configured
            if provider_type == STTProvider.WHISPER_LOCAL and self._config.device:
                kwargs["device"] = self._config.device

            self._provider_instance = get_stt_provider(
                provider=provider_type,
                api_key=api_key,
                model=model,
                **kwargs,
            )

        return self._provider_instance

    async def transcribe(
        self,
        audio: AudioInput,
        user_id: str | None = None,
    ) -> TranscriptionResult:
        """Transcribe audio to text.

        Args:
            audio: AudioInput containing raw audio bytes and metadata.
            user_id: Optional user identifier for usage tracking.

        Returns:
            TranscriptionResult with transcribed text and metadata.

        Raises:
            RuntimeError: If transcription fails.
        """
        provider = self._get_provider()

        logger.debug(
            f"Transcribing audio ({len(audio.content)} bytes, "
            f"format={audio.format.value}) with {provider.provider_type.value}"
        )

        start_time = time.perf_counter()
        result: TranscriptionResult | None = None
        error_message: str | None = None
        success = True

        try:
            result = await provider.transcribe(audio)

            logger.debug(
                f"Transcription complete: {len(result.text)} chars, "
                f"language={result.language}"
            )

            return result

        except Exception as e:
            success = False
            error_message = str(e)
            raise

        finally:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            await self._record_usage(
                input_bytes=len(audio.content),
                input_duration_seconds=audio.duration_seconds,
                output_characters=len(result.text) if result else None,
                detected_language=result.language if result else None,
                latency_ms=latency_ms,
                user_id=user_id,
                success=success,
                error_message=error_message,
            )

    def reset_provider(self) -> None:
        """Reset the provider instance.

        Call this after changing configuration to force re-initialization.
        """
        self._provider_instance = None

    def validate(self) -> list[str]:
        """Validate the STT configuration.

        Returns:
            List of validation error messages (empty if valid).
        """
        if self._settings:
            return self._config.validate(self._settings)
        return []

    def is_available(self) -> bool:
        """Check if the configured STT provider is available.

        Returns:
            True if the provider is properly configured and available.
        """
        if self._settings:
            return self._config.is_available(self._settings)
        # Without settings, assume available (will fail at runtime if not)
        return True

    def get_status(self) -> dict[str, Any]:
        """Get STT service status information.

        Returns:
            Dictionary with provider type, model, availability, and validation info.
        """
        errors = self.validate()
        return {
            "provider": self.provider_type.value,
            "model": self.model,
            "language": self._config.language,
            "device": self._config.device,
            "initialized": self._provider_instance is not None,
            "available": len(errors) == 0,
            "errors": errors if errors else None,
        }

    async def _record_usage(
        self,
        input_bytes: int,
        input_duration_seconds: float | None,
        output_characters: int | None,
        detected_language: str | None,
        latency_ms: int,
        user_id: str | None,
        success: bool,
        error_message: str | None,
    ) -> None:
        """Record STT usage to database.

        Args:
            input_bytes: Size of input audio in bytes.
            input_duration_seconds: Duration of input audio.
            output_characters: Length of transcribed text.
            detected_language: Detected or specified language.
            latency_ms: Request latency in milliseconds.
            user_id: Optional user identifier.
            success: Whether transcription succeeded.
            error_message: Error message if transcription failed.
        """
        try:
            async with get_async_session() as session:
                usage = STTUsage(
                    provider=self.provider_type.value,
                    model=self.model,
                    user_id=user_id,
                    timestamp=datetime.now(UTC),
                    input_duration_seconds=input_duration_seconds,
                    input_bytes=input_bytes,
                    output_characters=output_characters,
                    detected_language=detected_language,
                    latency_ms=latency_ms,
                    total_cost=0.0,  # TODO: Calculate cost based on provider pricing
                    success=success,
                    error_message=error_message,
                )
                session.add(usage)

            logger.debug(
                f"STT usage recorded: {input_bytes} bytes, "
                f"{latency_ms}ms, success={success}"
            )

        except Exception as e:
            # Don't fail the request if usage tracking fails
            logger.warning(f"Failed to record STT usage: {e}")
