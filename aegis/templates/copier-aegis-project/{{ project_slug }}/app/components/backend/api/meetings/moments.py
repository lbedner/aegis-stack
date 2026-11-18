"""Moments and their actions over HTTP.

- ``router`` / ``admin_router``: a meeting's moments with what each offers
  (a browser action with the prompt it copies) and what was asked of it,
  an action asked of one, its call read over again for them, and what one
  of its lines is about, as Illiana says it (``actions.about``). The caller's own
  (``get_meetings_service``), or every owner's for Overseer: reading the
  admin's (``get_admin_reader``), asking an operator's (``get_admin_actor``).

Both go in before the meeting routes: ``admin`` is not a meeting id. A run
asked here is claimed and finished through the runner component's routes
(``/runner/runs``).
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.components.backend.api.runner import RunStanding
from app.services.meetings.deps import (
    as_http,
    get_every_owners_meetings,
    get_meetings_service,
)
from app.services.meetings.service import (
    LineAbout,
    MeetingsService,
    MomentRecord,
    line_about,
    moments_of,
)
from app.services.shared.deps import get_admin_actor, get_admin_reader


class AskRequest(BaseModel):
    action: str = Field(description="The action's name (``agent``, ``ai``...)")


def _routes(
    router: APIRouter,
    service: object,
    read: list[Any] | None = None,
    change: list[Any] | None = None,
) -> None:
    """A meeting's moments, over the meetings ``service`` provides."""
    scoped = Depends(service)  # type: ignore[call-overload]

    @router.get(
        "/{meeting_id}/moments", response_model=list[MomentRecord], dependencies=read
    )
    async def moments(
        meeting_id: int, svc: MeetingsService = scoped
    ) -> list[MomentRecord]:
        """What the call threw up, in the order it was said."""
        with as_http():
            await svc.get(meeting_id)
        return await moments_of(svc.db, meeting_id)

    @router.post(
        "/{meeting_id}/moments/{moment_id}/runs",
        response_model=RunStanding,
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=change,
    )
    async def ask(
        meeting_id: int, moment_id: int, body: AskRequest, svc: MeetingsService = scoped
    ) -> RunStanding:
        """Ask an action of a moment: in the app it starts at once; on a
        runner it waits to be claimed."""
        with as_http():
            run = await svc.ask(meeting_id, moment_id, body.action)
        return RunStanding.model_validate(run)

    @router.post(
        "/{meeting_id}/moments/find",
        response_model=list[MomentRecord],
        dependencies=change,
    )
    async def find(
        meeting_id: int, svc: MeetingsService = scoped
    ) -> list[MomentRecord]:
        """Read the call over again for moments (one kept before they were
        looked for, or before a detector changed): what it holds now. Where
        the stack has a model, its questions are cleaned up after, in the
        background."""
        with as_http():
            return (await svc.look_over(meeting_id)).moments

    @router.post(
        "/{meeting_id}/lines/{line_id}/about",
        response_model=LineAbout,
        dependencies=change,
    )
    async def about(
        meeting_id: int,
        line_id: int,
        part: str | None = None,
        svc: MeetingsService = scoped,
    ) -> LineAbout:
        """What a line of the call is about, as Illiana says it, or the part
        it names (``part``, a node id: ``component:scheduler``): her words,
        and the id of the card she drew of the part. 404 for a line the
        meeting does not hold, or a stack without her."""
        with as_http():
            said = await line_about(svc, meeting_id, line_id, part=part)
        if said is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such line to ask about")
        return said


router = APIRouter(prefix="/meetings", tags=["meetings"])
_routes(router, get_meetings_service)

admin_router = APIRouter(prefix="/meetings/admin", tags=["meetings"])
_routes(
    admin_router,
    get_every_owners_meetings,
    read=[Depends(get_admin_reader)],
    change=[Depends(get_admin_actor)],
)
