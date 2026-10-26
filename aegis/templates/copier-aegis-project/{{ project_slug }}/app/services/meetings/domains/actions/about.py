"""What a line of a call is about, as Illiana says it to whoever asked
(``ask_ai.about``): from the lines either side of it, to the one who asked
alone. Nothing is kept."""

from typing import TYPE_CHECKING

from app.core.discovery import optional
from app.services.meetings.domains.actions.prompt import around
from app.services.meetings.domains.actions.registry import ASK_ILLIANA
from app.services.meetings.domains.moments import queries as moments_queries
from app.services.meetings.models import LineAbout

if TYPE_CHECKING:
    from app.services.meetings.service import MeetingsService


def asks_about() -> bool:
    """Whether a line can be asked what it is about: where the stack has
    Illiana."""
    return optional(ASK_ILLIANA, "about") is not None


async def line_about(
    svc: "MeetingsService", meeting_id: int, line_id: int
) -> LineAbout | None:
    """What a line of one of ``svc``'s meetings is about, as Illiana says it
    to the meeting's owner, from the lines either side of it; asked through
    every owner's meetings (Overseer), as an admin. None where the stack has
    no Illiana or the meeting no such line."""
    ask = optional(ASK_ILLIANA, "about")
    if ask is None:
        return None
    meeting = await svc.get(meeting_id)
    found = around(await moments_queries.said(svc.db, meeting_id), line_id)
    if found is None:
        return None
    admin = True if svc.owner_user_id is None else None
    return await ask(*found, owner_user_id=meeting.owner_user_id, admin=admin)
