"""
Test conversation persistence and memory at the service layer.

Tests the core AIService and ConversationManager classes to ensure
conversation memory works correctly for both streaming and non-streaming modes.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

from app.services.ai.domains.chat.conversation import ConversationManager
from app.services.ai.models import (
    AIProvider,
    MessageRole,
)
from app.services.ai.service import AIService


@pytest.fixture
def mock_settings():
    """Mock settings for testing."""
    settings = MagicMock()
    settings.AI_ENABLED = True
    settings.AI_PROVIDER = "openai"
    settings.AI_MODEL = "gpt-4"
    settings.OPENAI_API_KEY = "test-key"
    # ``AIServiceConfig.from_settings`` now reads RAG_CHAT_* off settings
    # and Pydantic validates them as real str/int/float — a bare
    # ``MagicMock`` attribute auto-generates a child mock and fails
    # validation with a confusing ``string_type`` error.
    settings.RAG_CHAT_DEFAULT_COLLECTION = "default"
    settings.RAG_CHAT_TOP_K = 10
    settings.RAG_CHAT_MIN_SCORE = 0.1
    return settings


@pytest.fixture(autouse=True)
def _no_user_memory_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the guarded user-memory block out of ``AIService.chat``.

    It opens the app's REAL async engine, which binds that engine's pool to
    whichever test loop touches it first - after which any later test on a
    fresh loop dies inside asyncpg. These tests are about conversation
    persistence, not memory.
    """

    async def no_memory(user_id: str, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        "app.services.ai.service.chat.build_user_memory_context", no_memory
    )
    monkeypatch.setattr(
        "app.services.ai.service.streaming.build_user_memory_context", no_memory
    )


@pytest.fixture
def conversation_manager():
    """Create a conversation manager for testing."""
    return ConversationManager()


@pytest.fixture
def sample_conversation(conversation_manager):
    """Create a sample conversation with message history."""
    conversation = conversation_manager.create_conversation(
        provider=AIProvider.OPENAI, model="gpt-4", user_id="test-user"
    )

    # Add some message history
    conversation.add_message(MessageRole.USER, "What is Python?")
    conversation.add_message(MessageRole.ASSISTANT, "Python is a programming language.")
    conversation.add_message(MessageRole.USER, "Tell me more about its features.")

    conversation_manager.save_conversation(conversation)
    return conversation


