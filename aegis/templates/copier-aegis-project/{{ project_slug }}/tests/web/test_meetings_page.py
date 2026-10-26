"""The Meetings page (``/meetings``): send the bot to a call, follow it
while it joins, and read what came out of it: the summary, my action
items first, then everyone's, then the transcript, each item jumping to
the line it came from. Through ``authenticated_client``, so it runs with
and without the auth service."""

from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.web_frontend.rendering import TZ_COOKIE
from app.components.web_frontend.routes.meetings import send_and_open
from app.services.meetings import service as meetings_service
from app.services.meetings.domains.calendar.service import read_calendars
from app.services.meetings.models import ActionItem, NoteItem, Notes
from app.services.meetings.service import MeetingsService
from tests._meetings import (
    MEET,
    STANDUP,
    Calendar,
    at,
    ended,
    hold_the_bot,
    hold_the_writer,
)
from tests.web.dom import location, none, one, select, text
from tests.web.overseer import page_html

HX = {"HX-Request": "true"}


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The meetings the bot was started on, without starting it."""
    return hold_the_bot(monkeypatch)


@pytest.fixture
def finished(
    async_db_session: AsyncSession, acting_owner_user_id: int | None
) -> Callable[..., Awaitable[tuple[int, list[int]]]]:
    """A meeting the bot has left: Leonard asked, Ada promised, and the
    notes say so. Returns its id and its transcript's line ids."""

    async def make(me: str | None = "Leonard") -> tuple[int, list[int]]:
        meeting_id, lines = await ended(
            async_db_session,
            acting_owner_user_id,
            ("Leonard", "I'll book the room."),
            ("Ada", "And I write the docs."),
            notes=lambda lines: Notes(
                summary="Room and docs.",
                decisions=[NoteItem(text="Meet on Monday", lines=[lines[0]])],
                action_items=[
                    ActionItem(text="Book the room", owner="Leonard", lines=[lines[0]]),
                    ActionItem(text="Write the docs", owner="Ada", lines=[lines[1]]),
                ],
            ),
        )
        if me:
            svc = MeetingsService(async_db_session, acting_owner_user_id)
            await svc.set_me(meeting_id, me)
        return meeting_id, lines

    return make


def _ok(response: Any) -> str:
    """A write's answer, which must be 200."""
    assert response.status_code == 200, response.text
    return response.text


async def test_the_list_shows_each_meeting_and_how_many_items_are_mine(
    authenticated_client: TestClient, finished: Callable[..., Any]
) -> None:
    meeting_id, _ = await finished()

    html = page_html(authenticated_client, "/meetings")

    row = one(html, f"#meeting-{meeting_id}")
    assert "Left" in text(row)
    assert text(one(row, "[data-mine]")) == "1"
    assert one(row, "a").get("href") == f"/meetings/{meeting_id}"


def test_sending_the_bot_starts_it_and_opens_its_page(
    authenticated_client: TestClient, started: list[int]
) -> None:
    response = authenticated_client.post(
        "/meetings", data={"url": MEET, "bot_name": "Notes"}, headers=HX
    )

    assert response.status_code == 200, response.text
    assert len(started) == 1
    assert location(response) == f"/meetings/{started[0]}"


def test_a_link_it_cannot_join_is_said_and_nothing_starts(
    authenticated_client: TestClient, started: list[int]
) -> None:
    response = authenticated_client.post(
        "/meetings", data={"url": "https://example.com/x", "bot_name": "Notes"}
    )

    assert response.status_code == 422
    assert "Not a meeting link the bot can join" in response.text
    assert not started


@pytest.mark.parametrize(
    ("url", "agent"), [("https://example.com/x", ""), (MEET, "nobody")]
)
async def test_the_form_again_reads_the_agents_once(
    async_db_session: AsyncSession, started: list[int], url: str, agent: str
) -> None:
    """A link it cannot join, or an agent there is not: the form comes
    back with the agents the send already read, not read again."""
    reads: list[str] = []

    def count(*args: Any) -> None:
        if "FROM meeting_bot_account" in args[2]:
            reads.append(args[2])

    engine = async_db_session.bind.engine.sync_engine  # type: ignore[union-attr]
    event.listen(engine, "before_cursor_execute", count)
    try:
        response = await send_and_open(
            MeetingsService(async_db_session, None),
            url,
            "",
            "/meetings",
            lambda meeting_id: f"/meetings/{meeting_id}",
            agent or None,
        )
    finally:
        event.remove(engine, "before_cursor_execute", count)

    assert response.status_code == 422
    assert len(reads) == 1


