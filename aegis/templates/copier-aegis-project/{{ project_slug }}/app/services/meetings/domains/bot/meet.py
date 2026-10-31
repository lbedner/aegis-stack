"""Google Meet's page, in one place: when Meet changes its UI, this module
is the fix.

The recipe is the MT-02 spike's: headless Chromium with fake media
devices, answer the "see and hear you?" dialog, give the bot's name, and
click whichever join button Meet shows. A signed-in Google account is
what gets the bot past Meet's guest check: ``open_meet`` joins with the
bot's stored sign-in (``login``), as a guest until there is one, and
hands the call's audio to whoever asks (``audio.listen``). Its camera is
its card and its microphone its voice (``card``): it joins with both,
muted, and unmutes only while it speaks.

Each control is found by its label, else by Meet's keyboard shortcut where
it has a safe one, and what it did is kept (``Steps``, ``models.bot``):
the first time each control went each way, with the page's buttons where
the label was not there, so a renamed one says what it is called now.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
import contextlib
from contextlib import asynccontextmanager
from enum import StrEnum
import re
from typing import Any

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.components.browser.client import connect
from app.core.time import utcnow
from app.services.meetings.domains.bot import card
from app.services.meetings.domains.bot.audio import listen
from app.services.meetings.domains.bot.login import LOGIN, stored_login
from app.services.meetings.models import (
    ALREADY,
    CAPTIONS,
    CHAT,
    JOIN,
    LABEL,
    LEAVE,
    MIC,
    MISSED,
    SHORTCUT,
    Caption,
    Took,
)

# A camera and microphone granted without a prompt, the card's script
# answering for both (``card``), and sound that plays with nobody at the
# page to click: the bot's voice.
BROWSER_ARGS = [
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
    "--autoplay-policy=no-user-gesture-required",
]

USE_MEDIA = 'button:has-text("Use microphone and camera")'
CONTINUE_WITHOUT_MEDIA = 'button:has-text("Continue without microphone and camera")'
MIC_ON = 'button[aria-label^="Turn on microphone"]'
MIC_OFF = 'button[aria-label^="Turn off microphone"]'
# After its words have played, a moment before it mutes: the end is not
# cut off.
SPOKEN_TAIL = 0.3
# Before its first words in a call, a moment after unmuting: Meet opens the
# microphone late the first time, and cut "Let me look that up" short.
FIRST_UNMUTE = 0.4
# How far ahead of what plays a live voice is taken: made faster than it
# plays, it is otherwise all taken at once, and her session counts it heard
# (``played_audio_bytes``), so cut off, she is cut past where the room was.
AHEAD_SECONDS = 0.5
NAME_INPUT = 'input[type="text"]'
JOIN_BUTTON = (
    'button:has-text("Join now"), button:has-text("Ask to join"), '
    'button:has-text("Switch here")'
)
# Meet draws its lobby a while after the page loads.
LOBBY_TIMEOUT_MS = 30_000
LEAVE_BUTTON = 'button[aria-label*="Leave call"]'
# How much of the page a log of why the bot left keeps.
PAGE_TEXT_KEPT = 1000
# The participant count badge: named "People" by aria-labelledby, not a label.
PEOPLE_BUTTON = 'role=button[name="People"]'
CHAT_BUTTON = 'button[aria-label*="Chat with everyone"]'
CHAT_INPUT = 'textarea[aria-label*="Send a message"]'
CAPTIONS_BUTTON = 'button[aria-label^="Turn on captions"]'
# Meet's own keyboard shortcuts, tried where a control's label is gone.
# The mic's (ctrl+d) is not: it toggles, and pressed not knowing which
# way the mic is it could leave it open.
CAPTIONS_SHORTCUT = "c"
CHAT_SHORTCUT = "Control+Alt+c"
# How long a shortcut has to show what it does.
SHORTCUT_WAIT_MS = 2000
# The page's buttons as a reader hears them (their labels, else their
# text), once each: what to look for a control as, where its label is gone.
BUTTONS = """() => [...new Set([...document.querySelectorAll('button, [role=button]')]
  .filter((button) => button.checkVisibility())
  .map((button) => (button.getAttribute('aria-label') || button.innerText || '')
    .trim().replace(/\\s+/g, ' '))
  .filter(Boolean))].join('\\n')"""
BUTTONS_KEPT = 2000
# What Meet puts over the call once the bot is in, each covering the chat,
# captions and Leave until answered: that a notetaker (Gemini) is on,
# accepted with "Join now" (the bot is one itself), and tips about its
# camera ("Got it"). Answered in one look, the click going to the button
# itself so one prompt stacked over another cannot block it. Only ever run
# in the call: in the lobby "Join now" is the join button.
ANSWER_PROMPTS = """() => {
  for (const button of document.querySelectorAll('button, [role=button]')) {
    const said = (button.innerText || button.getAttribute('aria-label') || '').trim();
    if ((said === 'Join now' || said === 'Got it') && button.checkVisibility()) {
      button.click();
    }
  }
}"""
# How long the bot keeps trying to post in the chat: a prompt can come a
# moment after it is let in.
SAY_TRIES = 30
CAPTIONS_REGION = 'role=region[name="Captions"]'
# Each block is a speaker's name, then what they said. A block is tagged
# the first time it is read, so one Meet is still writing reads as the same
# line on the next look; the counter is the page's, so blocks never share
# a tag. A block with a button is the region's own control, not a caption.
READ_CAPTIONS = """(region) => [...region.children].flatMap((block) => {
  if (block.querySelector('button')) return [];
  const [speaker, ...words] = block.innerText.split('\\n');
  if (!speaker || !words.length) return [];
  block.dataset.line ??= String((window.captionLines = (window.captionLines || 0) + 1));
  return [{line: block.dataset.line, speaker: speaker.trim(), text: words.join(' ').trim()}];
})"""


# How much of what Meet shows has to match what was already heard to find
# where a trimmed block picks up.
ANCHOR = 24


def merge_caption(kept: str, shown: str) -> str:
    """A caption block as heard so far, from what was kept of it and what
    Meet shows now. Meet keeps a long turn short on screen by trimming its
    start as it grows: the start already heard stays, and from where the
    block picks up Meet's text wins (it corrects words as it goes)."""
    if not kept or shown.startswith(kept[:ANCHOR]):
        return shown
    at = kept.rfind(shown[:ANCHOR])
    if at >= 0:
        return kept[:at] + shown
    # ponytail: no overlap found. Longer is Meet correcting the block's
    # start: take it. Shorter is a long gap between looks: keep both rather
    # than lose either; a fuzzy match would join them if this shows up.
    return shown if len(shown) >= len(kept) else f"{kept} {shown}"


