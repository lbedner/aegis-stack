"""Extraction and the pages it produces.

``POST /{id}/extract`` reads the document (synchronously by default, as a
background job with ``?background=true`` so a 40-page statement can
stream progress over the jobs SSE endpoint). The page routes read back
what extraction stored: status per page, one page's text, its image.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.db import get_async_session
from app.core.storage import get_storage
from app.services.documents.deps import get_document_service, get_owner_user_id
from app.services.documents.extraction import (
    DocumentContentMissingError,
    DocumentNotFoundError,
    ExtractionResult,
    extract_document,
)
from app.services.documents.models import DocumentPage
from app.services.documents.queries import page_for, pages_for
from app.services.documents.service import DocumentService
from app.services.documents.vision import vision_reader
from app.services.system.jobs import JobHandle, get_job_runner

router = APIRouter()

_NOT_FOUND = "Document not found"
_PAGE_NOT_FOUND = "Page not found"


class PageSummary(BaseModel):
    page_number: int
    status: str
    method: str
    has_image: bool
    model: str | None
    detail: str | None

    @classmethod
    def from_row(cls, row: DocumentPage) -> PageSummary:
        return cls(
            page_number=row.page_number,
            status=row.status,
            method=row.method,
            has_image=bool(row.image_key),
            model=row.model,
            detail=row.detail,
        )


class PageDetail(PageSummary):
    text: str | None

    @classmethod
    def from_row(cls, row: DocumentPage) -> PageDetail:
        return cls(**PageSummary.from_row(row).model_dump(), text=row.text)


@router.post("/{document_id}/extract")
async def extract(
    document_id: int,
    background: bool = False,
    force: bool = False,
    service: DocumentService = Depends(get_document_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> Response:
    """Read every page not yet read. Returns the counts, or a job id."""
    if await service.get(document_id, owner_user_id=owner_user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    if not background:
        try:
            result = await extract_document(
                service.db,
                document_id,
                owner_user_id=owner_user_id,
                vision=vision_reader(),
                force=force,
            )
        except DocumentNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND
            ) from None
        except DocumentContentMissingError as exc:
            # The row outlived its object: the store lost it, not the client.
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
            ) from None
        return JSONResponse(result.as_dict())

    async def work(handle: JobHandle) -> dict[str, int]:
        def progress(page: int, total: int) -> None:
            handle.set_label(f"Reading page {page} of {total}...")

        async with get_async_session() as session:
            result: ExtractionResult = await extract_document(
                session,
                document_id,
                owner_user_id=owner_user_id,
                vision=vision_reader(),
                force=force,
                progress=progress,
            )
            await session.commit()
        return result.as_dict()

    job_id = get_job_runner().start(
        f"documents-extract:{document_id}", work, label="Opening the document..."
    )
    return JSONResponse({"job_id": job_id}, status_code=status.HTTP_202_ACCEPTED)


@router.get("/{document_id}/pages", response_model=list[PageSummary])
async def list_pages(
    document_id: int,
    service: DocumentService = Depends(get_document_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> list[PageSummary]:
    if await service.get(document_id, owner_user_id=owner_user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return [
        PageSummary.from_row(row) for row in await pages_for(service.db, document_id)
    ]


@router.get("/{document_id}/pages/{page_number}", response_model=PageDetail)
async def get_page(
    document_id: int,
    page_number: int,
    service: DocumentService = Depends(get_document_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> PageDetail:
    row = await _page(service, document_id, page_number, owner_user_id)
    return PageDetail.from_row(row)


@router.get("/{document_id}/pages/{page_number}/image")
async def get_page_image(
    document_id: int,
    page_number: int,
    service: DocumentService = Depends(get_document_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> Response:
    row = await _page(service, document_id, page_number, owner_user_id)
    if not row.image_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No page image"
        )
    data = await get_storage().get(row.image_key)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Page image is not retrievable from storage",
        )
    document = await service.get(document_id, owner_user_id=owner_user_id)
    media_type = "image/png"
    if document is not None and row.image_key == document.storage_key:
        media_type = document.media_type or media_type
    return Response(content=data, media_type=media_type)


async def _page(
    service: DocumentService,
    document_id: int,
    page_number: int,
    owner_user_id: int | None,
) -> DocumentPage:
    if await service.get(document_id, owner_user_id=owner_user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    row = await page_for(service.db, document_id, page_number)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_PAGE_NOT_FOUND
        )
    return row
