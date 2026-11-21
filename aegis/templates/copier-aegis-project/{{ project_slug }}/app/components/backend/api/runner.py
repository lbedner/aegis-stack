"""The runner over HTTP.

- ``runs_router``: a runner on another machine claims a run of the actions
  it runs and posts its result, and its agent's hooks post what the run is
  doing, all holding a runner token (``Authorization: Bearer rnr_...``),
  never a session.
- ``tokens_router``: the caller's runner tokens, made (the value shown
  once), listed and revoked. With no one to sign in they are the
  operator's, made and revoked only where an operator's change is let
  through (``get_token_holder``).
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.runner import hooks, runs, tokens
from app.components.runner.models import RunnerToken
from app.components.runner.protocol import (
    CLAIM,
    FINISH,
    Answer,
    ClaimedRun,
    ClaimRequest,
)
from app.core.db import get_async_db
from app.services.shared.deps import get_owner_user_id, get_token_holder


class RunStanding(BaseModel):
    """A run and where it stands, as whoever asked or finished it is told."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    action: str
    status: str


class TokenRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255, description="The runner's name")


class TokenRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    hint: str
    created_at: datetime
    last_used_at: datetime | None = None


class NewToken(TokenRecord):
    value: str = Field(description="The token, shown this once")


async def get_runner_token(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_async_db),
) -> RunnerToken:
    """The runner token the request carries (``Authorization: Bearer
    rnr_...``), noting its use; a 401 without a live one. A runner is a
    machine: it never holds a session."""
    value = (authorization or "").removeprefix("Bearer ").strip()
    known = value.startswith(tokens.PREFIXES)
    token = await tokens.resolve(db, value) if known else None
    if token is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "A live runner token is needed",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


# Mounted at the root: its paths are the ones the runner and its agent's
# hooks post to (``protocol``, ``hooks.PATH``), so neither can drift.
runs_router = APIRouter(tags=["runner"])


@runs_router.post(
    CLAIM,
    response_model=ClaimedRun,
    responses={204: {"description": "Nothing waits for these actions"}},
)
async def claim(
    body: ClaimRequest,
    token: RunnerToken = Depends(get_runner_token),
    db: AsyncSession = Depends(get_async_db),
) -> ClaimedRun | Response:
    """The oldest run of ``actions`` waiting among the token's owner's, now
    this runner's (named for its token)."""
    run = await runs.claim(
        db,
        token.owner_user_id,
        body.actions,
        runner=token.name,
        timeout=body.timeout,
        worktrees=body.worktrees,
        agent=body.agent,
    )
    if run is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    claimed = ClaimedRun.model_validate(run)
    return claimed.model_copy(update={"resume": await runs.resumes(db, run)})


@runs_router.post(FINISH, response_model=RunStanding)
async def finish(
    run_id: int,
    body: Answer,
    token: RunnerToken = Depends(get_runner_token),
    db: AsyncSession = Depends(get_async_db),
) -> RunStanding:
    """Post what a run this runner claimed came back with: done, or failed
    with why."""
    try:
        run = await runs.finish(
            db,
            run_id,
            token.owner_user_id,
            body.result,
            ok=body.ok,
            runner=token.name,
            cost=body.cost,
            worktree=body.worktree,
        )
    except runs.RunNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return RunStanding.model_validate(run)


@runs_router.post(hooks.PATH, status_code=status.HTTP_204_NO_CONTENT)
async def activity(
    event: dict[str, Any],
    token: RunnerToken = Depends(get_runner_token),
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    """An agent's hook says what its session is doing (``hooks``): kept on
    the latest run a runner took in it. An event that says nothing of that
    is taken and changes nothing."""
    doing, session = hooks.activity_of(event), event.get("session_id")
    if doing is not None and session:
        await runs.note(db, token.owner_user_id, str(session), doing)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


tokens_router = APIRouter(prefix="/runner/tokens", tags=["runner"])


@tokens_router.get("", response_model=list[TokenRecord])
async def every_token(
    owner_user_id: int | None = Depends(get_owner_user_id),
    db: AsyncSession = Depends(get_async_db),
) -> list[TokenRecord]:
    """The caller's runner tokens, newest first; never their values."""
    rows = await tokens.live(db, owner_user_id)
    return [TokenRecord.model_validate(row) for row in rows]


@tokens_router.post("", response_model=NewToken, status_code=status.HTTP_201_CREATED)
async def make_token(
    body: TokenRequest,
    owner_user_id: int | None = Depends(get_token_holder),
    db: AsyncSession = Depends(get_async_db),
) -> NewToken:
    """A token for the caller's runner ``name``; its value is shown once."""
    row, value = await tokens.create(db, owner_user_id, body.name)
    return NewToken(**TokenRecord.model_validate(row).model_dump(), value=value)


@tokens_router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(
    token_id: int,
    owner_user_id: int | None = Depends(get_token_holder),
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    """Revoke one of the caller's tokens: its runner is refused from now."""
    try:
        await tokens.revoke(db, token_id, owner_user_id)
    except tokens.RunnerTokenNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
