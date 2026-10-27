"""The agent's card in a call: what its camera shows (its image, or its
initials, its name and what it is doing) and the voice its microphone
carries.

The page is hooked before Meet loads (``script``): Meet's camera and
microphone requests are answered by the page itself, the camera with a
canvas the card is drawn on (``card.js``), the microphone with a track
that carries only what the bot says (``speak``). Idle, the card is the
agent; with requests in flight it presents one (``Card``: ``Focus``, the
question as put, what the agent is doing, then its answer in brief), the
agent small at the top left, the others as pills along the foot (up next,
and its last answers), the bottom right left clear for the host's own
picture Meet lays there. The browser has no devices of its
own, so the page lists these as its camera, microphone and speaker; with
none, Meet says "Camera not found" and never asks. The canvas is redrawn only when the
card changes (``show``), drawn at twice its size for a sharp picture, and
sent ten frames a second, steady: fewer, Meet left a change half drawn or
not drawn at all. An agent with its camera off gives Meet no
picture at all. The script runs in the page itself, never in the frames
Meet opens inside it, and carries no picture: its initials stand until
the page has loaded and the picture is handed over (``open_meet``).
"""

import asyncio
import base64
from collections.abc import Sequence
import json
import math
from pathlib import Path
import re
from typing import Any

from playwright.async_api import Page
from pydantic import BaseModel, ConfigDict

from app.services.meetings.domains.bot.voice import sentences
from app.services.meetings.domains.moments.detectors import put_to
from app.services.meetings.models import CLAIMED, DONE, IN_THE_APP, Going

LISTENING = "Listening"
NO_CAPTIONS = "Can't see captions"
QUESTION_HEARD = "Question heard"
ANSWERING = "Answering"
LEAVING = "Leaving"
# Where a request in flight is, as the card says it.
WAITING = "waiting"
ANSWERING_ITEM = "answering"
SAYING = "saying it"
# A line put to the agent still being said: not yet a request.
HEARING = "hearing"
HEARD_RANK = 3  # where it comes in which request the card is about (``_rank``)
# What a pill along the foot says it is.
NEXT, ANSWERED, FAILED_PILL = "next", "answered", "failed"
NOT_FOUND = "Couldn't find that."
# How long an answer back stays up once it has played, while nothing else is
# asked: live, most of it plays as she makes it, before it is back at all.
LINGER_SECONDS = 8.0
# What the agent says before an answer, which is not the answer: the trail
# keeps the first sentence that is (``gist``).
LEAD_IN = re.compile(
    r"^(let me|sure|okay|ok|alright|all right|one moment|give me|i'll|i will)\b",
    re.IGNORECASE,
)


class Start(BaseModel):
    """The card as the bot joins: who it is, its image (a data URL) and
    whether its camera is on."""

    name: str
    image: str | None = None
    camera: bool = True


class Focus(BaseModel):
    """The one request the card is about: the question as put (``put_to``),
    where it is, what the agent is doing about it and how many steps in,
    and once it is saying the answer, the answer in brief (``brief``)."""

    model_config = ConfigDict(frozen=True)

    question: str
    status: str
    step: str | None = None
    steps: int = 0
    verdict: str | None = None
    detail: str | None = None
    # What it is saying while it works, as Meet captions it ("Let me check
    # the recent logs"), until its answer is back.
    voice: str | None = None


class Pill(BaseModel):
    """A request beside the one in focus, a line along the card's foot:
    one up next, or one already answered (or not)."""

    model_config = ConfigDict(frozen=True)

    question: str
    mark: str


def brief(answer: str) -> tuple[str, str]:
    """An answer in brief: its first sentence past what is said before it
    (``LEAD_IN``: "Let me check...", "Sure, ..."), and the one after; its
    first alone where it is all lead-in."""
    said = sentences(answer)
    real = [s for s in said if not LEAD_IN.match(s)] or said[:1]
    return (real[0] if real else "", real[1] if len(real) > 1 else "")


