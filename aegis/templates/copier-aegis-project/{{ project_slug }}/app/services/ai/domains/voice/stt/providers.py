"""
STT provider implementations.

Provides a unified interface for Speech-to-Text transcription across
multiple providers: OpenAI Whisper, local Whisper, faster-whisper, and Groq.
"""

import asyncio
import io
import logging
from abc import ABC, abstractmethod
from typing import Any

from ..models import (
    AudioFormat,
    AudioInput,
    STTProvider,
    TranscriptionResult,
    TranscriptionSegment,
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

    def _get_file_extension(self, format: AudioFormat) -> str:
        """Get file extension for audio format."""
        return f".{format.value}"


class OpenAIWhisperProvider(BaseSTTProvider):
    """OpenAI Whisper API provider.

    Uses the OpenAI API for high-quality cloud-based transcription.
    Requires OPENAI_API_KEY environment variable.
    """

    provider_type = STTProvider.OPENAI_WHISPER

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "whisper-1",
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

        # Create file-like object from bytes
        audio_file = io.BytesIO(audio.content)
        audio_file.name = f"audio{self._get_file_extension(audio.format)}"

        try:
            # Build request parameters
            params: dict[str, Any] = {
                "model": self.model,
                "file": audio_file,
                "response_format": "verbose_json",  # Get segments and duration
            }

            if audio.language:
                params["language"] = audio.language

            response = await client.audio.transcriptions.create(**params)

            # Parse segments if available
            segments: list[TranscriptionSegment] | None = None
            if hasattr(response, "segments") and response.segments:
                segments = [
                    TranscriptionSegment(
                        text=getattr(seg, "text", "").strip(),
                        start=getattr(seg, "start", 0.0),
                        end=getattr(seg, "end", 0.0),
                    )
                    for seg in response.segments
                ]

            return TranscriptionResult(
                text=response.text.strip(),
                language=getattr(response, "language", audio.language),
                duration_seconds=getattr(response, "duration", None),
                provider=self.provider_type,
                segments=segments,
            )

        except Exception as e:
            logger.error(f"OpenAI Whisper transcription failed: {e}")
            raise RuntimeError(f"Transcription failed: {e}") from e


class WhisperLocalProvider(BaseSTTProvider):
    """Local Whisper via HuggingFace transformers.

    Uses the transformers library to run Whisper locally.
    Requires: transformers, torch
    """

    provider_type = STTProvider.WHISPER_LOCAL

    def __init__(
        self,
        model_name: str = "openai/whisper-base",
        device: str | None = None,
    ) -> None:
        """Initialize local Whisper provider.

        Args:
            model_name: HuggingFace model name (default: openai/whisper-base).
                Options: whisper-tiny, whisper-base, whisper-small,
                        whisper-medium, whisper-large-v3
            device: Device to use ('cpu', 'cuda', 'mps'). Auto-detects if None.
        """
        self.model_name = model_name
        self.device = device
        self._pipeline: Any = None

    def _get_pipeline(self) -> Any:
        """Lazy-load the transformers pipeline."""
        if self._pipeline is None:
            try:
                import torch
                from transformers import pipeline
            except ImportError as e:
                raise RuntimeError(
                    "Transformers not installed. Install with: "
                    "uv add transformers torch"
                ) from e

            # Auto-detect device if not specified
            device = self.device
            if device is None:
                if torch.cuda.is_available():
                    device = "cuda"
                elif (
                    hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
                ):
                    device = "mps"
                else:
                    device = "cpu"

            logger.info(f"Loading Whisper model {self.model_name} on {device}")

            self._pipeline = pipeline(
                "automatic-speech-recognition",
                model=self.model_name,
                device=device,
                chunk_length_s=30,
                return_timestamps=True,
            )

        return self._pipeline

    async def transcribe(self, audio: AudioInput) -> TranscriptionResult:
        """Transcribe audio using local Whisper model."""
        pipe = self._get_pipeline()

        try:
            # Run inference in thread pool to avoid blocking
            loop = asyncio.get_event_loop()

            def _transcribe() -> dict[str, Any]:
                result: dict[str, Any] = pipe(
                    audio.content,
                    generate_kwargs={"language": audio.language}
                    if audio.language
                    else {},
                )
                return result

            result = await loop.run_in_executor(None, _transcribe)

            # Parse segments if available (chunks from transformers)
            segments: list[TranscriptionSegment] | None = None
            if "chunks" in result:
                segments = [
                    TranscriptionSegment(
                        text=chunk["text"].strip(),
                        start=chunk["timestamp"][0] if chunk["timestamp"] else 0.0,
                        end=chunk["timestamp"][1]
                        if chunk["timestamp"] and len(chunk["timestamp"]) > 1
                        else 0.0,
                    )
                    for chunk in result["chunks"]
                    if chunk.get("text")
                ]

            return TranscriptionResult(
                text=result["text"].strip(),
                language=audio.language,
                provider=self.provider_type,
                segments=segments,
            )

        except Exception as e:
            logger.error(f"Local Whisper transcription failed: {e}")
            raise RuntimeError(f"Transcription failed: {e}") from e


class FasterWhisperProvider(BaseSTTProvider):
    """SYSTRAN faster-whisper for optimized local inference.

    4x faster than OpenAI Whisper with similar accuracy.
    Requires: faster-whisper
    """

    provider_type = STTProvider.FASTER_WHISPER

    def __init__(
        self,
        model_size: str = "base",
        device: str = "auto",
        compute_type: str = "default",
    ) -> None:
        """Initialize faster-whisper provider.

        Args:
            model_size: Model size (tiny, base, small, medium, large-v3).
            device: Device ('cpu', 'cuda', 'auto'). Auto-detects if 'auto'.
            compute_type: Compute precision ('default', 'float16', 'int8').
        """
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model: Any = None

    def _get_model(self) -> Any:
        """Lazy-load the faster-whisper model."""
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as e:
                raise RuntimeError(
                    "faster-whisper not installed. Install with: uv add faster-whisper"
                ) from e

            logger.info(f"Loading faster-whisper model {self.model_size}")

            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )

        return self._model

    async def transcribe(self, audio: AudioInput) -> TranscriptionResult:
        """Transcribe audio using faster-whisper."""
        model = self._get_model()

        try:
            # Run inference in thread pool
            loop = asyncio.get_event_loop()

            def _transcribe() -> tuple[Any, Any]:
                # faster-whisper expects a file path or numpy array
                # Create temp file from bytes
                import tempfile

                with tempfile.NamedTemporaryFile(
                    suffix=self._get_file_extension(audio.format), delete=False
                ) as f:
                    f.write(audio.content)
                    temp_path = f.name

                try:
                    segments_iter, info = model.transcribe(
                        temp_path,
                        language=audio.language,
                        beam_size=5,
                        word_timestamps=True,
                    )
                    # Consume iterator
                    segments_list = list(segments_iter)
                    return segments_list, info
                finally:
                    import os

                    os.unlink(temp_path)

            segments_list, info = await loop.run_in_executor(None, _transcribe)

            # Build result
            full_text = " ".join(seg.text.strip() for seg in segments_list)

            segments = [
                TranscriptionSegment(
                    text=seg.text.strip(),
                    start=seg.start,
                    end=seg.end,
                    confidence=seg.avg_logprob if hasattr(seg, "avg_logprob") else None,
                )
                for seg in segments_list
            ]

            return TranscriptionResult(
                text=full_text,
                language=info.language,
                duration_seconds=info.duration,
                provider=self.provider_type,
                segments=segments if segments else None,
            )

        except Exception as e:
            logger.error(f"faster-whisper transcription failed: {e}")
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
        model: str = "whisper-large-v3-turbo",
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

        # Create file-like object from bytes
        audio_file = io.BytesIO(audio.content)
        audio_file.name = f"audio{self._get_file_extension(audio.format)}"

        try:
            # Build request parameters
            params: dict[str, Any] = {
                "model": self.model,
                "file": audio_file,
                "response_format": "verbose_json",
            }

            if audio.language:
                params["language"] = audio.language

            response = await client.audio.transcriptions.create(**params)

            # Parse segments if available
            segments: list[TranscriptionSegment] | None = None
            if hasattr(response, "segments") and response.segments:
                segments = [
                    TranscriptionSegment(
                        text=getattr(seg, "text", "").strip(),
                        start=getattr(seg, "start", 0.0),
                        end=getattr(seg, "end", 0.0),
                    )
                    for seg in response.segments
                ]

            return TranscriptionResult(
                text=response.text.strip(),
                language=getattr(response, "language", audio.language),
                duration_seconds=getattr(response, "duration", None),
                provider=self.provider_type,
                segments=segments,
            )

        except Exception as e:
            logger.error(f"Groq Whisper transcription failed: {e}")
            raise RuntimeError(f"Transcription failed: {e}") from e


def get_stt_provider(
    provider: STTProvider,
    api_key: str | None = None,
    model: str | None = None,
    **kwargs: Any,
) -> BaseSTTProvider:
    """Factory function to create an STT provider instance.

    Args:
        provider: The STT provider type to create.
        api_key: Optional API key for cloud providers.
        model: Optional model name/size to use.
        **kwargs: Additional provider-specific arguments.

    Returns:
        Configured STT provider instance.

    Raises:
        ValueError: If provider type is not supported.
    """
    if provider == STTProvider.OPENAI_WHISPER:
        return OpenAIWhisperProvider(
            api_key=api_key,
            model=model or "whisper-1",
            **kwargs,
        )
    elif provider == STTProvider.WHISPER_LOCAL:
        return WhisperLocalProvider(
            model_name=model or "openai/whisper-base",
            **kwargs,
        )
    elif provider == STTProvider.FASTER_WHISPER:
        return FasterWhisperProvider(
            model_size=model or "base",
            **kwargs,
        )
    elif provider == STTProvider.GROQ_WHISPER:
        return GroqWhisperProvider(
            api_key=api_key,
            model=model or "whisper-large-v3-turbo",
            **kwargs,
        )
    else:
        raise ValueError(f"Unsupported STT provider: {provider}")
