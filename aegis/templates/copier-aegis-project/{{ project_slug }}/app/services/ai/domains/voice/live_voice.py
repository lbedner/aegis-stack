"""A voice spoken to in text: one live call (``realtime_calls``) put a
question at a time as a text turn, her answer heard as it is made (each
piece of its audio handed to ``play``) and its words given back once said.

It is her, built the way a live call builds her (``open_call``: her
prompt, tools and code mode on the live engine), and driven the way one
is (``drive``): her tools run in a turn's context, each turn is saved into
the conversation, the call's usage is priced. The meeting bot answers a
question put to her in a call this way, so she is heard as she thinks, not
once a reply and its speech are both made.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from typing import Any

from app.core.config import settings
from app.core.log import logger
from app.services.ai.domains.voice import live_engines
from app.services.ai.domains.voice.realtime_calls import drive, open_call

# Where a piece of her voice goes, at its sample rate (PCM16, mono).
Play = Callable[[bytes, int], Awaitable[None]]
# The longest one answer may take, tools and all, before it is given up.
ANSWER_SECONDS = 90.0
# How long the call may take to come up before she is not live after all.
OPEN_SECONDS = 15.0


class LiveVoice:
    """Her, live: ``ask`` puts a question to her and gives back what she
    said, one question at a time; her voice goes to ``play`` as it comes,
    and ``on_end`` hears when the call is over, however it ends."""

    def __init__(
        self, play: Play, on_end: Callable[[], Awaitable[None]] | None = None
    ) -> None:
        self.play, self.on_end = play, on_end
        self.ready = asyncio.Event()  # the call is up
        self._session: Any = None
        self._reply: asyncio.Future[str] | None = None
        self._one = asyncio.Lock()
        self._said: list[str] = []

    @property
    def open(self) -> bool:
        return self._session is not None

    async def ask(self, text: str) -> str:
        """Her answer to ``text``: heard as she makes it, its words once she
        has said it all. RuntimeError once the call is over; TimeoutError
        past ``ANSWER_SECONDS``, the call then ended so the answer given up
        on neither plays on nor lands on the next question."""
        async with self._one:
            if self._session is None:
                raise RuntimeError("Her live call is over")
            self._reply = asyncio.get_running_loop().create_future()
            await self._session.send(text)
            try:
                async with asyncio.timeout(ANSWER_SECONDS):
                    said = await self._reply
            except TimeoutError:
                await self.close()
                raise
            self._said.append(said)
            return said

    def spoke(self, text: str) -> bool:
        """Whether ``text`` is an answer she said aloud here."""
        return text in self._said

    async def turned(self, turn: tuple[str, str, list[dict[str, Any]]]) -> None:
        """Each finished turn of the call (``drive``'s ``on_turn``): what she
        said is the answer owed."""
        if self._reply is not None and not self._reply.done():
            self._reply.set_result(turn[1])

    async def carry(self, session: Any) -> None:
        """Beside the call (``drive``'s ``alongside``): her voice to
        ``play`` as it comes, until the call is over."""
        self._session = session
        self.ready.set()
        rate = session.audio_output_sample_rate
        try:
            async for chunk in session.stream_audio():
                await self.play(chunk, rate)
        finally:
            self._session = None
            if self._reply is not None and not self._reply.done():
                self._reply.set_exception(RuntimeError("Her live call ended"))
            if self.on_end is not None:
                await self.on_end()

    async def close(self) -> None:
        """The call ended, where it is still up."""
        session, self._session = self._session, None
        if session is not None:
            await session.close()


@asynccontextmanager
async def live_voice(
    ai: Any,
    *,
    engine: Any,
    play: Play,
    surface: str,
    user_id: str = "default",
    voice: str | None = None,
    agent_slug: str | None = None,
    on_end: Callable[[], Awaitable[None]] | None = None,
) -> AsyncGenerator[LiveVoice | None]:
    """Her live voice (``LiveVoice``) on ``engine`` (``live_engines.resolve``,
    in the caller's session), saved into a conversation of ``surface``'s,
    as ``user_id``, speaking in ``voice``; None where the call would not
    come up, for the caller to answer the way it did. She cannot hang it up
    (asked one question after another, a "thanks" must not end it)."""
    try:
        conversation, realtime = await open_call(
            ai,
            engine,
            user_id=user_id,
            surface=surface,
            agent_slug=agent_slug,
            voice=voice or settings.TTS_VOICE,
            hang_up=False,
        )
    except Exception:
        logger.exception("Her live voice could not be made; she answers as before")
        yield None
        return
    spoken = LiveVoice(play, on_end)
    call = asyncio.create_task(
        drive(
            ai,
            realtime,
            conversation_id=conversation.id,
            model=live_engines.realtime_model(engine),
            agent_slug=agent_slug,
            user_id=user_id,
            alongside=spoken.carry,
            on_turn=spoken.turned,
        )
    )
    # Up, or over (refused as it opened): whichever comes first.
    up = asyncio.create_task(spoken.ready.wait())
    await asyncio.wait({call, up}, timeout=OPEN_SECONDS, return_when="FIRST_COMPLETED")
    if not spoken.ready.is_set():
        logger.warning("Her live call did not come up; she answers as before")
        up.cancel()
        call.cancel()
        with suppress(asyncio.CancelledError):  # the cancel just asked for
            await call
        yield None
        return
    try:
        yield spoken
    finally:
        await spoken.close()
        await call