def status_of(captions: bool, going: list[Going]) -> str:
    """What the bot is doing, from what it knows: answering a question a
    runner has taken or saying one's answer (``going``: the call's runs
    not yet done, and those done it is still saying), one heard and
    waiting, captions it cannot see (nothing is being written), else
    listening."""
    if any(run.status in (CLAIMED, DONE) for run in going):
        return ANSWERING
    if going:
        return QUESTION_HEARD
    return LISTENING if captions else NO_CAPTIONS


class Card:
    """What the bot's card shows, from the last read (``update``): its
    status, the one request it is about (``Focus``: the one it is saying,
    else answering, else hearing, else waiting), the others as pills (up
    next, and its last answers), and what it is doing for each (``heard``);
    a run done stays its focus until it has been said. Redrawn only when
    that changes."""

    def __init__(self, call: Any, captions: bool, name: str = "") -> None:
        self.call, self.captions, self.name = call, captions, name
        self.shown: tuple[str, Focus | None, tuple[Pill, ...]] = (LISTENING, None, ())
        self.runs: dict[int, Going] = {}  # moment -> its run, as listed
        # moment -> what it is doing for it, and how many steps so far
        self.steps: dict[int, tuple[str, int]] = {}
        self.back_at: dict[int, float] = {}  # moment -> when its answer was back
        self.seen_at: dict[int, float] = {}  # moment -> when it was first shown
        # What it looked something up for: only those answers are history (a
        # mic check is small talk, kept in the chat).
        self.looked: set[int] = set()

    def heard(self, step: str, moment: int) -> None:
        """A step of the agent's turn answering ``moment``."""
        self.steps[moment] = (step, self.steps.get(moment, ("", 0))[1] + 1)
        self.looked.add(moment)

    async def update(
        self,
        going: list[Going],
        saying: set[int],
        answered: list[Going],
        hearing: Sequence[tuple[str, str]] = (),
        her: tuple[float, str] = (-math.inf, ""),
    ) -> None:
        """The card for the runs in flight (``going``), the moments whose
        answers it is still saying (``saying``), the lines put to it still
        being said (``hearing``: speaker, what of it so far), its last
        answers (``answered``, newest first: ``answered_in``), and its own
        words as Meet last captioned them (``her``: when, and what)."""
        were, now = self.runs, asyncio.get_running_loop().time()
        going_on = {run.moment for run in going}
        over = {run.moment: run for run in answered}
        for m in were.keys() - going_on:
            if m in over:
                self.back_at.setdefault(m, now)
        asked = bool(going or hearing)  # something else to show
        said = {
            m: run.model_copy(update={"status": DONE})
            for m, run in were.items()
            if m not in going_on
            and (
                m in saying
                or (not asked and now - self.back_at.get(m, -math.inf) < LINGER_SECONDS)
            )
        }
        self.runs = said | {run.moment: run for run in going}
        # A step heard before its run is read stays for it; one of a run
        # gone goes with it.
        self.steps = {
            m: s for m, s in self.steps.items() if m in self.runs or m not in were
        }
        self.back_at = {m: t for m, t in self.back_at.items() if m in self.runs}
        self.seen_at = {m: self.seen_at.get(m, now) for m in self.runs}
        listed = sorted(self.runs.values(), key=lambda run: (_rank(run), run.id))
        status = status_of(self.captions, listed)
        if hearing and not listed:
            status = QUESTION_HEARD
        heard = [put_to(text, self.name) for _, text in hearing]
        focus: Focus | None = None
        if listed and (_rank(listed[0]) < HEARD_RANK or not heard):
            first = listed.pop(0)
            focus = self._focus(first, over.get(first.moment), her)
        elif heard:
            focus = Focus(question=heard.pop(0), status=HEARING)
        pills = (
            ()
            if focus is None
            else tuple(
                [Pill(question=self._asked(r), mark=NEXT) for r in listed]
                + [Pill(question=q, mark=NEXT) for q in heard]
                + [
                    Pill(
                        question=self._asked(r),
                        mark=ANSWERED if r.status == DONE else FAILED_PILL,
                    )
                    for r in answered
                    if r.moment not in self.runs and r.moment in self.looked
                ]
            )
        )
        if (status, focus, pills) != self.shown:
            self.shown = (status, focus, pills)
            await self.call.show(
                status=status,
                focus=None if focus is None else focus.model_dump(),
                pills=[pill.model_dump() for pill in pills],
            )

    def _asked(self, run: Going) -> str:
        return put_to(run.text, self.name)

    def _focus(self, run: Going, over: Going | None, her: tuple[float, str]) -> Focus:
        if run.status == DONE:
            if over is not None and over.status != DONE:
                return Focus(
                    question=self._asked(run), status=SAYING, verdict=NOT_FOUND
                )
            verdict, detail = brief(over.result or "" if over else "")
            return Focus(
                question=self._asked(run),
                status=SAYING,
                verdict=verdict or None,
                detail=detail or None,
            )
        if run.status != CLAIMED:
            status = WAITING
        elif run.runner in (None, IN_THE_APP):
            status = ANSWERING_ITEM
        else:
            status = f"{ANSWERING_ITEM} on {run.runner}"
        spoke, words = her
        said = sentences(words)
        voice = said[-1] if said and spoke > self.seen_at[run.moment] else None
        step, steps = self.steps.get(run.moment, (None, 0))
        return Focus(
            question=self._asked(run),
            status=status,
            step=step,
            steps=steps,
            voice=voice,
        )


