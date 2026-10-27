"""The agent's card in a call (``card``): what its camera shows and the
voice its microphone carries. The page half runs in the browser
container, so those tests skip where none is up."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import io
from itertools import count
import math
import struct
from typing import Any
import wave

from playwright.async_api import Page
import pytest

from app.services.meetings.domains.bot import card
from app.services.meetings.domains.bot.meet import BROWSER_ARGS
from app.services.meetings.models import ASKED, CLAIMED, DONE, FAILED, IN_THE_APP, Going
from tests._browser import live_browser

_ids = count(1)


def _going(status: str, runner: str | None = None, **asked: str | None) -> Going:
    """A run not yet done, as the card reads it."""
    who = {"action": "agent", "speaker": "Dana", "text": "Can it ship?"} | asked
    run = next(_ids)
    return Going(id=run, moment=run, status=status, runner=runner, **who)


def test_the_status_says_what_the_bot_is_doing() -> None:
    asked, claimed = _going(ASKED), _going(CLAIMED, "laptop")

    assert card.status_of(captions=True, going=[]) == card.LISTENING
    assert card.status_of(captions=False, going=[]) == card.NO_CAPTIONS
    assert card.status_of(captions=True, going=[asked]) == card.QUESTION_HEARD
    assert card.status_of(captions=False, going=[asked, claimed]) == card.ANSWERING


def _card() -> tuple[Any, card.Card]:
    from tests._meetings import FakeCall

    call = FakeCall([])
    return call, card.Card(call, captions=True, name="Notes")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("said", "question"),
    [
        ("Uh, hey, Notes, how many workers are there?", "How many workers are there?"),
        (
            "Notes, are there any errors in the last hour?",
            "Are there any errors in the last hour?",
        ),
        ("Is the build green, Notes?", "Is the build green?"),
        ("Yeah, go ahead.", "Go ahead."),  # said back: its fillers off
        ("Can the CSV export ship?", "Can the CSV export ship?"),
        # Captions mark a pause on a filler mid-question, and end it on a ".".
        (
            "Are there any, uh? Errors in the last hour.",
            "Are there any errors in the last hour?",
        ),
        ("Notes, how many, um, workers are up?", "How many workers are up?"),
        # Asks nothing: no question mark.
        ("Tell me about the scheduler.", "Tell me about the scheduler."),
    ],
)
def test_a_question_shows_as_put_without_her_name_or_fillers(
    said: str, question: str
) -> None:
    """The card shows what was asked, not how it was said to her or how
    captions marked its pauses: no name, no fillers, a question mark on a
    question. Done on the text, at once: no model is asked."""
    from app.services.meetings.domains.moments.detectors import put_to

    assert put_to(said, "Notes") == question


@pytest.mark.parametrize(
    ("answer", "verdict", "detail"),
    [
        (
            "Let me check the current worker status so I can answer accurately. "
            "Yes, the workers are up and running. They're in a warning state. More.",
            "Yes, the workers are up and running.",
            "They're in a warning state.",
        ),
        ("Sure, I'll keep it tight. One worker, running.", "One worker, running.", ""),
        ("Let me look that up.", "Let me look that up.", ""),  # nothing else said
        ("", "", ""),
    ],
)
def test_her_answer_in_brief_is_its_first_real_sentence_and_the_next(
    answer: str, verdict: str, detail: str
) -> None:
    """What she says before an answer ("Let me check...", "Sure, ...") is not
    it: the card shows the first sentence that is, and one more."""
    assert card.brief(answer) == (verdict, detail)


async def test_the_card_is_about_one_request_and_the_rest_are_pills() -> None:
    """One request is the card's (the one she is saying, else answering,
    else hearing, else waiting); the others in flight are up next, and her
    last answers are earlier, each a pill."""
    call, shown = _card()
    hers = _going(CLAIMED, IN_THE_APP, text="Notes, is Redis up?")
    queued = _going(ASKED, text="Notes, how many workers are there?")
    done = _going(DONE, IN_THE_APP, text="Notes, any errors?", result="Yes, 60.")
    failed = _going(FAILED, IN_THE_APP, text="Notes, how does it work?", result="x")

    small_talk = _going(DONE, IN_THE_APP, text="Notes, can you hear me?", result="Yes.")
    for looked in (done, failed):  # each looked something up
        shown.heard("Reading the logs", looked.moment)
    shown.heard("Checking what is wrong now", hers.moment)
    shown.heard("Reading the logs", hers.moment)
    await shown.update([hers, queued], set(), [small_talk, done, failed])

    assert call.cards[-1] == {
        "status": card.ANSWERING,
        "focus": {
            "question": "Is Redis up?",
            "status": "answering",
            "step": "Reading the logs",
            "steps": 2,
            "verdict": None,
            "detail": None,
            "voice": None,
        },
        # Earlier: what she looked something up for; a mic check is not.
        "pills": [
            {"question": "How many workers are there?", "mark": card.NEXT},
            {"question": "Any errors?", "mark": card.ANSWERED},
            {"question": "How does it work?", "mark": card.FAILED_PILL},
        ],
    }


async def test_her_answer_is_the_card_while_she_says_it_then_she_is_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Her answer is done before she has said it: the card shows it in brief,
    her steps gone, until it has played; then the card is the agent's."""
    monkeypatch.setattr(card, "LINGER_SECONDS", 0.0)
    call, shown = _card()
    hers = _going(CLAIMED, IN_THE_APP, text="Notes, is Redis up?")
    said = hers.model_copy(
        update={"status": DONE, "result": "Let me look. Redis is up. No restarts."}
    )
    shown.heard("Checking what is wrong now", hers.moment)
    await shown.update([hers], set(), [])

    await shown.update([], {hers.moment}, [said])
    saying = call.cards[-1]["focus"]
    await shown.update([], set(), [said])

    assert saying["status"] == card.SAYING and saying["step"] is None
    assert (saying["verdict"], saying["detail"]) == ("Redis is up.", "No restarts.")
    assert call.cards[-1] == {"status": card.LISTENING, "focus": None, "pills": []}
    assert shown.steps == {}


