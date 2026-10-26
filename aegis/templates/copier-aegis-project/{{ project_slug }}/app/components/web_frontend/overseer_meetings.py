"""Context for the Overseer Meetings page: every owner's meetings, for the
admin, and the bot sent from here. A row opens one meeting in the drawer,
drawn from the Meetings page's own context
(``routes.meetings.meeting_context``): its notes and transcript, with the
bot asked to leave or the meeting deleted from there; a search hit opens
it at its line (``overseer_meeting_search``). People is how to
work with each person who speaks in them, one guide in the drawer with
the lines each point rests on and their threads; a meeting's own threads
load into its drawer once its notes are there. Calendar is a month of every
agent's calendar (``meeting_calendar``); Series is what each series of
meetings keeps coming back to, one in the drawer with each theme's lines;
Agents is each Google account the bot joins as (``meeting_agents``). Registered only in projects with the
meetings service (see ``overseer_sections``).
"""

from collections.abc import Iterable
from typing import Any

from app.core.formatting import format_relative_time
from app.services.meetings.domains.accounts.service import agent_names, agents
from app.services.meetings.domains.calendar.entries import CalendarEventDetail
from app.services.meetings.domains.calendar.owners import owners
from app.services.meetings.domains.people.service import PeopleService, said_when
from app.services.meetings.domains.search.service import LINE_PARAM, MEETING_PARAM
from app.services.meetings.domains.series.service import SeriesService
from app.services.meetings.models import (
    GuideRecord,
    GuideRow,
    Quote,
    SeriesRecord,
    SeriesRow,
    ThreadSection,
)
from app.services.meetings.queries import meetings_counts
from app.services.meetings.service import MeetingsService
from app.services.system.models import ComponentStatus

from .meeting_agents import agent_options, agents_context, owner_options
from .meeting_calendar import calendar_context
from .meeting_status import state_cell
from .overseer_meeting_search import search_context
from .overseer_nav import SectionRequest, page_url
from .rendering import drawer_state, with_query
from .routes.meetings import row_of, send_form

SECTIONS = (
    (
        None,
        {
            "overview": "Overview",
            "calendar": "Calendar",
            "series": "Series",
            "people": "People",
            "agents": "Agents",
        },
    ),
)

PAGE = page_url("services", "meetings")
PARTIALS = "/partials/overseer/meetings"
DRAWER_PARAM = MEETING_PARAM
PEOPLE = f"{PAGE}/people"
CALENDAR = f"{PAGE}/calendar"
EVENT_PARAM = "event"
PEOPLE_PARTIALS = f"{PARTIALS}/people"
PERSON_PARAM = "person"
SERIES = f"{PAGE}/series"
SERIES_PARTIALS = f"{PARTIALS}/series"
SERIES_PARAM = "series"
LIMIT = 200


