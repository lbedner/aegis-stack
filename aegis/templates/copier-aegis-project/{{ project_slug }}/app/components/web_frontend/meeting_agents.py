"""The meeting agents on the htmx pages: the choice of agent the bot is
sent as (the Meetings page's send form and Overseer's), which agent each
meeting was, and Overseer > Meetings > Agents, where each says who it is,
whether its sign-in still works, which meeting it is in now and who owns
a meeting it joins from its calendar that nobody on the invite owns. An
agent is made by signing it in: ``meetings login --agent``.
"""

from collections.abc import Callable
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.domains.accounts.service import (
    NOT_SIGNED_IN,
    SIGNED_IN,
    AgentRow,
    overview,
)
from app.services.meetings.domains.calendar.owners import Owner, owners
from app.services.meetings.models import BotAccount

from .rendering import status_cell

# A sign-in that has run out, or one that cannot be read: error.
TONES = {SIGNED_IN: "ok", NOT_SIGNED_IN: "warn"}


def agent_options(every: list[BotAccount]) -> list[dict[str, str]]:
    """The send form's choice of agent (``agents``): none while there is
    only the one."""
    if len(every) < 2:
        return []
    return [{"id": a.name, "name": f"{a.display_name} ({a.name})"} for a in every]


def owner_options(every: list[Owner]) -> list[dict[str, Any]]:
    """Everyone a meeting can be given to, as a picker's choices."""
    return [{"id": owner.id, "name": owner.email} for owner in every]


async def agents_context(
    db: AsyncSession, opened: Callable[[int], str]
) -> dict[str, Any]:
    """Every agent as a row, each meeting it is in now linked to
    ``opened(meeting id)``, and everyone its calendar meetings can go to
    (nobody without auth)."""
    return {
        "rows": [_row(row, opened) for row in await overview(db)],
        "owners": owner_options(await owners(db)),
    }


def _row(row: AgentRow, opened: Callable[[int], str]) -> dict[str, Any]:
    account = row.account
    return {
        "agent": account.name,
        "joins_as": account.display_name,
        "email": account.email,
        "sign_in": status_cell(row.sign_in, TONES.get(row.sign_in, "error")),
        "in_now": [{"label": f"Meeting {m}", "url": opened(m)} for m in row.in_now],
        "default_owner": {"agent": account.name, "id": account.default_owner_id},
    }
