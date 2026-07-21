"""Memory module model."""

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class MemoryModule(SQLModel, table=True):
    """
    A reusable prompt-context block agents opt into via
    ``Agent.memory_modules``.

    Hybrid by design: ``prompt_content`` (static text) and
    ``fetch_function`` (a registered fetcher name) are independent
    columns; a module may carry either or both, and assembly emits the
    static block first, then the live data. There is deliberately no
    ``kind`` column.
    """

    __tablename__ = "memory_module"

    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(unique=True, index=True)
    name: str
    description: str | None = None
    category: str | None = None
    prompt_content: str | None = None
    fetch_function: str | None = None
    context_key: str
    supports_days_back: bool = Field(default=False)
    default_days_back: int | None = None
    priority: int = Field(default=100)
    token_estimate: int = Field(default=0)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
