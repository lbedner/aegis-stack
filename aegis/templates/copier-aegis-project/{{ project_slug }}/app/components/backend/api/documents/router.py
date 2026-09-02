"""Document store API routes.

Upload, list, fetch metadata, download bytes, tag, retire. What a
document means is the caller's business; these routes only keep it and
give it back.
"""

from __future__ import annotations

from datetime import date, datetime
import re

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field

from app.components.backend.api.documents.pages import router as pages_router
from app.services.documents.deps import get_document_service, get_owner_user_id
from app.services.documents.models import Document
from app.services.documents.service import DocumentService, ProtectedDocumentError

router = APIRouter(prefix="/documents", tags=["documents"])

_NOT_FOUND = "Document not found"
# Anything that could end a header line or a quoted filename. The title is
# user input and lands in Content-Disposition, so a stray newline there is
# header injection, not a formatting nuisance.
_UNSAFE_FILENAME = re.compile(r'[\r\n"\\]+')


def _safe_filename(title: str) -> str:
    return _UNSAFE_FILENAME.sub("", title).strip() or "document"


class DocumentResponse(BaseModel):
    """A document as the API describes it.

    ``storage_key`` is deliberately included: it is content-addressed
    and therefore stable across backends, which makes it a safe handle
    for a caller that wants to reference the same bytes elsewhere.
    """

    id: int
    title: str
    kind: str
    media_type: str | None
    byte_size: int
    page_count: int | None
    document_date: date | None
    received_at: datetime | None
    source: str
    storage_key: str
    storage_backend: str
    channel: str | None
    supersedes_id: int | None
    protected: bool
    note: str | None
    tags: list[str] = Field(default_factory=list)

    @classmethod
    def from_row(cls, row: Document, tags: list[str] | None = None) -> DocumentResponse:
        return cls(
            id=row.id or 0,
            title=row.title,
            kind=row.kind,
            media_type=row.media_type,
            byte_size=row.byte_size,
            page_count=row.page_count,
            document_date=row.document_date,
            received_at=row.received_at,
            source=row.source,
            storage_key=row.storage_key,
            storage_backend=row.storage_backend,
            channel=row.channel,
            supersedes_id=row.supersedes_id,
            protected=row.protected,
            note=row.note,
            tags=tags or [],
        )


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int


class TagRequest(BaseModel):
    label: str


class TagCount(BaseModel):
    label: str
    count: int


class DocumentUpdate(BaseModel):
    """What may change after filing. Fields left unset stay as they are.
    ``document_date`` and ``note`` clear when sent as null; ``title`` and
    ``kind`` must always hold a value, so null there is a 400."""

    title: str | None = None
    kind: str | None = None
    document_date: date | None = None
    note: str | None = None
    channel: str | None = None
    supersedes_id: int | None = None
    protected: bool | None = None


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    response: Response,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    kind: str = Form("other"),
    note: str | None = Form(None),
    channel: str | None = Form(None),
    service: DocumentService = Depends(get_document_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> DocumentResponse:
    """Store an uploaded file.

    Uploading the same bytes twice returns the existing document rather
    than a second one, so a retried upload is safe. The status code says
    which happened: 201 for a new document, 200 for one already held.
    """
    data = await file.read()
    try:
        document, created = await service.store(
            data,
            title=title or file.filename or "Untitled",
            kind=kind,
            media_type=file.content_type,
            source="upload",
            note=note,
            channel=channel,
            owner_user_id=owner_user_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from None
    if not created:
        response.status_code = status.HTTP_200_OK
    return DocumentResponse.from_row(document)


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    kind: str | None = None,
    tag: str | None = None,
    channel: str | None = None,
    include_superseded: bool = False,
    page: int = 1,
    page_size: int = 50,
    service: DocumentService = Depends(get_document_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> DocumentListResponse:
    rows, total = await service.list_documents(
        kind=kind,
        tag=tag,
        channel=channel,
        include_superseded=include_superseded,
        page=page,
        page_size=page_size,
        owner_user_id=owner_user_id,
    )
    # One tags query for the whole page, not one per row.
    tags = await service.tags_for_many([row.id for row in rows if row.id])
    items = [DocumentResponse.from_row(row, tags.get(row.id or 0, [])) for row in rows]
    return DocumentListResponse(items=items, total=total)


@router.get("/tags", response_model=list[TagCount])
async def list_tags(
    service: DocumentService = Depends(get_document_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> list[TagCount]:
    """Every label in use, most used first."""
    counts = await service.tag_counts(owner_user_id=owner_user_id)
    return [TagCount(label=label, count=count) for label, count in counts]


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: int,
    service: DocumentService = Depends(get_document_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> DocumentResponse:
    document = await service.get(document_id, owner_user_id=owner_user_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return DocumentResponse.from_row(document, await service.tags_for(document_id))


@router.patch("/{document_id}", response_model=DocumentResponse)
async def update_document(
    document_id: int,
    body: DocumentUpdate,
    service: DocumentService = Depends(get_document_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> DocumentResponse:
    try:
        document = await service.update(
            document_id,
            body.model_dump(exclude_unset=True),
            owner_user_id=owner_user_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from None
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return DocumentResponse.from_row(document, await service.tags_for(document_id))


@router.get("/{document_id}/content")
async def download_document(
    document_id: int,
    service: DocumentService = Depends(get_document_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> Response:
    """The bytes themselves, read through whichever backend holds them."""
    document = await service.get(document_id, owner_user_id=owner_user_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    data = await service.content(document_id, owner_user_id=owner_user_id)
    if data is None:
        # The row outlived its object: a real failure, not a 404 - the
        # document exists and the store lost it.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Document content is not retrievable from storage",
        )
    return Response(
        content=data,
        media_type=document.media_type or "application/octet-stream",
        headers={
            "Content-Disposition": (
                f'inline; filename="{_safe_filename(document.title)}"'
            ),
        },
    )


@router.post("/{document_id}/tags", response_model=DocumentResponse)
async def tag_document(
    document_id: int,
    body: TagRequest,
    service: DocumentService = Depends(get_document_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> DocumentResponse:
    try:
        tagged = await service.tag(document_id, body.label)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from None
    if tagged is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    document = await service.get(document_id, owner_user_id=owner_user_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return DocumentResponse.from_row(document, await service.tags_for(document_id))


@router.delete("/{document_id}/tags/{label}", response_model=DocumentResponse)
async def untag_document(
    document_id: int,
    label: str,
    service: DocumentService = Depends(get_document_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> DocumentResponse:
    document = await service.get(document_id, owner_user_id=owner_user_id)
    if document is None or not await service.untag(document_id, label):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return DocumentResponse.from_row(document, await service.tags_for(document_id))


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: int,
    confirm: str | None = None,
    service: DocumentService = Depends(get_document_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> Response:
    """Retire a document. The bytes stay: another document may hold the
    same content, and the audit trail should not lose its subject. A
    protected document needs ``?confirm=<its exact title>``."""
    try:
        retired = await service.soft_delete(
            document_id, owner_user_id=owner_user_id, confirm=confirm
        )
    except ProtectedDocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from None
    if not retired:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Extraction and page routes live in their own module; same prefix.
router.include_router(pages_router)
