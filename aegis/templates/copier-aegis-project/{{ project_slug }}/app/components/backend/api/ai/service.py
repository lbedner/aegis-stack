"""The one AIService the /ai routes share, and the lift every way in to
it runs before a turn (``lifted_turn``).

Its own module because every sub-router needs it and the router that
assembles them imports those sub-routers - so it cannot be the one
holding the singleton.
"""

from app.core.config import settings
from app.services.ai.service import (
    AIService,
    ChatAttachment,
    LiftedTurn,
    keeps_pastes,
    lift_turn,
)

ai_service = AIService(settings)


async def lifted_turn(
    message: str,
    attachments: list[ChatAttachment] | None,
    user_id: str,
    owner_user_id: int | None = None,
) -> LiftedTurn | None:
    """The turn lifted before it runs (``lift_turn``): its documents read
    and its walls of pasted text kept apart, in a short session of its
    own, so none is held across the streamed answer. None where nobody's
    turn is kept (``keeps_pastes``): it goes as it came. The browser, the
    API and the CLI each hand the result to the turn as ``lifted``."""
    if not keeps_pastes(user_id):
        return None
    from app.core.db import get_async_session

    async with get_async_session() as session:
        return await lift_turn(session, message, attachments, user_id, owner_user_id)
