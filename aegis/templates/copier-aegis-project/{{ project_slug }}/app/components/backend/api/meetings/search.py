"""Search over HTTP: the lines and notes of the meetings that have the
words. ``router`` searches the caller's own (``get_owner_user_id``);
``admin_router`` every owner's, for Overseer (``get_admin_reader``). Both go
in before the meeting routes: ``search`` is not a meeting id."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_async_db
from app.services.meetings.domains.search.service import SearchHit, search_meetings
from app.services.shared.deps import get_admin_reader, get_owner_user_id

Db = Annotated[AsyncSession, Depends(get_async_db)]
Words = Annotated[str, Query(min_length=1, max_length=500)]

router = APIRouter(prefix="/meetings/search", tags=["meetings"])
admin_router = APIRouter(prefix="/meetings/admin/search", tags=["meetings"])


@router.get("", response_model=list[SearchHit])
async def search(
    q: Words,
    db: Db,
    owner_user_id: Annotated[int | None, Depends(get_owner_user_id)],
) -> list[SearchHit]:
    """The caller's meetings' lines and notes with the words of ``q``,
    newest meeting first."""
    return await search_meetings(db, owner_user_id, q)


@admin_router.get(
    "", response_model=list[SearchHit], dependencies=[Depends(get_admin_reader)]
)
async def search_every_owner(q: Words, db: Db) -> list[SearchHit]:
    """Every owner's meetings' lines and notes with the words of ``q``."""
    return await search_meetings(db, None, q)
