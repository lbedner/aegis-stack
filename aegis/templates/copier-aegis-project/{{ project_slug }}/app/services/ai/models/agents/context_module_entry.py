"""A per-subject context module's text for one subject."""

from datetime import datetime

from sqlalchemy import Column, ForeignKey, Integer, Text, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.time import utcnow


class ContextModuleEntry(SQLModel, table=True):
    """What a ``per_subject`` module says about one subject.

    The subject is whatever a turn is about, as the app names it (a
    project's id, a ledger's): the renderer is handed it, never the
    model. One row per module and subject.
    ``updated_by_user_id`` is a plain id, not a key: the AI service ships
    without auth too.
    """

    __tablename__ = "context_module_entry"
    __table_args__ = (UniqueConstraint("module_id", "subject"),)

    id: int | None = Field(default=None, primary_key=True)
    module_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("context_module.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    subject: str = Field(max_length=64)
    content: str = Field(sa_column=Column(Text, nullable=False))
    updated_by_user_id: int | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
