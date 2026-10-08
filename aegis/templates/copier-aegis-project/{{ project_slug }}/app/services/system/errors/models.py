"""Error contracts: ``id`` identifies one source occurrence, ``fingerprint``
groups a cause. Counts describe retained occurrences, never lifetime totals."""

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

MAX_PAYLOAD = 65536  # bytes one serialized occurrence may take
SEARCHED_CHARACTERS = 1024  # of a message, what search and grouping read


class ErrorOccurrence(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    fingerprint: str
    timestamp: datetime
    # Docker's own timestamp, nanoseconds kept, for replay identity.
    source_timestamp: str | None
    ordinal: int = Field(ge=0)
    page: str
    service: str
    app_service: str | None = None
    container_id: str
    container_name: str
    stream: str
    level: str
    logger: str | None
    message: str
    exception_type: str | None
    traceback: str | None
    fields: dict[str, str]
    truncated: bool = False
    incomplete: bool = False


class ErrorSearch(BaseModel):
    """What the search projection keeps of an occurrence: enough to filter
    and group it, its message cut to ``SEARCHED_CHARACTERS``."""

    model_config = ConfigDict(frozen=True)
    id: str
    fingerprint: str
    timestamp: datetime
    page: str
    service: str
    app_service: str | None = None
    container_name: str | None = None
    level: str
    message: str
    exception_type: str | None

    @classmethod
    def of(cls, event: ErrorOccurrence) -> Self:
        projected = event.model_dump(include=set(cls.model_fields))
        return cls(**projected | {"message": event.message[:SEARCHED_CHARACTERS]})


class ErrorIssue(BaseModel):
    model_config = ConfigDict(frozen=True)
    fingerprint: str
    page: str
    service: str
    app_service: str | None = None
    container_name: str | None = None
    message: str
    exception_type: str | None
    count: int = Field(ge=1)
    first_seen: datetime
    last_seen: datetime
    latest_id: str
