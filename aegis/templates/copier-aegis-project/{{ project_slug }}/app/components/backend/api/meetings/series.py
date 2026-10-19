"""What each series of meetings keeps coming back to, over HTTP: the
series, one read with each theme's lines, and one written again.
``router`` is the caller's own (``get_series_service``); ``admin_router``
every owner's, for Overseer: reading is the admin's
(``get_admin_reader``), writing again an operator's (``get_admin_actor``).
Both go in before the meeting routes: ``series`` is not a meeting id."""

from typing import Any

from fastapi import APIRouter, Depends, status

from app.services.meetings.deps import (
    as_http,
    get_every_owners_series,
    get_series_service,
)
from app.services.meetings.domains.series.service import SeriesService
from app.services.meetings.models import SeriesRecord, SeriesRow
from app.services.shared.deps import get_admin_actor, get_admin_reader


def _routes(
    router: APIRouter,
    service: object,
    read: list[Any] | None = None,
    change: list[Any] | None = None,
) -> None:
    """The three routes, over the series ``service`` provides, reads behind
    ``read`` and the write behind ``change``."""
    scoped = Depends(service)  # type: ignore[call-overload]

    @router.get("", response_model=list[SeriesRow], dependencies=read)
    async def every_series(svc: SeriesService = scoped) -> list[SeriesRow]:
        """The series, latest written first."""
        return await svc.series()

    @router.get("/{series_id}", response_model=SeriesRecord, dependencies=read)
    async def one(series_id: int, svc: SeriesService = scoped) -> SeriesRecord:
        """The series, each theme with every line it was said in."""
        with as_http():
            return await svc.read(series_id)

    @router.post(
        "/{series_id}/write",
        response_model=SeriesRecord,
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=change,
    )
    async def write(series_id: int, svc: SeriesService = scoped) -> SeriesRecord:
        """Write the series again from its latest meetings, in the
        background."""
        with as_http():
            return await svc.write_again(series_id)


router = APIRouter(prefix="/meetings/series", tags=["meetings"])
_routes(router, get_series_service)

admin_router = APIRouter(prefix="/meetings/admin/series", tags=["meetings"])
_routes(
    admin_router,
    get_every_owners_series,
    read=[Depends(get_admin_reader)],
    change=[Depends(get_admin_actor)],
)
