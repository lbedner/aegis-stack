"""Context for the Overseer Meetings page: every owner's meetings, for the
admin, and the bot sent from here. A row opens one meeting in the drawer,
drawn from the Meetings page's own context
(``routes.meetings.meeting_context``): its notes and transcript, with the
bot asked to leave or the meeting deleted from there. People is how to
work with each person who speaks in them, one guide in the drawer with
the lines each point rests on. Registered only in projects with the
meetings service (see ``overseer_sections``).
"""

from typing import Any

from app.core.formatting import format_relative_time
from app.services.meetings.domains.people.service import PeopleService, said_when
from app.services.meetings.models import GuideRecord, PersonGuide
from app.services.meetings.service import MeetingsService, meetings_counts
from app.services.system.models import ComponentStatus

from .overseer_nav import SectionRequest, page_url
from .rendering import drawer_state, with_query
from .routes.meetings import row_of, send_form

SECTIONS = ((None, {"overview": "Meetings", "people": "People"}),)

PAGE = page_url("services", "meetings")
PARTIALS = "/partials/overseer/meetings"
DRAWER_PARAM = "meeting"
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
    counts = await meetings_counts(req.db)
    rows = [
        row_of(m, with_query(PAGE, **{DRAWER_PARAM: str(m.id)}))
        | {"owner": m.owner_user_id}
        for m in await MeetingsService(req.db, None).list_meetings(LIMIT)
    ]
    wanted = req.query.get(DRAWER_PARAM) or ""
    return (
        drawer_state(
            DRAWER_PARAM, f"{PARTIALS}/{wanted}/drawer" if wanted.isdigit() else None
        )
        | {
            "figures": [
                {"label": "Meetings", "value": counts["meetings"]},
                {"label": "In a call now", "value": counts["in_call"]},
            ],
            "rows": rows,
        }
        | send_form(PARTIALS)
    )


async def _people(req: SectionRequest) -> dict[str, Any]:
    """Every owner's guides, latest written first, one open in the drawer
    when the address names it."""
    wanted = req.query.get(PERSON_PARAM) or ""
    return drawer_state(
        PERSON_PARAM, f"{PEOPLE_PARTIALS}/{wanted}/drawer" if wanted.isdigit() else None
    ) | {"rows": [_person_row(g) for g in await PeopleService(req.db, None).guides()]}


def _person_row(guide: PersonGuide) -> dict[str, Any]:
    return {
        "person": {
            "label": guide.person,
            "url": with_query(PEOPLE, **{PERSON_PARAM: str(guide.id)}),
        },
        "owner": guide.owner_user_id,
        "meetings": guide.meetings,
        "written": format_relative_time(guide.written_at),
    }


def guide_context(record: GuideRecord) -> dict[str, Any]:
    """One guide in the drawer: each part, its points with the lines they
    rest on, each line opening its meeting."""
    return {
        "record": record,
        "base": f"{PEOPLE_PARTIALS}/{record.guide.id}",
        "written": format_relative_time(record.guide.written_at),
        "said": {
            quote.id: {
                "when": said_when(quote.meeting_id, quote.at),
                "url": with_query(PAGE, **{DRAWER_PARAM: str(quote.meeting_id)}),
            }
            for section in record.sections
            for point in section.points
            for quote in point.quotes
        },
    }
