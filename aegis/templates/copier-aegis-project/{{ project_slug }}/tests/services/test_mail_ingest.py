"""Reading a file of mail into documents.

The messages are already parsed by then; this is what the pipeline does
with them. Every session is short - the parse and the extraction
dispatch both happen holding nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import OpenSession
from app.services.documents.domains.extraction import dispatch
from app.services.documents.models import Document, DocumentPage
from app.services.documents.service import DocumentService
from app.services.mail import ingest
from app.services.mail.models import MailAttachment, MailBatch, MailMessage
from app.services.mail.parse import NotMailError
from tests._mbox import PDF, eml_bytes, mbox_bytes, message
from tests._session import rows_of

pytestmark = pytest.mark.usefixtures("no_mail_hooks")


async def papers(db: AsyncSession) -> list[Document]:
    return [d for d in await rows_of(db, Document) if d.kind != "letter"]


class TestEveryMessageLandsOnce:
    async def test_messages_become_rows(
        self,
        async_db_session: AsyncSession,
        open_session: OpenSession,
        dispatched: list[int],
    ) -> None:
        data = mbox_bytes([message(subject="one"), message(subject="two")])
        result = await ingest.ingest_mail(
            open_session, data=data, file_name="export.mbox"
        )

        assert result.messages_total == 2 and result.messages_new == 2
        assert [m.subject for m in await rows_of(async_db_session, MailMessage)] == [
            "one",
            "two",
        ]

    @pytest.mark.queryspy(allow_n_plus_one=True)  # two imports, one read each
    async def test_an_overlapping_export_adds_only_what_is_new(
        self,
        async_db_session: AsyncSession,
        open_session: OpenSession,
        dispatched: list[int],
    ) -> None:
        """An export is re-run; the new file holds most of the old one. Each
        message lands once, on Message-ID, whatever file it came in."""
        old = message(subject="old", message_id="<old@example.com>")
        await ingest.ingest_mail(
            open_session, data=mbox_bytes([old]), file_name="first.mbox"
        )

        new = message(subject="new", message_id="<new@example.com>")
        result = await ingest.ingest_mail(
            open_session, data=mbox_bytes([old, new]), file_name="second.mbox"
        )

        assert (result.messages_new, result.messages_duplicate) == (1, 1)
        assert len(await rows_of(async_db_session, MailMessage)) == 2

    async def test_one_message_twice_in_a_file_is_one_row(
        self,
        async_db_session: AsyncSession,
        open_session: OpenSession,
        dispatched: list[int],
    ) -> None:
        """The same message under two labels: the lookup is per chunk, so
        the chunk has to remember what it filed itself."""
        twice = message(message_id="<same@example.com>")
        result = await ingest.ingest_mail(
            open_session, data=mbox_bytes([twice, twice]), file_name="x.mbox"
        )

        assert (result.messages_new, result.messages_duplicate) == (1, 1)
        assert len(await rows_of(async_db_session, MailMessage)) == 1

    @pytest.mark.queryspy(allow_n_plus_one=True)  # two imports, one read each
    async def test_the_same_bytes_are_answered_with_the_batch_that_read_them(
        self,
        async_db_session: AsyncSession,
        open_session: OpenSession,
        dispatched: list[int],
    ) -> None:
        data = mbox_bytes([message()])
        first = await ingest.ingest_mail(open_session, data=data, file_name="a.mbox")
        again = await ingest.ingest_mail(open_session, data=data, file_name="b.mbox")

        assert again.batch_id == first.batch_id
        assert again.messages_new == 0
        assert len(await rows_of(async_db_session, MailBatch)) == 1

    async def test_a_file_that_is_not_mail_writes_nothing(
        self,
        async_db_session: AsyncSession,
        open_session: OpenSession,
        dispatched: list[int],
    ) -> None:
        with pytest.raises(NotMailError):
            await ingest.ingest_mail(open_session, data=b"%PDF-1.4", file_name="x.pdf")
        assert await rows_of(async_db_session, MailBatch) == []

    @pytest.mark.queryspy(allow_n_plus_one=True)  # two imports, one read each
    async def test_a_run_that_stops_fails_its_batch_and_the_same_bytes_retry(
        self,
        async_db_session: AsyncSession,
        open_session: OpenSession,
        dispatched: list[int],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A batch left 'processing' answers every later upload of the same
        bytes, so the file could never be read again (a real Postgres
        import, 2026-11-20). The run that stops says so, in the app's own
        words, and the next upload picks the batch back up."""
        data = mbox_bytes([message(subject="one"), message(subject="two")])
        filing = ingest._file_one

        async def broken(*args: Any, **kwargs: Any) -> MailMessage:
            raise RuntimeError("SELECT secret FROM somewhere")

        monkeypatch.setattr(ingest, "_file_one", broken)
        with pytest.raises(RuntimeError):
            await ingest.ingest_mail(open_session, data=data, file_name="a.mbox")
        [batch] = await rows_of(async_db_session, MailBatch)
        assert batch.status == "failed"
        assert batch.error and "SELECT" not in batch.error

        monkeypatch.setattr(ingest, "_file_one", filing)
        again = await ingest.ingest_mail(open_session, data=data, file_name="a.mbox")

        assert again.batch_id == batch.id and again.messages_new == 2
        [batch] = await rows_of(async_db_session, MailBatch)
        assert batch.status == "done" and batch.error is None