class TestConversationManager:
    """Test ConversationManager for memory persistence."""

    def test_create_and_retrieve_conversation(self, conversation_manager):
        """Test creating and retrieving conversations."""
        conversation = conversation_manager.create_conversation(
            provider=AIProvider.OPENAI,
            model="gpt-4",
            user_id="test-user",
            conversation_id="specific-id-123",
        )

        assert conversation.id == "specific-id-123"
        assert conversation.provider == AIProvider.OPENAI
        assert conversation.model == "gpt-4"
        assert conversation.metadata["user_id"] == "test-user"

        # Retrieve the conversation
        retrieved = conversation_manager.get_conversation("specific-id-123")
        assert retrieved is not None
        assert retrieved.id == conversation.id
        assert retrieved.provider == conversation.provider

    def test_conversation_auto_id_generation(self, conversation_manager):
        """Test that conversations get auto-generated IDs when not specified."""
        conversation = conversation_manager.create_conversation(
            provider=AIProvider.OPENAI, model="gpt-4", user_id="test-user"
        )

        assert conversation.id is not None
        assert len(conversation.id) > 0
        # Should be a valid UUID format
        uuid.UUID(conversation.id)  # Will raise ValueError if invalid

    def test_save_and_update_conversation(self, conversation_manager):
        """Test saving and updating conversations."""
        conversation = conversation_manager.create_conversation(
            provider=AIProvider.OPENAI, model="gpt-4", user_id="test-user"
        )

        # Normalize to offset-aware for comparison (SQLite returns offset-aware)
        original_updated_at = conversation.updated_at
        if original_updated_at.tzinfo is None:
            original_updated_at = original_updated_at.replace(tzinfo=UTC)

        # Add a message and save
        conversation.add_message(MessageRole.USER, "Test message")
        conversation_manager.save_conversation(conversation)

        # Verify the conversation was updated
        retrieved = conversation_manager.get_conversation(conversation.id)
        assert retrieved.get_message_count() == 1

        # Normalize retrieved timestamp for comparison
        retrieved_updated_at = retrieved.updated_at
        if retrieved_updated_at.tzinfo is None:
            retrieved_updated_at = retrieved_updated_at.replace(tzinfo=UTC)

        assert retrieved_updated_at >= original_updated_at

    def test_list_conversations_by_user(self, conversation_manager):
        """Test listing conversations filtered by user."""
        # Use unique user IDs for this test run to avoid conflicts with persisted data
        unique_suffix = str(uuid.uuid4())[:8]
        user1_id = f"user-1-{unique_suffix}"
        user2_id = f"user-2-{unique_suffix}"

        # Create conversations for different users
        conv1 = conversation_manager.create_conversation(
            provider=AIProvider.OPENAI, model="gpt-4", user_id=user1_id
        )
        conv2 = conversation_manager.create_conversation(
            provider=AIProvider.OPENAI, model="gpt-4", user_id=user2_id
        )
        conv3 = conversation_manager.create_conversation(
            provider=AIProvider.OPENAI, model="gpt-4", user_id=user1_id
        )

        # List conversations for user-1
        user1_conversations = conversation_manager.list_conversations(user1_id)
        user1_ids = [conv.id for conv in user1_conversations]

        assert len(user1_conversations) == 2
        assert conv1.id in user1_ids
        assert conv3.id in user1_ids
        assert conv2.id not in user1_ids

    def test_conversation_message_history(self, sample_conversation):
        """Test that conversation maintains message history correctly."""
        assert sample_conversation.get_message_count() == 3

        messages = sample_conversation.messages
        assert messages[0].role == MessageRole.USER
        assert messages[0].content == "What is Python?"
        assert messages[1].role == MessageRole.ASSISTANT
        assert messages[1].content == "Python is a programming language."
        assert messages[2].role == MessageRole.USER
        assert messages[2].content == "Tell me more about its features."

    def test_conversation_context_building(self, sample_conversation):
        """Test conversation context building from message history."""
        # Simulate the _build_conversation_context method logic
        recent_messages = sample_conversation.messages[-10:]  # Last 10 messages
        context_parts = []

        for msg in recent_messages[:-1]:  # Exclude latest message
            if msg.role == MessageRole.USER:
                context_parts.append(f"User: {msg.content}")
            elif msg.role == MessageRole.ASSISTANT:
                context_parts.append(f"Assistant: {msg.content}")

        # Add the current user message
        latest_message = sample_conversation.get_last_message()
        if latest_message and latest_message.role == MessageRole.USER:
            full_context = (
                "\n".join(context_parts) + f"\n\nUser: {latest_message.content}"
            )

        assert "User: What is Python?" in full_context
        assert "Assistant: Python is a programming language." in full_context
        assert "User: Tell me more about its features." in full_context