async def test_my_items_come_first_and_each_jumps_to_its_line(
    authenticated_client: TestClient, finished: Callable[..., Any]
) -> None:
    meeting_id, lines = await finished()

    html = page_html(authenticated_client, f"/meetings/{meeting_id}")

    assert text(one(html, "#meeting-summary")) == "Room and docs."
    mine = one(html, "#my-items")
    assert "Book the room" in text(mine) and "Write the docs" not in text(mine)
    assert one(mine, "a").get("href") == f"#line-{lines[0]}"
    everyone = text(one(html, "#all-items"))
    assert "Book the room" in everyone and "Write the docs" in everyone
    assert "Meet on Monday" in text(one(html, "#decisions"))
    assert "And I write the docs." in text(one(html, f"#line-{lines[1]}"))


async def test_picking_who_i_am_changes_my_items(
    authenticated_client: TestClient, finished: Callable[..., Any]
) -> None:
    meeting_id, _ = await finished(me=None)

    html = _ok(
        authenticated_client.post(
            f"/meetings/{meeting_id}/me", data={"name": "Ada"}, headers=HX
        )
    )

    assert "Write the docs" in text(one(html, "#my-items"))
    assert "Book the room" not in text(one(html, "#my-items"))


async def test_a_meeting_under_way_keeps_updating_and_a_done_one_stops(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
    finished: Callable[..., Any],
) -> None:
    live = await MeetingsService(async_db_session, acting_owner_user_id).request(MEET)
    done, _ = await finished()

    body = page_html(authenticated_client, f"/meetings/{live.id}/body")
    assert "every" in one(body, "#meeting-body").get("hx-trigger")
    assert one(body, "[data-leave]") is not None

    body = page_html(authenticated_client, f"/meetings/{done}/body")
    assert one(body, "#meeting-body").get("hx-trigger") is None
    none(body, "[data-leave]")


