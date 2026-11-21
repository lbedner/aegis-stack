"""The ``arrivals`` tool reads the Mail page's rows.

The tool opens its own session in production; tests point that at the
test's session so what was ingested is visible and rolled back.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import OpenSession
from app.core.tools import registered_tool_names
from app.services.mail import ingest, pull
from app.services.mail.arrivals import arrivals as page_arrivals
from app.services.mail.models import MailMessage
import app.services.mail.tools as mail_tools
from tests._mbox import PDF, eml_bytes, mbox_bytes, message
from tests._secret_settings import secret_settings
from tests._session import opens, rows_of

pytestmark = pytest.mark.usefixtures("no_mail_hooks")


@pytest.fixture(autouse=True)
def _tools_use_test_session(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mail_tools, "get_async_session", opens(async_db_session))


def test_arrivals_registers_on_import() -> None:
    assert "arrivals" in registered_tool_names()


@pytest.mark.queryspy(allow_n_plus_one=True)  # the tool's read, then the page's
async def test_arrivals_says_what_the_page_says(
    async_db_session: AsyncSession, open_session: OpenSession, dispatched: list[int]
) -> None:
    data = mbox_bytes(
        [
            message(
                sender="Example Insurer <claims@insurer.example>",
                subject="Your statement",
                attachments=[("statement.pdf", "application/pdf", PDF)],
            ),
            message(sender="County <intake@county.example>", subject="Renewal notice"),
            message(sender="News <news@shop.example>", subject="Weekly deals", body=""),
        ]
    )
    await ingest.ingest_mail(open_session, data=data, file_name="export.mbox")

    with secret_settings(pull.HOST, pull.USER, pull.FOLDER, pull.PASSWORD):
        [day] = (await mail_tools.arrivals()).days
    [page_day] = await page_arrivals(async_db_session, owner_user_id=None)

    assert day == page_day
    assert {m.became for m in day.messages} == {
        "letter + 1 attachment",
        "letter",
        "nothing: empty message, no attachments",
    }


async def test_days_one_returns_the_latest_day_when_today_is_empty(
    async_db_session: AsyncSession, open_session: OpenSession, dispatched: list[int]
) -> None:
    await ingest.ingest_mail(
        open_session, data=eml_bytes(message(subject="yesterday")), file_name="a.eml"
    )
    [row] = await rows_of(async_db_session, MailMessage)
    row.created_at = datetime.now(UTC) - timedelta(days=1)
    async_db_session.add(row)
    await async_db_session.flush()

    with secret_settings(pull.HOST, pull.USER, pull.FOLDER, pull.PASSWORD):
        days = (await mail_tools.arrivals(days=1)).days
    assert [m.subject for d in days for m in d.messages] == ["yesterday"]
    assert days[0].date == row.created_at.date()


async def test_without_a_mailbox_the_tool_says_none() -> None:
    """The page's status line and the assistant's read the same thing:
    which mailbox is pulled, or that none is."""
    with secret_settings(pull.HOST, pull.USER, pull.FOLDER, pull.PASSWORD):
        assert (await mail_tools.arrivals()).mailbox is None


def test_overseers_chat_is_granted_the_arrivals(db_session: Session) -> None:
    """Registering a tool grants it to nobody: the default agent, whose
    answers Overseer's chat gives, is handed it when the agents are seeded
    (asked "what came in by mail?", it had no such tool, 2026-11-20)."""
    fixtures = pytest.importorskip("app.services.ai.fixtures.agent_fixtures")
    from app.services.ai.models.agents import Agent

    fixtures.load_agent_fixtures(db_session)  # the tool rows, from the registry
    mail_tools.load_mail_agent_fixtures(db_session)

    assistant = db_session.exec(
        select(Agent).where(Agent.slug == fixtures.DEFAULT_AGENT_SLUG)
    ).one()
    assert "arrivals" in {t.name for t in assistant.tools}
