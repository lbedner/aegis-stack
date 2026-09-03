"""Reading a stored document once, per page, and keeping the result.

Two read paths, one shape. A PDF page with a text layer is read for free;
a page without one (a scan) is rendered and handed to a vision reader,
which is the same model call the chat surface makes on a pasted
screenshot. Either way the result is a ``DocumentPage`` row that names
its method, so anything built on it later can say where it came from.

A page is read exactly once. Re-running touches only pages still
``unread`` and calls no model for the rest; ``force`` is the one way to
spend model time again. What cannot be read is a row too, with the
reason, never a silent blank.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.log import logger
from app.core.storage import get_storage
from app.services.documents.domains.extraction.pdf import PNG_MEDIA_TYPE, PdfPages
from app.services.documents.models import Document, DocumentPage, utcnow
from app.services.documents.queries import document_by_id, pages_for

# Reads one page image and returns (text, model name). None when the
# stack has no vision model to offer.
VisionReader = Callable[[bytes, str], Awaitable[tuple[str, str]]]
Progress = Callable[[int, int], None]

IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})

# ponytail: a scanned PDF often carries a junk text layer of a few glyphs
# per page, so "has text" is a threshold, not a boolean. Raise it if
# real scans slip through as text; lower it if short pages get sent to
# the model needlessly.
MIN_TEXT_CHARS = 10

NO_VISION = "No vision model is available to read a page without a text layer."


@dataclass
class ExtractionResult:
    read: int = 0
    unread: int = 0
    skipped: int = 0
    pages: list[DocumentPage] = field(default_factory=list)

    def as_dict(self) -> dict[str, int]:
        return {"read": self.read, "unread": self.unread, "skipped": self.skipped}


class DocumentNotFoundError(LookupError):
    """No such document for this owner."""


class DocumentContentMissingError(LookupError):
    """The row exists but storage no longer holds its bytes."""


async def extract_document(
    db: AsyncSession,
    document_id: int,
    *,
    owner_user_id: int | None = None,
    vision: VisionReader | None,
    force: bool = False,
    progress: Progress | None = None,
) -> ExtractionResult:
    """Read every page not yet read (or every page, when forced)."""
    document = await document_by_id(db, document_id, owner_user_id=owner_user_id)
    if document is None:
        raise DocumentNotFoundError(f"Document {document_id} not found")
    data = await get_storage().get(document.storage_key)
    if data is None:
        raise DocumentContentMissingError(
            f"Document {document_id} has no content in storage"
        )

    existing = {p.page_number: p for p in await pages_for(db, document_id)}
    result = ExtractionResult()
    media_type = (document.media_type or "").lower()
    if media_type == "application/pdf":
        await _extract_pdf(
            db, document, document_id, data, existing, result, vision, force, progress
        )
    elif media_type in IMAGE_TYPES:
        await _extract_image(db, document, document_id, existing, result, vision, force)
    else:
        await _unsupported(db, document, document_id, existing, result, force)
    await db.flush()
    return result


async def _extract_pdf(
    db: AsyncSession,
    document: Document,
    document_id: int,
    data: bytes,
    existing: dict[int, DocumentPage],
    result: ExtractionResult,
    vision: VisionReader | None,
    force: bool,
    progress: Progress | None,
) -> None:
    pdf = PdfPages(data)
    try:
        total = len(pdf)
        if document.page_count != total:
            document.page_count = total
            db.add(document)
        for number in range(1, total + 1):
            page = existing.get(number)
            if page is not None and page.status == "read" and not force:
                result.skipped += 1
                continue
            page = page or DocumentPage(document_id=document_id, page_number=number)
            if not page.image_key:
                page.image_key = await get_storage().put(
                    pdf.render_png(number), content_type=PNG_MEDIA_TYPE
                )
            text = pdf.text(number)
            if len(text) >= MIN_TEXT_CHARS:
                _mark_read(page, text, method="text_layer", model=None)
            else:
                await _read_with_vision(page, page.image_key, PNG_MEDIA_TYPE, vision)
            _finish(db, page, result)
            if progress is not None:
                progress(number, total)
    finally:
        pdf.close()


async def _extract_image(
    db: AsyncSession,
    document: Document,
    document_id: int,
    existing: dict[int, DocumentPage],
    result: ExtractionResult,
    vision: VisionReader | None,
    force: bool,
) -> None:
    """An uploaded photo or screenshot is a one-page document whose
    render is the image itself."""
    page = existing.get(1)
    if page is not None and page.status == "read" and not force:
        result.skipped += 1
        return
    page = page or DocumentPage(document_id=document_id, page_number=1)
    page.image_key = document.storage_key
    if document.page_count != 1:
        document.page_count = 1
        db.add(document)
    await _read_with_vision(page, page.image_key, document.media_type or "", vision)
    _finish(db, page, result)


async def _unsupported(
    db: AsyncSession,
    document: Document,
    document_id: int,
    existing: dict[int, DocumentPage],
    result: ExtractionResult,
    force: bool,
) -> None:
    page = existing.get(1)
    if page is not None and not force:
        result.skipped += 1
        return
    page = page or DocumentPage(document_id=document_id, page_number=1)
    _mark_unread(
        page,
        f"Unsupported media type {document.media_type or 'unknown'}: only PDF and "
        "images are read.",
    )
    _finish(db, page, result)


async def _read_with_vision(
    page: DocumentPage, image_key: str, media_type: str, vision: VisionReader | None
) -> None:
    if vision is None:
        _mark_unread(page, NO_VISION)
        return
    image = await get_storage().get(image_key)
    if image is None:
        _mark_unread(page, "The page image is missing from storage.")
        return
    try:
        text, model = await vision(image, media_type)
    except Exception as exc:  # noqa: BLE001 - one bad page must not sink the run
        logger.warning("documents.vision_failed", page=page.page_number, error=str(exc))
        _mark_unread(page, f"Vision read failed: {exc}")
        return
    if not text.strip():
        _mark_unread(page, f"{model} returned no text for this page.")
        return
    _mark_read(page, text.strip(), method="vision", model=model)


def _mark_read(
    page: DocumentPage, text: str, *, method: str, model: str | None
) -> None:
    page.status, page.method, page.text, page.model, page.detail = (
        "read",
        method,
        text,
        model,
        None,
    )


def _mark_unread(page: DocumentPage, detail: str) -> None:
    page.status, page.method, page.text, page.model, page.detail = (
        "unread",
        "none",
        None,
        None,
        detail,
    )


def _finish(db: AsyncSession, page: DocumentPage, result: ExtractionResult) -> None:
    page.updated_at = utcnow()
    db.add(page)
    result.pages.append(page)
    if page.status == "read":
        result.read += 1
    else:
        result.unread += 1
