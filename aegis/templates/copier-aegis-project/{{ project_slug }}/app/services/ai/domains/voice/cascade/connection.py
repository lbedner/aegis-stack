"""A live call with no realtime model: the app runs the chain itself.

The caller's audio is heard (``turns``: Silero, then Smart Turn), each
finished turn transcribed (``hear``), answered by a chat model, tools and
all (``brain``), and the answer said a sentence at a time as it is written
(``say``). Built as a Pydantic AI realtime model, so a call on it takes the
one path every engine takes (``realtime_calls``): the relay, the tools, the
saved turns and the bill are the same as on Gemini Live.

It keeps the call's history itself, as a chat model reads it: the
session's own records speech as realtime parts, and this has to answer the
moment a turn ends, before the session has read the transcript.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager, suppress
import io
import re
from typing import Any
import wave

from pydantic_ai.messages import (
    BinaryAudio,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    PartDeltaEvent,
    PartStartEvent,
    RealtimeInputSpeechEndEvent,
    RealtimeInputSpeechStartEvent,
    RealtimeResponseInterruptedEvent,
    TextPart,
    TextPartDelta,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.realtime import RealtimeModel
from pydantic_ai.realtime.codec import (
    AudioDelta,
    CancelResponse,
    CreateResponse,
    InputTranscript,
    OutputTranscript,
    RealtimeCodecEvent,
    RealtimeConnection,
    RealtimeInput,
    ResponseDone,
    SessionUsage,
    TextContext,
    ToolCall,
    ToolResult,
)
from pydantic_ai.realtime.profiles import RealtimeModelProfile

try:  # Pydantic AI 2.6x on: a connection yields frames, its lifecycle in them
    from pydantic_ai.realtime.lifecycle import InferredLifecycle
except ImportError:  # before: it yields its codec events alone
    InferredLifecycle = None

from app.services.ai.models.provider_names import LOCAL_PROVIDERS
from app.services.ai.models.providers import AIProvider

from ..live_engines import split_model
from ..models import AudioFormat, AudioInput, SpeechRequest
from ..tts import realtime
from . import turns

SYSTEM = "cascade"
# What the call hears in (Silero and Smart Turn's rate) and says out (Kokoro's).
INPUT_RATE = turns.RATE
OUTPUT_RATE = realtime.RATE
# Where a sentence ends, as the chat's own voice splits a streamed answer.
ENDS = re.compile(r"(?<=[.!?])\s+|\n+")

Hear = Callable[[bytes], Awaitable[str]]
Say = Callable[[str], Awaitable[bytes]]


def serves(model: str) -> bool:
    """Whether a call on ``model`` (a Pydantic AI model string) runs as a
    cascade: a local chat model, which has no realtime API of its own."""
    return split_model(model)[0] in LOCAL_PROVIDERS


async def for_call(ai: Any, model: str, *, user_id: str | None) -> CascadeRealtimeModel:
    """The cascade on ``model`` ("llamacpp:<id>"), hearing and speaking in
    the voice profile's own STT and TTS (``ai.stt``, ``ai.tts``), what they
    spend recorded against the caller (``user_id``)."""
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

    return CascadeRealtimeModel(brain, hear=hear, say=say)


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


class CascadeRealtimeModel(RealtimeModel):
    """``brain`` (any chat model) on a call: ``hear`` turns a finished turn
    (PCM16 at 16 kHz) into its words, ``say`` a sentence into PCM16 at 24
    kHz, and ``ear`` makes each call's listener (``turns.Listener``)."""

    def __init__(
        self,
        brain: Model,
        *,
        hear: Hear,
        say: Say,
        ear: Callable[[], turns.Listener] = turns.Listener,
    ) -> None:
        super().__init__(
            profile=RealtimeModelProfile(
                audio_input_sample_rate=INPUT_RATE,
                audio_output_sample_rate=OUTPUT_RATE,
                supports_interruption=True,
            )
        )
        self.brain, self._hear, self._say, self._ear = brain, hear, say, ear

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


