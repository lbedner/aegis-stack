"""A conversation as the AI service holds it in memory, its messages and
their streaming, and the service's status."""

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.core.figures import FIGURES
from app.services.ai.models.providers import AIProvider


class MessageRole(str, Enum):
    """Message roles in a conversation."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ConversationMessage(BaseModel):
    """A single message in a conversation."""

    id: str = Field(..., description="Unique message identifier")
    role: MessageRole
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


class Conversation(BaseModel):
    """A conversation containing multiple messages."""

    id: str = Field(..., description="Unique conversation identifier")
    title: str | None = None
    messages: list[ConversationMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    provider: AIProvider
    model: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    def add_message(
        self,
        role: MessageRole,
        content: str,
        message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationMessage:
        """Add a new message to the conversation.

        ``metadata`` is persisted with the row and read back on load, so
        anything a message needs to remember beyond its text - which
        images rode it, for instance - belongs here.
        """
        import uuid

        message = ConversationMessage(
            id=message_id or str(uuid.uuid4()),
            role=role,
            content=content,
            metadata=metadata or {},
        )
        self.messages.append(message)
        self.updated_at = datetime.now(UTC)

        # Auto-generate title from first user message
        if not self.title and role == MessageRole.USER and len(self.messages) == 1:
            # Use first 50 characters as title
            self.title = content[:50] + "..." if len(content) > 50 else content

        return message

    def get_message_count(self) -> int:
        """Get total number of messages in conversation."""
        return len(self.messages)

    def get_last_message(self) -> ConversationMessage | None:
        """Get the most recent message."""
        return self.messages[-1] if self.messages else None


class StreamingMessage(BaseModel):
    """A streaming message chunk with metadata."""

    content: str = Field(..., description="Partial or complete message content")
    is_final: bool = Field(False, description="Whether this is the final chunk")
    is_delta: bool = Field(False, description="Whether content is delta or cumulative")
    message_id: str | None = Field(None, description="Message ID once finalized")
    conversation_id: str | None = Field(None, description="Associated conversation ID")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


class StreamingConversation(BaseModel):
    """Extended conversation model for streaming state management."""

    conversation: Conversation
    current_message_id: str | None = None
    accumulated_content: str = ""
    stream_start_time: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def reset_stream(self) -> None:
        """Reset streaming state for new message."""
        self.current_message_id = None
        self.accumulated_content = ""
        self.stream_start_time = datetime.now(UTC)

    def accumulate_content(self, content: str, is_delta: bool = False) -> str:
        """Accumulate streaming content and return total content."""
        if is_delta:
            self.accumulated_content += content
        else:
            self.accumulated_content = content
        return self.accumulated_content


class ConversationStats(BaseModel):
    """How much has been said, across every user: the health check's and
    the service status's counts."""

    model_config = FIGURES

    total_conversations: int
    total_messages: int
    unique_users: int
    average_messages_per_conversation: float


class AIServiceStatus(BaseModel):
    """Status information for the AI service."""

    enabled: bool
    provider: AIProvider
    model: str
    available_providers: list[AIProvider]
    conversation_count: int = 0
    last_activity: datetime | None = None
