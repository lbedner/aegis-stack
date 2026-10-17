"""Context for the Overseer Meetings page: every owner's meetings, for the
admin, and the bot sent from here. A row opens one meeting in the drawer,
drawn from the Meetings page's own context
(``routes.meetings.meeting_context``): its notes and transcript, with the
bot asked to leave or the meeting deleted from there; a search hit opens
it at its line (``overseer_meeting_search``). People is how to
work with each person who speaks in them, one guide in the drawer with
the lines each point rests on and their threads; a meeting's own threads
load into its drawer once its notes are there. Agents is each Google
account the bot joins as (``meeting_agents``). Registered only in projects with the
meetings service (see ``overseer_sections``).
"""

from collections.abc import Iterable
from typing import Any

from app.core.formatting import format_relative_time
from app.services.meetings.domains.accounts.service import agent_names, agents
from app.services.meetings.domains.people.service import PeopleService, said_when
from app.services.meetings.domains.search.service import LINE_PARAM, MEETING_PARAM
from app.services.meetings.models import (
    GuideRecord,
    GuideRow,
    Quote,
    ThreadSection,
)
from app.services.meetings.service import MeetingsService, meetings_counts
from app.services.system.models import ComponentStatus

from .meeting_agents import agent_options, agents_context
from .overseer_meeting_search import search_context
from .overseer_nav import SectionRequest, page_url
from .rendering import drawer_state, with_query
from .routes.meetings import row_of, send_form

SECTIONS = ((None, {"overview": "Meetings", "people": "People", "agents": "Agents"}),)

PAGE = page_url("services", "meetings")
PARTIALS = "/partials/overseer/meetings"
DRAWER_PARAM = MEETING_PARAM
PEOPLE = f"{PAGE}/people"
PEOPLE_PARTIALS = f"{PARTIALS}/people"
PERSON_PARAM = "person"
LIMIT = 200


async def section_context(
    section: str, meetings: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    """Every owner's meetings, newest first, one open in the drawer when
    the address names it; or, on People, every owner's guides."""
    if section == "people":
        return await _people(req)
    if section == "agents":
        return await agents_context(req.db, meeting_url)
    counts = await meetings_counts(req.db)
    every = await agents(req.db)
    names = agent_names((a.id, a.name) for a in every)
    rows = [
        row_of(m, meeting_url(m.id))  # type: ignore[arg-type]
        | {"owner": m.owner_user_id, "agent": names.get(m.account_id)}
        for m in await MeetingsService(req.db, None).list_meetings(LIMIT)
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
                {"label": "Meetings", "value": counts["meetings"]},
                {"label": "In a call now", "value": counts["in_call"]},
            ],
            "rows": rows,
        }
        | send_form(PARTIALS, agents=agent_options(every))
    )


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