class CallState(StrEnum):
    WAITING = "waiting"
    IN_CALL = "in_call"
    REFUSED = "refused"
    ENDED = "ended"


# What the page says, read before the Leave button: the waiting room shows
# that button too (``STATE``).
PAGE_TEXTS = (
    (CallState.REFUSED, ("denied your request", "can't join this video call")),
    (
        CallState.ENDED,
        ("You left the meeting", "removed from the meeting", "call has ended"),
    ),
    (CallState.WAITING, ("until a meeting host brings you in", "Asking to be let in")),
)


# The state ``PAGE_TEXTS`` names, from the page's text, else in the call
# while Leave shows, else waiting.
STATE = """([texts, leave, inCall, waiting]) => {
  const body = document.body.innerText;
  for (const [state, said] of texts) {
    if (said.some((text) => body.includes(text))) return state;
  }
  const button = document.querySelector(leave);
  return button && button.checkVisibility() ? inCall : waiting;
}"""


class MeetPageError(RuntimeError):
    """The page is not the one this module knows."""


class Steps:
    """What the bot did on the page (``models.bot``): the first time each
    control went each way in the call, kept until taken to be written."""

    def __init__(self) -> None:
        self._kept: set[tuple[str, str]] = set()
        self._new: list[Took] = []

    def took(self, step: str, how: str, seen: str | None = None) -> None:
        if (step, how) not in self._kept:
            self._kept.add((step, how))
            self._new.append((step, how, seen, utcnow()))

    def taken(self) -> list[Took]:
        """The steps since the last time."""
        new, self._new = self._new, []
        return new


