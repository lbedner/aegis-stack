"""The Meet page module (``meet.MeetPage``) against a fake Meet page: the
lobby, the waiting room, the call, chat, being turned away and the call
ending. It runs in the browser container, so it is skipped where none is
up. The fake is shaped like the real Meet page as last checked (October
2026); when Meet changes, ``meet.py`` and this page change together."""

from collections.abc import AsyncIterator

from playwright.async_api import Page
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.domains.bot import card
from app.services.meetings.domains.bot import run as bot
from app.services.meetings.domains.bot.meet import CallState, MeetPage, merge_caption
from app.services.meetings.models import MeetingStatus
from app.services.meetings.service import MeetingsService
from tests._browser import live_browser
from tests._meetings import MEET, SAID, SHOWN, bot_on

# The bot beats on every look in the full run, by design.
pytestmark = pytest.mark.queryspy(allow_n_plus_one=True)

# ``window.said`` is what the bot last sent in chat; the host is played by
# ``admit()``, ``deny()`` and ``end()``, and whoever talks by ``caption()``
# (a new block) and ``more()`` (the last block grows).
FAKE_MEET = """
<html><body>
<div id="media">
  <button onclick="window.media = 'on'; media.remove()">Use microphone and camera</button>
  <button onclick="window.media = 'off'; media.remove()">
    Continue without microphone and camera</button>
</div>
<button id="mic" aria-label="Turn off microphone (ctrl + d)" onclick="toggleMic()">mic</button>
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
  function toggleMic() {
    const on = mic.getAttribute('aria-label').startsWith('Turn off');
    mic.setAttribute('aria-label', (on ? 'Turn on' : 'Turn off') + ' microphone (ctrl + d)');
  }
  function deny() { note.textContent = 'Someone in the call denied your request to join'; }
  function end(text) { call.remove(); note.textContent = text; }
  // What Meet puts over the call once someone is in: that a notetaker is
  // on (answered "Join now"), then a tip about the camera ("Got it"), each
  // covering everything under it.
  function prompts() {
    for (const answer of ['Join now', 'Got it']) {
      const prompt = document.createElement('div');
      prompt.setAttribute('role', 'dialog');
      prompt.className = 'prompt';
      prompt.style = 'position: fixed; inset: 0; background: #000; z-index: 9';
      prompt.innerHTML = '<button>Leave</button><button>' + answer + '</button>';
      prompt.lastElementChild.onclick = () => prompt.remove();
      document.body.appendChild(prompt);
    }
  }
</script>
</body></html>
"""


def test_a_block_meet_trimmed_keeps_the_start_already_heard() -> None:
    assert merge_caption(SAID, SHOWN) == SAID + " Let me just"


def test_a_block_that_grows_or_is_corrected_is_what_meet_shows() -> None:
    assert merge_caption("Hello", "Hello there.") == "Hello there."
    assert merge_caption("Okay testing one", "Okay, testing one two.") == (
        "Okay, testing one two."
    )
    assert merge_caption("", "Hi.") == "Hi."


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


async def test_it_joins_with_its_camera_and_mic_and_the_mic_off(
    meet: MeetPage,
) -> None:
    """The card's script answers for both (``card``); muted until it
    speaks."""
    await meet.ask_to_join("Notes")

    assert await meet.page.evaluate("window.media") == "on"
    assert await meet.page.get_attribute("#mic", "aria-label") == (
        "Turn on microphone (ctrl + d)"
    )


async def test_it_unmutes_only_while_it_speaks(
    meet: MeetPage, monkeypatch: pytest.MonkeyPatch
) -> None:
    await meet.ask_to_join("Notes")
    await meet.page.evaluate("admit()")
    heard: list[str | None] = []

    async def speak(page: Page, audio: bytes) -> float:
        heard.append(await page.get_attribute("#mic", "aria-label"))
        return 0.0

    monkeypatch.setattr(card, "speak", speak)
    await meet.speak(b"audio")

    assert heard == ["Turn off microphone (ctrl + d)"]
    assert await meet.page.get_attribute("#mic", "aria-label") == (
        "Turn on microphone (ctrl + d)"
    )


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


async def test_meets_prompts_over_the_call_are_answered_before_it_talks(
    meet: MeetPage,
) -> None:
    """A notetaker's notice and a camera tip cover the chat and the
    captions button: answered, both still work."""
    await meet.ask_to_join("Notes")
    await meet.page.evaluate("admit(); prompts()")

    await meet.say("Notes is taking notes.")
    assert await meet.page.evaluate("window.said") == "Notes is taking notes."

    await meet.page.evaluate("prompts()")
    assert await meet.turn_on_captions()
    assert await meet.page.locator(".prompt").count() == 0


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


async def test_a_prompt_over_the_call_does_not_keep_it_in(meet: MeetPage) -> None:
    await meet.ask_to_join("Notes")
    await meet.page.evaluate("admit(); prompts()")

    await meet.leave()

    assert await meet.state() == CallState.ENDED


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
    # The host lets the bot in; once it has spoken, Ada does, and the call
    # ends once the bot has read her (it marks what it read ``data-line``):
    # a fixed delay lost the race on a busy machine.
    await meet.page.add_script_tag(
        content="lobby.querySelector('button').addEventListener("
        "'click', () => setTimeout(admit, 100));"
        "const ended = () => document.querySelector('[data-line]')"
        " ? setTimeout(() => end('The call has ended'), 100)"
        " : setTimeout(ended, 50);"
        "chat.addEventListener('keydown', (e) => { if (e.key === 'Enter') {"
        " caption('Ada', 'Hello there.'); ended(); } });"
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
