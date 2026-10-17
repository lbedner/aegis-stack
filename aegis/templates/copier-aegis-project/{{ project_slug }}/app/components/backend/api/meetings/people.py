"""How to work with each person, over HTTP: the guides, one read with the
lines each point rests on, the owner's note on it, and the guide written
again. ``router`` is the caller's own (``get_people_service``);
``admin_router`` every owner's, for Overseer: reading is the admin's
(``get_admin_reader``), a change an operator's (``get_admin_actor``).
Both go in before the meeting routes: ``people`` is not a meeting id."""

from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from app.services.meetings.deps import (
    as_http,
    get_every_owners_people,
    get_people_service,
)
from app.services.meetings.domains.people.service import PeopleService
from app.services.meetings.models import GuideRecord, GuideRow
from app.services.shared.deps import get_admin_actor, get_admin_reader


class Note(BaseModel):
    note: str = ""


def _routes(
    router: APIRouter,
    service: object,
    read: list[Any] | None = None,
    change: list[Any] | None = None,
) -> None:
    """The four routes, over the people ``service`` provides, reads behind
    ``read`` and changes behind ``change``."""
    scoped = Depends(service)  # type: ignore[call-overload]

    @router.get("", response_model=list[GuideRow], dependencies=read)
    async def guides(svc: PeopleService = scoped) -> list[GuideRow]:
        """The guides, latest written first."""
        return await svc.guides()

    @router.get("/{guide_id}", response_model=GuideRecord, dependencies=read)
    async def guide(guide_id: int, svc: PeopleService = scoped) -> GuideRecord:
        """The guide, each point with the lines it rests on."""
        with as_http():
            return await svc.read(guide_id)

    @router.put("/{guide_id}/note", response_model=GuideRecord, dependencies=change)
    async def note(
        guide_id: int, body: Note, svc: PeopleService = scoped
    ) -> GuideRecord:
        """The owner's own note on the person; blank clears it."""
        with as_http():
            return await svc.set_note(guide_id, body.note)

    @router.post(
        "/{guide_id}/guide",
        response_model=GuideRecord,
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=change,
    )
    async def write(guide_id: int, svc: PeopleService = scoped) -> GuideRecord:
        """Write the guide again from every meeting, in the background."""
        with as_http():
            return await svc.write_again(guide_id)


router = APIRouter(prefix="/meetings/people", tags=["meetings"])
_routes(router, get_people_service)

admin_router = APIRouter(prefix="/meetings/admin/people", tags=["meetings"])
_routes(
    admin_router,
    get_every_owners_people,
    read=[Depends(get_admin_reader)],
    change=[Depends(get_admin_actor)],
)
