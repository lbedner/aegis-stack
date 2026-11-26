"""A chain call's model (``CascadeRealtimeModel``), built for the chat
model it thinks with (``for_call``), hearing and speaking in the voice
profile's own STT and TTS; each call on it a ``connection``."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
import io
from typing import Any
import wave

from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.realtime import RealtimeModel
from pydantic_ai.realtime.profiles import RealtimeModelProfile

from app.services.ai.models.provider_names import LOCAL_PROVIDERS
from app.services.ai.models.providers import AIProvider

from ..live_engines import split_model
from ..models import AudioFormat, AudioInput, SpeechRequest
from ..tts import realtime
from . import turns
from .connection import INPUT_RATE, OUTPUT_RATE, CascadeConnection

SYSTEM = "cascade"

Hear = Callable[[bytes], Awaitable[str]]
Say = Callable[[str], Awaitable[bytes]]


class CascadeRealtimeModel(RealtimeModel):
    """``brain`` (any chat model) on a call: ``hear`` turns a finished turn
    (PCM16 at 16 kHz) into its words, ``say`` a sentence into PCM16 at 24
    kHz, and ``ear`` makes each call's listener (``turns.Listener``). A
    ``warm`` brain reads the call's context while the opening plays: a
    local one's cache; a cloud one would bill the prompt for it."""

    def __init__(
        self,
        brain: Model,
        *,
        hear: Hear,
        say: Say,
        ear: Callable[[], turns.Listener] = turns.Listener,
        warm: bool = True,
    ) -> None:
        super().__init__(
            profile=RealtimeModelProfile(
                audio_input_sample_rate=INPUT_RATE,
                audio_output_sample_rate=OUTPUT_RATE,
                supports_interruption=True,
            )
        )
        self.brain, self._hear, self._say, self._ear = brain, hear, say, ear
        self.warm = warm

    @property
    def model_name(self) -> str:
        return self.brain.model_name

    @property
    def system(self) -> str:
        return SYSTEM

    @asynccontextmanager
    async def connect(
        self,
        *,
        messages: Sequence[ModelMessage],
        model_settings: Any,
        model_request_parameters: ModelRequestParameters,
    ) -> AsyncIterator[CascadeConnection]:
        connection = CascadeConnection(
            self,
            list(messages),
            self._merge_model_settings(model_settings),
            model_request_parameters,
        )
        try:
            yield connection
        finally:
            await connection.close()


def local(model: str) -> bool:
    """Whether ``model`` (a Pydantic AI model string) runs on this machine:
    its prompt is minutes of prefill, so it is warmed before the first
    question."""
    return split_model(model)[0] in LOCAL_PROVIDERS


async def for_call(ai: Any, model: str, *, user_id: str | None) -> CascadeRealtimeModel:
    """The cascade on ``model`` ("llamacpp:<id>", "anthropic:<id>"), hearing
    and speaking in the voice profile's own STT and TTS (``ai.stt``,
    ``ai.tts``), what they spend recorded against the caller (``user_id``)."""
    from app.core.config import settings
    from app.services.ai.domains.llm import providers
    from app.services.ai.domains.llm.config import AIServiceConfig

    provider, name = split_model(model)
    config = AIServiceConfig(provider=AIProvider(provider), model=name)
    brain, _ = await providers.model_for(config, settings)

    async def hear(pcm: bytes) -> str:
        audio = AudioInput(
            content=realtime.wav(pcm, INPUT_RATE),
            format=AudioFormat.WAV,
            sample_rate=INPUT_RATE,
        )
        return (await ai.stt.transcribe(audio, user_id=user_id)).text

    async def say(sentence: str) -> bytes:
        line = SpeechRequest(text=sentence, format=AudioFormat.WAV)
        return pcm_at(OUTPUT_RATE, (await ai.tts.synthesize(line, user_id)).audio)

    return CascadeRealtimeModel(brain, hear=hear, say=say, warm=local(model))


def pcm_at(rate: int, audio: bytes) -> bytes:
    """A mono WAV's sound as PCM16 at ``rate``, resampled when it is not."""
    with wave.open(io.BytesIO(audio)) as w:
        pcm, at = w.readframes(w.getnframes()), w.getframerate()
    if at == rate:
        return pcm
    import numpy as np

    samples = np.frombuffer(pcm, "<i2").astype(np.float32)
    times = np.arange(round(len(samples) * rate / at)) * at / rate
    return np.interp(times, np.arange(len(samples)), samples).astype("<i2").tobytes()
