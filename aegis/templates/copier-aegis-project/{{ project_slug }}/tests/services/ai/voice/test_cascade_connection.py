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
from pydantic_ai.models.function import (
    AgentInfo,
    DeltaThinkingPart,
    DeltaToolCall,
    FunctionModel,
)
import pytest

from app.core import steps
from app.services.ai.domains.voice.cascade import call, connection, words
from app.services.ai.domains.voice.cascade.call import CascadeRealtimeModel
from app.services.ai.domains.voice.models import AudioFormat
from app.services.ai.domains.voice.tts import realtime
from tests._cascade import ear, said, turn

ANSWER = "Your checking has 42 dollars. Anything else?"


async def _hear(pcm: bytes) -> str:
    return "What is in checking?"


async def _say(sentence: str) -> bytes:
    return sentence.encode()


def _model(brain: Any, say: Any = _say, hear: Any = _hear) -> CascadeRealtimeModel:
    return CascadeRealtimeModel(
        FunctionModel(stream_function=brain), hear=hear, say=say, ear=ear
    )


def _warming(info: AgentInfo) -> bool:
    """The call's warm-up request: one token, its answer thrown away."""
    return (info.model_settings or {}).get("max_tokens") == 1


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
                await session.send(BinaryContent(said(), media_type="audio/pcm"))
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
    model = await call.for_call(ai, "ollama:qwen3.8:27b", user_id="u1")

    assert model.model_name == "qwen3.8:27b"
    assert await model._hear(bytes(320)) == "Hi"
    said = await model._say("Hello.")
    assert len(said) == 2 * 24_000  # a second, at the call's rate
    assert asked == [
        ("heard", (AudioFormat.WAV, 16_000, "u1")),
        ("said", (AudioFormat.WAV, "u1")),
    ]


async def test_a_failed_hearing_ends_the_call_with_its_error() -> None:
    """The hearing server did not answer: the turn's transcription failed in
    a task no one read, and the call sat there working on nothing
    (2026-11-21)."""

    async def deaf(pcm: bytes) -> str:
        raise RuntimeError("the hearing server (parakeet) did not answer")

    model = _model(_brain, hear=deaf)
    async with Agent().realtime(model).session() as session:
        await _ask(session)
        with pytest.raises(RuntimeError, match="parakeet"):
            async with asyncio.timeout(5):
                async for _ in session:
                    pass


async def test_a_failed_answer_ends_the_call_with_its_error() -> None:
    """The local model refused the opening (past its window, a 500)."""

    async def refused(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str]:
        raise RuntimeError("context window exceeded")
        yield ""

    async with Agent().realtime(_model(refused)).session() as session:
        await session.send("Greet them.")
        with pytest.raises(RuntimeError, match="context window"):
            async with asyncio.timeout(5):
                async for _ in session:
                    pass


async def test_the_opening_is_said_at_once_while_the_model_warms_up() -> None:
    """A local model took minutes to read her prompt before its greeting
    (2026-11-21): the call opens on a fixed line, and the model reads the
    call's context behind it, one token long, so its cache is warm by the
    first question."""
    asked: list[Any] = []

    async def warming(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str]:
        asked.append(info.model_settings)
        yield "Hello there, I am the model."

    said: list[str] = []
    async with Agent().realtime(_model(warming)).session() as session:
        await session.send("Greet them.")
        async for event in session:
            if (
                isinstance(event, PartDeltaEvent)
                and isinstance(event.delta, SpeechPartDelta)
                and event.delta.audio_chunk
            ):
                said.append(event.delta.audio_chunk.decode())
            if isinstance(event, RealtimeTurnCompleteEvent):
                break
        async with asyncio.timeout(5):
            while not asked:
                await asyncio.sleep(0.01)

    assert said == [words.OPENING]
    assert asked == [{"max_tokens": 1}]


async def _staged(model: CascadeRealtimeModel) -> list[Any]:
    """The stages one spoken turn goes through, as a watcher is told them
    (``connection.stages``), to the end of its answer."""
    told: list[Any] = []
    agent = Agent()

    @agent.tool_plain
    def balance() -> str:
        """The checking balance."""
        return "$42"

    with connection.stages.watching(told.append):
        async with agent.realtime(model).session() as session:
            await _ask(session)
            async with asyncio.timeout(5):
                async for event in session:
                    if isinstance(event, RealtimeTurnCompleteEvent):
                        break
    return told


async def test_each_stage_of_a_turn_is_told_as_it_starts() -> None:
    """A call on a local model sat on "working" for minutes with nothing to
    say which part was slow: the model was reading a 20k-token prompt
    (2026-11-21). Hearing, then the model reading the call, once per
    request (again after the tool's result)."""
    told = await _staged(_model(_brain))

    assert told == [connection.HEARING, connection.READING, connection.READING]