async def test_asking_it_to_leave_from_the_page(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    meeting = await MeetingsService(async_db_session, acting_owner_user_id).request(
        MEET
    )

    body = _ok(authenticated_client.post(f"/meetings/{meeting.id}/leave", headers=HX))

    # Not started yet, so there is no call to leave: it is over at once.
    assert "Left" in text(one(body, "[data-status]"))


async def test_the_notes_can_be_written_again(
    authenticated_client: TestClient,
    finished: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meeting_id, _ = await finished()
    asked, runs = hold_the_writer(monkeypatch)

    body = _ok(authenticated_client.post(f"/meetings/{meeting_id}/notes", headers=HX))

    assert "Writing the notes" in text(one(body, "#meeting-notes"))
    assert "every" in one(body, "#meeting-body").get("hx-trigger")
    await runs[0]
    assert asked == [meeting_id]


async def test_notes_being_written_are_not_started_again(
    authenticated_client: TestClient,
    finished: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meeting_id, _ = await finished()
    started, _ = hold_the_writer(monkeypatch)
    meetings_service.WRITING.add(meeting_id)

    response = authenticated_client.post(f"/meetings/{meeting_id}/notes", headers=HX)

    assert response.status_code == 409
    assert started == []
    body = page_html(authenticated_client, f"/meetings/{meeting_id}/body")
    none(body, '[hx-post$="/notes"]')


async def test_who_said_what_reads_at_a_glance(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """One speaker's lines run together under their name, which has their
    color, the same one their action items show them in."""
    meeting_id, lines = await ended(
        async_db_session,
        acting_owner_user_id,
        ("Ada", "One."),
        ("Ada", "Two."),
        ("Leonard", "I'll book it."),
        notes=lambda ids: Notes(
            summary="Booked.",
            action_items=[ActionItem(text="Book it", owner="Leonard", lines=[ids[2]])],
        ),
    )

    html = page_html(authenticated_client, f"/meetings/{meeting_id}")

    turns = select(html, "#meeting-transcript [data-turn]")
    assert [text(one(turn, "[data-speaker]")) for turn in turns] == ["Ada", "Leonard"]
    assert all(one(html, f"#line-{line}") is not None for line in lines)
    owner = one(html, "#all-items [data-owner]")
    assert text(owner) == "Leonard"
    # The theme's way: a small dot in the speaker's color, the name in text.
    ada, leonard = (one(turn, "[data-dot]").get("style") for turn in turns)
    assert (
        "--aegis-chart-" in leonard and one(owner, "[data-dot]").get("style") == leonard
    )
    assert ada != leonard


async def test_the_transcript_is_quick_to_get_up_and_down(
    authenticated_client: TestClient, finished: Callable[..., Any]
) -> None:
    """The house's ``data-scroll-to`` buttons, kept in view while reading:
    back to the notes, to the start, to the latest line."""
    meeting_id, _ = await finished()

    html = page_html(authenticated_client, f"/meetings/{meeting_id}")

    jumps = [
        b.get("data-scroll-to")
        for b in select(html, "#meeting-transcript [data-scroll-to]")
    ]
    assert jumps == [
        "#meeting-notes",
        "#meeting-transcript [data-turn]:first-child",
        "#meeting-transcript [data-turn]:last-child",
    ]


async def test_picking_who_i_am_redraws_only_my_items(
    authenticated_client: TestClient, finished: Callable[..., Any]
) -> None:
    """The page stays where it is."""
    meeting_id, _ = await finished(me=None)

    form = one(
        page_html(authenticated_client, f"/meetings/{meeting_id}"), "#my-items form"
    )

    assert form.get("hx-target") == "#my-items"
    assert form.get("hx-select") == "#my-items"


def test_an_unknown_meeting_is_not_found(authenticated_client: TestClient) -> None:
    assert authenticated_client.get("/meetings/987654").status_code == 404


def test_the_navbar_links_the_page(authenticated_client: TestClient) -> None:
    assert select(page_html(authenticated_client, "/meetings"), 'a[href="/meetings"]')


async def test_the_page_has_the_calendar_of_the_meetings_i_am_invited_to(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    acting_owner_user_id: int | None,
) -> None:
    """A month of the agents' calendars in my time zone, moved a month at a
    time: every meeting on them without auth, else the invites I am on
    (this one is Dana's and Leo's)."""
    calendar = Calendar(monkeypatch, STANDUP)
    await read_calendars(async_db_session, calendar.read, at(18, 0))
    authenticated_client.cookies.set(TZ_COOKIE, "America/New_York")

    html = page_html(authenticated_client, "/meetings?month=2026-10")

    days = select(html, "#meetings-calendar [data-day]")
    assert len(days) == 35
    entries = select(html, '#meetings-calendar [data-day="2026-10-19"] [data-entry]')
    assert len(entries) == (1 if acting_owner_user_id is None else 0)
    if entries:
        assert "09:00" in text(entries[0])
    [later] = select(html, "#meetings-calendar a[data-month-later]")
    assert "month=2026-11" in (later.get("href") or "")


async def test_a_line_asks_her_what_it_is_about(
    authenticated_client: TestClient,
    finished: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every line can be asked "what is this about?": her answer opens under
    it on the asker's page alone, in a place the live re-read keeps."""
    from app.components.web_frontend.routes import meetings as page
    from app.services.meetings.models import LineAbout

    said = LineAbout(summary="Booking the **room**.")
    monkeypatch.setattr(page, "asks_about", lambda: True)
    monkeypatch.setattr(page, "line_about", AsyncMock(return_value=said))
    meeting_id, lines = await finished()
    asked = f"/meetings/{meeting_id}/lines/{lines[0]}/about"

    html = page_html(authenticated_client, f"/meetings/{meeting_id}")
    answer = _ok(authenticated_client.post(asked, headers=HX))

    assert one(html, f"#about-line-{lines[0]}").get("hx-preserve") is not None
    assert one(html, f'[data-about="{lines[0]}"]').get("hx-post") == asked
    assert text(one(answer, "[data-about-answer] strong")) == "room"


async def test_the_card_she_draws_shows_in_her_answer(
    authenticated_client: TestClient,
    finished: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The card her answer drew (a part's wiring, where a line names one)
    is drawn full size under the line, as the chat draws it."""
    chat_card = pytest.importorskip("app.services.ai.models.chat_card")
    from app.components.web_frontend.routes import meetings as page
    from app.core.db import get_async_session
    from app.services.meetings.models import LineAbout
    from tests.web.test_chat_cards import PAYLOADS

    async with get_async_session() as session:
        card = chat_card.ChatCard(
            conversation_id="c1", kind="table", payload=PAYLOADS["table"]
        )
        session.add(card)
        card_id = card.id

    said = LineAbout(summary="The workers.", card_id=card_id)
    monkeypatch.setattr(page, "line_about", AsyncMock(return_value=said))
    meeting_id, lines = await finished()

    answer = _ok(
        authenticated_client.post(
            f"/meetings/{meeting_id}/lines/{lines[0]}/about", headers=HX
        )
    )

    assert one(answer, '[data-about-answer] [data-card="table"]') is not None
