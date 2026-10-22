"""The requests the server kept (``services.system.kept_requests``), for
an operator: the recent ones and one with its hops, each hop named as the
dry path names it. Behind ``get_admin_actor`` (open on a stack without
auth, as every operator route is). The server's last requests, kept a
day; reading them is not kept (``replays.SKIPPED``)."""

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from app.core import replays
from app.services.shared.deps import get_admin_actor
from app.services.system import kept_requests
from app.services.system.kept_requests import RequestHops, RequestSummary

router = APIRouter(
    prefix="/requests",
    tags=["requests"],
    dependencies=[Depends(get_admin_actor)],
)


@router.get("", response_model=list[RequestSummary])
async def recent(
    route: str | None = None,
    limit: int = Query(default=replays.KEEP, ge=1, le=replays.KEEP),
) -> list[RequestSummary]:
    """The requests kept, newest first; ``route`` (as declared,
    ``/api/v1/users/{id}``) keeps one route's."""
    return await kept_requests.recent(route, limit)


@router.get("/{request_id}", response_model=RequestHops)
async def one(request_id: str = Path(pattern=replays.ID)) -> RequestHops:
    """A request kept, with its hops in the order they started; a
    malformed id is refused before any lookup."""
    found = await kept_requests.find(request_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such request kept.")
    return found
