"""Questions put to the bot by name in a call, from heard to said: the
one place what she is doing about each is kept, for the card (``saying``),
her mic (``mic``) and her echo (``talk``) to read.

Once her answer to one (an ``addressed`` moment; ``actions.ask_ai``) is
done, it is posted in the chat at once and said aloud, and one that
failed, that it could not find it. Once she starts looking it up (a step
of her turn answering it: ``looking_up``), she says so (``LOOKING``, its
speech made as it joins), once; an answer she looks nothing up for is
just said, however long it takes. Without a voice it types instead. With
her live voice (``voice.live``) she is heard as she makes the answer:
nothing is said while she thinks, and her answer is not said again. She
is saying an answer until the last of it has played (the call's
``until``), whichever way it was said.

Speech is said apart from the call's loop (``_speaking``): made a sentence
at a time, each played after the last as soon as it is made, so captions
are read on while it talks."""

import asyncio
import contextlib
import math
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.log import logger
from app.services.meetings.domains.actions import runs
from app.services.meetings.domains.actions.queries import answered
from app.services.meetings.domains.bot.meet import SPOKEN_TAIL
from app.services.meetings.domains.bot.voice import sentences, spoken
from app.services.meetings.domains.moments.detectors import ADDRESSED, STOP
from app.services.meetings.domains.moments.service import answerer
from app.services.meetings.models import DONE

LOOKING = "Let me look that up."
NOT_FOUND = "Sorry, I couldn't find that."


