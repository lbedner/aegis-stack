"""The agent's card in a call (``card``): what its camera shows and the
voice its microphone carries. The page half runs in the browser
container, so those tests skip where none is up."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import io
import math
import struct
import wave

from playwright.async_api import Page
import pytest

from app.services.meetings.domains.bot import card
from app.services.meetings.domains.bot.meet import BROWSER_ARGS
from app.services.meetings.models import ASKED, CLAIMED
from tests._browser import live_browser


def test_the_status_says_what_the_bot_is_doing() -> None:
    assert card.status_of(captions=True, going=set()) == card.LISTENING
    assert card.status_of(captions=False, going=set()) == card.NO_CAPTIONS
    assert card.status_of(captions=True, going={ASKED}) == card.QUESTION_HEARD
    assert card.status_of(captions=False, going={ASKED, CLAIMED}) == card.ANSWERING


def test_the_picture_is_not_carried_in_the_page_script() -> None:
    """The script runs in every page Meet opens: a picture in it (megabytes
    as a data URL) kept Meet from loading. It is handed over after."""
    start = card.Start(name="A", image="data:image/png;base64," + "A" * 1000)

    assert "data:image" not in card.script(start)


def test_no_image_shows_initials() -> None:
    assert card.initials("Illiana Notes") == "IN"
    assert card.initials("notetaker") == "N"
    assert card.initials("  ") == "?"


# A page at an https address, as Meet's is: the camera and microphone are
# only offered to a secure page.
PAGE = "https://meet.test/"


@asynccontextmanager
async def _card_page(start: card.Start) -> AsyncIterator[Page]:
    async with live_browser(BROWSER_ARGS) as browser:
        page = await browser.new_page()
        await page.route(PAGE, lambda route: route.fulfill(body="<html></html>"))
        await page.add_init_script(card.script(start))
        await page.goto(PAGE)
        yield page


@pytest.fixture
async def page() -> AsyncIterator[Page]:
    """A page with the card's script, as the bot's: an agent, camera on."""
    async with _card_page(card.Start(name="Illiana")) as page:
        yield page


async def _tracks(page: Page, constraints: str) -> list[str]:
    return await page.evaluate(
        f"""async () => {{
          const stream = await navigator.mediaDevices.getUserMedia({constraints});
          return stream.getTracks().map((t) => t.kind);
        }}"""
    )


async def test_the_camera_is_the_card_and_the_mic_its_voice(page: Page) -> None:
    assert await _tracks(page, "{video: true}") == ["video"]
    assert await _tracks(page, "{audio: true}") == ["audio"]
    assert sorted(await _tracks(page, "{audio: true, video: true}")) == [
        "audio",
        "video",
    ]


async def _devices(page: Page) -> list[str]:
    return await page.evaluate(
        """async () => (await navigator.mediaDevices.enumerateDevices())
          .map((d) => d.kind).sort()"""
    )


async def test_meet_finds_the_card_and_the_voice_as_its_devices(page: Page) -> None:
    """The browser has none of its own: Meet would say "Camera not found"
    and never ask for one."""
    assert await _devices(page) == ["audioinput", "audiooutput", "videoinput"]


async def test_with_its_camera_off_no_picture_is_given() -> None:
    async with _card_page(card.Start(name="A", camera=False)) as page:
        assert await _tracks(page, "{audio: true, video: true}") == ["audio"]
        refused = await page.evaluate(
            """() => navigator.mediaDevices.getUserMedia({video: true})
              .then(() => '', (e) => e.name)"""
        )
        assert refused == "NotAllowedError"
        assert "videoinput" not in await _devices(page)


async def test_the_card_redraws_when_its_status_changes(page: Page) -> None:
    before = await page.evaluate("() => window.__meetingCard.picture()")
    await card.show(page, status=card.ANSWERING)
    after = await page.evaluate("() => window.__meetingCard.picture()")
    assert before != after


def _pcm(seconds: float, rate: int = 16_000) -> bytes:
    """A tone as PCM16 mono: what a live voice sends, a piece at a time."""
    samples = (
        int(8000 * math.sin(2 * math.pi * 440 * n / rate))
        for n in range(int(rate * seconds))
    )
    return b"".join(struct.pack("<h", s) for s in samples)


def _tone(seconds: float) -> bytes:
    """A short WAV tone: what the page decodes as it would TTS's audio."""
    rate = 16_000
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(_pcm(seconds, rate))
    return out.getvalue()


async def test_speech_plays_into_the_mic_and_says_how_long(page: Page) -> None:
    seconds = await card.speak(page, _tone(0.5))

    assert seconds == pytest.approx(0.5, abs=0.05)


async def test_speech_still_being_made_plays_piece_after_piece(page: Page) -> None:
    """A live voice sends its speech in pieces as it is made: each plays
    after the one before, and the page says how much is still to play."""
    first = await card.stream(page, _pcm(0.25, 24_000), 24_000)
    second = await card.stream(page, _pcm(0.25, 24_000), 24_000)

    assert first == pytest.approx(0.25, abs=0.05)
    assert second == pytest.approx(0.5, abs=0.08)
