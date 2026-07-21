"""Agent-tool link table."""

from sqlalchemy import Column, ForeignKey, Integer
from sqlmodel import Field, SQLModel


class AgentTool(SQLModel, table=True):
    """
    Attaches a registered tool to an agent.

    Link rows are agent-owned: deleting an agent (or a tool) removes its
    links via ON DELETE CASCADE.
    """

    __tablename__ = "agent_tool"

    id: int | None = Field(default=None, primary_key=True)
    agent_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("agent.id", ondelete="CASCADE"), nullable=False
        )
    )
    tool_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("tool.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
