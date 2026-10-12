"""The Meet page module (``meet.MeetPage``) against a fake Meet page: the
lobby, the waiting room, the call, chat, being turned away and the call
ending. It runs in the browser container, so it is skipped where none is
up. The fake is shaped like the real Meet page as last checked (October
2026); when Meet changes, ``meet.py`` and this page change together."""

from collections.abc import AsyncIterator

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings import bot
from app.services.meetings.meet import CallState, MeetPage
from app.services.meetings.models import MeetingStatus
from app.services.meetings.service import MeetingsService
from tests._browser import live_browser
from tests._meetings import MEET, bot_on

# The bot beats on every look in the full run, by design.
pytestmark = pytest.mark.queryspy(allow_n_plus_one=True)

# ``window.said`` is what the bot last sent in chat; the host is played by
# ``admit()``, ``deny()`` and ``end()``, and whoever talks by ``caption()``
# (a new block) and ``more()`` (the last block grows).
FAKE_MEET = """
<html><body>
<div><button onclick="this.parentNode.remove()">
  Continue without microphone and camera</button></div>
<div id="lobby">
  <input type="text" aria-label="Your name">
  <button onclick="lobby.hidden = true; note.textContent = 'Asking to be let in...'">
    Ask to join</button>
</div>
<div id="note"></div>
<div id="call" hidden>
  <span id="people-label" hidden>People</span>
  <div role="button" aria-labelledby="people-label"><div>3</div></div>
  <button aria-label="Chat with everyone" onclick="chat.hidden = false">Chat</button>
  <button aria-label="Leave call" onclick="end('You left the meeting')">Leave</button>
  <button aria-label="Turn on captions (c)" onclick="captions.hidden = false">cc</button>
  <textarea id="chat" hidden aria-label="Send a message"
    onkeydown="if (event.key === 'Enter') { window.said = this.value; this.value = ''; }">
  </textarea>
</div>
<div id="captions" role="region" aria-label="Captions" hidden>
  <div><button aria-label="Jump to most recent captions">Jump to bottom</button></div>
</div>
<script>
  function caption(name, text) {
    const block = document.createElement('div');
    block.innerHTML = '<span>' + name + '</span><div>' + text + '</div>';
    captions.insertBefore(block, captions.lastElementChild);
  }
  function more(text) {
    const blocks = captions.children;
    blocks[blocks.length - 2].lastElementChild.textContent += ' ' + text;
  }
  function admit() { note.textContent = ''; call.hidden = false; }
  function deny() { note.textContent = 'Someone in the call denied your request to join'; }
  function end(text) { call.remove(); note.textContent = text; }
</script>
</body></html>
"""


@pytest.fixture
async def meet() -> AsyncIterator[MeetPage]:
    async with live_browser() as browser:
        page = await browser.new_page()
        await page.set_content(FAKE_MEET)
        yield MeetPage(page)


async def test_it_asks_to_join_by_name_and_waits(meet: MeetPage) -> None:
    await meet.ask_to_join("Notes")

    assert await meet.state() == CallState.WAITING
    assert await meet.page.input_value("[aria-label='Your name']") == "Notes"


async def test_it_waits_for_meet_to_draw_its_lobby(meet: MeetPage) -> None:
    """Meet draws the lobby a while after the page loads."""
    await meet.page.evaluate(
        "lobby.hidden = true; setTimeout(() => { lobby.hidden = false; }, 500)"
    )

    await meet.ask_to_join("Notes")

    assert await meet.state() == CallState.WAITING


async def test_the_waiting_room_is_not_the_call(meet: MeetPage) -> None:
    """Meet's waiting room has a Leave button too."""
    await meet.ask_to_join("Notes")
    await meet.page.evaluate(
        "call.hidden = false;"
        "note.textContent = 'Please wait until a meeting host brings you into the call'"
    )

    assert await meet.state() == CallState.WAITING


async def test_once_admitted_it_counts_people_and_talks_in_chat(
    meet: MeetPage,
) -> None:
    await meet.ask_to_join("Notes")
    await meet.page.evaluate("admit()")

    await meet.say("Notes is taking notes.")

    assert await meet.state() == CallState.IN_CALL
    assert await meet.people() == 3
    assert await meet.page.evaluate("window.said") == "Notes is taking notes."


async def test_captions_read_as_lines_that_grow(meet: MeetPage) -> None:
    """Meet writes a speaker's block as they talk: it stays one line."""
    await meet.ask_to_join("Notes")
    await meet.page.evaluate("admit()")
    await meet.turn_on_captions()
    await meet.page.evaluate("caption('Leonard', 'Okay.')")
    first = await meet.captions()

    await meet.page.evaluate("more('Testing.'); caption('Ada', 'Hello.')")
    after = await meet.captions()

    assert [(c.speaker, c.text) for c in first] == [("Leonard", "Okay.")]
    assert [(c.speaker, c.text) for c in after] == [
        ("Leonard", "Okay. Testing."),
        ("Ada", "Hello."),
    ]
    assert after[0].line == first[0].line != after[1].line


async def test_a_denied_request_reads_as_refused(meet: MeetPage) -> None:
    await meet.ask_to_join("Notes")
    await meet.page.evaluate("deny()")

    assert await meet.state() == CallState.REFUSED


async def test_leaving_ends_the_call(meet: MeetPage) -> None:
    await meet.ask_to_join("Notes")
    await meet.page.evaluate("admit()")

    await meet.leave()

    assert await meet.state() == CallState.ENDED


async def test_the_bot_runs_a_whole_meeting_on_the_page(
    meet: MeetPage, async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The host admits it, it announces itself, someone speaks, the call
    ends: the row ends left, the announcement went to the chat, and what was
    said is in the transcript."""
    bot_on(monkeypatch, async_db_session, meet, poll_seconds=0.05)
    # The host lets the bot in; once it has spoken, Ada does, and the call ends.
    await meet.page.add_script_tag(
        content="lobby.querySelector('button').addEventListener("
        "'click', () => setTimeout(admit, 100));"
        "chat.addEventListener('keydown', (e) => { if (e.key === 'Enter') {"
        " caption('Ada', 'Hello there.');"
        " setTimeout(() => end('The call has ended'), 300); } });"
    )
    meeting = await MeetingsService(async_db_session, None).request(MEET, "Notes")

    await bot.run_meeting(meeting.id)  # type: ignore[arg-type]

    await async_db_session.refresh(meeting)
    assert meeting.status == MeetingStatus.LEFT, meeting.failure_reason
    assert meeting.joined_at and meeting.left_at
    assert (await meet.page.evaluate("window.said")).startswith("Notes is taking")
    lines = await MeetingsService(async_db_session, None).transcript(meeting)
    assert [(speaker, line.text) for speaker, line in lines] == [
        ("Ada", "Hello there.")
    ]