async def test_her_answer_stays_up_a_while_even_once_said() -> None:
    """Live, she says most of her answer as she makes it: by the time it is
    back it may have played already. Its brief stays up a while all the
    same (``LINGER_SECONDS``), until something else is asked."""
    call, shown = _card()
    hers = _going(CLAIMED, IN_THE_APP, text="Notes, any errors?")
    done = hers.model_copy(update={"status": DONE, "result": "Yes, 60. All one job."})
    shown.heard("Looking through the errors", hers.moment)
    await shown.update([hers], set(), [])

    await shown.update([], set(), [done])  # back, and already played
    lingering = call.cards[-1]["focus"]
    await shown.update([], set(), [done], hearing=[("Dana", "Hey Notes, and")])
    asked = call.cards[-1]

    assert lingering["verdict"] == "Yes, 60." and lingering["status"] == card.SAYING
    assert asked["focus"]["status"] == card.HEARING
    assert asked["pills"] == [{"question": "Any errors?", "mark": card.ANSWERED}]


async def test_what_she_says_while_she_works_shows_under_the_question() -> None:
    """Live, she says what she is doing before her answer is back ("Let me
    check the recent system logs"): her own words, as Meet captions them,
    show under the question until her answer replaces them. Words of hers
    from before it was asked do not."""
    import asyncio

    call, shown = _card()
    now = asyncio.get_running_loop().time
    hers = _going(CLAIMED, IN_THE_APP, text="Notes, any errors?")
    earlier = (now() - 60, "Redis looks healthy.")

    await shown.update([hers], set(), [], her=earlier)
    before = call.cards[-1]["focus"]["voice"]
    said = "Redis looks healthy. Let me check the recent system logs so I can answer."
    await shown.update([hers], set(), [], her=(now() + 1, said))

    assert before is None
    assert call.cards[-1]["focus"]["voice"] == (
        "Let me check the recent system logs so I can answer."
    )


async def test_a_line_for_her_is_the_card_as_it_is_heard() -> None:
    """A line put to her is the card's while it is still being said, before
    it is a request."""
    call, shown = _card()

    await shown.update([], set(), [], hearing=[("Dana", "Hey Notes, who owns")])

    assert call.cards[-1]["status"] == card.QUESTION_HEARD
    assert call.cards[-1]["focus"]["question"] == "Who owns"
    assert call.cards[-1]["focus"]["status"] == card.HEARING


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


async def test_answering_it_presents_one_request_and_keeps_the_corner_clear(
    page: Page,
) -> None:
    """Answering, the card is the request: a long question is cut to fit,
    never drawn past the card, and the bottom right (where Meet lays the
    host's own picture) is left empty. With nothing, the card it was."""
    idle = await page.evaluate("() => window.__meetingCard.picture()")
    focus = card.Focus(
        question="Why " * 60,
        status=card.SAYING,
        verdict="Yes, " * 40,
        detail="Because " * 40,
    )
    pills = [
        card.Pill(question="How does a request hit the database?", mark=card.ANSWERED)
    ] * 6

    await card.show(
        page,
        status=card.ANSWERING,
        focus=focus.model_dump(),
        pills=[p.model_dump() for p in pills],
    )
    shown = await page.evaluate("() => window.__meetingCard.picture()")
    widest = await page.evaluate("() => window.__meetingCard.widest()")
    corner = await page.evaluate("() => window.__meetingCard.cornerClear()")
    await card.show(page, status=card.LISTENING, focus=None, pills=[])
    back = await page.evaluate("() => window.__meetingCard.picture()")

    assert shown != idle and widest <= 640
    assert corner
    assert back == idle


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