class TestAIServiceConversationMemory:
    """Test AIService conversation memory functionality."""

    def test_ai_service_initialization(self, mock_settings):
        """Test AIService initializes with conversation manager."""
        with patch("app.services.ai.config.get_ai_config") as mock_config:
            mock_config.return_value.enabled = True
            mock_config.return_value.provider = AIProvider.OPENAI

            ai_service = AIService(mock_settings)

            assert ai_service.conversation_manager is not None
            assert isinstance(ai_service.conversation_manager, ConversationManager)

    @pytest.mark.asyncio
    async def test_chat_creates_conversation_when_none_provided(self, mock_settings):
        """Test that chat creates new conversation when none provided."""
        with (
            patch("app.services.ai.config.get_ai_config") as mock_config,
            patch("app.services.ai.service.prompt.get_agent") as mock_get_agent,
        ):
            # Setup mocks
            mock_config.return_value.enabled = True
            mock_config.return_value.provider = AIProvider.OPENAI
            mock_config.return_value.model = "gpt-4"

            mock_agent = AsyncMock()
            mock_agent.run = AsyncMock(return_value=MagicMock(output="Test response"))
            mock_get_agent.return_value = mock_agent

            ai_service = AIService(mock_settings)

            # Call chat without conversation_id
            response = await ai_service.chat(
                message="Hello AI", conversation_id=None, user_id="test-user"
            )

            assert response is not None
            assert response.content == "Test response"
            assert "conversation_id" in response.metadata

            # Verify conversation was created
            conv_id = response.metadata["conversation_id"]
            conversation = ai_service.get_conversation(conv_id)
            assert conversation is not None
            assert conversation.get_message_count() == 2  # User + AI messages

    @pytest.mark.asyncio
    async def test_chat_uses_existing_conversation(self, mock_settings):
        """Test that chat uses existing conversation when provided."""
        with (
            patch("app.services.ai.config.get_ai_config") as mock_config,
            patch("app.services.ai.service.prompt.get_agent") as mock_get_agent,
        ):
            # Setup mocks
            mock_config.return_value.enabled = True
            mock_config.return_value.provider = AIProvider.OPENAI
            mock_config.return_value.model = "gpt-4"

            mock_agent = AsyncMock()
            mock_agent.run = AsyncMock(return_value=MagicMock(output="Test response"))
            mock_get_agent.return_value = mock_agent

            ai_service = AIService(mock_settings)

            # Create initial conversation
            first_response = await ai_service.chat(
                message="First message", conversation_id=None, user_id="test-user"
            )

            first_conv_id = first_response.metadata["conversation_id"]

            # Continue conversation
            second_response = await ai_service.chat(
                message="Second message",
                conversation_id=first_conv_id,
                user_id="test-user",
            )

            # Should use same conversation
            second_conv_id = second_response.metadata["conversation_id"]
            assert second_conv_id == first_conv_id

            # Verify conversation has both messages
            conversation = ai_service.get_conversation(first_conv_id)
            assert conversation.get_message_count() == 4  # 2 user + 2 AI messages

    def test_conversation_memory_across_service_instances(self, mock_settings):
        """Test conversation memory behavior across service instances.

        In-memory mode: Each instance has isolated storage (retrieved is None)
        SQLite mode: Instances share database storage (retrieved is not None)
        """
        with patch("app.services.ai.config.get_ai_config") as mock_config:
            mock_config.return_value.enabled = True
            mock_config.return_value.provider = AIProvider.OPENAI

            # Create first service instance and conversation
            service1 = AIService(mock_settings)
            conversation = service1.conversation_manager.create_conversation(
                provider=AIProvider.OPENAI, model="gpt-4", user_id="test-user"
            )
            conversation.add_message(MessageRole.USER, "Test message")
            service1.conversation_manager.save_conversation(conversation)

            # Create second service instance
            service2 = AIService(mock_settings)

            # Try to retrieve from second instance
            retrieved = service2.conversation_manager.get_conversation(conversation.id)

            # Check if using database persistence (has db_session import)
            try:
                from app.core.db import db_session  # noqa: F401

                uses_database = True
            except ImportError:
                uses_database = False

            if uses_database:
                # SQLite mode: conversations persist across instances
                assert retrieved is not None
                assert retrieved.id == conversation.id
            else:
                # In-memory mode: each instance has isolated storage
                assert retrieved is None


class TestConversationMemoryEdgeCases:
    """Test edge cases for conversation memory."""

    def test_conversation_manager_nonexistent_conversation(self, conversation_manager):
        """Test retrieving non-existent conversation returns None."""
        result = conversation_manager.get_conversation("nonexistent-id")
        assert result is None

    def test_conversation_manager_empty_message_list(self, conversation_manager):
        """Test conversation with no messages."""
        conversation = conversation_manager.create_conversation(
            provider=AIProvider.OPENAI, model="gpt-4", user_id="test-user"
        )

        assert conversation.get_message_count() == 0
        assert conversation.messages == []
        assert conversation.get_last_message() is None

    def test_conversation_metadata_updates(self, conversation_manager):
        """Test that conversation metadata gets updated properly."""
        conversation = conversation_manager.create_conversation(
            provider=AIProvider.OPENAI, model="gpt-4", user_id="test-user"
        )

        # Update metadata
        conversation.metadata.update(
            {
                "last_response_time_ms": 1500.0,
                "total_messages": 2,
                "last_activity": datetime.now(UTC).isoformat(),
                "streaming": True,
            }
        )

        conversation_manager.save_conversation(conversation)

        # Retrieve and verify metadata
        retrieved = conversation_manager.get_conversation(conversation.id)
        assert retrieved.metadata["last_response_time_ms"] == 1500.0
        assert retrieved.metadata["total_messages"] == 2
        assert retrieved.metadata["streaming"] is True

    def test_conversation_cleanup_old_conversations(self, conversation_manager):
        """Test cleanup of old conversations.

        Note: In SQLite mode, we need to update the database timestamp directly.
        In memory mode, modifying the object's updated_at is sufficient.

        SQLite stores datetimes as strings and returns naive datetimes. When comparing
        timestamps, naive datetimes are interpreted as local time. To ensure the test
        works consistently, we use a time far enough in the past to account for any
        timezone differences.
        """
        from datetime import timedelta

        # Use unique user ID to isolate this test from other data
        unique_user = f"cleanup-test-{uuid.uuid4()}"

        # Create some conversations
        old_conversation = conversation_manager.create_conversation(
            provider=AIProvider.OPENAI, model="gpt-4", user_id=unique_user
        )

        recent_conversation = conversation_manager.create_conversation(
            provider=AIProvider.OPENAI, model="gpt-4", user_id=unique_user
        )

        # Save both conversations
        conversation_manager.save_conversation(old_conversation)
        conversation_manager.save_conversation(recent_conversation)

        # Set old timestamp - use 48 hours to account for timezone differences
        # SQLite returns naive datetimes, which timestamp() interprets as local time
        old_time = datetime.now(UTC) - timedelta(hours=48)

        # Check if using database persistence
        try:
            from app.core.db import db_session
            from app.models.conversation import Conversation as ConversationModel

            # SQLite mode: update database directly
            # Store as naive datetime to match how SQLite handles it
            with db_session() as session:
                conv_db = session.get(ConversationModel, old_conversation.id)
                if conv_db:
                    # Remove tzinfo for consistent storage
                    conv_db.updated_at = old_time.replace(tzinfo=None)
                    session.add(conv_db)
                    session.commit()
        except ImportError:
            # Memory mode: update object directly
            old_conversation.updated_at = old_time

        # Cleanup conversations older than 24 hours
        cleaned_count = conversation_manager.cleanup_old_conversations(max_age_hours=24)

        assert cleaned_count >= 1  # At least our old conversation should be cleaned
        assert conversation_manager.get_conversation(old_conversation.id) is None
        assert conversation_manager.get_conversation(recent_conversation.id) is not None


