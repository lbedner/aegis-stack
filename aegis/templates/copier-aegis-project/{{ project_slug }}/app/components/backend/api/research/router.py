"""Research over HTTP: watches, refreshing them, and reading what they
found. Scoped to the caller (``get_research_service``)."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.services.research.deps import get_research_service
from app.services.research.models import ResearchItem, ResearchWatch
from app.services.research.registry import UnknownSourceError, installed_sources
from app.services.research.service import (
    MAX_RESULTS,
    ResearchService,
    SourceFailedError,
    WatchNotFoundError,
)

router = APIRouter(prefix="/research", tags=["research"])


class WatchCreate(BaseModel):
    source: str
    name: str
    query: dict[str, Any]
    with_threads: bool = False


@router.get("/sources")
async def list_sources() -> list[dict[str, str]]:
    return [{"name": s.name, "title": s.title} for s in installed_sources()]


@router.get("/watches", response_model=list[ResearchWatch])
async def list_watches(
    svc: ResearchService = Depends(get_research_service),
) -> list[ResearchWatch]:
    return await svc.list_watches()


@router.post(
    "/watches", response_model=ResearchWatch, status_code=status.HTTP_201_CREATED
)
async def add_watch(
    body: WatchCreate, svc: ResearchService = Depends(get_research_service)
) -> ResearchWatch:
    try:
        return await svc.add_watch(
            body.source, body.name, body.query, with_threads=body.with_threads
        )
    except (UnknownSourceError, ValueError) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.post("/watches/{watch_id}/refresh")
async def refresh_watch(
    watch_id: int, svc: ResearchService = Depends(get_research_service)
) -> dict[str, int]:
    try:
        return {"found": await svc.refresh_watch(watch_id)}
    except WatchNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except SourceFailedError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e


@router.delete("/watches/{watch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watch(
    watch_id: int, svc: ResearchService = Depends(get_research_service)
) -> None:
    try:
        await svc.delete_watch(watch_id)
    except WatchNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e


@router.get("/items", response_model=list[ResearchItem])
async def search_items(
    text: str | None = None,
    source: str | None = None,
    kind: str | None = None,
    watch_id: int | None = None,
    current_only: bool = False,
    limit: int = Query(50, ge=1, le=MAX_RESULTS),
    svc: ResearchService = Depends(get_research_service),
) -> list[ResearchItem]:
    return await svc.search(
        text,
        source=source,
        kind=kind,
        watch_id=watch_id,
        current_only=current_only,
        limit=limit,
    )


@router.get("/items/{item_id}/thread", response_model=list[ResearchItem])
async def item_thread(
    item_id: int, svc: ResearchService = Depends(get_research_service)
) -> list[ResearchItem]:
    return await svc.thread(item_id)
