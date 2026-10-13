"""Context for the Overseer Meetings page: every owner's meetings, for the
admin, and the bot sent from here. A row opens one meeting in the drawer, drawn from the Meetings
page's own context (``routes.meetings.meeting_context``): its notes and
transcript, with the bot asked to leave or the meeting deleted from
there. Registered only in projects with the meetings service (see
``overseer_sections``).
"""

from typing import Any

from app.services.meetings.service import MeetingsService, meetings_counts
from app.services.system.models import ComponentStatus

from .overseer_nav import SectionRequest, page_url
from .rendering import drawer_state, with_query
from .routes.meetings import row_of, send_form

SECTIONS = ((None, {"overview": "Meetings"}),)

PAGE = page_url("services", "meetings")
PARTIALS = "/partials/overseer/meetings"
DRAWER_PARAM = "meeting"
LIMIT = 200


async def section_context(
    section: str, meetings: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    """Every owner's meetings, newest first, one open in the drawer when
    the address names it."""
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
