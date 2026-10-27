"""The meeting bot's run: ask to join, wait to be admitted, say who it is,
stay until there is a reason to leave, and write each step on the meeting
row.

It runs inside whichever process starts it: the CLI waits for it
(``meetings join``), and the app hands it to the worker, or runs it in its
own process where the stack has none (``domains.bot.dispatch``). Stopped
at shutdown, it records itself as left. It writes the
row only through the service's ``transition`` and ``heartbeat``. Each step
opens its own short session, so an hour-long call holds no database
connection. What it hears goes to whoever the captions say was talking
(``audio.Hearing``). Its camera shows its card, saying what it is doing,
and it says who it is in the chat; it speaks (``voice``) only to answer.
"""

import asyncio
import base64
import contextlib
import math
from pathlib import Path
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import get_async_session
from app.core.log import logger
from app.core.steps import watching
from app.core.tools import acting_as
from app.services.meetings.domains.accounts.service import (
    image_named,
    pick,
    sent_as,
)
from app.services.meetings.domains.actions.changes import (
    watching as runs_watching,
)
from app.services.meetings.domains.actions.live import ASKED
from app.services.meetings.domains.actions.queries import answered_in, going_in
from app.services.meetings.domains.bot import card
from app.services.meetings.domains.bot.answers import Answers
from app.services.meetings.domains.bot.audio import Hearing
from app.services.meetings.domains.bot.dispatch import start_meeting
from app.services.meetings.domains.bot.meet import CallState, MeetPage, open_meet
from app.services.meetings.domains.bot.row import heartbeat, keep_steps, transition
from app.services.meetings.domains.bot.transcript import BEAT_SECONDS, Transcript
from app.services.meetings.domains.bot.voice import (
    live,
    live_engine_of,
    voice_of,
)
from app.services.meetings.domains.moments.tidy import cleaner
from app.services.meetings.domains.people.participants import keep_heard
from app.services.meetings.domains.people.service import guides_writer
from app.services.meetings.domains.series.service import themes_writer
from app.services.meetings.models import (
    LEFT,
    NOT_DONE,
    STILL_WANTED,
    BotAccount,
    Going,
    Meeting,
    MeetingStatus,
    Took,
)
from app.services.meetings.service import JOINS, MeetingsService, notes_writer

POLL_SECONDS = 2.0
# How often instead while a line for the bot is settling or its answer is
# still playing: a beat of the slower one would be on every answer. Her
# answer awaited needs none: it wakes the bot as it lands (``changes``).
QUICK_POLL_SECONDS = 0.5
# How often the runs in flight are read again while any is: the card says
# what is going on without waiting for a beat.
GOING_SECONDS = 2.0
# Said in every call the bot joins, after who it is: nobody is recorded
# without being told.
TRANSCRIBED = "What is said here is transcribed."
ADMIT_TIMEOUT_SECONDS = 300.0
# How long the bot stays once everyone else has gone.
ALONE_SECONDS = 120.0
# How long it waits in a call nobody else has come to yet: the calendar
# sends it a minute early, and people come late.
WAIT_FOR_OTHERS_SECONDS = 900.0
# How long Leave can be gone before the bot takes the call as over: what
# Meet puts over the call (someone joining, a prompt) can hide it for a
# look. A page that says the call ended, or the bot was removed, is over
# at once.
GONE_SECONDS = 10.0
# How long it waits on its way in for Meet to offer captions: Meet draws
# them seconds after letting it in, and what is said meanwhile is lost.
CAPTIONS_WAIT_MS = 15_000


class _RunEnded(Exception):  # noqa: N818 - control flow, not an error
    """The run ends here, as ``status``; a row already done (failed by
    another process) keeps what it says."""

    def __init__(self, status: MeetingStatus, reason: str | None = None) -> None:
        self.status, self.reason = status, reason


