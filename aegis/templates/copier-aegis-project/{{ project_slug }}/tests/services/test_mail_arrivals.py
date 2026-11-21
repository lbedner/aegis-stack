"""What came in: one answer for the page and for the chat.

What is waiting is a queue's question; this is what ARRIVED. The rows
say, per message: when, from whom, what it became - a letter, its
attachments - and, when nothing, why. The page and the assistant read the
same rows, so they cannot disagree.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import OpenSession
from app.services.mail import ingest
from app.services.mail.arrivals import arrivals
from app.services.mail.models import MailMessage
from tests._mbox import PDF, eml_bytes, mbox_bytes, message
from tests._session import rows_of

pytestmark = pytest.mark.usefixtures("no_mail_hooks")


class TestWhatCameIn:
    async def test_three_mails_and_what_each_became(
        self,
        async_db_session: AsyncSession,
        open_session: OpenSession,
        dispatched: list[int],
    ) -> None:
        """A statement with an attachment, a letter with none, and a
        newsletter with nothing in it: each says what it became."""
        data = mbox_bytes(
            [
                message(
                    sender="Example Insurer <claims@insurer.example>",
                    subject="Your statement",
                    attachments=[("statement.pdf", "application/pdf", PDF)],
                ),
                message(
                    sender="County <intake@county.example>", subject="Renewal notice"
                ),
                message(
                    sender="News <news@shop.example>", subject="Weekly deals", body=""
                ),
            ]
        )
        await ingest.ingest_mail(open_session, data=data, file_name="export.mbox")

        [day] = await arrivals(async_db_session, owner_user_id=None)
        rows = {row.subject: row for row in day.messages}
        assert set(rows) == {"Your statement", "Renewal notice", "Weekly deals"}

        statement = rows["Your statement"]
        assert (statement.sender, statement.address) == (
            "Example Insurer",
            "claims@insurer.example",
        )
        assert statement.letter_id is not None
        assert [a.filename for a in statement.attachments] == ["statement.pdf"]
        assert statement.became == "letter + 1 attachment"
        assert statement.via == "export.mbox"

        notice = rows["Renewal notice"]
        assert notice.became == "letter" and notice.attachments == []

        deals = rows["Weekly deals"]
        assert deals.letter_id is None and deals.attachments == []
        assert deals.became == "nothing: empty message, no attachments"

    @pytest.mark.queryspy(allow_n_plus_one=True)  # two imports, one read each
    async def test_days_are_newest_first_and_only_this_owners(
        self,
        async_db_session: AsyncSession,
        open_session: OpenSession,
        dispatched: list[int],
    ) -> None:
        db = async_db_session
        await ingest.ingest_mail(
            open_session, data=eml_bytes(message(subject="today")), file_name="a.eml"
        )
        await ingest.ingest_mail(
            open_session,
            data=eml_bytes(message(subject="yesterday", message_id="<y@x.example>")),
            file_name="b.eml",
        )
        [old] = [r for r in await rows_of(db, MailMessage) if r.subject == "yesterday"]
        old.created_at = datetime.now(UTC) - timedelta(days=1)
        db.add(old)
        await db.flush()

        days = await arrivals(db, owner_user_id=None)
        assert [d.messages[0].subject for d in days] == ["today", "yesterday"]
        assert days[0].date > days[1].date
        assert await arrivals(db, owner_user_id=99) == []
