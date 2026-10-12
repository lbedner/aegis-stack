"""Google Meet's page, in one place: when Meet changes its UI, this module
is the fix.

The recipe is the MT-02 spike's: headless Chromium with fake media
devices, dismiss the "see and hear you?" dialog, give the bot's name, and
click whichever join button Meet shows. A signed-in Google account is
what gets the bot past Meet's guest check; until the bot's login is
stored, ``open_meet`` joins as a guest.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from enum import StrEnum
import re

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.components.browser.client import connect

# A fake camera and microphone granted without a prompt: the bot joins with
# both off.
BROWSER_ARGS = [
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
]

CONTINUE_WITHOUT_MEDIA = 'button:has-text("Continue without microphone and camera")'
NAME_INPUT = 'input[type="text"]'
JOIN_BUTTONS = (
    'button:has-text("Join now")',
    'button:has-text("Ask to join")',
    'button:has-text("Switch here")',
)
LEAVE_BUTTON = 'button[aria-label*="Leave call"]'
PEOPLE_BUTTON = 'button[aria-label^="People"]'
CHAT_BUTTON = 'button[aria-label*="Chat with everyone"]'
CHAT_INPUT = 'textarea[aria-label*="Send a message"]'
REFUSED_TEXTS = ("denied your request", "can't join this video call")
ENDED_TEXTS = ("You left the meeting", "removed from the meeting", "call has ended")


class CallState(StrEnum):
    WAITING = "waiting"
    IN_CALL = "in_call"
    REFUSED = "refused"
    ENDED = "ended"


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
        """Past the media dialog, named, and the join button clicked."""
        await self._click_if_visible(CONTINUE_WITHOUT_MEDIA)
        if await self._shown(NAME_INPUT):
            await self.page.locator(NAME_INPUT).first.fill(bot_name)
        for button in JOIN_BUTTONS:
            if await self._click_if_visible(button):
                return
        raise MeetPageError("No join button on the meeting page")

    async def state(self) -> CallState:
        if await self._shown(LEAVE_BUTTON):
            return CallState.IN_CALL
        body = await self.page.inner_text("body")
        if any(text in body for text in REFUSED_TEXTS):
            return CallState.REFUSED
        if any(text in body for text in ENDED_TEXTS):
            return CallState.ENDED
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


@asynccontextmanager
async def open_meet(url: str) -> AsyncIterator[MeetPage]:
    """A Meet page at ``url`` in the browser container; the browser closes
    on exit, whatever happened, so no Chrome outlives its meeting."""
    async with connect(BROWSER_ARGS) as browser:
        page = await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        yield MeetPage(page)
