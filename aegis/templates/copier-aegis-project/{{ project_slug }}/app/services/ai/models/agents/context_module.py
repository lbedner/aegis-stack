"""Context module model."""

from datetime import datetime

from sqlalchemy import false
from sqlmodel import Field, SQLModel

from app.core.time import utcnow


class ContextModule(SQLModel, table=True):
    """
    A reusable prompt-context block agents opt into via
    ``Agent.context_modules``.

    Hybrid by design: ``prompt_content`` (static text), ``per_subject``
    (its own text for each subject, ``ContextModuleEntry``) and
    ``fetch_function`` (a registered fetcher name) are independent; a
    module may carry any of them, and assembly emits the static block
    first, then the subject's text, then the live data. There is
    deliberately no ``kind`` column.
    """

    __tablename__ = "context_module"

    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(unique=True, index=True)
    name: str
    description: str | None = None
    category: str | None = None
    prompt_content: str | None = None
    fetch_function: str | None = None
    # A server default too, for rows written outside the ORM (the rename's
    # carry-over copies modules that predate the column).
    per_subject: bool = Field(default=False, sa_column_kwargs={"server_default": false()})
    context_key: str
    supports_days_back: bool = Field(default=False)
    default_days_back: int | None = None
    priority: int = Field(default=100)
    token_estimate: int = Field(default=0)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