async def section_context(
    section: str, meetings: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    """Every owner's meetings, newest first, one open in the drawer when
    the address names it; or, on People, every owner's guides."""
    if section == "people":
        return await _people(req)
    if section == "series":
        return await _series(req)
    if section == "agents":
        return await agents_context(req.db, meeting_url) | {"partials": PARTIALS}
    if section == "calendar":
        return await _calendar(req)
    counts = await meetings_counts(req.db)
    every = await agents(req.db)
    names = agent_names((a.id, a.name) for a in every)
    meetings = await MeetingsService(req.db, None).list_meetings(LIMIT)
    rows = [
        row_of(m, meeting_url(m.id))  # type: ignore[arg-type]
        | {"owner": m.owner_user_id, "agent": names.get(m.account_id)}
        for m in meetings
    ]
    wanted = req.query.get(DRAWER_PARAM) or ""
    # A search hit opens its meeting at its line (``overseer_meeting_search``).
    line = req.query.get(LINE_PARAM) or ""
    drawer = with_query(
        f"{PARTIALS}/{wanted}/drawer", line=line if line.isdigit() else None
    )
    return (
        drawer_state(DRAWER_PARAM, drawer if wanted.isdigit() else None)
        | await search_context(req, PAGE)
        | {
            "figures": [
                {"label": "Meetings", "value": counts.meetings},
                {"label": "In a call now", "value": counts.in_call},
            ],
            "rows": rows,
        }
        | send_form(PARTIALS, agents=agent_options(every), meetings=meetings)
    )


async def _calendar(req: SectionRequest) -> dict[str, Any]:
    """Every agent's month, any meeting on it open in the drawer when the
    address names it (``?event=``)."""
    calendar = await calendar_context(
        req.db,
        req.query,
        req.zone,
        CALENDAR,
        meeting_url,
        await agents(req.db),
        details=EVENT_PARAM,
    )
    wanted = req.query.get(EVENT_PARAM) or ""
    drawer = f"{PARTIALS}/calendar/{wanted}/drawer" if wanted.isdigit() else None
    return drawer_state(EVENT_PARAM, drawer) | {"calendar": calendar}


async def owner_context(svc: MeetingsService) -> dict[str, Any]:
    """Everyone the drawer's meeting can be given to while nobody owns it
    (nobody without auth); its owner shows by their email."""
    return {"owners": owner_options(await owners(svc.db))}


def event_context(entry: CalendarEventDetail) -> dict[str, Any]:
    """One meeting on a calendar in the drawer: when, whose calendar, where
    it stands, who organized it and who is invited, its link, and the call
    the agent was sent into, when it was."""
    return {
        "entry": entry,
        "when": f"{entry.starts_at:%a %b} {entry.starts_at.day}, "
        f"{entry.starts_at:%H:%M} - {entry.ends_at:%H:%M}",
        "state": state_cell(entry.state),
        "opens": meeting_url(entry.meeting_id) if entry.meeting_id else None,
    }


def meeting_url(meeting_id: int) -> str:
    """The page with ``meeting_id`` open in the drawer."""
    return with_query(PAGE, **{DRAWER_PARAM: str(meeting_id)})


async def _people(req: SectionRequest) -> dict[str, Any]:
    """Every owner's guides, latest written first, one open in the drawer
    when the address names it."""
    wanted = req.query.get(PERSON_PARAM) or ""
    return drawer_state(
        PERSON_PARAM, f"{PEOPLE_PARTIALS}/{wanted}/drawer" if wanted.isdigit() else None
    ) | {"rows": [_person_row(g) for g in await PeopleService(req.db, None).guides()]}


def _person_row(row: GuideRow) -> dict[str, Any]:
    return {
        "person": {
            "label": row.person,
            "url": with_query(PEOPLE, **{PERSON_PARAM: str(row.guide.id)}),
        },
        "owner": row.owner_user_id,
        "meetings": row.guide.meetings,
        "written": format_relative_time(row.guide.written_at),
    }


async def _series(req: SectionRequest) -> dict[str, Any]:
    """Every owner's series, latest written first, one open in the drawer
    when the address names it."""
    wanted = req.query.get(SERIES_PARAM) or ""
    drawer = f"{SERIES_PARTIALS}/{wanted}/drawer" if wanted.isdigit() else None
    rows = [_series_row(s) for s in await SeriesService(req.db, None).series()]
    return drawer_state(SERIES_PARAM, drawer) | {"rows": rows}


def _series_row(row: SeriesRow) -> dict[str, Any]:
    return {
        "series": {
            "label": row.name,
            "url": with_query(SERIES, **{SERIES_PARAM: str(row.series.id)}),
        },
        "owner": row.series.owner_user_id,
        "meetings": row.series.meetings,
        "written": format_relative_time(row.series.written_at),
    }


def series_context(record: SeriesRecord) -> dict[str, Any]:
    """One series in the drawer: its run over time, a card per part, then
    each theme, every point with the lines it rests on, each opening its
    meeting."""
    return {
        "record": record,
        "base": f"{SERIES_PARTIALS}/{record.series.id}",
        "written": format_relative_time(record.series.written_at),
        "said": said(thread_quotes([*record.over_time, *record.sections])),
    }


def guide_context(record: GuideRecord) -> dict[str, Any]:
    """One guide in the drawer: each part, its points with the lines they
    rest on, then the person's threads, each line opening its meeting."""
    points = [p for section in record.sections for p in section.points]
    return {
        "record": record,
        "base": f"{PEOPLE_PARTIALS}/{record.guide.id}",
        "written": format_relative_time(record.guide.written_at),
        "said": said(
            [*(q for p in points for q in p.quotes), *thread_quotes(record.threads)]
        ),
    }


def threads_context(sections: list[ThreadSection], meeting_id: int) -> dict[str, Any]:
    """A meeting's threads in its drawer: a line of its own jumps to its
    transcript, an earlier meeting's opens that meeting."""
    return {"sections": sections, "said": said(thread_quotes(sections), meeting_id)}


def thread_quotes(sections: list[ThreadSection]) -> list[Quote]:
    return [q for s in sections for i in s.items for q in [*i.quotes, *i.other]]


def said(quotes: Iterable[Quote], here: int | None = None) -> dict[int, Any]:
    """Each quoted line's id: when it was said, and where it opens (the
    line itself in meeting ``here``, else its meeting in the drawer)."""
    return {
        q.id: {
            "when": said_when(q.meeting_id, q.at),
            "url": f"#line-{q.id}"
            if q.meeting_id == here
            else meeting_url(q.meeting_id),
        }
        for q in quotes
    }
