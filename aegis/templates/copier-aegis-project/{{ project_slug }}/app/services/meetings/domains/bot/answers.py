"""Questions put to the bot by name in a call, answered out loud: once her
answer to one (an ``addressed`` moment; ``actions.ask_ai``) is done, it is
posted in the chat at once and said aloud, and one that failed, that it
could not find it. An answer not back within ``LOOKING_AFTER`` seconds is
said to be looked up (``LOOKING``, its speech made as it joins), once; a
quick one is just said. Without a voice it types instead.

Speech is said apart from the call's loop (``_speaking``): made a sentence
at a time, the first played while the rest are made, so captions are read
on while it talks."""

import asyncio
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.log import logger
from app.services.meetings.domains.actions.queries import answered
from app.services.meetings.domains.bot.voice import sentences, spoken
from app.services.meetings.domains.moments.detectors import ADDRESSED
from app.services.meetings.domains.moments.service import answerer
from app.services.meetings.models import DONE

LOOKING = "Let me look that up."
LOOKING_AFTER = 3.0
NOT_FOUND = "Sorry, I couldn't find that."


class Answers:
    """The call's questions put to the bot, from heard to answered."""

    def __init__(self, call: Any, voice: Any | None) -> None:
        self.call, self.voice = call, voice
        # What answers her (``answerer``); with nothing, nothing is waited on.
        self.answers = answerer()
        self.waiting: dict[int, float] = {}  # moment -> when it was heard
        self.told: set[int] = set()  # those said to be looked up
        self.looking = asyncio.create_task(spoken(LOOKING, voice))
        self.to_say: asyncio.Queue[str] = asyncio.Queue()
        self.speaking = asyncio.create_task(self._speaking())

    async def heard(self, made: list[tuple[int, str]]) -> None:
        """New moments (id, kind): each put to the bot is waited on."""
        now = asyncio.get_running_loop().time()
        for moment, kind in made:
            if kind == ADDRESSED and self.answers and moment not in self.waiting:
                self.waiting[moment] = now
                logger.info("Bot: asked by name, her answer asked", moment=moment)

    async def answer(self, db: AsyncSession) -> None:
        """Each answer done since the last look, posted in the chat and
        said aloud; for those still slow to come, that it is looking them
        up."""
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
            self._aloud(said)
        since = now - LOOKING_AFTER
        slow = {m for m, heard in self.waiting.items() if heard <= since} - self.told
        if slow:
            self.told |= slow
            if self.voice is None:
                await self.call.say(LOOKING)
            self._aloud(LOOKING)

    def _aloud(self, text: str) -> None:
        if self.voice is not None:
            self.to_say.put_nowait(text)

    async def said(self) -> None:
        """Once everything given it to say has been said."""
        await self.to_say.join()

    async def _speaking(self) -> None:
        """Say each thing given it in turn, a sentence at a time: every
        sentence's speech made at once, each played as soon as it and those
        before it are."""
        while True:
            text = await self.to_say.get()
            try:
                parts = (
                    [self.looking]
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
                    made = loop.time() - began
                    await self.call.speak(audio)
                    logger.info(
                        "Bot: said a sentence aloud",
                        sentence=f"{n}/{len(parts)}",
                        ready_after=round(made, 1),
                        done_after=round(loop.time() - began, 1),
                    )
            except Exception:
                # Posted in the chat already: the call goes on unheard.
                logger.exception("The bot could not say its answer aloud")
            finally:
                self.to_say.task_done()

    def close(self) -> None:
        self.looking.cancel()
        self.speaking.cancel()
