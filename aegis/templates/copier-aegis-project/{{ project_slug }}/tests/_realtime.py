"""A stand-in for a Pydantic AI realtime agent and its session (#273).

It plays given events, one burst after the call's first audio (or at
once), then stays open until closed, the way a call waits on the person.
Its voice is one chunk of audio. What it was sent is kept for the test.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

VOICE = b"\x00\x01\x02\x03"


class FakeSession:
    audio_input_sample_rate = 16_000
    audio_output_sample_rate = 24_000

    def __init__(self, events: list[Any], *, after_audio: bool) -> None:
        self.events = events
        self.after_audio = after_audio
        self.audio: list[bytes] = []
        self.sent: list[str] = []
        self.usage = SimpleNamespace(input_tokens=100, output_tokens=40)
        self._heard: asyncio.Event | None = None
        self._closed: asyncio.Event | None = None

    def _flag(self, name: str) -> asyncio.Event:
        # Made on first use, inside the loop that serves the call.
        if getattr(self, name) is None:
            setattr(self, name, asyncio.Event())
        flag: asyncio.Event = getattr(self, name)
        return flag

    async def send_audio(self, data: bytes) -> None:
        self.audio.append(data)
        self._flag("_heard").set()

    async def send(self, text: str) -> None:
        self.sent.append(text)

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
            for event in self.events:
                yield event
            await self._flag("_closed").wait()

        return events()


class FakeRealtime:
    def __init__(self, events: list[Any], *, after_audio: bool = False) -> None:
        self.live = FakeSession(events, after_audio=after_audio)
        self.provider_session: Any = "unset"

    @asynccontextmanager
    async def session(
        self, provider_session: Any = None
    ) -> AsyncGenerator[FakeSession]:
        self.provider_session = provider_session
        yield self.live
