"""Reading a stored document once, per page, and keeping the result.

The property under test: a page is read exactly once. Text layers are
read for free; scans go to a vision reader; a re-run touches nothing and
calls no model unless forced; what cannot be read is recorded as unread,
with the reason, never as an empty string.
"""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.storage import FilesystemStorage, get_storage, set_storage
from app.services.documents import DocumentService
from app.services.documents.extraction import extract_document
from app.services.documents.queries import pages_for
from tests._pdf import pdf_bytes


@pytest.fixture
def svc(async_db_session: AsyncSession, tmp_path):
    set_storage(FilesystemStorage(tmp_path))
    yield DocumentService(async_db_session)
    set_storage(None)


class FakeVision:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, image: bytes, media_type: str) -> tuple[str, str]:
        self.calls += 1
        assert image[:8] == b"\x89PNG\r\n\x1a\n" or media_type != "image/png"
        return f"transcribed page {self.calls}", "fake-vision"


class TestTextLayer:
    @pytest.mark.asyncio
    async def test_pages_with_text_are_read_without_a_model(self, svc) -> None:
        doc = await svc.ingest(
            pdf_bytes(["Hello renewal request", "Second page of the letter"]),
            title="Letter",
            media_type="application/pdf",
            owner_user_id=1,
        )
        vision = FakeVision()

        result = await extract_document(svc.db, doc.id, owner_user_id=1, vision=vision)

        assert (result.read, result.unread) == (2, 0)
        assert vision.calls == 0
        pages = await pages_for(svc.db, doc.id)
        assert [p.page_number for p in pages] == [1, 2]
        assert all(p.method == "text_layer" and p.status == "read" for p in pages)
        assert "Hello renewal" in (pages[0].text or "")
        assert (await svc.get(doc.id, owner_user_id=1)).page_count == 2

    @pytest.mark.asyncio
    async def test_every_page_gets_a_stored_image_for_the_strip(self, svc) -> None:
        doc = await svc.ingest(
            pdf_bytes(["The only page of this one"]),
            title="L",
            media_type="application/pdf",
            owner_user_id=1,
        )

        await extract_document(svc.db, doc.id, owner_user_id=1, vision=None)

        (page,) = await pages_for(svc.db, doc.id)
        assert page.image_key
        png = await get_storage().get(page.image_key)
        assert png is not None and png[:8] == b"\x89PNG\r\n\x1a\n"


class TestScans:
    @pytest.mark.asyncio
    async def test_blank_text_layers_go_to_vision(self, svc) -> None:
        doc = await svc.ingest(
            pdf_bytes(["", ""]),
            title="Scan",
            media_type="application/pdf",
            owner_user_id=1,
        )
        vision = FakeVision()

        result = await extract_document(svc.db, doc.id, owner_user_id=1, vision=vision)

        assert (result.read, result.unread) == (2, 0)
        assert vision.calls == 2
        pages = await pages_for(svc.db, doc.id)
        assert all(p.method == "vision" and p.model == "fake-vision" for p in pages)
        assert pages[1].text == "transcribed page 2"

    @pytest.mark.asyncio
    async def test_a_rerun_reads_nothing_and_calls_no_model(self, svc) -> None:
        doc = await svc.ingest(
            pdf_bytes([""]), title="Scan", media_type="application/pdf", owner_user_id=1
        )
        vision = FakeVision()
        await extract_document(svc.db, doc.id, owner_user_id=1, vision=vision)

        again = await extract_document(svc.db, doc.id, owner_user_id=1, vision=vision)

        assert vision.calls == 1
        assert (again.read, again.unread, again.skipped) == (0, 0, 1)

    @pytest.mark.asyncio
    async def test_force_reads_again(self, svc) -> None:
        doc = await svc.ingest(
            pdf_bytes([""]), title="Scan", media_type="application/pdf", owner_user_id=1
        )
        vision = FakeVision()
        await extract_document(svc.db, doc.id, owner_user_id=1, vision=vision)

        await extract_document(
            svc.db, doc.id, owner_user_id=1, vision=vision, force=True
        )

        assert vision.calls == 2
        (page,) = await pages_for(svc.db, doc.id)
        assert page.text == "transcribed page 2"

    @pytest.mark.asyncio
    async def test_without_a_vision_reader_a_scan_is_unread_with_a_reason(
        self, svc
    ) -> None:
        doc = await svc.ingest(
            pdf_bytes([""]), title="Scan", media_type="application/pdf", owner_user_id=1
        )

        result = await extract_document(svc.db, doc.id, owner_user_id=1, vision=None)

        assert (result.read, result.unread) == (0, 1)
        (page,) = await pages_for(svc.db, doc.id)
        assert page.status == "unread" and page.method == "none"
        assert page.text is None
        assert "vision" in (page.detail or "").lower()

    @pytest.mark.asyncio
    async def test_a_rerun_retries_only_the_unread_pages(self, svc) -> None:
        doc = await svc.ingest(
            pdf_bytes(["A page with a text layer", ""]),
            title="Mixed",
            media_type="application/pdf",
            owner_user_id=1,
        )
        await extract_document(svc.db, doc.id, owner_user_id=1, vision=None)
        vision = FakeVision()

        result = await extract_document(svc.db, doc.id, owner_user_id=1, vision=vision)

        assert vision.calls == 1
        assert (result.read, result.skipped) == (1, 1)


class TestFailures:
    @pytest.mark.asyncio
    async def test_a_model_error_leaves_the_page_unread_with_the_reason(
        self, svc
    ) -> None:
        async def broken(image: bytes, media_type: str) -> tuple[str, str]:
            raise RuntimeError("model 'llama3.2:3b' not found")

        doc = await svc.ingest(
            pdf_bytes(["", "A second page with real text on it"]),
            title="Scan",
            media_type="application/pdf",
            owner_user_id=1,
        )

        result = await extract_document(svc.db, doc.id, owner_user_id=1, vision=broken)

        assert (result.read, result.unread) == (1, 1)
        pages = await pages_for(svc.db, doc.id)
        assert pages[0].status == "unread" and "not found" in (pages[0].detail or "")
        assert pages[1].status == "read"


class TestPng:
    def test_only_rgb_and_rgba_buffers_are_encoded(self) -> None:
        from app.services.documents.pdf import encode_png

        assert encode_png(1, 1, b"\x00\x00\x00\xff", 4, 4)[:8] == b"\x89PNG\r\n\x1a\n"
        with pytest.raises(ValueError, match="channels"):
            encode_png(1, 1, b"\x00", 1, 1)


class TestOtherMedia:
    @pytest.mark.asyncio
    async def test_an_image_document_is_one_page_read_by_vision(self, svc) -> None:
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
        doc = await svc.ingest(
            png, title="Photo", media_type="image/png", owner_user_id=1
        )
        vision = FakeVision()

        result = await extract_document(svc.db, doc.id, owner_user_id=1, vision=vision)

        assert (result.read, result.unread) == (1, 0)
        (page,) = await pages_for(svc.db, doc.id)
        assert page.method == "vision" and page.image_key == doc.storage_key

    @pytest.mark.asyncio
    async def test_an_unsupported_type_is_one_unread_page(self, svc) -> None:
        doc = await svc.ingest(
            b"hello", title="Note", media_type="text/plain", owner_user_id=1
        )

        result = await extract_document(
            svc.db, doc.id, owner_user_id=1, vision=FakeVision()
        )

        assert (result.read, result.unread) == (0, 1)
        (page,) = await pages_for(svc.db, doc.id)
        assert "unsupported" in (page.detail or "").lower()
