"""Reading a stored document once, per page, and keeping the result.

The property under test: a page is read exactly once. Text layers are
read for free; scans go to a vision reader; a re-run touches nothing and
calls no model unless forced; what cannot be read is recorded as unread,
with the reason, never as an empty string.
"""

import asyncio

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.storage import FilesystemStorage, get_storage, set_storage
from app.services.documents import DocumentService
from app.services.documents.domains.extraction.pages import extract_document
from app.services.documents.queries import pages_for
from tests._pdf import pdf_bytes


@pytest.fixture
def svc(async_db_session: AsyncSession, tmp_path):
    set_storage(FilesystemStorage(tmp_path))
    yield DocumentService(async_db_session)
    set_storage(None)


class FakeVision:
    """A stand-in reader that numbers its answers by call.

    Pages are read concurrently, so call order is not page order and the
    number in the text says nothing about which page it came back for.
    The real reader transcribes the image it is handed, which is what
    ties text to page; a fake over two blank pages cannot tell them
    apart at all, since their renders are byte-identical.
    """

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
        # Both transcriptions landed, one per page. Which page got which
        # is the fake's call counter, not a property of the code - see
        # FakeVision.
        assert sorted(p.text or "" for p in pages) == [
            "transcribed page 1",
            "transcribed page 2",
        ]

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
        from app.services.documents.domains.extraction.pdf import encode_png

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


class TestEachPageLandsOnItsOwn:
    """One transaction across a whole scan held the write lock for every
    model call of every page - minutes - and two readings of one file
    deadlocked. A page commits as soon as it is read.

    This used to assert strict alternation: each model call sees exactly
    one more commit than the last. That was true while the pages were
    read one at a time and is not true now that they overlap - the third
    call can begin before the second page has landed, and which pages
    are in flight together is a matter of timing. What has to stay true
    is the thing the alternation was standing in for: one transaction
    per page, not one per document.
    """

    async def test_each_page_lands_in_its_own_transaction(self, svc) -> None:
        """More pages than the concurrency limit, on purpose.

        With everything in flight at once there is nothing to observe:
        every call starts before any page lands. Eight pages against a
        limit of four means the last batch can only begin after earlier
        pages have committed, so a version that gathered them all and
        wrote at the end is visibly different - its last call still sees
        only the one commit that ended the read.
        """
        from app.services.documents.domains.extraction.pages import PAGE_CONCURRENCY
        from tests._pdf import pdf_bytes

        pages = PAGE_CONCURRENCY * 2
        doc = await svc.ingest(
            pdf_bytes([""] * pages),
            title="scan.pdf",
            media_type="application/pdf",
            owner_user_id=1,
        )
        commits_at_call: list[int] = []
        commits = 0
        real_commit = svc.db.commit

        async def counting_commit() -> None:
            nonlocal commits
            commits += 1
            await real_commit()

        async def vision(image: bytes, media_type: str) -> tuple[str, str]:
            commits_at_call.append(commits)
            await asyncio.sleep(0.01)
            return "read", "fake-model"

        svc.db.commit = counting_commit  # type: ignore[method-assign]
        await extract_document(svc.db, doc.id, owner_user_id=1, vision=vision)

        # One commit ends the read before any page is touched, then one
        # per page.
        assert commits == 1 + pages
        assert len(commits_at_call) == pages
        # The later pages started after earlier ones had already landed.
        # Gather-then-write would leave every one of these at 1.
        assert commits_at_call[-1] > 1, (
            "no page had committed by the last model call, so the writes "
            f"were deferred to the end; counts seen: {commits_at_call}"
        )


