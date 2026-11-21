"""A cascade call through a real Pydantic AI session: a spoken turn is
heard, answered by a chat model (a tool call on the way), and said back a
sentence at a time, and the session closes the turn as it does on Gemini
Live. The ear, the transcriber, the voice and the chat model are stood in
for (``turns`` has its own tests)."""

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.messages import (
    BinaryContent,
    ModelMessage,
    ModelRequest,
    PartDeltaEvent,
    PartEndEvent,
    RealtimeResponseInterruptedEvent,
    RealtimeTurnCompleteEvent,
    SpeechPart,
    SpeechPartDelta,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from app.services.ai.domains.voice.cascade import connection
from app.services.ai.domains.voice.cascade.connection import CascadeRealtimeModel
from app.services.ai.domains.voice.models import AudioFormat
from app.services.ai.domains.voice.tts import realtime
from tests._cascade import LOUD, ear, turn, windows

ANSWER = "Your checking has 42 dollars. Anything else?"


async def _hear(pcm: bytes) -> str:
    return "What is in checking?"


async def _say(sentence: str) -> bytes:
    return sentence.encode()


def _model(brain: Any, say: Any = _say) -> CascadeRealtimeModel:
    return CascadeRealtimeModel(
        FunctionModel(stream_function=brain), hear=_hear, say=say, ear=ear
    )


async def _ask(session: Any) -> None:
    await session.send(BinaryContent(turn(), media_type="audio/pcm"))


async def _brain(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[Any]:
    """Looks the balance up first, then answers in two sentences."""
    returned = any(
        isinstance(part, ToolReturnPart)
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
    )
    if not returned:
        yield {0: DeltaToolCall("balance", "{}", tool_call_id="call-1")}
        return
    for piece in ("Your checking has 42 ", "dollars. Anything ", "else?"):
        yield piece


async def test_a_spoken_turn_is_answered_and_said_back() -> None:
    agent = Agent()
    looked_up: list[str] = []

    @agent.tool_plain
    def balance() -> str:
        """The checking balance."""
        looked_up.append("checking")
        return "$42"

    said: list[bytes] = []
    realtime = agent.realtime(_model(_brain), instructions="Be brief.")
    async with realtime.session() as session:
        assert session.audio_input_sample_rate == 16_000
        await _ask(session)
        async for event in session:
            if isinstance(event, RealtimeTurnCompleteEvent):
                break
            if isinstance(event, PartDeltaEvent) and isinstance(
                event.delta, SpeechPartDelta
            ):
                said.append(event.delta.audio_chunk or b"")
        history = session.all_messages()

    assert looked_up == ["checking"]
    assert b"".join(said) == b"Your checking has 42 dollars.Anything else?"
    spoken = [
        part.transcript
        for message in history
        for part in message.parts
        if isinstance(part, SpeechPart)
    ]
    assert spoken == ["What is in checking?", ANSWER]


async def test_speaking_over_the_answer_cuts_it_off() -> None:
    """The caller talks while the answer is being said: what was not said
    yet is dropped, and the session hears the reply was interrupted."""
    hold = asyncio.Event()

    async def slow(sentence: str) -> bytes:
        if sentence != "Your checking has 42 dollars.":
            await hold.wait()
        return sentence.encode()

    async def answers(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str]:
        for piece in ("Your checking has 42 dollars. ", "Anything else?"):
            yield piece

    kinds: list[str] = []
    async with Agent().realtime(_model(answers, slow)).session() as session:
        await _ask(session)
        async for event in session:
            kinds.append(type(event).__name__)
            if isinstance(event, PartDeltaEvent) and isinstance(
                event.delta, SpeechPartDelta
            ):
                loud = windows(LOUD)
                await session.send(BinaryContent(loud, media_type="audio/pcm"))
            if isinstance(event, RealtimeResponseInterruptedEvent):
                break

    assert "RealtimeResponseInterruptedEvent" in kinds
    assert not hold.is_set()


async def test_a_turn_is_one_user_part_holding_its_words() -> None:
    """Speech start, its end and its transcript are one item: no empty
    part for the speech before the words arrive."""
    ended: list[str | None] = []
    async with Agent().realtime(_model(_brain)).session() as session:
        await _ask(session)
        async for event in session:
            if isinstance(event, PartEndEvent) and isinstance(event.part, SpeechPart):
                if event.part.speaker == "user":
                    ended.append(event.part.transcript)
                else:
                    break

    assert ended == ["What is in checking?"]


async def test_it_hears_and_speaks_in_the_voices_own_stt_and_tts() -> None:
    """The profile's STT hears a turn as a 16 kHz WAV and its TTS is asked
    for WAV, resampled to the call's 24 kHz; both bill the caller."""
    asked: list[tuple[str, Any]] = []

    async def transcribe(audio: Any, user_id: str | None = None) -> Any:
        asked.append(("heard", (audio.format, audio.sample_rate, user_id)))
        return SimpleNamespace(text="Hi")

    async def synthesize(line: Any, user_id: str | None = None) -> Any:
        asked.append(("said", (line.format, user_id)))
        return SimpleNamespace(audio=realtime.wav(bytes(2 * 12_000), 12_000))

    ai = SimpleNamespace(
        stt=SimpleNamespace(transcribe=transcribe),
        tts=SimpleNamespace(synthesize=synthesize),
    )
    model = await connection.for_call(ai, "ollama:qwen3.8:27b", user_id="u1")

    assert model.model_name == "qwen3.8:27b"
    assert await model._hear(bytes(320)) == "Hi"
    said = await model._say("Hello.")
    assert len(said) == 2 * 24_000  # a second, at the call's rate
    assert asked == [
        ("heard", (AudioFormat.WAV, 16_000, "u1")),
        ("said", (AudioFormat.WAV, "u1")),
    ]
