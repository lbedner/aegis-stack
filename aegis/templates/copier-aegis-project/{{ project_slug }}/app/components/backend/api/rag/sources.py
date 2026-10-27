"""One source at a time (``/rag/collections/{name}/sources``): added, a
file uploaded or a path the server holds, or removed. An admin's: a path
names a file on the server."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.services.rag import uploads
from app.services.rag.config import get_rag_service
from app.services.rag.service import LoaderError
from app.services.shared.deps import get_admin_actor

router = APIRouter(dependencies=[Depends(get_admin_actor)])


class SourceResponse(BaseModel):
    """A source added to or removed from a collection, and its chunks."""

    collection_name: str
    source: str
    chunks: int


@router.post(
    "/collections/{collection_name}/sources",
    response_model=SourceResponse,
)
async def add_source(
    collection_name: str,
    file: UploadFile | None = File(default=None),
    path: str | None = Form(default=None),
) -> SourceResponse:
    """Add one source: a file uploaded (kept beside the index) or a path
    the server holds. Indexed again if it was before."""
    if (file is None) == (path is None):
        raise HTTPException(status_code=400, detail="Send a file or a path, one.")
    service = get_rag_service()
    kept = None
    if file is not None:
        try:
            kept = uploads.kept_at(
                service.config.persist_directory, collection_name, file.filename or ""
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
        await uploads.keep(kept, await file.read())
    try:
        added = await service.add_file(kept or str(path), collection_name)
    except LoaderError as e:
        if kept is not None:
            await uploads.forget(kept)
        raise HTTPException(status_code=400, detail=f"Failed to load: {e}") from None
    return SourceResponse(
        collection_name=collection_name,
        source=added.file_path,
        chunks=added.chunk_count,
    )


@router.delete(
    "/collections/{collection_name}/sources",
    response_model=SourceResponse,
)
async def remove_source(collection_name: str, source: str) -> SourceResponse:
    """Remove one source (its path, as the collection's files list it)."""
    removed = await get_rag_service().remove_file(source, collection_name)
    if not removed.chunk_count:
        raise HTTPException(
            status_code=404, detail=f"No source {source!r} in '{collection_name}'"
        )
    return SourceResponse(
        collection_name=collection_name, source=source, chunks=removed.chunk_count
    )
