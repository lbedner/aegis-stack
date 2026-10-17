"""FastAPI dependency provider for the meetings service, scoped to the
caller (``get_owner_user_id``): one owner never reads another's meetings."""

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_async_db
from app.services.meetings.domains.accounts.service import AgentNotFoundError
from app.services.meetings.domains.people.service import (
    GuideNotFoundError,
    PeopleService,
)
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


@contextmanager
def as_http() -> Iterator[None]:
    """The service's refusals as HTTP, for every route over meetings (the
    API's, the Meetings page's and Overseer's): a meeting or guide the
    caller cannot see is a 404, one the bot is still in (or notes or a
    guide that cannot be written now) a 409, a link it cannot join, a speaker who was not
    there or an agent there is not a 422."""
    try:
        yield
    except (MeetingNotFoundError, GuideNotFoundError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except (MeetingInProgressError, NothingToWriteError) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except (UnsupportedMeetingLinkError, NotASpeakerError, AgentNotFoundError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
