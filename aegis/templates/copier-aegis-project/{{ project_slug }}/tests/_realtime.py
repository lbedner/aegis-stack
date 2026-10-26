"""A stand-in for a Pydantic AI realtime agent and its session (#273).

It plays given events, one burst after the call's first audio (or its
first text turn, ``after_text``; or at once), then stays open until
closed, the way a call waits on the person; or (``ends``) the provider
ends it once they are played.
Its voice is one chunk of audio. What it was sent is kept for the test.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

VOICE = b"\x00\x01\x02\x03"
# A live engine as ``live_engines.resolve`` gives it.
ENGINE = SimpleNamespace(
    key="gemini-live",
    instructions="## THIS IS A LIVE VOICE CALL",
    max_output_tokens=1_200,
    llm=SimpleNamespace(
        model_id="gemini-3.8-live",
        title="Gemini 3.8 Live",
        served_by=SimpleNamespace(slug="google"),
    ),
)


class FakeSession:
    audio_input_sample_rate = 16_000
    audio_output_sample_rate = 24_000

    def __init__(
        self, events: list[Any], *, after_audio: bool, ends: bool, after_text: bool
    ) -> None:
        self.events = events
        self.after_audio = after_audio
        self.after_text = after_text
        self.ends = ends
        self.audio: list[bytes] = []
        self.sent: list[str] = []
        self.usage = SimpleNamespace(input_tokens=100, output_tokens=40)
        self._heard: asyncio.Event | None = None
        self._asked: asyncio.Event | None = None
        self._closed: asyncio.Event | None = None

    def _flag(self, name: str) -> asyncio.Event:
        # Made on first use, inside the loop that serves the call.
        if getattr(self, name) is None:
            setattr(self, name, asyncio.Event())
        flag: asyncio.Event = getattr(self, name)
        return flag

    async def _either(self, *names: str) -> None:
        """Until one of these flags is set."""
        waits = [asyncio.ensure_future(self._flag(name).wait()) for name in names]
        _, pending = await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
        for wait in pending:
            wait.cancel()

    async def send_audio(self, data: bytes) -> None:
        self.audio.append(data)
        self._flag("_heard").set()

    async def send(self, text: str) -> None:
        self.sent.append(text)
        self._flag("_asked").set()

    async def close(self) -> None:
        self._flag("_closed").set()

    def stream_audio(self) -> AsyncIterator[bytes]:
        async def voice() -> AsyncIterator[bytes]:
            yield VOICE
            await self._flag("_closed").wait()

        return voice()

    def __aiter__(self) -> AsyncIterator[Any]:
        async def events() -> AsyncIterator[Any]:
            if self.after_audio:
                await self._flag("_heard").wait()
            if self.after_text:
                await self._either("_asked", "_closed")
                if self._flag("_closed").is_set():
                    return
            for event in self.events:
                yield event
            if not self.ends:
                await self._flag("_closed").wait()

        return events()


class FakeRealtime:
    def __init__(
        self,
        events: list[Any],
        *,
        after_audio: bool = False,
        ends: bool = False,
        after_text: bool = False,
    ) -> None:
        self.live = FakeSession(
            events, after_audio=after_audio, ends=ends, after_text=after_text
        )
        self.provider_session: Any = "unset"

    @asynccontextmanager
    async def session(
        self, provider_session: Any = None
    ) -> AsyncGenerator[FakeSession]:
        self.provider_session = provider_session
        yield self.live


class BrokenRealtime:
    """A live call whose provider refuses it as it opens."""

    @asynccontextmanager
    async def session(self, provider_session: Any = None) -> AsyncGenerator[Any]:
        raise ConnectionError("the provider refused the call")
        yield  # an async generator, for the context manager
