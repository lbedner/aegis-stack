"""Storing paper and finding it again.

The property the service is built around: ingest is idempotent, because
the storage key comes from the payload's own hash. A scanner that runs
twice, an email fetched again, and a user who double-clicks upload all
cost one document.
"""

from datetime import date

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.storage import FilesystemStorage, set_storage
from app.services.documents import DocumentService


@pytest.fixture
def svc(async_db_session: AsyncSession, tmp_path):
    set_storage(FilesystemStorage(tmp_path))
    yield DocumentService(async_db_session)
    set_storage(None)


class TestIngest:
    @pytest.mark.asyncio
    async def test_it_stores_the_bytes_and_records_where(self, svc) -> None:
        doc = await svc.ingest(
            b"%PDF-1.7 scan",
            title="Renewal request",
            kind="letter",
            media_type="application/pdf",
            owner_user_id=1,
        )

        assert doc.id is not None
        assert doc.storage_key.startswith("sha256/")
        assert doc.content_hash == doc.storage_key.rsplit("/", 1)[-1]
        assert doc.byte_size == len(b"%PDF-1.7 scan")
        assert await svc.content(doc.id, owner_user_id=1) == b"%PDF-1.7 scan"

    @pytest.mark.asyncio
    async def test_the_same_scan_twice_is_one_document(self, svc) -> None:
        """A scanner that runs twice must not double the file cabinet."""
        first = await svc.ingest(b"same bytes", title="Statement", owner_user_id=1)
        second = await svc.ingest(b"same bytes", title="Statement", owner_user_id=1)

        assert first.id == second.id
        rows, total = await svc.list_documents(owner_user_id=1)
        assert total == 1 and len(rows) == 1

    @pytest.mark.asyncio
    async def test_two_people_holding_the_same_form_are_two_documents(
        self, svc
    ) -> None:
        """Dedupe is per owner: the identical blank form filed by two
        people is two filings, not one shared row."""
        mine = await svc.ingest(b"blank form", title="Form", owner_user_id=1)
        theirs = await svc.ingest(b"blank form", title="Form", owner_user_id=2)

        assert mine.id != theirs.id

    @pytest.mark.asyncio
    async def test_empty_content_and_blank_titles_are_refused(self, svc) -> None:
        with pytest.raises(ValueError, match="content"):
            await svc.ingest(b"", title="Nothing")
        with pytest.raises(ValueError, match="title"):
            await svc.ingest(b"bytes", title="   ")

    @pytest.mark.asyncio
    async def test_an_unknown_kind_is_refused_before_the_database(self, svc) -> None:
        with pytest.raises(ValueError, match="kind"):
            await svc.ingest(b"bytes", title="Thing", kind="invoice-ish")

    @pytest.mark.asyncio
    async def test_the_documents_own_date_is_separate_from_arrival(self, svc) -> None:
        """A letter dated the 27th can land in the following month's post."""
        doc = await svc.ingest(
            b"letter",
            title="RFI",
            kind="letter",
            document_date=date(2026, 8, 27),
            owner_user_id=1,
        )

        assert doc.document_date == date(2026, 8, 27)
        assert doc.received_at is not None


class TestFinding:
    @pytest.mark.asyncio
    async def test_documents_can_be_narrowed_by_kind(self, svc) -> None:
        await svc.ingest(b"a letter", title="RFI", kind="letter", owner_user_id=1)
        await svc.ingest(
            b"a statement", title="July", kind="statement", owner_user_id=1
        )

        rows, total = await svc.list_documents(owner_user_id=1, kind="statement")

        assert total == 1 and rows[0].title == "July"

    @pytest.mark.asyncio
    async def test_tags_are_free_form_and_idempotent(self, svc) -> None:
        doc = await svc.ingest(b"bytes", title="Policy", owner_user_id=1)

        await svc.tag(doc.id, "medicaid")
        await svc.tag(doc.id, "medicaid")
        await svc.tag(doc.id, "2026")

        assert await svc.tags_for(doc.id) == ["2026", "medicaid"]

    @pytest.mark.asyncio
    async def test_documents_can_be_found_by_tag(self, svc) -> None:
        tagged = await svc.ingest(b"one", title="Tagged", owner_user_id=1)
        await svc.ingest(b"two", title="Untagged", owner_user_id=1)
        await svc.tag(tagged.id, "medicaid")

        rows, total = await svc.list_documents(owner_user_id=1, tag="medicaid")

        assert total == 1 and rows[0].id == tagged.id


class TestRetiring:
    @pytest.mark.asyncio
    async def test_delete_hides_the_row_but_keeps_the_bytes(self, svc) -> None:
        """Another document may hold the same content, and an audit trail
        that loses its subject is not an audit trail."""
        doc = await svc.ingest(b"bytes", title="Old", owner_user_id=1)
        key = doc.storage_key

        assert await svc.soft_delete(doc.id, owner_user_id=1) is True

        assert await svc.get(doc.id, owner_user_id=1) is None
        _rows, total = await svc.list_documents(owner_user_id=1)
        assert total == 0
        from app.core.storage import get_storage

        assert await get_storage().get(key) == b"bytes"