class _Pulse:
    """The run's heartbeat, every ``BEAT_SECONDS``: False once the meeting
    is no longer one the run should be in (asked to leave, or failed by
    another process). Each beat also reads the call's runs not yet done
    (``going``) and its last answers (``answered``), for its card; while any
    is going, or once wanted (``soon``), every ``GOING_SECONDS`` between
    beats too."""

    def __init__(self, meeting_id: int) -> None:
        self.meeting_id = meeting_id
        self.last = self.read = float("-inf")
        self.going: list[Going] = []
        self.answered: list[Going] = []  # its last answers, for the card's trail
        self.wanted = False
        self.woken = asyncio.Event()

    def soon(self) -> None:
        """Read the runs in flight on the next look, not the next beat, and
        look now: a run changed here (``changes.watching``) or she took a
        step."""
        self.wanted = True
        self.woken.set()

    async def nap(self, seconds: float) -> None:
        """Wait ``seconds`` until the next look, or until woken (``soon``)."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.woken.wait(), seconds)
        self.woken.clear()

    async def still_wanted(self) -> bool:
        now = asyncio.get_running_loop().time()
        if now - self.last >= BEAT_SECONDS:
            self.last = self.read = now
            async with get_async_session() as session:
                await self._read(session)
                return await heartbeat(session, self.meeting_id) in STILL_WANTED
        if self.wanted or (self.going and now - self.read >= GOING_SECONDS):
            self.read, self.wanted = now, False
            async with get_async_session() as session:
                await self._read(session)
        return True

    async def _read(self, session: AsyncSession) -> None:
        self.going = await going_in(session, self.meeting_id)
        self.answered = await answered_in(session, self.meeting_id)


async def _move(
    meeting_id: int,
    to: MeetingStatus,
    from_: tuple[MeetingStatus, ...],
    reason: str | None = None,
) -> bool:
    async with get_async_session() as session:
        return await transition(session, meeting_id, to, from_=from_, reason=reason)


async def _step(meeting_id: int, to: MeetingStatus, from_: MeetingStatus) -> None:
    """The next step, or the end of the run when the row moved elsewhere
    (a leave request: it leaves; a failure: it stays failed)."""
    if not await _move(meeting_id, to, (from_,)):
        raise _RunEnded(MeetingStatus.LEFT)


async def _admitted(call: MeetPage, pulse: _Pulse) -> None:
    """Back once the host lets the bot in; ends the run otherwise."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + ADMIT_TIMEOUT_SECONDS
    while True:
        state = await call.state()
        if state == CallState.IN_CALL:
            return
        if state == CallState.REFUSED:
            raise _RunEnded(MeetingStatus.FAILED, "The host refused the bot's request")
        if state == CallState.ENDED or not await pulse.still_wanted():
            raise _RunEnded(MeetingStatus.LEFT)
        if loop.time() >= deadline:
            raise _RunEnded(
                MeetingStatus.FAILED,
                f"Nobody admitted the bot within {ADMIT_TIMEOUT_SECONDS:.0f} seconds",
            )
        await asyncio.sleep(POLL_SECONDS)


async def _stay(
    call: MeetPage,
    pulse: _Pulse,
    transcript: Transcript,
    hearing: Hearing,
    shown: card.Card,
    answering: Answers,
) -> None:
    """Back when the bot should leave: asked to, alone too long once the
    others have gone (nobody counted by Meet, nobody talking), or nobody
    came. Ends the run when the call ends on its own (any page but the
    call's). Each look keeps what was said since the last, and gives what
    was heard to its speaker once the captions have caught up."""
    loop = asyncio.get_running_loop()
    # Alone since the others went, or since the bot came while nobody had.
    alone_since: float | None = loop.time()
    others_came = False
    gone_since: float | None = None
    captions_tried = -math.inf
    try:
        while True:
            state = await call.state()
            if state != CallState.IN_CALL:
                gone_since = loop.time() if gone_since is None else gone_since
                # Only Leave missing (WAITING) waits out GONE_SECONDS.
                gone = loop.time() - gone_since >= GONE_SECONDS
                if state != CallState.WAITING or gone:
                    await _left_because(call, transcript.meeting_id, state)
                    raise _RunEnded(MeetingStatus.LEFT)
                await asyncio.sleep(POLL_SECONDS)
                continue
            gone_since = None
            # Meet can draw its captions button after the bot is in: looked
            # for again on the beat, not on every look.
            if not shown.captions and loop.time() - captions_tried >= BEAT_SECONDS:
                captions_tried = loop.time()
                shown.captions = await call.turn_on_captions()
            if steps := call.taken():
                async with get_async_session() as session:
                    await keep_steps(session, transcript.meeting_id, steps)
            spoke = len(transcript.spoke)
            if writing := transcript.take(await call.captions()):
                async with get_async_session() as session:
                    made = await transcript.write(session, writing)
                await answering.heard(made)
            if answering.waiting:
                async with get_async_session() as session:
                    await answering.answer(session)
            await answering.mic()
            hearing.settle(transcript.spoke, loop.time())
            if not await pulse.still_wanted():
                return
            saying = answering.saying()
            await shown.update(
                pulse.going,
                saying,
                pulse.answered,
                transcript.hearing(),
                her=(transcript.bot_spoke, transcript.bot_said),
            )
            # A caption that moved is someone here, whatever Meet's People
            # count says: it can read 1 with others in the call.
            talking = len(transcript.spoke) > spoke
            people = await call.people()
            if talking or people is None or people > 1:
                others_came = others_came or talking or people is not None
                alone_since = None
            elif alone_since is None:
                alone_since = loop.time()
            elif loop.time() - alone_since >= (
                ALONE_SECONDS if others_came else WAIT_FOR_OTHERS_SECONDS
            ):
                logger.info(
                    "Leaving: alone in the call",
                    meeting_id=transcript.meeting_id,
                    others_came=others_came,
                )
                return
            await pulse.nap(between(bool(transcript.held), bool(saying)))
    finally:
        if rest := transcript.rest():
            async with get_async_session() as session:
                await transcript.write(session, rest)
        hearing.settle(transcript.spoke, math.inf)
        hearing.close()
        if hearing.seconds:
            async with get_async_session() as session:
                await keep_heard(session, transcript.meeting_id, hearing.seconds)


