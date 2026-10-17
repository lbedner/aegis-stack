"""Search across every meeting's transcript and notes (``domains.search``):
a word said finds its line, with its meeting, speaker and time; a word in
the notes finds the item, opening at the line it came from; one owner's
search never reaches another's meetings. Each test runs on SQLite's FTS5,
and again on Postgres's full-text search where ``TEST_POSTGRES_URL`` names
a server (``postgresql+asyncpg://...``) to search on."""

from collections.abc import AsyncIterator
import os
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import acting_as
from app.services.meetings import tools
from app.services.meetings.domains.notes.service import keep_notes
from app.services.meetings.domains.search import queries
from app.services.meetings.domains.search.service import search_meetings
from app.services.meetings.models import (
    ActionItem,
    BotAccount,
    Meeting,
    MeetingNoteItem,
    MeetingNoteLine,
    MeetingNotes,
    MeetingParticipant,
    MeetingPerson,
    NoteItem,
    Notes,
    TranscriptLine,
)
from app.services.meetings.service import MeetingsService
from tests._meetings import ended, said
from tests._session import opens

POSTGRES = os.environ.get("TEST_POSTGRES_URL")
TABLES = [
    model.__table__  # type: ignore[attr-defined]
    for model in (
        BotAccount,
        Meeting,
        MeetingPerson,
        MeetingParticipant,
        TranscriptLine,
        MeetingNotes,
        MeetingNoteItem,
        MeetingNoteLine,
    )
]


def _summary(_: list[int]) -> Notes:
    return Notes(summary="-")


@pytest.fixture(params=["sqlite", "postgres"])
async def db(
    request: pytest.FixtureRequest, async_db_session: AsyncSession
) -> AsyncIterator[AsyncSession]:
    """The test's session on each engine search runs on."""
    if request.param == "sqlite":
        yield async_db_session
        return
    if not POSTGRES:
        pytest.skip("TEST_POSTGRES_URL names no Postgres to search on")
    # A schema of the test's own, so parallel workers never meet.
    schema = f"search_{uuid4().hex[:12]}"
    admin = create_async_engine(POSTGRES)
    async with admin.begin() as conn:
        await conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = create_async_engine(
        POSTGRES, connect_args={"server_settings": {"search_path": schema}}
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all, tables=TABLES)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session
    finally:
        await engine.dispose()
        async with admin.begin() as conn:
            await conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        await admin.dispose()


async def test_a_word_said_finds_its_line_with_who_said_it_and_when(
    db: AsyncSession,
) -> None:
    meeting_id, ids = await ended(
        db,
        1,
        ("Ada", "Shall we start?"),
        ("Lawrence", "Our pricing is too low for the enterprise tier."),
        notes=_summary,
    )

    hits = await search_meetings(db, 1, "pricing")

    assert [
        (h.meeting_id, h.part, h.speaker, h.line_id, h.at, h.text) for h in hits
    ] == [
        (
            meeting_id,
            "Transcript",
            "Lawrence",
            ids[1],
            1.0,
            "Our pricing is too low for the enterprise tier.",
        )
    ]


async def test_a_word_finds_its_other_forms(db: AsyncSession) -> None:
    _, ids = await ended(db, 1, ("Lawrence", "We priced it at 49."), notes=_summary)

    assert [h.line_id for h in await search_meetings(db, 1, "pricing")] == ids


async def test_a_word_in_the_notes_finds_the_item_at_its_line(
    db: AsyncSession,
) -> None:
    meeting_id, ids = await ended(
        db,
        1,
        ("Ada", "Let's go with forty-nine."),
        ("Lawrence", "I'll send the sheet."),
        notes=lambda ids: Notes(
            summary="The team settled the launch.",
            decisions=[NoteItem(text="Pricing stays at 49", lines=[ids[0]])],
            action_items=[
                ActionItem(
                    text="Send the pricing sheet", owner="Lawrence", lines=[ids[1]]
                )
            ],
            open_questions=[NoteItem(text="Who owns the launch?")],
        ),
    )

    pricing = await search_meetings(db, 1, "pricing")
    launch = await search_meetings(db, 1, "launch")

    assert [(h.part, h.text, h.line_id, h.at) for h in pricing] == [
        ("Decisions", "Pricing stays at 49", ids[0], 0.0),
        ("Action items", "Send the pricing sheet", ids[1], 1.0),
    ]
    assert {(h.meeting_id, h.part, h.line_id, h.speaker) for h in launch} == {
        (meeting_id, "Summary", None, None),
        (meeting_id, "Open questions", None, None),
    }


