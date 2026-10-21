"""A series of meetings (``domains.series``): an owner's meetings on one
link, which a recurring meeting keeps every time; what the series keeps
coming back to (its themes), each with every line it was said in, read
over the series and beside each meeting's own threads. Writing them is a
model pass (``test_meetings_series_themes``); here they are kept by hand."""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.domains.series.queries import series_link
from app.services.meetings.domains.series.service import (
    SeriesNotFoundError,
    SeriesService,
)
from app.services.meetings.domains.threads.service import meeting_threads
from app.services.meetings.models import NoteItem, Notes, Theme, ThreadSection
from app.services.meetings.service import MeetingsService
from tests._meetings import MEET, asked_twice, ended, kept_series

OTHER = "https://meet.google.com/xyz-wxyz-xyz"


def _themes(sections: list[ThreadSection]) -> ThreadSection:
    return next(s for s in sections if s.key == "themes")


def test_a_series_is_its_link_without_what_follows_it() -> None:
    """The same call however the link was pasted; another call is not."""
    assert series_link(f"{MEET}?authuser=0") == series_link(MEET)
    assert series_link(f"{MEET}/") == series_link(MEET)
    assert series_link(MEET.replace("meet.", "MEET.")) == series_link(MEET)
    assert series_link(OTHER) != series_link(MEET)


async def test_a_theme_reads_with_every_line_it_was_said_in(
    async_db_session: AsyncSession,
) -> None:
    """Who raised it, in how many meetings, and where it stands; the
    series named for its calendar event, else for its link."""
    meetings, asked = await asked_twice(async_db_session, 1)
    report = Theme(text="Dana wants the usage report", lines=asked)
    series_id = await kept_series(async_db_session, 1, name="Dev call", themes=[report])
    await kept_series(async_db_session, 1, url=OTHER)
    svc = SeriesService(async_db_session, 1)

    assert [r.name for r in await svc.series()] == [series_link(OTHER), "Dev call"]
    record = await svc.read(series_id)
    (item,) = _themes(record.sections).items
    assert record.series.summary == "Over time."
    assert record.meetings == meetings[::-1]
    # Who said it is on each line: a theme raised by many reads as itself.
    assert (item.text, item.speaker, item.status) == (report.text, None, "open")
    assert item.detail == "2 meetings"
    assert [q.meeting_id for q in item.quotes] == meetings


async def test_over_time_reads_as_cards_each_point_with_when(
    async_db_session: AsyncSession,
) -> None:
    """What was settled (and in which meeting), what shifted (from when to
    when), what is still open (since when) and the mood, each point with
    its lines; a card with nothing in it is left out."""
    (first, second), asked = await asked_twice(async_db_session, None)
    series_id = await kept_series(
        async_db_session,
        None,
        summary="The report is still missing.",
        settled=[NoteItem(text="Dana owns the report", lines=[asked[1]])],
        shifted=[NoteItem(text="Weekly -> daily", lines=asked)],
        still_open=[NoteItem(text="The usage report", lines=asked)],
    )

    record = await SeriesService(async_db_session, None).read(series_id)

    cards = {c.key: c for c in record.over_time}
    assert record.series.summary == "The report is still missing."
    assert list(cards) == ["settled", "shifted", "still_open"]
    assert [i.detail for c in cards.values() for i in c.items] == [
        f"Meeting {second}",
        f"Meetings {first} → {second}",
        f"Since meeting {first}",
    ]
    assert [q.id for q in cards["shifted"].items[0].quotes] == asked
    (theme_section,) = record.sections
    assert theme_section.items == []


async def test_a_meetings_threads_say_what_keeps_coming_up(
    async_db_session: AsyncSession,
) -> None:
    """Its own lines of each theme it is part of, the series' other
    meetings' beside them; a theme it is not part of is left out."""
    (_, second), asked = await asked_twice(async_db_session, None)
    _, ids = await ended(
        async_db_session,
        None,
        ("Dana", "Unrelated."),
        notes=lambda _: Notes(summary="-"),
    )
    await kept_series(
        async_db_session,
        None,
        themes=[
            Theme(text="The usage report", lines=asked),
            Theme(text="Not in the second", lines=[asked[0], ids[0]]),
        ],
    )
    svc = MeetingsService(async_db_session, None)

    (item,) = _themes(await meeting_threads(svc, second)).items
    assert item.text == "The usage report"
    assert [q.id for q in item.quotes] == [asked[1]]
    assert [q.id for q in item.other] == [asked[0]]
    on_its_own, _ = await ended(
        async_db_session,
        None,
        ("Ada", "Hi."),
        notes=lambda _: Notes(summary="-"),
        url=OTHER,
    )
    assert _themes(await meeting_threads(svc, on_its_own)).items == []


async def test_a_deleted_meeting_takes_what_only_it_said(
    async_db_session: AsyncSession,
) -> None:
    """A theme left citing nothing goes, and the series with its last
    meeting."""
    (first, second), asked = await asked_twice(async_db_session, None)
    series_id = await kept_series(
        async_db_session,
        None,
        themes=[
            Theme(text="The usage report", lines=asked),
            Theme(text="Only the first", lines=[asked[0]]),
        ],
    )
    svc = SeriesService(async_db_session, None)

    await MeetingsService(async_db_session, None).delete(first)
    (item,) = _themes((await svc.read(series_id)).sections).items
    assert item.text == "The usage report"
    await MeetingsService(async_db_session, None).delete(second)
    with pytest.raises(SeriesNotFoundError):
        await svc.read(series_id)


async def test_another_owners_series_is_not_found(
    async_db_session: AsyncSession,
) -> None:
    theirs = await kept_series(async_db_session, 2)

    with pytest.raises(SeriesNotFoundError):
        await SeriesService(async_db_session, 1).read(theirs)
    assert (await SeriesService(async_db_session, None).read(theirs)).series.id