class TestSurfaceScopingAndTitles:
    """New conversations carry a surface tag and a first-message title."""

    def _service(self, mock_settings) -> "AIService":
        return AIService(mock_settings)

    async def _chat(
        self, ai_service, message: str, surface: str | None, user_id: str
    ) -> str:
        response = await ai_service.chat(
            message=message, user_id=user_id, surface=surface
        )
        return response.metadata["conversation_id"]

    @pytest.mark.asyncio
    async def test_new_conversation_records_surface_and_title(self, mock_settings):
        with (
            patch("app.services.ai.config.get_ai_config") as mock_config,
            patch("app.services.ai.service.prompt.get_agent") as mock_get_agent,
        ):
            mock_config.return_value.enabled = True
            mock_config.return_value.provider = AIProvider.OPENAI
            mock_config.return_value.model = "gpt-4"
            mock_agent = AsyncMock()
            mock_agent.run = AsyncMock(return_value=MagicMock(output="ok"))
            mock_get_agent.return_value = mock_agent
            ai_service = self._service(mock_settings)

            user = f"scoped-{uuid.uuid4().hex[:8]}"
            conv_id = await self._chat(
                ai_service, "What is my burn rate this month?", "finance", user
            )

            conversation = ai_service.get_conversation(conv_id)
            assert conversation.metadata.get("surface") == "finance"
            assert conversation.title == "What is my burn rate this month?"

    @pytest.mark.asyncio
    async def test_long_first_message_truncates_into_the_title(self, mock_settings):
        with (
            patch("app.services.ai.config.get_ai_config") as mock_config,
            patch("app.services.ai.service.prompt.get_agent") as mock_get_agent,
        ):
            mock_config.return_value.enabled = True
            mock_config.return_value.provider = AIProvider.OPENAI
            mock_config.return_value.model = "gpt-4"
            mock_agent = AsyncMock()
            mock_agent.run = AsyncMock(return_value=MagicMock(output="ok"))
            mock_get_agent.return_value = mock_agent
            ai_service = self._service(mock_settings)

            user = f"scoped-{uuid.uuid4().hex[:8]}"
            conv_id = await self._chat(ai_service, "x" * 100, None, user)

            conversation = ai_service.get_conversation(conv_id)
            assert len(conversation.title) == 60
            assert conversation.title.endswith("...")

    @pytest.mark.asyncio
    async def test_list_conversations_filters_by_surface(self, mock_settings):
        with (
            patch("app.services.ai.config.get_ai_config") as mock_config,
            patch("app.services.ai.service.prompt.get_agent") as mock_get_agent,
        ):
            mock_config.return_value.enabled = True
            mock_config.return_value.provider = AIProvider.OPENAI
            mock_config.return_value.model = "gpt-4"
            mock_agent = AsyncMock()
            mock_agent.run = AsyncMock(return_value=MagicMock(output="ok"))
            mock_get_agent.return_value = mock_agent
            ai_service = self._service(mock_settings)

            user = f"scoped-{uuid.uuid4().hex[:8]}"
            finance_id = await self._chat(
                ai_service, "finance question", "finance", user
            )
            await self._chat(ai_service, "general question", None, user)

            scoped = ai_service.list_conversations(user, surface="finance")
            assert [c.id for c in scoped] == [finance_id]

            all_convos = ai_service.list_conversations(user)
            assert len(all_convos) == 2