class Answers:
    """The call's questions put to the bot, from heard to answered."""

    def __init__(self, call: Any, voice: Any | None, live: Any | None = None) -> None:
        # ``live``: her live voice in the call (``voice.live``), which says
        # her answers itself as she makes them.
        self.call, self.voice, self.live = call, voice, live
        # What answers her (``answerer``); with nothing, nothing is waited on.
        self.answers = answerer()
        self.waiting: dict[int, float] = {}  # moment -> when it was heard
        self.looked: set[int] = set()  # those she has started looking up
        self.told: set[int] = set()  # those said to be looked up
        # moment -> when its answer has played: never, while still to say
        self.ends: dict[int, float] = {}
        self.words = ""  # what she last said, or is saying
        # Made ahead, to be said at once; made only when needed when she is
        # live (``_looking``), since she is heard as she thinks then.
        self.looking: asyncio.Task[bytes | None] | None = (
            None if live is not None else asyncio.create_task(spoken(LOOKING, voice))
        )
        self.to_say: asyncio.Queue[tuple[int | None, str]] = asyncio.Queue()
        self.speaking = asyncio.create_task(self._speaking())

    async def heard(self, db: AsyncSession, made: list[tuple[int, str]]) -> None:
        """New moments (id, kind): each put to the bot is waited on; a stop
        drops everything before it (``stop``)."""
        now = asyncio.get_running_loop().time()
        for moment, kind in made:
            if kind == STOP:
                await self.stop(db)
                continue
            if kind == ADDRESSED and self.answers and moment not in self.waiting:
                self.waiting[moment] = now
                logger.info("Bot: asked by name, her answer asked", moment=moment)

    async def stop(self, db: AsyncSession) -> None:
        """Told to stop: every answer owed dropped (its run cut off and
        failed, never posted or said), what she is saying cut off (her live
        answer, what is queued, what the call is playing) and her mic
        closed. She listens again: only a line put to her wakes her."""
        logger.info("Bot: told to stop", dropped=len(self.waiting))
        await runs.drop(db, sorted(self.waiting))
        self.speaking.cancel()
        # Over before what it said is forgotten: its end is written as it stops.
        with contextlib.suppress(asyncio.CancelledError):
            await self.speaking
        while not self.to_say.empty():
            self.to_say.get_nowait()
            self.to_say.task_done()
        for kept in (self.waiting, self.ends, self.looked, self.told):
            kept.clear()
        self.speaking = asyncio.create_task(self._speaking())
        if self.live is not None:
            await self.live.stop()
        await self.call.silence()
        await self.call.hush()

    def looking_up(self, moment: int | None) -> int | None:
        """A step of her turn (a tool call, ``steps.watching``) answering
        ``moment`` (its run's, ``actions.live.ASKED``): one of her live
        call's has none, and is a step of the oldest question waited on, the
        one it answers. She is looking that one up; the moment it is for."""
        if moment is None:
            moment = min(self.waiting, key=self.waiting.__getitem__, default=None)
        if moment in self.waiting:
            self.looked.add(moment)
        return moment

    def saying(self) -> set[int]:
        """The questions whose answers she is still saying: to say, or not
        yet played."""
        now = asyncio.get_running_loop().time()
        self.ends = {m: end for m, end in self.ends.items() if end > now}
        return set(self.ends)

    def talk(self) -> tuple[float, str]:
        """When what she says has played, and what she last said: her own
        words heard back meanwhile are her echo (``Transcript.her``)."""
        return self.call.until, self.words

    async def mic(self) -> None:
        """Her mic open from a question put to her until the last of its
        answer has played (``SPOKEN_TAIL`` after): Meet opens a mic late,
        and opened as she spoke, her first words were lost."""
        if self.voice is None:
            return
        if self.waiting or self.saying():
            await self.call.unmute()
        elif asyncio.get_running_loop().time() >= self.call.until + SPOKEN_TAIL:
            await self.call.hush()

    async def answer(self, db: AsyncSession) -> None:
        """Each answer done since the last look, posted in the chat and
        said aloud; for those she has started looking up, that she is."""
        if self.answers is None:  # nothing is waited on without it (``heard``)
            return
        done = await answered(db, sorted(self.waiting), self.answers)
        now = asyncio.get_running_loop().time()
        for moment, (status, result) in done.items():
            logger.info(
                "Bot: her answer is back",
                moment=moment,
                status=status,
                seconds=round(now - self.waiting.pop(moment), 1),
            )
            said = result if status == DONE and result else NOT_FOUND
            await self.call.say(said)
            self._aloud(said, moment)
        looked = (self.looked & self.waiting.keys()) - self.told
        if looked and not self._live():
            self.told |= looked
            if self.voice is None:
                await self.call.say(LOOKING)
            self._aloud(LOOKING)

    def _live(self) -> bool:
        return self.live is not None and self.live.open

    def _aloud(self, text: str, moment: int | None = None) -> None:
        """``text`` said, for ``moment``: by her live voice already, which
        has played once the call's audio has, or to say now."""
        if self.voice is None:
            return
        self.words = text
        if self.live is not None and self.live.spoke(text):
            ends = self.call.until
        else:
            self.to_say.put_nowait((moment, text))
            ends = math.inf
        if moment is not None:
            self.ends[moment] = ends

    async def said(self) -> None:
        """Once everything given it to say has been said."""
        await self.to_say.join()

    async def _speaking(self) -> None:
        """Say each thing given it in turn, a sentence at a time: every
        sentence's speech made at once, each played as soon as it and those
        before it are."""
        while True:
            moment, text = await self.to_say.get()
            parts: list[asyncio.Task[bytes | None]] = []
            try:
                parts = (
                    [self._looking()]
                    if text == LOOKING
                    else [
                        asyncio.create_task(spoken(sentence, self.voice))
                        for sentence in sentences(text)
                    ]
                )
                loop = asyncio.get_running_loop()
                began = loop.time()
                for n, part in enumerate(parts, 1):
                    if (audio := await part) is None:
                        continue
                    await self.call.speak(audio)
                    logger.info(
                        "Bot: a sentence to say",
                        sentence=f"{n}/{len(parts)}",
                        ready_after=round(loop.time() - began, 1),
                        plays_for=round(self.call.until - loop.time(), 1),
                    )
            except asyncio.CancelledError:  # told to stop: none of it is made
                for part in parts:
                    if part is not self.looking:  # made once, said again later
                        part.cancel()
                raise
            except Exception:
                # Posted in the chat already: the call goes on unheard.
                logger.exception("The bot could not say its answer aloud")
            finally:
                if moment is not None:
                    self.ends[moment] = self.call.until
                self.to_say.task_done()

    def _looking(self) -> asyncio.Task[bytes | None]:
        if self.looking is None:
            self.looking = asyncio.create_task(spoken(LOOKING, self.voice))
        return self.looking

    def close(self) -> None:
        if self.looking is not None:
            self.looking.cancel()
        self.speaking.cancel()
