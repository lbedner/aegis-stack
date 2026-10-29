"""A collection's sources (``/rag/collections/{name}/sources``): files
uploaded, a path the server holds (a file or a folder) and parts of this
app (``part``) added, or replacing the collection; every source, or one,
re-indexed; one removed. An admin's: a path names files on the server."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.services.rag import sources
from app.services.rag.config import get_rag_service
from app.services.rag.models import Indexed
from app.services.shared.deps import get_admin_actor

router = APIRouter(dependencies=[Depends(get_admin_actor)])


class SourcesResponse(Indexed):
    """Sources added to a collection (``Indexed``), and which."""

    collection_name: str


class SourceResponse(BaseModel):
    """A source removed from a collection, and its chunks."""

    collection_name: str
    source: str
    chunks: int


@router.post(
    "/collections/{collection_name}/sources",
    response_model=SourcesResponse,
)
async def add_sources(
    collection_name: str,
    file: list[UploadFile] = File(default=[]),
    path: str = Form(default=""),
    part: list[str] = Form(default=[]),
    extensions: str = Form(default=""),
    exclude: str = Form(default=""),
    replace: bool = Form(default=False),
) -> SourcesResponse:
    """Add files uploaded (each kept beside the index), a path the server
    holds (a file or a folder) and parts of this app (``part``, repeated:
    the ids ``GET /rag/knowable`` lists), reading ``extensions`` and leaving
    out ``exclude`` (comma-separated globs); ``replace`` starts the
    collection again."""
    try:
        the = await sources.plan(
            collection_name,
            uploads=[(f.filename or "", await f.read()) for f in file],
            paths=[path],
            parts=part,
            extensions=sources.listed(extensions, dotted=True),
            exclude=sources.listed(exclude),
            replace=replace,
        )
        done = await sources.index(the)
    except ValueError as e:  # LoaderError, unreadable, is one too
        raise HTTPException(status_code=400, detail=str(e)) from None
    return SourcesResponse(collection_name=collection_name, **done.model_dump())


@router.post(
    "/collections/{collection_name}/reindex",
    response_model=SourcesResponse,
)
async def reindex(collection_name: str, source: str | None = None) -> SourcesResponse:
    """Read every source of the collection again (after a change of
    embedding model or chunking), or ``source`` alone."""
    try:
        done = await sources.index(await sources.held(collection_name, source))
    except ValueError as e:  # a source it does not hold, or nothing readable
        raise HTTPException(status_code=400, detail=str(e)) from None
    return SourcesResponse(collection_name=collection_name, **done.model_dump())


@router.delete(
    "/collections/{collection_name}/sources",
    response_model=SourceResponse,
)
async def remove_source(collection_name: str, source: str) -> SourceResponse:
    """Remove one source (its path, as the collection's files list it),
    and its kept copy if it was uploaded."""
    removed = await get_rag_service().remove_file(source, collection_name)
    if not removed.chunk_count:
        raise HTTPException(
            status_code=404, detail=f"No source {source!r} in '{collection_name}'"
        )
    return SourceResponse(
        collection_name=collection_name, source=source, chunks=removed.chunk_count
    )
