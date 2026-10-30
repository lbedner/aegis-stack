"""A voice spoken to in text (``live_voice``): one realtime call put a
question at a time, her answer heard as it is made and its words given
back once said. The meeting bot answers in a call this way."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
import time
from typing import Any

from pydantic_ai.messages import PartEndEvent, RealtimeTurnCompleteEvent, SpeechPart
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.backend.api.ai.service import ai_service
from app.services.ai.domains.spend import recording as usage_recording
from app.services.ai.domains.voice import live_voice as module
from app.services.ai.domains.voice import realtime_calls
from app.services.ai.domains.voice.live_voice import LiveVoice, live_voice
from tests._realtime import ENGINE, VOICE, BrokenRealtime, FakeRealtime
from tests._session import opens

ANSWER = [
    PartEndEvent(
        index=0, part=SpeechPart(speaker="assistant", transcript="Sam owns billing.")
    ),
    RealtimeTurnCompleteEvent(),
]


def _her(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    realtime: Any,
    played: list[Any],
    built: dict[str, Any] | None = None,
    on_end: Callable[[], Awaitable[None]] | None = None,
    instructions: str | None = None,
) -> AbstractAsyncContextManager[LiveVoice | None]:
    """Her live voice on ``realtime`` as the engine's call, its audio kept,
    what she was built with in ``built``."""
    monkeypatch.setattr(usage_recording, "get_async_session", opens(session))

    async def realtime_for(*args: Any, **kwargs: Any) -> Any:
        (built if built is not None else {}).update(kwargs)
        return realtime

    async def play(chunk: bytes, rate: int) -> None:
        played.append((chunk, rate))

    monkeypatch.setattr(realtime_calls, "realtime_for", realtime_for)
    return live_voice(
        ai_service,
        engine=ENGINE,
        play=play,
        surface="meetings",
        user_id="7",
        on_end=on_end,
        instructions=instructions,
    )


pytestmark = pytest.mark.queryspy(allow_n_plus_one=True)  # a saved turn, read back


async def test_a_question_is_answered_aloud_and_its_words_given_back(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    played: list[Any] = []
    built: dict[str, Any] = {}
    realtime = FakeRealtime(ANSWER, after_text=True)

    async with _her(async_db_session, monkeypatch, realtime, played, built) as voice:
        assert voice is not None
        said = await voice.ask("Who owns billing?")

    assert said == "Sam owns billing." and voice.spoke(said)
    assert realtime.live.sent == ["Who owns billing?"]
    assert played == [(VOICE, 24_000)]  # heard as it was made, at its rate
    assert built["hang_up"] is False  # a "thanks" must not end her
    assert not voice.open  # closed with the meeting


async def test_gpt_live_spoken_to_in_text_is_never_opened(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GPT-Live listens and talks at once: asked a question as text it says
    nothing until its session expires, so there is no voice of it to speak
    to in text, under whatever key its engine row has."""
    from types import SimpleNamespace

    built: dict[str, Any] = {}
    gpt_live = SimpleNamespace(
        **{**vars(ENGINE), "key": "calls", "llm": SimpleNamespace(
            model_id="gpt-live-1", served_by=SimpleNamespace(slug="openai")
        )}
    )

    async def realtime_for(*args: Any, **kwargs: Any) -> Any:
        built.update(kwargs)
        return FakeRealtime([], after_text=True)

    monkeypatch.setattr(realtime_calls, "realtime_for", realtime_for)

    async def play(chunk: bytes, rate: int) -> None:
        pass

    async with live_voice(
        ai_service, engine=gpt_live, play=play, surface="meetings"
    ) as voice:
        assert voice is None
    assert built == {}


async def test_how_she_talks_is_the_callers_else_the_engines(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The engine's call manners are for a call with one person; a caller
    with others in it (a meeting) gives its own."""
    for given, used in ((None, ENGINE.instructions), ("## A MEETING", "## A MEETING")):
        built: dict[str, Any] = {}
        realtime = FakeRealtime([], after_text=True)
        async with _her(
            async_db_session, monkeypatch, realtime, [], built, instructions=given
        ):
            pass
        assert built["instructions"] == used


async def test_told_to_stop_her_answer_is_cut_off_and_she_stays_on(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stopped mid-answer: the provider cancels it where it was heard to,
    the question owed is answered with nothing, and the call stays up for
    the next one."""
    realtime = FakeRealtime([], after_text=True)  # still answering

    async with _her(async_db_session, monkeypatch, realtime, []) as voice:
        assert voice is not None
        asking = asyncio.create_task(voice.ask("Who owns billing?"))
        while not realtime.live.sent:
            await asyncio.sleep(0.01)

        await voice.stop()

        assert await asyncio.wait_for(asking, 1) == ""
        assert realtime.live.interrupted == [0]
        assert voice.open


async def test_once_the_call_is_over_she_is_asked_nothing_more(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The provider ends it (its session cap, an error): her voice is told
    it is over (the bot closes its mic), and asks fail for the old way."""
    realtime = FakeRealtime([], after_text=True)
    ended = asyncio.Event()

    async def on_end() -> None:
        ended.set()

    async with _her(
        async_db_session, monkeypatch, realtime, [], on_end=on_end
    ) as voice:
        assert voice is not None
        await realtime.live.close()
        await asyncio.wait_for(ended.wait(), 5)

        assert not voice.open
        with pytest.raises(RuntimeError):
            await voice.ask("Who owns billing?")


async def test_an_answer_too_slow_to_come_ends_her_live_call(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Given up on, an answer must not play on or land on the next question:
    the call ends, and the answer is made the old way."""
    monkeypatch.setattr(module, "ANSWER_SECONDS", 0.05)
    realtime = FakeRealtime([], after_text=True)  # never answers

    async with _her(async_db_session, monkeypatch, realtime, []) as voice:
        assert voice is not None
        with pytest.raises(TimeoutError):
            await voice.ask("Who owns billing?")

        assert not voice.open


async def test_a_call_that_cannot_come_up_is_given_up_at_once(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refused as it opens, she answers the old way straight off, not after
    waiting out ``OPEN_SECONDS`` while no caption is read."""
    monkeypatch.setattr(module, "OPEN_SECONDS", 30.0)
    began = time.monotonic()

    async with _her(async_db_session, monkeypatch, BrokenRealtime(), []) as voice:
        assert voice is None

    assert time.monotonic() - began < 5
