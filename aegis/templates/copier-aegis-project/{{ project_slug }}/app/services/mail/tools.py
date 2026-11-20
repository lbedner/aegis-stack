"""Mail's tool (``app.core.tools.load_tools``): what came in, as the Mail
page sees it. One call, the same rows the page reads, so the page and the
assistant cannot disagree about what arrived or what it became. Read-only.
"""

from __future__ import annotations

from pydantic import BaseModel
from sqlmodel import Session

from app.core.db import get_async_session
from app.core.figures import FIGURES
from app.core.tools import current_owner_user_id, register_tool
from app.services.mail.arrivals import Day
from app.services.mail.arrivals import arrivals as _arrivals
from app.services.mail.pull import MailboxStatus, mailbox_status


class Arrivals(BaseModel):
    """What the tool answers: the mailbox the app pulls, and the days."""

    model_config = FIGURES

    mailbox: MailboxStatus | None
    days: list[Day]


async def arrivals(days: int = 1) -> Arrivals:
    """What came in by mail, grouped by the day it arrived, newest first.

    Args:
        days: How many of the most recent days WITH mail to report. The
            default 1 is "today, or the most recent day anything came in":
            when nothing arrived today the latest day is returned instead,
            so the answer is never an empty "nothing" while recent mail
            exists. Say which date you are reporting.

    Returns 'days': a list of {'date': 'YYYY-MM-DD', 'messages': [...]}.
    Each message carries 'id', 'received_at', 'sent_at', 'sender',
    'address', 'subject', 'letter_id' and 'attachments' (each a
    document's 'document_id' and 'filename'), 'became' - the one sentence saying what
    the message turned into, or why nothing - and 'via': the file it was
    dropped in, or "pulled from <mailbox>". Repeat 'became' to the user
    as written; do not reword it.

    Also 'mailbox': the mailbox the app pulls itself, with 'label',
    'pulled_at' and 'error' (the one line saying why the last pull
    failed, else null) - or null when no mailbox is set. When 'error'
    is set, say so: nothing new is a failing pull, not a quiet inbox.
    """
    async with get_async_session() as db:
        found = await _arrivals(db, owner_user_id=current_owner_user_id.get())
        mailbox = await mailbox_status(db)
    return Arrivals(mailbox=mailbox, days=found[: max(days, 1)])


def load_mail_agent_fixtures(session: Session) -> dict[str, int]:
    """Grant the default agent, Overseer's chat, the arrivals tool: a
    registered tool is granted to nobody. Additive, as every seed."""
    # Here, not at the top: the AI fixtures package loads these seeds.
    from app.services.ai.fixtures.agent_fixtures import (
        DEFAULT_AGENT_SLUG,
        attach_tools,
    )

    granted = attach_tools(session, DEFAULT_AGENT_SLUG, ["arrivals"])
    if granted:
        session.commit()
    return {"mail_tool_links": granted}


register_tool(
    "arrivals",
    arrivals,
    description="What came in by mail and what each message became, by day",
    effect="read",
)
