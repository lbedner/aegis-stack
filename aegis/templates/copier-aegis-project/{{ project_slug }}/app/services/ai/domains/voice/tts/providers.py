"""
TTS provider implementations.

Provides a unified interface for Text-to-Speech synthesis.
"""

from abc import ABC, abstractmethod
import asyncio
import base64
from collections.abc import AsyncIterator
import logging
from typing import Any

from ..models import (
    DEFAULT_TTS_MODEL,
    DEFAULT_TTS_MODELS,
    DEFAULT_TTS_VOICE,
    DEFAULT_TTS_VOICES,
    INSTRUCTED_TTS_MODELS,
    REALTIME_TTS_MODELS,
    TTS_FORMATS,
    AudioFormat,
    SpeechRequest,
    SpeechResult,
    TTSProvider,
)
from . import length, realtime

logger = logging.getLogger(__name__)

# A Gemini speech model out of its quota (the free tier's is ten requests a
# day for each) answers 429 at once, and its SDK would retry that on the
# answer's Retry-After: hours, a preview spinning on. Its client retries
# only a server's own trouble, and a 429, or a try with no answer in time,
# is said on the lite model, whose quota is its own; the caller is never
# left waiting on hours.
GEMINI_RETRIED = [408, 500, 502, 503, 504]
GEMINI_TRY_SECONDS = 20.0
GEMINI_SECONDS_PER_CHARACTER = 0.05
GEMINI_FALLBACK = "gemini-3.8-flash-lite-tts"


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
    """OpenAI's speech: gpt-realtime-2.1-mini over the Realtime API
    (``realtime``), or, until they shut down on Jan 6, 2027, the
    /v1/audio/speech models (gpt-4o-mini-tts, tts-1, tts-1-hd).
    Requires OPENAI_API_KEY.
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
            model: Speech model (the catalog's OpenAI ones).
            voice: Default voice (one the model speaks).
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

    async def _realtime(self, request: SpeechRequest) -> SpeechResult:
        """The line read by a realtime model, as a WAV, with its tokens."""
        try:
            pcm, tokens = await realtime.say(
                self._get_client(),
                self.model,
                request.text,
                voice=request.voice or self.default_voice,
                delivery=request.instructions,
                speed=request.speed,
            )
        except Exception as e:
            logger.error(f"OpenAI realtime speech failed: {e}")
            raise RuntimeError(f"Speech synthesis failed: {e}") from e
        wav = realtime.wav(pcm)
        return SpeechResult(
            audio=wav,
            format=AudioFormat.WAV,
            duration_seconds=length.wav_seconds(wav),
            provider=self.provider_type,
            tokens=tokens,
        )

    async def synthesize(self, request: SpeechRequest) -> SpeechResult:
        """Synthesize speech using OpenAI TTS API."""
        if self.model in REALTIME_TTS_MODELS:
            return await self._realtime(request)
        client = self._get_client()

        try:
            response = await client.audio.speech.create(**self._speech_kwargs(request))

            audio = response.content
            spoken_as = TTS_FORMATS[self.provider_type]
            return SpeechResult(
                audio=audio,
                format=spoken_as,
                duration_seconds=length.seconds(audio, spoken_as),
                provider=self.provider_type,
            )

        except Exception as e:
            logger.error(f"OpenAI TTS synthesis failed: {e}")
            raise RuntimeError(f"Speech synthesis failed: {e}") from e

    async def synthesize_stream(self, request: SpeechRequest) -> AsyncIterator[bytes]:
        """Stream audio from OpenAI's speech endpoint (``TTSService`` sends a
        model that cannot stream, a realtime one, to ``synthesize``)."""
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


class GeminiTTSProvider(BaseTTSProvider):
    """Gemini's speech models (``google-genai``'s Interactions API), in its
    voices: the 30 prebuilt ones Gemini Live speaks, or one from its voice
    library by id. The line is the transcript; the delivery
    (``instructions``) is its ``speech_metadata`` style. It answers with a
    WAV; it has no speed to set."""

    provider_type = TTSProvider.GEMINI

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_TTS_MODELS[TTSProvider.GEMINI],
        voice: str = DEFAULT_TTS_VOICES[TTSProvider.GEMINI],
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.default_voice = voice
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai
            from google.genai import types

            self._client = genai.Client(
                api_key=self.api_key,
                http_options=types.HttpOptions(
                    retry_options=types.HttpRetryOptions(
                        attempts=1, http_status_codes=GEMINI_RETRIED
                    )
                ),
            )
        return self._client

    async def synthesize(self, request: SpeechRequest) -> SpeechResult:
        text: dict[str, Any] = {"type": "text", "text": request.text}
        if request.instructions:
            text["annotations"] = [
                {"type": "speech_metadata", "style": request.instructions}
            ]
        try:
            said = await self._answered(
                len(request.text),
                model=self.model,
                input=[{"type": "user_input", "content": [text]}],
                response_format={"type": "audio"},
                generation_config={
                    "speech_config": [{"voice": request.voice or self.default_voice}]
                },
            )
            audio = base64.b64decode(said.output_audio.data)
        except Exception as e:
            logger.error(f"Gemini TTS synthesis failed: {e}")
            raise RuntimeError(f"Speech synthesis failed: {e}") from e
        return SpeechResult(
            audio=audio,
            format=TTS_FORMATS[self.provider_type],
            duration_seconds=length.wav_seconds(audio),
            provider=self.provider_type,
        )

    async def _answered(self, characters: int, **asked: Any) -> Any:
        """Gemini's answer to ``asked``: on its model, else (out of quota, or
        no answer in time) on the lite one, ``GEMINI_FALLBACK``. When neither
        can, the last refusal is raised, saying why."""
        wait = GEMINI_TRY_SECONDS + characters * GEMINI_SECONDS_PER_CHARACTER
        model = asked.pop("model")
        refused: Exception = TimeoutError("Gemini did not answer")
        for trying in dict.fromkeys((model, GEMINI_FALLBACK)):
            try:
                async with asyncio.timeout(wait):
                    return await self._get_client().aio.interactions.create(
                        model=trying, **asked
                    )
            except TimeoutError:
                refused = TimeoutError(
                    f"Gemini did not answer on {trying} in {wait:.0f}s"
                )
            except Exception as exc:
                if getattr(exc, "status_code", None) != 429:
                    raise
                refused = exc
            logger.warning(f"Gemini speech on {trying} could not: {refused}")
        raise refused


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
    elif provider == TTSProvider.GEMINI:
        return GeminiTTSProvider(
            api_key=api_key,
            model=model or DEFAULT_TTS_MODELS[provider],
            voice=voice or DEFAULT_TTS_VOICES[provider],
        )
    else:
        raise ValueError(f"Unsupported TTS provider: {provider}")