async def test_each_notes_text_that_matches_is_read_once(db: AsyncSession) -> None:
    """A text read twice would spend the limit on its double, and older
    meetings' hits would fall off it."""
    await ended(
        db,
        1,
        ("Ada", "Hello."),
        notes=lambda _: Notes(
            summary="Pricing settled.",
            decisions=[NoteItem(text="Pricing stays at 49"), NoteItem(text="Hire")],
            action_items=[ActionItem(text="Send pricing deck", owner="Ada")],
        ),
    )

    texts = [item.text for item, *_ in await queries.notes(db, 1, "pricing", 50)]

    assert sorted(texts) == [
        "Pricing settled.",
        "Pricing stays at 49",
        "Send pricing deck",
    ]


async def test_newest_meeting_first_and_its_lines_in_the_order_said(
    db: AsyncSession,
) -> None:
    older, _ = await ended(db, 1, ("Ada", "Pricing first."), notes=_summary)
    newer, ids = await ended(
        db,
        1,
        ("Ada", "Pricing again."),
        ("Lawrence", "More pricing."),
        notes=lambda ids: Notes(
            summary="-", decisions=[NoteItem(text="Pricing holds", lines=[ids[1]])]
        ),
    )

    hits = await search_meetings(db, 1, "pricing")

    assert [(h.meeting_id, h.part, h.line_id) for h in hits][:3] == [
        (newer, "Decisions", ids[1]),
        (newer, "Transcript", ids[0]),
        (newer, "Transcript", ids[1]),
    ]
    assert hits[-1].meeting_id == older


async def test_one_owner_never_finds_anothers_meetings(db: AsyncSession) -> None:
    mine, _ = await ended(db, 1, ("Ada", "Pricing for us."), notes=_summary)
    theirs, _ = await ended(db, 2, ("Grace", "Pricing for them."), notes=_summary)

    assert {h.meeting_id for h in await search_meetings(db, 1, "pricing")} == {mine}
    every = await search_meetings(db, None, "pricing")
    assert {h.meeting_id for h in every} == {mine, theirs}


async def test_a_line_is_found_as_it_reads_now(db: AsyncSession) -> None:
    """A caption grows while it is said, and a meeting can be deleted: the
    search keeps up with both."""
    meeting = await MeetingsService(db, 1).request(
        "https://meet.google.com/abc-defg-hij"
    )
    meeting_id: int = meeting.id  # type: ignore[assignment]
    await said(db, meeting_id, ("Ada", "The budget"))
    await db.commit()
    assert await search_meetings(db, 1, "pricing") == []

    await keep_notes(db, meeting_id, Notes(summary="Budget."), None)
    line = (await MeetingsService(db, 1).transcript(meeting))[0][1]
    line.text = "The budget and the pricing"
    db.add(line)
    await db.commit()
    assert [h.text for h in await search_meetings(db, 1, "pricing")] == [
        "The budget and the pricing"
    ]

    await MeetingsService(db, 1).delete(meeting_id)
    assert await search_meetings(db, 1, "pricing") == []
    assert await search_meetings(db, 1, "budget") == []


async def test_notes_written_again_are_searched_as_they_read_now(
    db: AsyncSession,
) -> None:
    meeting_id, _ = await ended(
        db, 1, ("Ada", "Hello."), notes=lambda _: Notes(summary="About pricing.")
    )
    await keep_notes(db, meeting_id, Notes(summary="About hiring."), None)

    assert await search_meetings(db, 1, "pricing") == []
    assert [h.text for h in await search_meetings(db, 1, "hiring")] == ["About hiring."]


@pytest.mark.parametrize("admin", [True, False])
async def test_the_chat_tool_answers_with_the_lines_linked(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, admin: bool
) -> None:
    """Overseer's chat (an admin) reads every owner's meetings and links
    Overseer's drawer at the line; anyone else reads their own, linked to
    their Meetings page."""
    monkeypatch.setattr(tools, "get_async_session", opens(async_db_session))
    mine, ids = await ended(
        async_db_session, 1, ("Lawrence", "Pricing at 49."), notes=_summary
    )
    theirs, _ = await ended(
        async_db_session, 2, ("Grace", "Pricing at 59."), notes=_summary
    )

    with acting_as(1, "assistant", admin=admin):
        hits = await tools.meetings_search("pricing")

    found = {hit["meeting_id"] for hit in hits}
    assert found == ({mine, theirs} if admin else {mine})
    hit = next(h for h in hits if h["meeting_id"] == mine)
    link = (
        f"/overseer/services/meetings?meeting={mine}&line={ids[0]}"
        if admin
        else f"/meetings/{mine}#line-{ids[0]}"
    )
    assert hit == {
        "meeting_id": mine,
        "part": "Transcript",
        "speaker": "Lawrence",
        "at": "00:00",
        "text": "Pricing at 49.",
        "link": link,
    }


@pytest.mark.parametrize("query", ["", "   ", '"', "AND (", "pricing* NEAR(", "-"])
async def test_any_text_is_a_search_never_an_error(
    db: AsyncSession, query: str
) -> None:
    await ended(db, 1, ("Ada", "Pricing."), notes=_summary)

    hits = await search_meetings(db, 1, query)

    assert all(h.text == "Pricing." for h in hits)
