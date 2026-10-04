"""
TTS provider implementations.

Provides a unified interface for Text-to-Speech synthesis.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
import logging
from typing import Any

from ..models import (
    DEFAULT_TTS_MODEL,
    DEFAULT_TTS_VOICE,
    INSTRUCTED_TTS_MODELS,
    AudioFormat,
    SpeechRequest,
    SpeechResult,
    TTSProvider,
)

logger = logging.getLogger(__name__)


class BaseTTSProvider(ABC):
    """Abstract base class for TTS providers."""

    provider_type: TTSProvider

    @abstractmethod
    async def synthesize(self, request: SpeechRequest) -> SpeechResult:
        """Synthesize speech from text.

        Args:
            request: SpeechRequest containing text and synthesis options.

        Returns:
            SpeechResult with synthesized audio data and metadata.

        Raises:
            RuntimeError: If synthesis fails.
        """
        pass

    async def synthesize_stream(self, request: SpeechRequest) -> AsyncIterator[bytes]:
        """Stream synthesized audio chunks.

        Default implementation falls back to non-streaming synthesis.
        Override in providers that support native streaming.

        Args:
            request: SpeechRequest containing text and synthesis options.

        Yields:
            Audio data chunks as bytes.
        """
        result = await self.synthesize(request)
        yield result.audio


class OpenAITTSProvider(BaseTTSProvider):
    """OpenAI TTS API provider.

    Uses the OpenAI API for high-quality cloud-based speech synthesis.
    Requires OPENAI_API_KEY environment variable.

    Supports two models:
    - tts-1: Optimized for speed
    - tts-1-hd: Higher quality, slightly slower
    """

    provider_type = TTSProvider.OPENAI

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_TTS_MODEL,
        voice: str = DEFAULT_TTS_VOICE,
        base_url: str | None = None,
    ) -> None:
        """Initialize OpenAI TTS provider.

        Args:
            api_key: OpenAI API key. If None, uses OPENAI_API_KEY env var.
            model: TTS model to use (tts-1 or tts-1-hd).
            voice: Default voice (alloy, echo, fable, onyx, nova, shimmer).
            base_url: Optional base URL for OpenAI-compatible APIs.
        """
        self.api_key = api_key
        self.model = model
        self.default_voice = voice
        self.base_url = base_url
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazy-load the OpenAI client."""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as e:
                raise RuntimeError(
                    "OpenAI SDK not installed. Install with: uv add openai"
                ) from e

            kwargs: dict[str, Any] = {}
            if self.api_key:
                kwargs["api_key"] = self.api_key
            if self.base_url:
                kwargs["base_url"] = self.base_url

            self._client = AsyncOpenAI(**kwargs)

        return self._client

    def _speech_kwargs(self, request: SpeechRequest) -> dict[str, Any]:
        """One set of arguments for the whole-file and the streamed call.
        ``speed`` works on every model (measured on gpt-4o-mini-tts: 6.40s ->
        4.95s at 1.5); ``instructions`` - tone, emotion, pacing - only on the
        gpt-4o ones, and tts-1 refuses it."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "voice": request.voice or self.default_voice,
            "input": request.text,
            "response_format": "mp3",
        }
        if request.speed:
            kwargs["speed"] = request.speed
        if request.instructions and self.model in INSTRUCTED_TTS_MODELS:
            kwargs["instructions"] = request.instructions
        return kwargs

    async def synthesize(self, request: SpeechRequest) -> SpeechResult:
        """Synthesize speech using OpenAI TTS API."""
        client = self._get_client()

        try:
            response = await client.audio.speech.create(**self._speech_kwargs(request))

            # Read the audio content
            audio_data = response.content

            return SpeechResult(
                audio=audio_data,
                format=AudioFormat.MP3,
                provider=self.provider_type,
            )

        except Exception as e:
            logger.error(f"OpenAI TTS synthesis failed: {e}")
            raise RuntimeError(f"Speech synthesis failed: {e}") from e

    async def synthesize_stream(self, request: SpeechRequest) -> AsyncIterator[bytes]:
        """Stream audio from OpenAI TTS."""
        client = self._get_client()

        # Passed on as OpenAI generates it: awaiting the whole response and
        # slicing it made a long answer wait for all of its audio before the
        # first byte left.
        try:
            async with client.audio.speech.with_streaming_response.create(
                **self._speech_kwargs(request)
            ) as response:
                async for chunk in response.iter_bytes(4096):
                    yield chunk

        except Exception as e:
            logger.error(f"OpenAI TTS streaming failed: {e}")
            raise RuntimeError(f"Speech synthesis failed: {e}") from e


def get_tts_provider(
    provider: TTSProvider,
    api_key: str | None = None,
    model: str | None = None,
    voice: str | None = None,
    **kwargs: Any,
) -> BaseTTSProvider:
    """Factory function to create a TTS provider instance.

    Args:
        provider: The TTS provider type to create.
        api_key: Optional API key for cloud providers.
        model: Optional model name to use.
        voice: Optional voice name to use.
        **kwargs: Additional provider-specific arguments.

    Returns:
        Configured TTS provider instance.

    Raises:
        ValueError: If provider type is not supported.
    """
    if provider == TTSProvider.OPENAI:
        return OpenAITTSProvider(
            api_key=api_key,
            model=model or DEFAULT_TTS_MODEL,
            voice=voice or DEFAULT_TTS_VOICE,
            **kwargs,
        )
    else:
        raise ValueError(f"Unsupported TTS provider: {provider}")