class TestPagesAreReadTogether:
    """The reads overlap; the writes do not.

    A scan is one model call per page and a person is watching, so the
    calls run concurrently. Everything that touches the session still
    happens one at a time, which is what keeps the write lock free
    between pages.
    """

    async def test_several_pages_are_in_the_model_at_once(self, svc) -> None:
        from app.services.documents.domains.extraction.pages import PAGE_CONCURRENCY
        from tests._pdf import pdf_bytes

        doc = await svc.ingest(
            pdf_bytes([""] * 6),
            title="scan.pdf",
            media_type="application/pdf",
            owner_user_id=1,
        )
        live = 0
        peak = 0

        async def vision(image: bytes, media_type: str) -> tuple[str, str]:
            nonlocal live, peak
            live += 1
            peak = max(peak, live)
            await asyncio.sleep(0.02)
            live -= 1
            return "read", "fake-model"

        await extract_document(svc.db, doc.id, owner_user_id=1, vision=vision)

        assert peak > 1, "pages were read one at a time"
        assert peak <= PAGE_CONCURRENCY, f"{peak} at once exceeds the cap"

    async def test_the_session_is_never_used_by_two_pages_at_once(self, svc) -> None:
        """The reads are safe to overlap only because none of them touch
        the session. A commit that overlapped another would corrupt it."""
        from tests._pdf import pdf_bytes

        doc = await svc.ingest(
            pdf_bytes([""] * 6),
            title="scan.pdf",
            media_type="application/pdf",
            owner_user_id=1,
        )
        committing = False
        overlapped = False
        real_commit = svc.db.commit

        async def counting_commit() -> None:
            nonlocal committing, overlapped
            if committing:
                overlapped = True
            committing = True
            await real_commit()
            committing = False

        async def vision(image: bytes, media_type: str) -> tuple[str, str]:
            await asyncio.sleep(0.01)
            return "read", "fake-model"

        svc.db.commit = counting_commit  # type: ignore[method-assign]
        await extract_document(svc.db, doc.id, owner_user_id=1, vision=vision)

        assert not overlapped, "two pages committed at the same time"

    async def test_a_page_that_blows_up_does_not_take_the_others_down(
        self, svc
    ) -> None:
        """One bad page is an unread row with a reason, not a failed run."""
        from tests._pdf import pdf_bytes

        doc = await svc.ingest(
            pdf_bytes([""] * 4),
            title="scan.pdf",
            media_type="application/pdf",
            owner_user_id=1,
        )
        seen = 0

        async def vision(image: bytes, media_type: str) -> tuple[str, str]:
            nonlocal seen
            seen += 1
            if seen == 2:
                raise RuntimeError("the model fell over")
            return "read", "fake-model"

        result = await extract_document(svc.db, doc.id, owner_user_id=1, vision=vision)

        assert (result.read, result.unread) == (3, 1)
        pages = await pages_for(svc.db, doc.id)
        assert len(pages) == 4
        (failed,) = [p for p in pages if p.status != "read"]
        assert "fell over" in (failed.detail or "")


class TestOcrComesBeforeTheModel:
    """A scan is typed more often than not. Tesseract reads those pages
    locally; the model sees only what OCR could not make sense of."""

    async def _scan(self, svc):  # noqa: ANN001, ANN202
        from tests._pdf import pdf_bytes

        return await svc.ingest(
            pdf_bytes(["", ""]),
            title="scan.pdf",
            media_type="application/pdf",
            owner_user_id=1,
        )

    async def test_a_typed_page_never_reaches_the_model(
        self, svc, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services.documents.domains.extraction import ocr

        monkeypatch.setattr(
            ocr,
            "read_png",
            lambda image: ("REQUEST FOR INFORMATION\nDue 9/8/2026 $1,500.00", 91.0),
        )
        vision = FakeVision()
        doc = await self._scan(svc)

        result = await extract_document(svc.db, doc.id, owner_user_id=1, vision=vision)

        assert (result.read, vision.calls) == (2, 0)
        pages = await pages_for(svc.db, doc.id)
        assert all(p.method == "ocr" and p.model is None for p in pages)
        assert "Due 9/8/2026" in (pages[0].text or "")

    async def test_a_page_ocr_cannot_read_goes_to_the_model(
        self, svc, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A landscape table read sideways is all letters and no words;
        Tesseract's own confidence is what says so."""
        from app.services.documents.domains.extraction import ocr

        monkeypatch.setattr(
            ocr,
            "read_png",
            lambda image: ("{SHINOW 08 WODNI HS 9 ANY OB8YRISNVEL", 34.0),
        )
        vision = FakeVision()
        doc = await self._scan(svc)

        await extract_document(svc.db, doc.id, owner_user_id=1, vision=vision)

        assert vision.calls == 2
        assert all(p.method == "vision" for p in await pages_for(svc.db, doc.id))

    async def test_no_tesseract_reads_as_before(
        self, svc, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services.documents.domains.extraction import ocr

        monkeypatch.setattr(ocr, "read_png", lambda image: None)
        vision = FakeVision()
        doc = await self._scan(svc)

        await extract_document(svc.db, doc.id, owner_user_id=1, vision=vision)

        assert vision.calls == 2


class TestWhatCountsAsARead:
    def test_confident_text_does(self) -> None:
        from app.services.documents.domains.extraction.ocr import looks_like_text

        assert looks_like_text(
            "Provide proof of your gross income as of 7/1/2026.", 88.0, 10
        )

    def test_a_low_confidence_page_or_an_empty_one_does_not(self) -> None:
        from app.services.documents.domains.extraction.ocr import looks_like_text

        assert not looks_like_text("", 95.0, 10)
        assert not looks_like_text("{SHINOW 08 WODNI HS 9 ANY", 34.0, 10)
        assert not looks_like_text("ok", 95.0, 10)

    def test_lines_come_back_out_of_the_word_table(self) -> None:
        from app.services.documents.domains.extraction.ocr import _assemble

        data = {
            "text": ["REQUEST", "FOR", "", "Due", "9/8/2026"],
            "conf": [96.0, 95.0, -1.0, 90.0, 80.0],
            "block_num": [1, 1, 1, 1, 1],
            "par_num": [1, 1, 1, 1, 1],
            "line_num": [1, 1, 1, 2, 2],
        }
        text, confidence = _assemble(data)
        assert text == "REQUEST FOR\nDue 9/8/2026"
        assert confidence == 90.25
