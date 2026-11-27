"""
STT provider implementations.

Provides a unified interface for Speech-to-Text transcription across
multiple providers: OpenAI Whisper, Groq, and a hearing server of yours.
"""

from abc import ABC, abstractmethod
import io
import logging
from typing import Any

from ..models import (
    DEFAULT_STT_MODELS,
    AudioFormat,
    AudioInput,
    CannotRunError,
    STTProvider,
    TranscriptionResult,
    TranscriptionSegment,
    unserved,
)

logger = logging.getLogger(__name__)


class BaseSTTProvider(ABC):
    """Abstract base class for STT providers."""

    provider_type: STTProvider

    @abstractmethod
    async def transcribe(self, audio: AudioInput) -> TranscriptionResult:
        """Transcribe audio to text.

        Args:
            audio: AudioInput containing raw audio bytes and metadata.

        Returns:
            TranscriptionResult with transcribed text and metadata.

        Raises:
            RuntimeError: If transcription fails.
        """
        pass

    def _request(
        self, audio: AudioInput, model: str, response_format: str
    ) -> dict[str, Any]:
        """The transcription request the hosted Whisper APIs both take: the
        audio as a named file, and the language and spelling hint if set."""
        audio_file = io.BytesIO(audio.content)
        audio_file.name = f"audio{self._get_file_extension(audio.format)}"
        params: dict[str, Any] = {
            "model": model,
            "file": audio_file,
            "response_format": response_format,
        }
        if audio.language:
            params["language"] = audio.language
        if audio.prompt:
            params["prompt"] = audio.prompt
        return params

    def _get_file_extension(self, format: AudioFormat) -> str:
        """Get file extension for audio format."""
        return f".{format.value}"


def _transcribed(
    response: Any, audio: AudioInput, provider: STTProvider
) -> TranscriptionResult:
    """A hosted Whisper API's answer (OpenAI's shape, which Groq shares),
    with its segments when it gave any."""
    segments = [
        TranscriptionSegment(
            text=getattr(seg, "text", "").strip(),
            start=getattr(seg, "start", 0.0),
            end=getattr(seg, "end", 0.0),
        )
        for seg in getattr(response, "segments", None) or []
    ]
    return TranscriptionResult(
        text=response.text.strip(),
        language=getattr(response, "language", audio.language),
        duration_seconds=getattr(response, "duration", None),
        provider=provider,
        segments=segments or None,
    )


class OpenAIWhisperProvider(BaseSTTProvider):
    """OpenAI Whisper API provider.

    Uses the OpenAI API for high-quality cloud-based transcription.
    Requires OPENAI_API_KEY environment variable.
    """

    provider_type = STTProvider.OPENAI_WHISPER

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_STT_MODELS[STTProvider.OPENAI_WHISPER],
        base_url: str | None = None,
    ) -> None:
        """Initialize OpenAI Whisper provider.

        Args:
            api_key: OpenAI API key. If None, uses OPENAI_API_KEY env var.
            model: Whisper model to use (default: whisper-1).
            base_url: Optional base URL for OpenAI-compatible APIs.
        """
        self.api_key = api_key
        self.model = model
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

    async def transcribe(self, audio: AudioInput) -> TranscriptionResult:
        """Transcribe audio using OpenAI Whisper API."""
        client = self._get_client()

        whisper = self.model.startswith("whisper")  # gpt-4o-*: json only
        params = self._request(audio, self.model, "verbose_json" if whisper else "json")
        try:
            response = await client.audio.transcriptions.create(**params)
            return _transcribed(response, audio, self.provider_type)
        except Exception as e:
            logger.error(f"OpenAI Whisper transcription failed: {e}")
            raise RuntimeError(f"Transcription failed: {e}") from e


class GroqWhisperProvider(BaseSTTProvider):
    """Groq Whisper API provider.

    Ultra-fast cloud transcription using Groq's optimized inference.
    Requires GROQ_API_KEY environment variable.
    """

    provider_type = STTProvider.GROQ_WHISPER

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_STT_MODELS[STTProvider.GROQ_WHISPER],
    ) -> None:
        """Initialize Groq Whisper provider.

        Args:
            api_key: Groq API key. If None, uses GROQ_API_KEY env var.
            model: Whisper model (whisper-large-v3-turbo, whisper-large-v3).
        """
        self.api_key = api_key
        self.model = model
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazy-load the Groq client."""
        if self._client is None:
            try:
                from groq import AsyncGroq
            except ImportError as e:
                raise RuntimeError(
                    "Groq SDK not installed. Install with: uv add groq"
                ) from e

            kwargs: dict[str, Any] = {}
            if self.api_key:
                kwargs["api_key"] = self.api_key

            self._client = AsyncGroq(**kwargs)

        return self._client

    async def transcribe(self, audio: AudioInput) -> TranscriptionResult:
        """Transcribe audio using Groq Whisper API."""
        client = self._get_client()

        params = self._request(audio, self.model, "verbose_json")
        try:
            response = await client.audio.transcriptions.create(**params)
            return _transcribed(response, audio, self.provider_type)
        except Exception as e:
            logger.error(f"Groq Whisper transcription failed: {e}")
            raise RuntimeError(f"Transcription failed: {e}") from e


def get_stt_provider(
    provider: STTProvider,
    api_key: str | None = None,
    model: str | None = None,
    server_url: str | None = None,
) -> BaseSTTProvider:
    """The provider ``provider`` names, on ``model`` (else its default):
    ``api_key`` for a cloud one, ``server_url`` for a hearing server. Raises
    CannotRunError where its server's address is missing, ValueError for a
    provider it does not know."""
    if refused := unserved(provider, server_url):
        raise CannotRunError(refused)
    model = model or DEFAULT_STT_MODELS[provider]
    if provider == STTProvider.OPENAI_WHISPER:
        return OpenAIWhisperProvider(api_key=api_key, model=model)
    elif provider == STTProvider.GROQ_WHISPER:
        return GroqWhisperProvider(api_key=api_key, model=model)
    elif provider == STTProvider.HEARING_SERVER:
        from .server import ServerSTTProvider  # it imports this module

        return ServerSTTProvider(base_url=server_url or "", model=model)
    else:
        raise ValueError(f"Unsupported STT provider: {provider}")