def between(held: bool, saying: bool) -> float:
    """How long until the next look: quick while a line for the bot is
    settling (``held``) or its answer is playing (``saying``)."""
    return QUICK_POLL_SECONDS if held or saying else POLL_SECONDS


async def _left_because(call: MeetPage, meeting_id: int, state: CallState) -> None:
    """Say why the call is over for the bot, with what the page showed: the
    one record of a call it left on its own, kept with its steps."""
    page = await call.page_text()
    call.took(LEFT, state, page)
    logger.warning(
        "The call is over for the bot", meeting_id=meeting_id, state=state, page=page
    )


def announcement(name: str) -> str:
    """What the bot says when it joins: who it is
    (``MEETINGS_ANNOUNCEMENT``, ``{name}`` the name it joins as), then
    that the call is transcribed, whatever the first is set to."""
    who = settings.MEETINGS_ANNOUNCEMENT.replace("{name}", name).rstrip(" .:")
    return f"{who}. {TRANSCRIBED}"


async def _start(
    session: AsyncSession, meeting: Meeting, account: BotAccount
) -> card.Start:
    """The card the bot joins as: the name it joins as, and its agent's
    (``account``) picture and camera setting."""
    kept = await image_named(session, account.name)
    image = None
    if kept is not None:
        encoded = base64.b64encode(kept.data).decode()
        image = f"data:{kept.content_type};base64,{encoded}"
    return card.Start(name=meeting.bot_name, image=image, camera=account.camera)


async def _join(
    meeting: Meeting,
    login: str,
    start: card.Start,
    voice: Any | None,
    engine: Any | None,
    taken: list[Took],
) -> None:
    """Into the call signed in as the agent it was sent as (``login``),
    showing its card (``start``), speaking in ``voice`` (``voice_of``), her
    answers made live on ``engine`` where there is one (``live_engine_of``).
    What it did on the page and has not kept yet ends up in ``taken``."""
    meeting_id: int = meeting.id  # type: ignore[assignment]
    pulse = _Pulse(meeting_id)
    keep_in = settings.MEETINGS_KEEP_AUDIO_DIR
    hearing = Hearing(Path(keep_in) / str(meeting_id) if keep_in else None)
    async with open_meet(meeting.url, hearing.heard, login=login, start=start) as call:
        try:
            await _in_call(call, meeting, pulse, hearing, voice, engine)
        finally:
            taken.extend(call.taken())