def _rank(run: Going) -> int:
    """Which request the card is about first: the one it is saying, then
    one it answers here, one answered elsewhere, (a line being heard,
    ``HEARD_RANK``), one waiting."""
    if run.status == DONE:
        return 0
    if run.status == CLAIMED:
        return 1 if run.runner in (None, IN_THE_APP) else 2
    return 4


def initials(name: str) -> str:
    """What stands for an agent with no image: the first letter of each
    of its first two words."""
    letters = [word[0] for word in name.split()[:2]]
    return "".join(letters).upper() or "?"


# Defines ``window.__meetingCard`` and answers getUserMedia before the
# page's own scripts run (``card.js``, ``__START__`` the card as it joins).
CARD = (Path(__file__).parent / "card.js").read_text()


def script(start: Start) -> str:
    """The card's page script, for the agent as it joins: everything but
    its picture (a data URL of megabytes, in a script Meet runs in every
    page it opens, kept Meet from loading), handed over once it has
    loaded."""
    card = start.model_dump(exclude={"image"}) | {
        "initials": initials(start.name),
        "status": LISTENING,
        "focus": None,
        "pills": [],
    }
    return CARD.replace("__START__", json.dumps(card))


async def show(page: Page, **update: Any) -> None:
    """Redraw the card with ``update`` (its status, image, name, ``focus``
    or ``pills``, each as a dict); a page opened without the card
    (``script``) has none to redraw."""
    await page.evaluate("(update) => window.__meetingCard?.show(update)", update)


async def speak(page: Page, audio: bytes) -> float:
    """Play ``audio`` (any format the browser decodes: TTS's MP3 or WAV) into the
    microphone; how many seconds it lasts."""
    encoded = base64.b64encode(audio).decode()
    return await page.evaluate("(audio) => window.__meetingCard.speak(audio)", encoded)


async def stream(page: Page, pcm: bytes, rate: int) -> float:
    """Play a piece of speech still being made (PCM16 mono at ``rate``)
    into the microphone, after what is already playing; how many seconds
    are still to play."""
    encoded = base64.b64encode(pcm).decode()
    return await page.evaluate(
        "([pcm, rate]) => window.__meetingCard.stream(pcm, rate)", [encoded, rate]
    )
