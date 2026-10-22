"""FastAPI dependency provider for the meetings service, scoped to the
caller (``get_owner_user_id``): one owner never reads another's meetings."""

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import Depends, Header, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_async_db
from app.services.meetings.domains.accounts.service import AgentNotFoundError
from app.services.meetings.domains.actions import tokens
from app.services.meetings.domains.actions.runs import (
    ActionNotFoundError,
    MomentNotFoundError,
    RunNotFoundError,
)
from app.services.meetings.domains.calendar.entries import EventNotFoundError
from app.services.meetings.domains.people.service import (
    GuideNotFoundError,
    PeopleService,
)
from app.services.meetings.domains.series.service import (
    SeriesNotFoundError,
    SeriesService,
)
from app.services.meetings.models import MeetingRunnerToken
from app.services.meetings.service import (
    MeetingInProgressError,
    MeetingNotFoundError,
    MeetingsService,
    NotASpeakerError,
    NothingToWriteError,
    UnsupportedMeetingLinkError,
)
from app.services.shared.deps import get_owner_user_id


async def get_meetings_service(
    db: AsyncSession = Depends(get_async_db),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> MeetingsService:
    return MeetingsService(db, owner_user_id)


def get_every_owners_meetings(
    db: AsyncSession = Depends(get_async_db),
) -> MeetingsService:
    """The service unscoped, for Overseer's reads and changes across every
    owner: each route that takes it guards itself as an admin's."""
    return MeetingsService(db, None)


async def get_people_service(
    db: AsyncSession = Depends(get_async_db),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> PeopleService:
    return PeopleService(db, owner_user_id)


def get_every_owners_people(db: AsyncSession = Depends(get_async_db)) -> PeopleService:
    """Every owner's guides, for Overseer: each route that takes it guards
    itself as an admin's."""
    return PeopleService(db, None)


async def get_series_service(
    db: AsyncSession = Depends(get_async_db),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> SeriesService:
    return SeriesService(db, owner_user_id)


def get_every_owners_series(db: AsyncSession = Depends(get_async_db)) -> SeriesService:
    """Every owner's series, for Overseer: each route that takes it guards
    itself as an admin's."""
    return SeriesService(db, None)


@contextmanager
def as_http() -> Iterator[None]:
    """The service's refusals as HTTP, for every route over meetings (the
    API's, the Meetings page's and Overseer's): a meeting, guide or series
    the caller cannot see is a 404, one the bot is still in (or notes, a
    guide or a series that cannot be written now) a 409, a link it cannot join, a speaker who was not
    there or an agent there is not a 422. A moment, action, claimed run or
    runner token the caller cannot reach is a 404 too, as is a meeting on no
    calendar."""
    try:
        yield
    except (
        MeetingNotFoundError,
        GuideNotFoundError,
        SeriesNotFoundError,
        MomentNotFoundError,
        ActionNotFoundError,
        RunNotFoundError,
        tokens.RunnerTokenNotFoundError,
        EventNotFoundError,
    ) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except (MeetingInProgressError, NothingToWriteError) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except (UnsupportedMeetingLinkError, NotASpeakerError, AgentNotFoundError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


async def get_runner_token(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_async_db),
) -> MeetingRunnerToken:
    """The runner token the request carries (``Authorization: Bearer
    mrt_...``), noting its use; a 401 without a live one. A runner is a
    machine: it never holds a session."""
    value = (authorization or "").removeprefix("Bearer ").strip()
    token = await tokens.resolve(db, value) if value.startswith(tokens.PREFIX) else None
    if token is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "A live runner token is needed",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token
