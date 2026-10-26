"""Moments and their actions over HTTP.

- ``router`` / ``admin_router``: a meeting's moments with what each offers
  (a browser action with the prompt it copies) and what was asked of it,
  an action asked of one, its call read over again for them, and what one
  of its lines is about, as Illiana says it (``actions.about``). The caller's own
  (``get_meetings_service``), or every owner's for Overseer: reading the
  admin's (``get_admin_reader``), asking an operator's (``get_admin_actor``).
- ``runs_router``: a runner on another machine claims a run of the actions
  it runs and posts its result, holding a runner token (``Authorization:
  Bearer mrt_...``), never a session.
- ``tokens_router``: the caller's runner tokens, made (the value shown
  once), listed and revoked.

All go in before the meeting routes: ``runs``, ``runner-tokens`` and
``admin`` are not meeting ids.
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_async_db
from app.services.meetings.deps import (
    as_http,
    get_every_owners_meetings,
    get_meetings_service,
    get_runner_token,
)
from app.services.meetings.domains.actions import runs, tokens
from app.services.meetings.domains.moments.service import moments_of
from app.services.meetings.models import LineAbout, MeetingRunnerToken, MomentRecord
from app.services.meetings.service import MeetingsService, line_about
from app.services.shared.deps import get_admin_actor, get_admin_reader


class AskRequest(BaseModel):
    action: str = Field(description="The action's name (``agent``, ``ai``...)")


class AskedRun(BaseModel):
    id: int
    action: str
    status: str


class ClaimRequest(BaseModel):
    actions: list[str] = Field(description="The actions this runner runs")


class ClaimedRun(BaseModel):
    id: int
    action: str
    prompt: str


class FinishRequest(BaseModel):
    ok: bool
    result: str


class TokenRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255, description="The runner's name")


class RunnerToken(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    hint: str
    created_at: datetime
    last_used_at: datetime | None = None


class NewRunnerToken(RunnerToken):
    value: str = Field(description="The token, shown this once")


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
        response_model=AskedRun,
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=change,
    )
    async def ask(
        meeting_id: int, moment_id: int, body: AskRequest, svc: MeetingsService = scoped
    ) -> AskedRun:
        """Ask an action of a moment: in the app it starts at once; on a
        runner it waits to be claimed."""
        with as_http():
            run = await svc.ask(meeting_id, moment_id, body.action)
        return AskedRun(id=run.id or 0, action=run.action, status=run.status)

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
        meeting_id: int, line_id: int, svc: MeetingsService = scoped
    ) -> LineAbout:
        """What a line of the call is about, as Illiana says it: her words,
        and the id of the card she drew of the part it names. 404 for a line
        the meeting does not hold, or a stack without her."""
        with as_http():
            said = await line_about(svc, meeting_id, line_id)
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

runs_router = APIRouter(prefix="/meetings/runs", tags=["meetings"])


@runs_router.post(
    "/claim",
    response_model=ClaimedRun,
    responses={204: {"description": "Nothing waits for these actions"}},
)
async def claim(
    body: ClaimRequest,
    token: MeetingRunnerToken = Depends(get_runner_token),
    db: AsyncSession = Depends(get_async_db),
) -> ClaimedRun | Response:
    """The oldest run of ``actions`` waiting among the token's owner's
    meetings, now this runner's (named for its token)."""
    run = await runs.claim(db, token.owner_user_id, body.actions, runner=token.name)
    if run is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return ClaimedRun(id=run.id or 0, action=run.action, prompt=run.prompt)


@runs_router.post("/{run_id}/finish", response_model=AskedRun)
async def finish(
    run_id: int,
    body: FinishRequest,
    token: MeetingRunnerToken = Depends(get_runner_token),
    db: AsyncSession = Depends(get_async_db),
) -> AskedRun:
    """Post what a run this runner claimed came back with: done, or failed
    with why."""
    with as_http():
        run = await runs.finish(
            db,
            run_id,
            token.owner_user_id,
            body.result,
            ok=body.ok,
            runner=token.name,
        )
    return AskedRun(id=run.id or 0, action=run.action, status=run.status)


tokens_router = APIRouter(prefix="/meetings/runner-tokens", tags=["meetings"])


@tokens_router.get("", response_model=list[RunnerToken])
async def every_token(
    svc: MeetingsService = Depends(get_meetings_service),
) -> list[RunnerToken]:
    """The caller's runner tokens, newest first; never their values."""
    return [
        RunnerToken.model_validate(row)
        for row in await tokens.live(svc.db, svc.owner_user_id)
    ]


@tokens_router.post(
    "", response_model=NewRunnerToken, status_code=status.HTTP_201_CREATED
)
async def make_token(
    body: TokenRequest, svc: MeetingsService = Depends(get_meetings_service)
) -> NewRunnerToken:
    """A token for the caller's runner ``name``; its value is shown once."""
    row, value = await tokens.create(svc.db, svc.owner_user_id, body.name)
    return NewRunnerToken(**RunnerToken.model_validate(row).model_dump(), value=value)


@tokens_router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(
    token_id: int, svc: MeetingsService = Depends(get_meetings_service)
) -> Response:
    """Revoke one of the caller's tokens: its runner is refused from now."""
    with as_http():
        await tokens.revoke(svc.db, token_id, svc.owner_user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