class TestConcurrency:
    @pytest.mark.asyncio
    async def test_the_database_enforces_dedupe_not_just_the_read(
        self, svc, async_db_session
    ) -> None:
        """Ingest reads before it writes, and two concurrent uploads can
        both miss that read. The partial unique index is what makes the
        second one fail rather than duplicate."""
        from sqlalchemy.exc import IntegrityError

        from app.services.documents.models import Document

        first = await svc.ingest(b"same paper", title="Scan", owner_user_id=1)
        smuggled = Document(
            owner_user_id=1,
            title="Scan again",
            kind="other",
            storage_key=first.storage_key,
            storage_backend=first.storage_backend,
            content_hash=first.content_hash,
            byte_size=first.byte_size,
        )
        async_db_session.add(smuggled)

        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_retiring_a_document_frees_the_content_to_be_refiled(
        self, svc
    ) -> None:
        """The unique index is partial: a soft-deleted document must not
        block filing the same paper again."""
        first = await svc.ingest(b"refiled", title="Old", owner_user_id=1)
        await svc.soft_delete(first.id, owner_user_id=1)

        second = await svc.ingest(b"refiled", title="New", owner_user_id=1)

        assert second.id != first.id


class TestUpdate:
    @pytest.mark.asyncio
    async def test_it_changes_what_the_paper_is_called_and_dated(self, svc) -> None:
        doc = await svc.ingest(b"letter", title="Untitled", owner_user_id=1)

        updated = await svc.update(
            doc.id,
            {
                "title": "Renewal request",
                "kind": "letter",
                "document_date": date(2026, 8, 27),
                "note": "Due Sep 8",
            },
            owner_user_id=1,
        )

        assert updated is not None
        assert updated.title == "Renewal request"
        assert updated.kind == "letter"
        assert updated.document_date == date(2026, 8, 27)
        assert updated.note == "Due Sep 8"
        assert updated.updated_at is not None

    @pytest.mark.asyncio
    async def test_an_unknown_kind_is_refused_before_the_row_changes(self, svc) -> None:
        doc = await svc.ingest(b"letter2", title="Kept", owner_user_id=1)

        with pytest.raises(ValueError, match="kind"):
            await svc.update(doc.id, {"kind": "invoice-ish"}, owner_user_id=1)

        assert (await svc.get(doc.id, owner_user_id=1)).kind == "other"

    @pytest.mark.asyncio
    async def test_someone_elses_document_is_not_yours_to_edit(self, svc) -> None:
        doc = await svc.ingest(b"theirs", title="Theirs", owner_user_id=2)

        assert await svc.update(doc.id, {"title": "Mine"}, owner_user_id=1) is None


class TestTags:
    @pytest.mark.asyncio
    async def test_untag_removes_only_that_label(self, svc) -> None:
        doc = await svc.ingest(b"tagged", title="T", owner_user_id=1)
        await svc.tag(doc.id, "medicaid")
        await svc.tag(doc.id, "2026")

        assert await svc.untag(doc.id, "medicaid") is True
        assert await svc.untag(doc.id, "medicaid") is False
        assert await svc.tags_for(doc.id) == ["2026"]

    @pytest.mark.asyncio
    async def test_tag_counts_group_by_label_for_the_owner(self, svc) -> None:
        a = await svc.ingest(b"a", title="A", owner_user_id=1)
        b = await svc.ingest(b"b", title="B", owner_user_id=1)
        other = await svc.ingest(b"c", title="C", owner_user_id=2)
        await svc.tag(a.id, "medicaid")
        await svc.tag(b.id, "medicaid")
        await svc.tag(b.id, "2026")
        await svc.tag(other.id, "medicaid")

        counts = await svc.tag_counts(owner_user_id=1)

        assert counts == [("medicaid", 2), ("2026", 1)]

    @pytest.mark.asyncio
    async def test_a_retired_document_stops_counting(self, svc) -> None:
        doc = await svc.ingest(b"gone", title="G", owner_user_id=1)
        await svc.tag(doc.id, "old")
        await svc.soft_delete(doc.id, owner_user_id=1)

        assert await svc.tag_counts(owner_user_id=1) == []


class TestSummary:
    @pytest.mark.asyncio
    async def test_it_counts_what_is_live_and_how_much_it_weighs(self, svc) -> None:
        await svc.ingest(b"12345", title="A", kind="letter", owner_user_id=1)
        await svc.ingest(b"1234567", title="B", kind="letter", owner_user_id=1)
        await svc.ingest(b"1", title="C", kind="statement", owner_user_id=1)
        gone = await svc.ingest(b"xx", title="D", kind="form", owner_user_id=1)
        await svc.soft_delete(gone.id, owner_user_id=1)

        summary = await svc.summary(owner_user_id=1)

        assert summary["total"] == 3
        assert summary["this_month"] == 3
        assert summary["bytes"] == 13
        assert summary["by_kind"] == {"letter": 2, "statement": 1}

    @pytest.mark.asyncio
    async def test_an_empty_store_is_zeros_not_nulls(self, svc) -> None:
        summary = await svc.summary(owner_user_id=99)

        assert summary == {"total": 0, "this_month": 0, "bytes": 0, "by_kind": {}}