class CascadeConnection(RealtimeConnection):
    """One call: what it has heard and said, the reply in flight, and the
    tool results it waits on before answering on."""

    def __init__(
        self,
        model: CascadeRealtimeModel,
        history: list[ModelMessage],
        settings: Any,
        parameters: ModelRequestParameters,
    ) -> None:
        self._model = model
        self._history = history
        self._settings = settings
        self._parameters = parameters
        self._instructions = next(
            (
                m.instructions
                for m in reversed(history)
                if isinstance(m, ModelRequest) and m.instructions
            ),
            None,
        )
        self._ear = model._ear()
        self._events: asyncio.Queue[RealtimeCodecEvent | None] = asyncio.Queue()
        # Which response, turn and input each event is about, worked out from
        # their order: nothing here names them (``InferredLifecycle``).
        self._lifecycle = InferredLifecycle() if InferredLifecycle else None
        self._reply: asyncio.Task[None] | None = None
        self._turns: set[asyncio.Task[None]] = set()
        self._spoken = 0  # turns heard: each one's id, start to transcript
        self._waiting: dict[str, str] = {}  # tool call id -> tool name
        self._returned: list[ToolReturnPart] = []

    @property
    def model_name(self) -> str | None:
        return self._model.model_name

    async def send(self, content: RealtimeInput) -> Any:
        """What ``content`` asks of the call, and (on a Pydantic AI that
        has lifecycles) the lifecycle events sending it settled."""
        if self._lifecycle is None:
            await self._take(content)
            return None
        with self._lifecycle.sending(content):
            await self._take(content)
        return self._lifecycle.take_pending()

    async def _take(self, content: RealtimeInput) -> None:
        if isinstance(content, BinaryAudio):
            for heard in await asyncio.to_thread(self._ear.hear, content.data):
                await self._heard(heard)
        elif isinstance(content, str):
            self._asked(content)
            self._answer()
        elif isinstance(content, TextContext):
            self._asked(content.text)
        elif isinstance(content, ToolResult):
            self._tool_returned(content)
        elif isinstance(content, CancelResponse):
            await self._cut_off()
        elif isinstance(content, CreateResponse):
            self._answer()

    def frames(self) -> Any:
        """What the call does, a frame at a time (Pydantic AI 2.6x on)."""
        assert self._lifecycle is not None
        return self._lifecycle.frames(self._said())

    def __aiter__(self) -> AsyncIterator[RealtimeCodecEvent]:
        if self._lifecycle is None:
            return self._said()
        return super().__aiter__()

    async def _said(self) -> AsyncIterator[RealtimeCodecEvent]:
        while (event := await self._events.get()) is not None:
            yield event

    async def close(self) -> None:
        for task in [*self._turns, *filter(None, [self._reply])]:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self._events.put_nowait(None)

    # --- hearing ---------------------------------------------------------------

    async def _heard(self, heard: turns.Heard) -> None:
        if heard.kind == "start":
            await self._cut_off()
            self._spoken += 1
            self._tell(RealtimeInputSpeechStartEvent(item_id=self._item))
            return
        self._tell(RealtimeInputSpeechEndEvent(item_id=self._item))
        task = asyncio.create_task(self._transcribed(heard.audio, self._item))
        self._turns.add(task)
        task.add_done_callback(self._turns.discard)

    @property
    def _item(self) -> str:
        return f"turn-{self._spoken}"

    async def _transcribed(self, pcm: bytes, item: str) -> None:
        words = (await self._model._hear(pcm)).strip()
        self._tell(InputTranscript(words, is_final=True, item_id=item))
        if not words:
            return
        self._asked(words)
        self._answer()

    def _asked(self, words: str) -> None:
        self._history.append(self._request(UserPromptPart(words)))

    def _request(self, *parts: Any) -> ModelRequest:
        return ModelRequest(parts=list(parts), instructions=self._instructions)

    def _tool_returned(self, result: ToolResult) -> None:
        name = self._waiting.pop(result.tool_call_id, None)
        if name is None:
            return
        self._returned.append(
            ToolReturnPart(name, result.output, tool_call_id=result.tool_call_id)
        )
        if not self._waiting:
            self._history.append(self._request(*self._returned))
            self._returned = []
            self._answer()

    # --- answering -------------------------------------------------------------

    def _answer(self) -> None:
        if self._reply is None or self._reply.done():
            self._reply = asyncio.create_task(self._replied())

    async def _cut_off(self) -> None:
        """The reply in flight stops where it is (the caller spoke over it)."""
        reply = self._reply
        if reply is None or reply.done():
            return
        reply.cancel()
        with suppress(asyncio.CancelledError):
            await reply
        self._tell(RealtimeResponseInterruptedEvent())
        self._tell(ResponseDone(interrupted=True))

    async def _replied(self) -> None:
        """One answer: written by the brain, said a sentence at a time as it
        comes; its tool calls handed to the session, which runs them and
        sends their results back (``_tool_returned``)."""
        said: list[str] = []
        pending = ""
        brain = self._model.brain
        messages = brain.prepare_messages(self._history)
        try:
            async with brain.request_stream(
                messages, self._settings, self._parameters
            ) as stream:
                async for event in stream:
                    delta = _text_of(event)
                    if not delta:
                        continue
                    *whole, pending = ENDS.split(pending + delta)
                    for sentence in filter(str.strip, whole):
                        await self._say(sentence, said)
                if pending.strip():
                    await self._say(pending, said)
                response = stream.get()
        except asyncio.CancelledError:
            if said:
                self._history.append(ModelResponse(parts=[TextPart(" ".join(said))]))
            raise
        self._history.append(response)
        calls = [p for p in response.parts if isinstance(p, ToolCallPart)]
        for call in calls:
            self._waiting[call.tool_call_id] = call.tool_name
            self._tell(
                ToolCall(
                    call.tool_call_id,
                    tool_name=call.tool_name,
                    args=call.args_as_json_str(),
                )
            )
        self._tell(SessionUsage(response.usage))
        self._tell(ResponseDone(finish_reason=response.finish_reason))

    async def _say(self, sentence: str, said: list[str]) -> None:
        text = sentence.strip()
        separator = " " if said else ""
        self._tell(AudioDelta(await self._model._say(text)))
        self._tell(OutputTranscript(separator + text))
        said.append(text)

    def _tell(self, event: RealtimeCodecEvent) -> None:
        self._events.put_nowait(event)


def _text_of(event: Any) -> str:
    """The answer's words an event of the stream adds, if any."""
    if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
        return event.part.content
    if isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
        return event.delta.content_delta
    return ""