async def test_the_model_thinking_is_a_stage_of_its_own() -> None:
    """A local model thinks before it answers: the call says so, not that
    it is still reading."""

    async def thinking(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[Any]:
        if not _warming(info):
            yield {0: DeltaThinkingPart(content="They want the balance.")}
        yield "You have 42 dollars."

    told = await _staged(_model(thinking))

    assert told == [connection.HEARING, connection.READING, steps.THINKING]


async def test_a_turn_with_no_words_ends_its_steps() -> None:
    """Heard as nothing (a cough): no answer comes, so the steps end."""

    async def nothing(pcm: bytes) -> str:
        return ""

    model = _model(_brain, hear=nothing)
    told: list[Any] = []
    with connection.stages.watching(told.append):
        async with Agent().realtime(model).session() as session:
            await _ask(session)
            async with asyncio.timeout(5):
                while None not in told:
                    await asyncio.sleep(0.01)

    assert told == [connection.HEARING, None]


async def test_a_question_asked_while_the_model_warms_up_says_it_waits() -> None:
    """The question waits behind the warm-up's read of the prompt (Ollama
    runs one request at a time)."""
    gate = asyncio.Event()

    async def slow(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        if _warming(info):
            await gate.wait()
        yield "Fine."

    told: list[Any] = []
    with connection.stages.watching(told.append):
        async with Agent().realtime(_model(slow)).session() as session:
            await session.send("Greet them.")
            await _ask(session)
            async with asyncio.timeout(5):
                while connection.WARMING not in told:
                    await asyncio.sleep(0.01)
                gate.set()
                while connection.READING not in told:
                    await asyncio.sleep(0.01)

    assert told[:3] == [connection.HEARING, connection.WARMING, connection.READING]


def _hearing(*heard: str) -> Any:
    """Hears each turn as the next of ``heard``."""
    left = list(heard)

    async def hear(pcm: bytes) -> str:
        return left.pop(0)

    return hear


async def test_a_question_waits_for_the_warm_up_so_it_reads_from_its_cache() -> None:
    """Sent beside the warm-up, the question read the whole prompt again
    as it ran, and both crawled (2026-11-21): the cache is kept only once
    a request ends."""
    gate = asyncio.Event()
    order: list[str] = []

    async def brain(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str]:
        warm = _warming(info)
        order.append("warm" if warm else "question")
        if warm:
            await gate.wait()
            order.append("warmed")
        yield "Fine."

    async with Agent().realtime(_model(brain)).session() as session:
        await session.send("Greet them.")
        async with asyncio.timeout(5):
            while not order:
                await asyncio.sleep(0.01)
            await _ask(session)
            await asyncio.sleep(0.1)
            assert order == ["warm"]
            gate.set()
            while "question" not in order:
                await asyncio.sleep(0.01)

    assert order == ["warm", "warmed", "question"]


def _asking(asked: list[list[str]], gate: asyncio.Event | None = None) -> Any:
    """A brain that notes the words of each request (a user-prompt part
    each), then answers; the first waits on ``gate`` when one is given."""

    async def brain(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str]:
        asked.append(
            [
                str(part.content)
                for message in messages
                if isinstance(message, ModelRequest)
                for part in message.parts
                if part.part_kind == "user-prompt"
            ]
        )
        if gate is not None and len(asked) == 1:
            await gate.wait()
        yield "Fine."

    return brain


async def test_an_answer_not_yet_said_gives_way_to_more_words() -> None:
    """ "Um" was answered while the caller went on, and the answer to what
    they went on to say waited behind it (2026-11-22): an answer that has
    said nothing yet is dropped unheard when they speak again, and its
    question asked again with what they add, as one."""
    asked: list[list[str]] = []
    model = _model(
        _asking(asked, asyncio.Event()),
        hear=_hearing("Can you show me", "the spending chart?"),
    )
    kinds: list[str] = []
    async with Agent().realtime(model).session() as session:
        await _ask(session)
        async with asyncio.timeout(5):
            while not asked:
                await asyncio.sleep(0.01)
            await _ask(session)
            async for event in session:
                kinds.append(type(event).__name__)
                if isinstance(event, RealtimeTurnCompleteEvent):
                    break

    assert "RealtimeResponseInterruptedEvent" not in kinds
    # Asked again as one, not twice over.
    assert asked == [
        ["Can you show me"],
        ["Can you show me the spending chart?"],
    ]


async def test_a_turn_of_only_um_waits_for_the_words_after_it() -> None:
    """ "Um" and "Hm." were each answered ("No rush, take your time")
    while the caller gathered the question (2026-11-22)."""
    asked: list[list[str]] = []
    model = _model(_asking(asked), hear=_hearing("Um.", "Hm, show me checking."))
    async with Agent().realtime(model).session() as session:
        await _ask(session)
        async with asyncio.timeout(5):
            await asyncio.sleep(0.1)
            assert asked == []
            await _ask(session)
            async for event in session:
                if isinstance(event, RealtimeTurnCompleteEvent):
                    break

    assert asked == [["Um. Hm, show me checking."]]