async def _in_call(
    call: MeetPage,
    meeting: Meeting,
    pulse: _Pulse,
    hearing: Hearing,
    voice: Any | None,
    engine: Any | None,
) -> None:
    """The call, from asking to join to leaving."""
    meeting_id: int = meeting.id  # type: ignore[assignment]
    if not await pulse.still_wanted():
        raise _RunEnded(MeetingStatus.LEFT)
    await call.ask_to_join(meeting.bot_name)
    await _step(meeting_id, MeetingStatus.WAITING, MeetingStatus.JOINING)
    await _admitted(call, pulse)
    await _step(meeting_id, MeetingStatus.IN_CALL, MeetingStatus.WAITING)
    transcript = Transcript(meeting_id, meeting.bot_name)
    # Hearing first: posting in the chat can take seconds.
    captions = await call.turn_on_captions(CAPTIONS_WAIT_MS)
    if not captions:
        logger.warning("No captions in this call", meeting_id=meeting_id)
    # In the chat only: said aloud, it cut into the call as it joined.
    await call.say(announcement(meeting.bot_name))
    shown = card.Card(call, captions, meeting.bot_name)
    await shown.update([], set(), [])
    answering: Answers | None = None

    def heard(step: str) -> None:
        """A step of her turns here (live, or answered in the app): on
        the card under the question it answers, read at the next look,
        and, for one put to her, that she looks it up."""
        moment = ASKED.get()
        if answering is not None:
            moment = answering.looking_up(moment)
        if moment is not None:
            shown.heard(step, moment)
            pulse.soon()

    # What is started inside (her live call, her answers) carries them.
    with watching(heard), runs_watching(pulse.soon):
        async with live(call, voice, engine, meeting.owner_user_id) as her_voice:
            answering = Answers(call, voice, her_voice)
            transcript.her = answering.talk
            try:
                await _stay(call, pulse, transcript, hearing, shown, answering)
            finally:
                answering.close()
    await call.show(status=card.LEAVING, focus=None, pills=[])
    await call.leave()


async def _after(meeting_id: int) -> None:
    """Once the bot is out: the notes, the questions cleaned up, how to work
    with each person and what the meeting's series keeps coming back to,
    where the stack has a model to write them."""
    if (write := notes_writer()) is not None:
        await write(meeting_id)
    if (clean := cleaner()) is not None:
        await clean(meeting_id)
    if (guide := guides_writer()) is not None:
        await guide(meeting_id)
    if (themes := themes_writer()) is not None:
        await themes(meeting_id)


async def run_meeting(meeting_id: int) -> None:
    """Take the bot through one meeting, start to finish, then write what
    it came to. Stopped from outside, it writes nothing (the page can). A
    meeting already taken (by another run, or left before any) is not this
    run's: a job delivered twice does nothing the second time."""
    if not await _move(meeting_id, MeetingStatus.JOINING, (MeetingStatus.REQUESTED,)):
        return
    async with get_async_session() as session:
        meeting = await MeetingsService(session, None).get(meeting_id)
        account = await sent_as(session, meeting.account_id)
        start = await _start(session, meeting, account)
        voice = await voice_of(session)
        engine = await live_engine_of(session, voice)
    # What the bot spends (her answers, its speech, the notes after) is the
    # meeting owner's, bound once for the run.
    taken: list[Took] = []
    with acting_as(meeting.owner_user_id, None):
        try:
            if meeting.platform not in JOINS:
                raise _RunEnded(
                    MeetingStatus.FAILED,
                    f"The bot joins Google Meet so far, not {meeting.platform.title()}",
                )
            await _join(meeting, account.login_secret, start, voice, engine, taken)
            await _move(meeting_id, MeetingStatus.LEFT, NOT_DONE)
        except _RunEnded as ended:
            await _move(meeting_id, ended.status, NOT_DONE, ended.reason)
        except asyncio.CancelledError:
            # Stopped from outside (Ctrl-C, the app shutting down): the browser
            # closed on the way out, so the bot has left the call.
            await _move(meeting_id, MeetingStatus.LEFT, NOT_DONE)
            raise
        except Exception as exc:
            logger.exception("Meeting bot failed", meeting_id=meeting_id)
            await _move(meeting_id, MeetingStatus.FAILED, NOT_DONE, str(exc))
        finally:
            if taken:
                async with get_async_session() as session:
                    await keep_steps(session, meeting_id, taken)
        await _after(meeting_id)


async def send_bot(
    svc: MeetingsService,
    url: str,
    bot_name: str,
    agent: str | None = None,
    every: list[BotAccount] | None = None,
) -> Meeting:
    """Record the meeting and start the bot on it as ``agent`` (the default
    when none is named; of ``every``, the agents, when read already),
    without waiting: the one way in for the Meetings page, Overseer and the
    API. It joins as the agent's name unless given ``bot_name``."""
    account = await pick(svc.db, agent, every)
    meeting = await svc.request(
        url, bot_name.strip() or account.display_name, account.id
    )
    meeting_id: int = meeting.id  # type: ignore[assignment]
    try:
        await start_meeting(meeting_id)
    except Exception as exc:
        # Nothing will ever run it: say so on the row, not only in this log.
        logger.exception("Meeting bot not started", meeting_id=meeting_id)
        await transition(
            svc.db,
            meeting_id,
            MeetingStatus.FAILED,
            from_=(MeetingStatus.REQUESTED,),
            reason=f"The bot could not be started: {exc}",
        )
    return meeting
