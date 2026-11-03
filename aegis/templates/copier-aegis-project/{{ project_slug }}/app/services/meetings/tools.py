"""Meetings' tool (``app.core.tools.load_tools``): one read of the
meetings for Overseer's chat or any agent granted it, answering by what it
is asked: the series and the latest meetings, one series, one meeting in
full, or a search of what was said. Read-only."""

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_async_session
from app.core.figures import FIGURES, absent
from app.core.formatting import format_clock
from app.core.tools import Refused, current_owner_user_id, register_tool
from app.services.meetings.service import (
    Meeting,
    MeetingNotFoundError,
    MeetingSeries,
    MeetingsService,
    SeriesNotFoundError,
    SeriesService,
    meeting_link,
    note_points,
    search_meetings,
    series_name,
    status_label,
)
from app.services.shared.deps import caller_is_admin

# How many hits a search hands over, and how many meetings the list does.
HITS = 20
RECENT = 10


class MeetingHit(BaseModel):
    """One place a search found the words, as the tool hands it over."""

    model_config = FIGURES

    meeting_id: int
    # "Transcript", or the part of the notes ("Summary", "Decisions", ...).
    part: str
    speaker: str | None
    # How far into the call, as a clock reads it ("12:04").
    at: str | None
    text: str
    link: str


async def _search(
    session: AsyncSession, admin: bool, owner: int | None, query: str
) -> list[MeetingHit]:
    hits = await search_meetings(session, owner, query, HITS)
    return [
        MeetingHit(
            meeting_id=hit.meeting_id,
            part=hit.part,
            speaker=hit.speaker,
            at=None if hit.at is None else format_clock(hit.at),
            text=hit.text,
            link=meeting_link(hit.meeting_id, hit.line_id, admin),
        )
        for hit in hits
    ]


class SeriesBrief(BaseModel):
    """One series of meetings: a recurring meeting over time."""

    model_config = FIGURES

    series_id: int
    name: str
    # How many of its meetings it was last read from.
    meetings: int
    # The day it was last written, after its latest meeting (ISO).
    updated: str
    # One sentence: where the series stands now.
    headline: str


class SeriesTheme(BaseModel):
    """Something the series keeps coming back to, and where it stands."""

    model_config = FIGURES

    text: str
    status: str


class SeriesRead(SeriesBrief):
    """A series in full; a part with nothing in it is left out."""

    themes: list[SeriesTheme] | None = absent()
    settled: list[str] | None = absent()
    shifted: list[str] | None = absent()
    still_open: list[str] | None = absent()
    mood: list[str] | None = absent()
    # Its latest meetings, newest first: each one reads in full.
    meeting_ids: list[int]


class MeetingBrief(BaseModel):
    """One meeting the bot was asked into."""

    model_config = FIGURES

    meeting_id: int
    # What its calendar calls it, if any does.
    title: str | None = absent()
    # The day it was asked for (ISO).
    day: str
    status: str
    link: str


class Overview(BaseModel):
    """Every series, latest written first, and the latest meetings."""

    model_config = FIGURES

    series: list[SeriesBrief]
    recent: list[MeetingBrief]


class MeetingNote(BaseModel):
    """One point of a meeting's notes."""

    model_config = FIGURES

    # "Summary", or the part of the notes ("Decisions", "Action items"...).
    part: str
    text: str
    # Whose it is (an action item's owner, a position's speaker).
    who: str | None = absent()
    due: str | None = absent()


class MeetingLine(BaseModel):
    """One line of a meeting, as it was said."""

    model_config = FIGURES

    speaker: str
    at: str
    text: str
    link: str


class MeetingRead(MeetingBrief):
    """A meeting in full: its notes (left out until written), every line."""

    notes: list[MeetingNote] | None = absent()
    lines: list[MeetingLine]


async def meetings(
    query: str | None = None,
    meeting_id: int | None = None,
    series_id: int | None = None,
) -> Overview | MeetingRead | SeriesRead | list[MeetingHit] | Refused:
    """The user's meetings (an admin's: everyone's), read back. Asked
    nothing: every series (a recurring meeting read over time) with its
    headline, and the latest meetings. With ``series_id``: that series in
    full, what it keeps coming back to (each theme open, answered or done),
    what was settled, shifted and is still open, the mood, and its
    meetings. With ``meeting_id``: that meeting in full, its notes and
    every line said, who said it and how far into the call; read it to
    answer anything about one call. With ``query``: the transcript lines
    and notes that have any of its words, those with the most first; use
    it to find which call something was said in, then read that one.
    Answer from the lines, quoting who said what, and link each line you
    use with its ``link``."""
    admin = await caller_is_admin()
    owner = None if admin else current_owner_user_id.get()
    async with get_async_session() as session:
        if query is not None:
            return await _search(session, admin, owner, query)
        if meeting_id is not None:
            return await _meeting(session, admin, owner, meeting_id)
        if series_id is not None:
            return await _series(session, owner, series_id)
        svc = SeriesService(session, owner)
        series = [_brief(row.series) for row in await svc.series()]
        recent = await MeetingsService(session, owner).list_meetings(RECENT)
    return Overview(series=series, recent=[_meeting_brief(m, admin) for m in recent])


async def _meeting(
    session: AsyncSession, admin: bool, owner: int | None, meeting_id: int
) -> MeetingRead | Refused:
    svc = MeetingsService(session, owner)
    try:
        meeting = await svc.get(meeting_id)
    except MeetingNotFoundError as exc:
        return Refused(error=str(exc))
    kept = (await svc.notes_for([meeting_id])).get(meeting_id)
    lines = [
        MeetingLine(
            speaker=speaker,
            at=format_clock(line.start_seconds),
            text=line.text,
            link=meeting_link(meeting_id, line.id, admin),
        )
        for speaker, line in await svc.transcript(meeting)
    ]
    notes = (
        [MeetingNote(**p._asdict()) for p in note_points(kept.notes)]
        if kept and kept.notes
        else None
    )
    brief = _meeting_brief(meeting, admin).model_dump()
    return MeetingRead(**brief, notes=notes, lines=lines)


async def _series(
    session: AsyncSession, owner: int | None, series_id: int
) -> SeriesRead | Refused:
    try:
        record = await SeriesService(session, owner).read(series_id)
    except SeriesNotFoundError as exc:
        return Refused(error=str(exc))
    texts = {s.key: [i.text for i in s.items] for s in record.over_time}
    themes = [
        SeriesTheme(text=i.text, status=i.status or "")
        for section in record.sections
        for i in section.items
    ]
    brief = _brief(record.series).model_dump()
    return SeriesRead(
        **brief, themes=themes or None, **texts, meeting_ids=record.meetings
    )


def _brief(series: MeetingSeries) -> SeriesBrief:
    return SeriesBrief(
        series_id=series.id,  # type: ignore[arg-type]
        name=series_name(series),
        meetings=series.meetings,
        updated=series.written_at.date().isoformat(),
        headline=series.summary,
    )


def _meeting_brief(meeting: Meeting, admin: bool) -> MeetingBrief:
    return MeetingBrief(
        meeting_id=meeting.id,  # type: ignore[arg-type]
        title=meeting.title or None,
        day=meeting.created_at.date().isoformat(),
        status=status_label(meeting.status),
        link=meeting_link(meeting.id, None, admin),  # type: ignore[arg-type]
    )


register_tool(
    "meetings",
    meetings,
    effect="read",
    doing="Reading the meetings",
)