class TestAnAttachmentBecomesPaper:
    async def test_it_is_filed_dated_and_marked_as_mail(
        self,
        async_db_session: AsyncSession,
        open_session: OpenSession,
        dispatched: list[int],
    ) -> None:
        sent = datetime(2026, 8, 27, 9, 5, tzinfo=UTC)
        data = eml_bytes(
            message(sent=sent, attachments=[("statement.pdf", "application/pdf", PDF)])
        )
        result = await ingest.ingest_mail(
            open_session, data=data, file_name="claim.eml"
        )

        [paper] = await papers(async_db_session)
        assert paper.title == "statement.pdf"
        assert paper.source == "mail" and paper.channel == "email"
        # The letter's own date, not the day it was imported.
        assert paper.document_date == sent.date()
        assert result.attachments_filed == 1

        [link] = await rows_of(async_db_session, MailAttachment)
        assert link.document_id == paper.id and link.filename == "statement.pdf"
        # And it is read, as any upload is.
        assert dispatched == [paper.id]

    async def test_the_same_paper_on_two_messages_is_one_document(
        self,
        async_db_session: AsyncSession,
        open_session: OpenSession,
        dispatched: list[int],
    ) -> None:
        """A statement forwarded twice is one statement: filed once, both
        messages pointing at it, read once."""
        twice = [
            message(subject="first", attachments=[("s.pdf", "application/pdf", PDF)]),
            message(
                subject="forwarded", attachments=[("s.pdf", "application/pdf", PDF)]
            ),
        ]
        result = await ingest.ingest_mail(
            open_session, data=mbox_bytes(twice), file_name="x.mbox"
        )

        [paper] = await papers(async_db_session)
        assert paper.title == "s.pdf"
        assert len(await rows_of(async_db_session, MailAttachment)) == 2
        assert (result.attachments_filed, result.attachments_duplicate) == (1, 1)
        assert dispatched == [paper.id]

    async def test_paper_already_filed_is_not_read_again(
        self,
        async_db_session: AsyncSession,
        open_session: OpenSession,
        dispatched: list[int],
    ) -> None:
        already = await DocumentService(async_db_session).ingest(PDF, title="s.pdf")
        data = eml_bytes(message(attachments=[("s.pdf", "application/pdf", PDF)]))
        result = await ingest.ingest_mail(open_session, data=data, file_name="x.eml")

        assert result.attachments_duplicate == 1
        [link] = await rows_of(async_db_session, MailAttachment)
        assert link.document_id == already.id
        assert dispatched == []

    async def test_a_down_worker_never_fails_the_import(
        self,
        async_db_session: AsyncSession,
        open_session: OpenSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The bytes are the valuable thing: a read that cannot start is
        offered again from the document, never a lost import."""

        async def down(document_id: int, *, owner_user_id: Any, force: bool) -> str:
            raise ConnectionError("no worker")

        monkeypatch.setattr(dispatch, "start_extraction", down)
        data = eml_bytes(message(attachments=[("s.pdf", "application/pdf", PDF)]))

        result = await ingest.ingest_mail(open_session, data=data, file_name="x.eml")

        assert result.attachments_filed == 1
        assert len(await papers(async_db_session)) == 1


class TestItSaysWhatItIsDoing:
    async def test_progress_reaches_the_label(
        self,
        async_db_session: AsyncSession,
        open_session: OpenSession,
        dispatched: list[int],
    ) -> None:
        said: list[str] = []
        data = mbox_bytes([message(), message()])

        await ingest.ingest_mail(
            open_session, data=data, file_name="export.mbox", report=said.append
        )

        # Before the work, with a count, and the batch's own record agrees.
        assert any("2" in line for line in said), said
        [batch] = await rows_of(async_db_session, MailBatch)
        assert batch.status == "done" and batch.finished_at is not None
        assert batch.messages_total == 2


class TestTheMessageIsALetter:
    async def test_the_body_becomes_a_letter_already_read(
        self,
        async_db_session: AsyncSession,
        open_session: OpenSession,
        dispatched: list[int],
    ) -> None:
        sent = datetime(2026, 8, 27, 9, 5, tzinfo=UTC)
        data = eml_bytes(
            message(
                sender="Example Insurer <Claims@Insurer.Example>",
                subject="Your claim has been processed",
                body="Your claim was paid. Call 800-555-0100 with questions.",
                sent=sent,
            )
        )
        result = await ingest.ingest_mail(
            open_session, data=data, file_name="claim.eml"
        )

        [letter] = await rows_of(async_db_session, Document)
        assert (letter.kind, letter.title) == (
            "letter",
            "Your claim has been processed",
        )
        assert letter.source == "mail" and letter.channel == "email"
        assert letter.document_date == sent.date()
        [page] = await rows_of(async_db_session, DocumentPage)
        # Already read: the mail IS text, so there is nothing to hand a reader.
        assert (page.document_id, page.status, page.method) == (
            letter.id,
            "read",
            "mail",
        )
        lines = (page.text or "").splitlines()
        # The header is the letterhead: who wrote, about what, and when.
        assert lines[0] == "From: Example Insurer <claims@insurer.example>"
        assert "Your claim was paid." in (page.text or "")
        [row] = await rows_of(async_db_session, MailMessage)
        assert row.document_id == letter.id
        assert result.letters_filed == 1
        assert dispatched == []

    async def test_an_empty_body_files_no_letter(
        self,
        async_db_session: AsyncSession,
        open_session: OpenSession,
        dispatched: list[int],
    ) -> None:
        data = eml_bytes(
            message(body="", attachments=[("s.pdf", "application/pdf", PDF)])
        )
        result = await ingest.ingest_mail(open_session, data=data, file_name="x.eml")
        assert result.letters_filed == 0
        assert [d.title for d in await rows_of(async_db_session, Document)] == ["s.pdf"]

    async def test_the_batch_counts_letters(
        self,
        async_db_session: AsyncSession,
        open_session: OpenSession,
        dispatched: list[int],
    ) -> None:
        data = mbox_bytes([message(body="one"), message(body="two")])
        await ingest.ingest_mail(open_session, data=data, file_name="x.mbox")
        [batch] = await rows_of(async_db_session, MailBatch)
        assert batch.letters_filed == 2


class TestTheSeam:
    """Who a sender is belongs to whatever consumes the messages (a contacts
    service), not to the import: each batch hands what it newly filed to
    every hook registered on ``register_messages_filed``, once."""

    async def test_a_registered_hook_is_given_the_new_messages(
        self,
        open_session: OpenSession,
        dispatched: list[int],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(ingest, "_filed_hooks", [])
        told: list[tuple[list[str], int | None]] = []

        async def hook(
            db: AsyncSession, rows: list[MailMessage], owner_user_id: int | None
        ) -> None:
            assert all(row.id is not None for row in rows)
            told.append(([row.message_id for row in rows], owner_user_id))

        ingest.register_messages_filed(hook)
        a = message(message_id="<a@example.com>")
        b = message(message_id="<b@example.com>")
        await ingest.ingest_mail(
            open_session, data=mbox_bytes([a, a, b]), file_name="x.mbox"
        )

        assert told == [(["<a@example.com>", "<b@example.com>"], None)]

    async def test_a_services_mail_hooks_module_is_loaded_first(
        self,
        open_session: OpenSession,
        dispatched: list[int],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A hook registers in its own service's ``mail_hooks.py``, found on
        disk as tools and change types are: the worker, which files a
        queued import, imports nothing else of that service, so a hook
        registered anywhere else was never there to call."""
        monkeypatch.setattr(ingest, "_filed_hooks", [])
        told: list[str] = []

        async def hook(
            db: AsyncSession, rows: list[MailMessage], owner_user_id: int | None
        ) -> None:
            told.extend(row.message_id for row in rows)

        def discovered(package: Any, name: str) -> list[Any]:
            assert name == "mail_hooks"
            if hook not in ingest._filed_hooks:
                ingest.register_messages_filed(hook)
            return []

        monkeypatch.setattr(ingest, "import_modules_named", discovered)
        await ingest.ingest_mail(
            open_session,
            data=mbox_bytes([message(message_id="<a@example.com>")]),
            file_name="x.mbox",
        )

        assert told == ["<a@example.com>"]

    async def test_a_failing_hook_never_fails_the_import(
        self,
        async_db_session: AsyncSession,
        open_session: OpenSession,
        dispatched: list[int],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The messages are filed by then; a consumer that breaks is its
        own failure, logged, not the import's."""
        monkeypatch.setattr(ingest, "_filed_hooks", [])

        async def broken(
            db: AsyncSession, rows: list[MailMessage], owner_user_id: int | None
        ) -> None:
            raise RuntimeError("consumer down")

        ingest.register_messages_filed(broken)
        result = await ingest.ingest_mail(
            open_session, data=eml_bytes(message()), file_name="x.eml"
        )

        assert result.messages_new == 1
        [batch] = await rows_of(async_db_session, MailBatch)
        assert batch.status == "done"
