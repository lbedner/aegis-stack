"""Tool registry model."""

from sqlmodel import Field, SQLModel


class Tool(SQLModel, table=True):
    """
    A registered tool an agent can call.

    ``name`` keys into the tool registry (``app.core.tools``); resolution
    rules live in ``resolve_tools``.
    """

    __tablename__ = "tool"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    description: str | None = None
    is_active: bool = Field(default=True)
