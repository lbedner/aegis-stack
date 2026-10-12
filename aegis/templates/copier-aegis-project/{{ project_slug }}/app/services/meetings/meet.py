"""Google Meet's page, in one place: when Meet changes its UI, this module
is the fix.

The recipe is the MT-02 spike's: headless Chromium with fake media
devices, dismiss the "see and hear you?" dialog, give the bot's name, and
click whichever join button Meet shows. A signed-in Google account is
what gets the bot past Meet's guest check: ``open_meet`` joins with the
bot's stored sign-in (``login``), as a guest until there is one.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from enum import StrEnum
import re

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.components.browser.client import connect
from app.services.meetings.login import stored_login
from app.services.meetings.models import Caption

# A fake camera and microphone granted without a prompt: the bot joins with
# both off.
BROWSER_ARGS = [
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
]

CONTINUE_WITHOUT_MEDIA = 'button:has-text("Continue without microphone and camera")'
NAME_INPUT = 'input[type="text"]'
JOIN_BUTTON = (
    'button:has-text("Join now"), button:has-text("Ask to join"), '
    'button:has-text("Switch here")'
)
# Meet draws its lobby a while after the page loads.
LOBBY_TIMEOUT_MS = 30_000
LEAVE_BUTTON = 'button[aria-label*="Leave call"]'
# The participant count badge: named "People" by aria-labelledby, not a label.
PEOPLE_BUTTON = 'role=button[name="People"]'
CHAT_BUTTON = 'button[aria-label*="Chat with everyone"]'
CHAT_INPUT = 'textarea[aria-label*="Send a message"]'
CAPTIONS_BUTTON = 'button[aria-label^="Turn on captions"]'
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


class CallState(StrEnum):
    WAITING = "waiting"
    IN_CALL = "in_call"
    REFUSED = "refused"
    ENDED = "ended"


# What the page says, read before the Leave button: the waiting room shows
# that button too.
PAGE_TEXTS = (
    (CallState.REFUSED, ("denied your request", "can't join this video call")),
    (
        CallState.ENDED,
        ("You left the meeting", "removed from the meeting", "call has ended"),
    ),
    (CallState.WAITING, ("until a meeting host brings you in", "Asking to be let in")),
)


class MeetPageError(RuntimeError):
    """The page is not the one this module knows."""


class MeetPage:
    def __init__(self, page: Page) -> None:
        self.page = page

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

    async def ask_to_join(self, bot_name: str) -> None:
        """Once Meet has drawn its lobby: past the media dialog, named, and
        the join button clicked."""
        join = self.page.locator(JOIN_BUTTON).first
        try:
            await join.wait_for(timeout=LOBBY_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            raise MeetPageError("No join button on the meeting page") from None
        await self._click_if_visible(CONTINUE_WITHOUT_MEDIA)
        if await self._shown(NAME_INPUT):
            await self.page.locator(NAME_INPUT).first.fill(bot_name)
        await join.click(timeout=5000)

    async def state(self) -> CallState:
        body = await self.page.inner_text("body")
        for state, texts in PAGE_TEXTS:
            if any(text in body for text in texts):
                return state
        if await self._shown(LEAVE_BUTTON):
            return CallState.IN_CALL
        return CallState.WAITING

    async def people(self) -> int | None:
        """How many are in the call, the bot included; None when the page
        does not say."""
        # What is on the page now: a call that just ended has no button, and
        # waiting for one would hold the bot until a timeout.
        texts = await self.page.locator(PEOPLE_BUTTON).all_inner_texts()
        found = re.search(r"\d+", texts[0]) if texts else None
        return int(found.group()) if found else None

    async def say(self, text: str) -> None:
        """Post ``text`` in the meeting chat."""
        if not await self._shown(CHAT_INPUT):
            await self._click_if_visible(CHAT_BUTTON)
        box = self.page.locator(CHAT_INPUT).first
        await box.fill(text)
        await box.press("Enter")

    async def leave(self) -> None:
        await self._click_if_visible(LEAVE_BUTTON)

    async def turn_on_captions(self) -> bool:
        """Captions on in the bot's own view (nobody else's); False when
        Meet offers none."""
        return await self._click_if_visible(CAPTIONS_BUTTON)

    async def captions(self) -> list[Caption]:
        """The caption blocks on screen now, oldest first."""
        region = self.page.locator(CAPTIONS_REGION)
        if not await region.count():
            return []
        return [Caption(**c) for c in await region.first.evaluate(READ_CAPTIONS)]


@asynccontextmanager
async def open_meet(url: str) -> AsyncIterator[MeetPage]:
    """A Meet page at ``url`` in the browser container; the browser closes
    on exit, whatever happened, so no Chrome outlives its meeting."""
    async with connect(BROWSER_ARGS) as browser:
        context = await browser.new_context(storage_state=await stored_login())
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        yield MeetPage(page)
