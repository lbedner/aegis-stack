"""The one tool Overseer's chat (or any agent granted it) reads the
meetings with (``meetings.tools``): with nothing asked, the series and the
latest meetings; one series in full; one meeting in full, its notes and
every line said; or a search of what was said. An admin reads everyone's,
anyone else their own."""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import acting_as, result_data
from app.services.meetings import tools
from app.services.meetings.models import ActionItem, NoteItem, Notes, Theme
from tests._meetings import OTHER, ended, kept_series
from tests._session import opens


@pytest.fixture(autouse=True)
def _session(async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools, "get_async_session", opens(async_db_session))


@pytest.mark.parametrize("admin", [True, False])
async def test_nothing_asked_lists_the_series_and_the_latest_meetings(
    async_db_session: AsyncSession, admin: bool
) -> None:
    mine, _ = await ended(async_db_session, 1, ("Ada", "Hello."))
    theirs, _ = await ended(async_db_session, 2, ("Grace", "Hi."), url=OTHER)
    series = await kept_series(async_db_session, 1, summary="Shipping slips.")

    with acting_as(1, "assistant", admin=admin):
        read = result_data(await tools.meetings())

    assert [s["series_id"] for s in read["series"]] == [series]
    assert [m["meeting_id"] for m in read["recent"]] == (
        [theirs, mine] if admin else [mine]
    )
    assert read["recent"][-1]["status"] == "Left"


@pytest.mark.parametrize("admin", [True, False])
async def test_a_meeting_reads_whole_its_notes_and_every_line_linked(
    async_db_session: AsyncSession, admin: bool
) -> None:
    """Asked about one call, she reads all of it: what the search finds is
    a few lines, and the answer is often in the ones around them."""
    mine, ids = await ended(
        async_db_session,
        1,
        ("Lisa", "I never got a nudge on Saturday."),
        ("Leonard", "Then the cadence is off."),
        notes=lambda ids: Notes(
            summary="Nudges are not arriving.",
            decisions=[NoteItem(text="Check the cadence", lines=[ids[1]])],
            action_items=[ActionItem(text="Fix the nudge", owner="Leonard")],
        ),
    )
    theirs, _ = await ended(async_db_session, 2, ("Grace", "Hi."))

    with acting_as(1, "assistant", admin=admin):
        read = result_data(await tools.meetings(meeting_id=mine))
        hidden = result_data(await tools.meetings(meeting_id=theirs))

    link = (
        f"/overseer/services/meetings?meeting={mine}&line={ids[1]}"
        if admin
        else f"/meetings/{mine}#line-{ids[1]}"
    )
    assert read["notes"] == [
        {"part": "Summary", "text": "Nudges are not arriving."},
        {"part": "Decisions", "text": "Check the cadence"},
        {"part": "Action items", "text": "Fix the nudge", "who": "Leonard"},
    ]
    assert read["lines"][1] == {
        "speaker": "Leonard",
        "at": "00:01",
        "text": "Then the cadence is off.",
        "link": link,
    }
    assert [line["speaker"] for line in read["lines"]] == ["Lisa", "Leonard"]
    assert ("error" in hidden) is not admin


@pytest.mark.parametrize("admin", [True, False])
async def test_a_series_reads_in_full_with_its_meetings(
    async_db_session: AsyncSession, admin: bool
) -> None:
    """Asked how a series is going, she reads the one asked about: what
    keeps coming up and where it stands, what is settled and still open,
    and which meetings to read for more."""
    meeting, _ = await ended(async_db_session, 1, ("Ada", "Hello."))
    mine = await kept_series(
        async_db_session,
        1,
        name="Dev call",
        summary="Shipping slips a week.",
        themes=[Theme(text="The usage report", status="answered")],
        settled=[NoteItem(text="Ship Friday")],
        still_open=[NoteItem(text="Who owns billing")],
    )
    theirs = await kept_series(async_db_session, 2, url=OTHER)

    with acting_as(1, "assistant", admin=admin):
        read = result_data(await tools.meetings(series_id=mine))
        hidden = result_data(await tools.meetings(series_id=theirs))

    assert (read["name"], read["meetings"], read["headline"]) == (
        "Dev call",
        2,
        "Shipping slips a week.",
    )
    assert read["meeting_ids"] == [meeting]
    assert read["themes"] == [{"text": "The usage report", "status": "answered"}]
    assert (read["settled"], read["still_open"]) == (
        ["Ship Friday"],
        ["Who owns billing"],
    )
    assert "shifted" not in read  # a part with nothing in it is left out
    assert ("error" in hidden) is not admin


@pytest.mark.parametrize("admin", [True, False])
async def test_a_query_finds_the_lines_linked(
    async_db_session: AsyncSession, admin: bool
) -> None:
    """Overseer's chat (an admin) searches every owner's meetings and links
    Overseer's drawer at the line; anyone else their own, linked to their
    Meetings page."""
    mine, ids = await ended(async_db_session, 1, ("Lawrence", "Pricing at 49."))
    theirs, _ = await ended(async_db_session, 2, ("Grace", "Pricing at 59."))

    with acting_as(1, "assistant", admin=admin):
        hits = result_data(await tools.meetings(query="what about pricing?"))

    assert {hit["meeting_id"] for hit in hits} == ({mine, theirs} if admin else {mine})
    link = (
        f"/overseer/services/meetings?meeting={mine}&line={ids[0]}"
        if admin
        else f"/meetings/{mine}#line-{ids[0]}"
    )
    assert next(h for h in hits if h["meeting_id"] == mine) == {
        "meeting_id": mine,
        "part": "Transcript",
        "speaker": "Lawrence",
        "at": "00:00",
        "text": "Pricing at 49.",
        "link": link,
    }
