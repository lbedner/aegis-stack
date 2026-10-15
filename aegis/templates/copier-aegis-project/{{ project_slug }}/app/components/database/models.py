"""Saved queries' one table: a statement Overseer's Query keeps, by name."""

from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text
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
