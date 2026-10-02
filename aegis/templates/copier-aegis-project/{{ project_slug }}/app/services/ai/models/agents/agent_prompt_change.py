"""An agent's prompt history: one row per change to its system prompt."""

from datetime import datetime

from app.core.time import utcnow
from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel


class AgentPromptChange(SQLModel, table=True):
    """One change to an agent's system prompt, the seed included.

    The agent row is the only source of its prompt; code seeds it once.
    This is the record of what it was and why it changed, and reverting
    is setting an earlier one. ``source`` says what wrote it: ``seed``,
    ``cli``, ``dashboard``, or ``migration`` for the prompt an install had
    when history began. The newest id is also the loader cache's
    version, so a change made in another process reaches the next turn.
    """

    __tablename__ = "agent_prompt_change"

    id: int | None = Field(default=None, primary_key=True)
    agent_id: int = Field(foreign_key="agent.id", index=True)
    system_prompt: str = Field(sa_column=Column(Text, nullable=False))
    source: str = Field(max_length=16)
    note: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
