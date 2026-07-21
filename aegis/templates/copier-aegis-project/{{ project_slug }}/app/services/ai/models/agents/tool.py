"""Tool registry model."""

from sqlmodel import Field, SQLModel


class Tool(SQLModel, table=True):
    """
    A registered tool an agent can call.

    ``name`` keys into the Python tool registry; a row whose name has no
    registered callable is skipped with a warning at load time, never an
    error.
    """

    __tablename__ = "tool"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    description: str | None = None
    is_active: bool = Field(default=True)
