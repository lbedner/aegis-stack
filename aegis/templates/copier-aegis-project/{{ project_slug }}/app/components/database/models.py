"""The component's own tables: a statement Overseer's Query keeps, by
name, and every object the store holds, by key."""

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, String, Text
from sqlmodel import Field, SQLModel

from app.core.time import utcnow

NAME = 120  # the most characters a name holds
SQL = 20_000  # ... and a statement


class SavedQuery(SQLModel, table=True):
    """A statement kept for Query, shared by every admin (see ``saved``)."""

    __tablename__ = "saved_query"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(sa_column=Column(String(NAME), nullable=False, unique=True))
    sql: str = Field(sa_column=Column(Text, nullable=False))
    saved_by: str | None = Field(
        default=None, sa_column=Column(String(320), nullable=True)
    )
    saved_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(DateTime, nullable=False)
    )


class StoredObject(SQLModel, table=True):
    """An object put in the store through ``stored.store``."""

    __tablename__ = "stored_object"

    key: str = Field(sa_column=Column(String(128), primary_key=True))
    bytes: int = Field(sa_column=Column(BigInteger, nullable=False))
    content_type: str | None = Field(
        default=None, sa_column=Column(String(128), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(DateTime, nullable=False)
    )
    # Set by ``stored.release``, cleared by storing it again; ``purge``
    # deletes what is still set once the release has committed.
    released_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=True)
    )
