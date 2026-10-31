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
are read on while it talks.

Talked over (a cut-in), she goes quiet where she was heard to and keeps
the rest (``pause``); told to go on, she says it (``go_on``), and a new
question put to her drops it. A stop drops everything (``stop``)."""

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
from app.services.meetings.domains.moments.detectors import (
    ADDRESSED,
    CUT_IN,
    GO_ON,
    STOP,
)
from app.services.meetings.domains.moments.service import answerer
from app.services.meetings.models import DONE

LOOKING = "Let me look that up."
NOT_FOUND = "Sorry, I couldn't find that."
# What she is asked live when told to go on: her call has her answer cut
# where it was heard to (``LiveVoice.stop``).
CARRY_ON = (
    "You were cut off. Carry on from where you were cut off, without starting over."
)
# A run on a line telling her to go on, said back to her: not a question.
WENT_ON = "Taken as told to go on."


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
        # The last answer said (its moment, sentences, and when each made
        # has played), and, once cut in on, what she was saying, still to say.
        self.said_last: tuple[int | None, list[str], list[float]] | None = None
        self.kept: list[tuple[int | None, str]] | None = None
        self.going_on: asyncio.Task[None] | None = None  # told to, live
        self.cut_short: set[int] = set()  # cut off live before it was back

    async def heard(self, db: AsyncSession, made: list[tuple[int, str]]) -> None:
        """New moments (id, kind): a stop drops everything (``stop``), a
        cut-in pauses her (``pause``). Told to go on, she does (``go_on``);
        else each put to her is waited on, and drops what a cut-in kept."""
        kinds = {kind for _, kind in made}
        if STOP in kinds:
            await self.stop(db)
        if CUT_IN in kinds:
            await self.pause()
        asked = [
            moment
            for moment, kind in made
            if kind == ADDRESSED and self.answers and moment not in self.waiting
        ]
        if GO_ON in kinds and self.kept is not None:
            # ponytail: what else is put to her in the same look goes with the
            # go-on (said back, it is asked too); carry each moment's line to
            # tell them apart if two lines put to her ever land in one look.
            if asked:
                await runs.drop(db, asked, WENT_ON)
            kept, self.kept = self.kept, None
            self.go_on(kept)
            return
        if asked:
            self.kept = None
        now = asyncio.get_running_loop().time()
        for moment in asked:
            self.waiting[moment] = now
            logger.info("Bot: asked by name, her answer asked", moment=moment)

    async def stop(self, db: AsyncSession) -> None:
        """Told to stop: every answer owed dropped (its run cut off and
        failed, never posted or said) and what she is saying cut off
        (``_cut_off``). She listens again: only a line put to her wakes her."""
        logger.info("Bot: told to stop", dropped=len(self.waiting))
        await runs.drop(db, sorted(self.waiting))
        await self._cut_off()
        for owed in (self.waiting, self.looked, self.told, self.cut_short):
            owed.clear()
        self.kept = None

    async def pause(self) -> None:
        """Cut in on while she is saying an answer: it is cut off
        (``_cut_off``) and what the room has not heard of it kept
        (``kept``): from the sentence playing, then all still to say but
        that she is looking it up. Live, the answers she was saying, or
        making: heard as she makes it, before its run is back."""
        saying = self.saying()
        if not saying and self._live():
            if self.call.until > asyncio.get_running_loop().time():
                saying = set(self.waiting)
        if self.kept is not None or not saying:
            return
        rest = self._unheard()
        queued = [said for said in await self._cut_off() if said[1] != LOOKING]
        self.kept = rest + queued or [(moment, "") for moment in sorted(saying)]
        logger.info("Bot: cut in on, the rest kept", kept=len(self.kept))

    def _unheard(self) -> list[tuple[int | None, str]]:
        """What of the last answer said (``said_last``) has not played yet:
        from the sentence playing on, those not yet made among them."""
        if self.said_last is None:
            return []
        moment, said, ends = self.said_last
        now = asyncio.get_running_loop().time()
        at = next((n for n, end in enumerate(ends) if end > now), len(ends))
        rest = " ".join(said[at:])
        return [(moment, rest)] if rest else []

    def go_on(self, kept: list[tuple[int | None, str]]) -> None:
        """Told to go on: what she was cut off saying (``kept``) said on.
        Live, she is asked to carry on (``CARRY_ON``), as her call heard her."""
        logger.info("Bot: told to go on", kept=len(kept))
        if self._live():
            moment = kept[0][0]
            unposted = moment in self.cut_short
            self.cut_short.clear()
            self.going_on = asyncio.create_task(self._carry_on(moment, unposted))
            return
        for moment, text in kept:
            if text:
                self._aloud(text, moment)

    async def _carry_on(self, moment: int | None, unposted: bool) -> None:
        """Her live answer, gone on with: saying it until it has played, and
        posted in the chat where what she was cut off saying never was."""
        assert self.live is not None
        if moment is not None:
            self.ends[moment] = math.inf
        try:
            self.words = await self.live.ask(CARRY_ON)
            if unposted and self.words:
                await self.call.say(self.words)
        except Exception:
            logger.exception("She could not go on with her answer")
        finally:
            if moment is not None:
                self.ends[moment] = self.call.until

    async def _cut_off(self) -> list[tuple[int | None, str]]:
        """What she is saying cut off (her live answer, what is queued, what
        the call is playing) and her mic closed; what was still to say."""
        for task in (self.speaking, self.going_on):
            if task is not None:
                task.cancel()
                # Over before what it said is forgotten: its end is written
                # as it stops.
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        queued: list[tuple[int | None, str]] = []
        while not self.to_say.empty():
            queued.append(self.to_say.get_nowait())
            self.to_say.task_done()
        self.ends.clear()
        self.said_last = self.going_on = None
        self.speaking = asyncio.create_task(self._speaking())
        if self.live is not None:
            await self.live.stop()
        await self.call.silence()
        await self.call.hush()
        return queued

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
            if self.kept is not None and not result and self._live():
                self.cut_short.add(moment)  # posted once she goes on
                continue
            said = result if status == DONE and result else NOT_FOUND
            await self.call.say(said)
            if self.kept is not None:  # cut in on: said once told to go on
                self.kept.append((moment, said))
            else:
                self._aloud(said, moment)
        looked = (self.looked & self.waiting.keys()) - self.told
        if looked and not self._live() and self.kept is None:
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
                ends: list[float] = []
                if text == LOOKING:
                    parts = [self._looking()]
                else:
                    said = sentences(text)
                    parts = [
                        asyncio.create_task(spoken(sentence, self.voice))
                        for sentence in said
                    ]
                    self.said_last = (moment, said, ends)
                loop = asyncio.get_running_loop()
                began = loop.time()
                for n, part in enumerate(parts, 1):
                    if (audio := await part) is None:
                        ends.append(-math.inf)
                        continue
                    await self.call.speak(audio)
                    ends.append(self.call.until)
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
        for task in (self.looking, self.going_on, self.speaking):
            if task is not None:
                task.cancel()