class MeetPage(Steps):
    def __init__(self, page: Page) -> None:
        super().__init__()
        self.page = page
        self._pressed: set[str] = set()  # the shortcuts tried, once a call
        self.spoken = False  # whether it has said anything yet
        self.open_mic = False  # open until ``hush``
        self.until = float("-inf")  # when what it says has played (loop time)

    async def _shown(self, selector: str) -> bool:
        """On the page and visible: Meet keeps controls it is not showing."""
        return await self.page.locator(selector).first.is_visible()

    async def _click_if_visible(self, selector: str) -> bool:
        """Click it if it is there. The page can drop it between the look
        and the click (the call ends): then it was not there."""
        if not await self._shown(selector):
            return False
        try:
            await self.page.locator(selector).first.click(timeout=5000)
        except PlaywrightTimeoutError:
            return False
        return True

    async def _work(
        self, step: str, selector: str, shortcut: str = "", shows: str = ""
    ) -> bool:
        """``step``'s control clicked by its label, else Meet's ``shortcut``
        pressed (once a call) where it has one, worked if ``shows`` comes
        up; kept as how it went."""
        if await self._click_if_visible(selector):
            self.took(step, LABEL)
            return True
        if shortcut and step not in self._pressed:
            self._pressed.add(step)
            # Nothing focused: a key pressed in the chat's box is typed there.
            await self.page.evaluate("document.activeElement?.blur()")
            await self.page.keyboard.press(shortcut)
            try:
                await self.page.locator(shows).first.wait_for(timeout=SHORTCUT_WAIT_MS)
            except PlaywrightTimeoutError:
                pass
            else:
                self.took(step, SHORTCUT, await self._buttons())
                return True
        await self._missed(step)
        return False

    async def _missed(self, step: str) -> None:
        if (step, MISSED) not in self._kept:
            self.took(step, MISSED, await self._buttons())

    async def _buttons(self) -> str:
        return str(await self.page.evaluate(BUTTONS))[:BUTTONS_KEPT]

    async def _mic(self, click: str, already: str) -> bool:
        """The mic switched by clicking ``click``, or already as wanted
        (``already`` showing); never by its shortcut."""
        if await self._click_if_visible(click):
            self.took(MIC, LABEL)
            return True
        if await self._shown(already):
            self.took(MIC, ALREADY)
        else:
            await self._missed(MIC)
        return False

    async def ask_to_join(self, bot_name: str) -> None:
        """Once Meet has drawn its lobby: its camera and microphone taken
        (the card's), the microphone muted, named, and the join button
        clicked."""
        join = self.page.locator(JOIN_BUTTON).first
        try:
            await join.wait_for(timeout=LOBBY_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            await self._missed(JOIN)
            raise MeetPageError("No join button on the meeting page") from None
        if not await self._click_if_visible(USE_MEDIA):
            await self._click_if_visible(CONTINUE_WITHOUT_MEDIA)
        await self._mic(MIC_OFF, MIC_ON)
        if await self._shown(NAME_INPUT):
            await self.page.locator(NAME_INPUT).first.fill(bot_name)
        await join.click(timeout=5000)
        self.took(JOIN, LABEL)

    async def state(self) -> CallState:
        """Where the bot is, read in the page in one look: only the answer
        comes back, not the page's text (it grows with the call)."""
        texts = [[state.value, list(said)] for state, said in PAGE_TEXTS]
        found = await self.page.evaluate(
            STATE, [texts, LEAVE_BUTTON, CallState.IN_CALL, CallState.WAITING]
        )
        return CallState(found)

    async def page_text(self) -> str:
        """What the page says, cut to what a log line can carry."""
        return (await self.page.inner_text("body"))[:PAGE_TEXT_KEPT]

    async def people(self) -> int | None:
        """How many are in the call, the bot included; None when the page
        does not say."""
        # What is on the page now: a call that just ended has no button, and
        # waiting for one would hold the bot until a timeout.
        texts = await self.page.locator(PEOPLE_BUTTON).all_inner_texts()
        found = re.search(r"\d+", texts[0]) if texts else None
        return int(found.group()) if found else None

    async def _answer_prompts(self) -> None:
        """Answer whatever Meet has put over the call, before any in-call
        step: one look, nothing to do on most."""
        await self.page.evaluate(ANSWER_PROMPTS)

    async def say(self, text: str) -> None:
        """Post ``text`` in the meeting chat."""
        box = self.page.locator(CHAT_INPUT).first
        for _ in range(SAY_TRIES):
            await self._answer_prompts()
            if await self._shown(CHAT_INPUT):
                await box.fill(text)
                await box.press("Enter")
                return
            await self._work(CHAT, CHAT_BUTTON, CHAT_SHORTCUT, CHAT_INPUT)
            await asyncio.sleep(1)
        raise MeetPageError("The meeting chat never opened")

    async def show(self, **update: Any) -> None:
        """Redraw the card its camera shows (``card.show``)."""
        await card.show(self.page, **update)

    async def unmute(self) -> None:
        """The mic open, until ``hush``: a moment later the first time (Meet
        opens it late then)."""
        if self.open_mic:
            return
        await self._answer_prompts()
        if await self._mic(MIC_ON, MIC_OFF) and not self.spoken:
            await asyncio.sleep(FIRST_UNMUTE)
        self.spoken = self.open_mic = True

    async def speak(self, audio: bytes) -> None:
        """Say ``audio`` into the call, after what it is saying already
        (``until`` then when it has all played). The mic opens for it, if it
        is not open already, until ``hush``: Meet opens a mic late, and
        unmuted for each sentence, each lost its start."""
        await self.unmute()
        self._played(await card.speak(self.page, audio))

    async def stream(self, pcm: bytes, rate: int) -> None:
        """Say a piece of speech still being made (a live voice's, PCM16 at
        ``rate``), as ``speak`` does, back once no more than
        ``AHEAD_SECONDS`` is left to play."""
        await self.unmute()
        left = await card.stream(self.page, pcm, rate)
        self._played(left)
        await asyncio.sleep(max(0.0, left - AHEAD_SECONDS))

    async def silence(self) -> None:
        """What it is saying cut off: nothing still to play."""
        await card.silence(self.page)
        self._played(0.0)

    def _played(self, seconds: float) -> None:
        self.until = asyncio.get_running_loop().time() + seconds

    async def hush(self) -> None:
        """The mic closed, where it is open."""
        if self.open_mic:
            self.open_mic = False
            await self._mic(MIC_OFF, MIC_ON)

    async def leave(self) -> None:
        await self._answer_prompts()
        await self._work(LEAVE, LEAVE_BUTTON)

    async def turn_on_captions(self, wait_ms: int = 0) -> bool:
        """Captions on in the bot's own view (nobody else's), or already on
        (Meet keeps an account's on from its last call); False when Meet
        offers none yet, waited for up to ``wait_ms`` (Meet draws them a
        while after letting it in)."""
        await self._answer_prompts()
        if wait_ms:
            offered = self.page.locator(CAPTIONS_BUTTON).or_(
                self.page.locator(CAPTIONS_REGION)
            )
            with contextlib.suppress(PlaywrightTimeoutError):
                await offered.first.wait_for(timeout=wait_ms)
        if await self._shown(CAPTIONS_REGION):
            self.took(CAPTIONS, ALREADY)
            return True
        return await self._work(
            CAPTIONS, CAPTIONS_BUTTON, CAPTIONS_SHORTCUT, CAPTIONS_REGION
        )

    async def captions(self) -> list[Caption]:
        """The caption blocks on screen now, oldest first."""
        await self._answer_prompts()
        region = self.page.locator(CAPTIONS_REGION)
        if not await region.count():
            return []
        return [Caption(**c) for c in await region.first.evaluate(READ_CAPTIONS)]


@asynccontextmanager
async def open_meet(
    url: str,
    on_audio: Callable[[str], None] | None = None,
    login: str = LOGIN,
    start: card.Start | None = None,
) -> AsyncIterator[MeetPage]:
    """A Meet page at ``url`` in the browser container, signed in with the
    sign-in kept as ``login`` (an agent's), its audio handed to
    ``on_audio`` and its camera and microphone the card ``start`` begins
    as; the browser closes on exit, whatever happened, so no Chrome
    outlives its meeting."""
    async with connect(BROWSER_ARGS) as browser:
        context = await browser.new_context(
            storage_state=await stored_login(login),
            permissions=["camera", "microphone"],
        )
        page = await context.new_page()
        if on_audio is not None:
            await listen(page, on_audio)
        if start is not None:
            await page.add_init_script(card.script(start))
        await page.goto(url, wait_until="domcontentloaded")
        if start is not None and start.image:
            await card.show(page, image=start.image)
        yield MeetPage(page)
