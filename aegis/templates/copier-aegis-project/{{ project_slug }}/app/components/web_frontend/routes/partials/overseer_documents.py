"""Actions for the Overseer Documents page: the drawer for one document
and its page previews, upload, save a document's details, tag and untag,
read its pages, download it, and retire it.
Mounted by ``routes/pages.py`` at ``overseer_documents.PARTIALS``; every
write goes through ``DocumentService`` on the request's session.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response

from app.components.backend.api.documents.pages import page_image
from app.components.web_frontend import overseer_documents
from app.components.web_frontend.rendering import dialog, go_to, toast_response
from app.core.formatting import safe_filename
from app.services.documents import queries
from app.services.documents.deps import get_document_service
from app.services.documents.domains.extraction.dispatch import start_extraction
from app.services.documents.models import DocumentPage
from app.services.documents.service import DocumentService, ProtectedDocumentError

router = APIRouter(prefix=overseer_documents.PARTIALS)


def _date(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:
        raise HTTPException(status_code=422, detail="Dates are YYYY-MM-DD.") from None


@router.get("/{document_id}/drawer", response_class=HTMLResponse)
async def drawer(
    request: Request,
    document_id: int,
    service: DocumentService = Depends(get_document_service),
) -> Response:
    """One document in the drawer: details, pages, tags, the edit form."""
    context = await overseer_documents.document_context(service, document_id)
    if context is None:
        raise HTTPException(status_code=404, detail="That document is gone.")
    return dialog(request, "pages/overseer/documents/_drawer.html", **context)


async def _page(
    service: DocumentService, document_id: int, number: int
) -> DocumentPage:
    row = await queries.page_for(service.db, document_id, number)
    if row is None:
        raise HTTPException(status_code=404, detail="No such page.")
    return row


@router.get("/{document_id}/pages/{number}", response_class=HTMLResponse)
async def page_preview(
    request: Request,
    document_id: int,
    number: int,
    service: DocumentService = Depends(get_document_service),
) -> Response:
    """One page in the modal: its render beside what was read off it."""
    row = await _page(service, document_id, number)
    return dialog(
        request,
        "pages/overseer/documents/_page.html",
        page=row,
        image=overseer_documents.page_url_for(document_id, number) + "/image"
        if row.image_key
        else None,
    )


@router.get("/{document_id}/pages/{number}/image")
async def page_render(
    document_id: int,
    number: int,
    service: DocumentService = Depends(get_document_service),
) -> Response:
    """The page's stored render, from the object store."""
    row = await _page(service, document_id, number)
    return await page_image(row, await service.get(document_id))


@router.post("/upload")
async def upload(
    file: UploadFile,
    kind: Annotated[str, Form()] = "other",
    service: DocumentService = Depends(get_document_service),
) -> Response:
    """File the bytes (the same bytes are filed once), then open the document."""
    name = safe_filename(file.filename or "", fallback="document")
    document = await service.ingest(
        await file.read(), title=name, kind=kind, media_type=file.content_type
    )
    return go_to(
        overseer_documents.document_url(document.id or 0),
        f"Filed {document.title}",
        target="#overseer-main",
    )


@router.post("/{document_id}")
async def save(
    document_id: int,
    title: Annotated[str, Form()] = "",
    kind: Annotated[str, Form()] = "other",
    document_date: Annotated[str, Form()] = "",
    note: Annotated[str, Form()] = "",
    service: DocumentService = Depends(get_document_service),
) -> Response:
    fields = {
        "title": title,
        "kind": kind,
        "document_date": _date(document_date),
        "note": note or None,
    }
    try:
        document = await service.update(document_id, fields)
    except ValueError as exc:
        return toast_response(str(exc), "error")
    if document is None:
        raise HTTPException(status_code=404, detail="That document is gone.")
    return go_to(
        overseer_documents.document_url(document_id), "Saved", target="#overseer-main"
    )


@router.post("/{document_id}/tags")
async def add_tag(
    document_id: int,
    label: Annotated[str, Form()] = "",
    service: DocumentService = Depends(get_document_service),
) -> Response:
    try:
        tag = await service.tag(document_id, label)
    except ValueError as exc:
        return toast_response(str(exc), "error")
    if tag is None:
        raise HTTPException(status_code=404, detail="That document is gone.")
    return go_to(
        overseer_documents.document_url(document_id),
        f"Tagged {label.strip()}",
        target="#overseer-main",
    )


@router.delete("/{document_id}/tags/{label}", status_code=204)
async def remove_tag(
    document_id: int,
    label: str,
    service: DocumentService = Depends(get_document_service),
) -> Response:
    if not await service.untag(document_id, label):
        raise HTTPException(status_code=404, detail="That tag is not on the document.")
    return Response(status_code=204)


@router.post("/{document_id}/read")
async def read(
    document_id: int,
    service: DocumentService = Depends(get_document_service),
) -> Response:
    """Hand the document to extraction on the worker; its pages fill in."""
    if await service.get(document_id) is None:
        raise HTTPException(status_code=404, detail="That document is gone.")
    await start_extraction(document_id, owner_user_id=None, force=True)
    return Response(status_code=200)


@router.get("/{document_id}/download")
async def download(
    document_id: int,
    service: DocumentService = Depends(get_document_service),
) -> Response:
    document = await service.get(document_id)
    data = await service.content(document_id) if document else None
    if document is None or data is None:
        raise HTTPException(status_code=404)
    return Response(
        data,
        media_type=document.media_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename(document.title)}"'
        },
    )


@router.get("/{document_id}/confirm-delete", response_class=HTMLResponse)
async def confirm_delete(
    request: Request,
    document_id: int,
    service: DocumentService = Depends(get_document_service),
) -> Response:
    document = await service.get(document_id)
    if document is None:
        raise HTTPException(status_code=404)
    return dialog(
        request,
        "pages/overseer/_confirm.html",
        title=f"Delete {document.title}?",
        body="It leaves the library. The stored file stays, since another document may share it.",
        url=f"{overseer_documents.PARTIALS}/{document_id}",
        label="Delete",
        method="delete",
        done="Document deleted",
    )


@router.delete("/{document_id}", status_code=204)
async def delete(
    document_id: int,
    service: DocumentService = Depends(get_document_service),
) -> Response:
    try:
        retired = await service.soft_delete(document_id)
    except ProtectedDocumentError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    if not retired:
        raise HTTPException(status_code=404, detail="That document is gone.")
    return Response(status_code=204)
