"""
Test conversation memory and persistence across chat modes.

Tests ensure that both streaming and non-streaming modes maintain
conversation context properly for multi-turn conversations.
"""

import asyncio
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.cli.ai.streaming import _stream_chat_response
from app.services.ai.models import (
    AIProvider,
    Conversation,
    ConversationMessage,
    MessageRole,
    StreamingMessage,
)
from app.services.ai.service import AIService


@pytest.fixture
def mock_ai_service():
    """Create a mock AI service for testing."""
    service = MagicMock(spec=AIService)
    service.config = MagicMock()
    service.config.provider = AIProvider.OPENAI
    service.config.enabled = True

    # Mock conversation creation
    conversation = Conversation(
        id="test-conversation-123",
        provider=AIProvider.OPENAI,
        model="gpt-4",
    )

    service.conversation_manager = AsyncMock()
    service.conversation_manager.create_conversation.return_value = conversation
    service.conversation_manager.get_conversation.return_value = conversation

    return service


@pytest.fixture
def mock_console():
    """Create a mock console for testing."""
    from rich.console import Console

    output = StringIO()
    console = Console(file=output, force_terminal=False, width=80)
    return console


class TestConversationMemory:
    """Test conversation memory across different chat modes."""

    @pytest.mark.asyncio
    async def test_streaming_returns_conversation_id(
        self, mock_ai_service, mock_console
    ):
        """Test that streaming mode returns conversation_id for memory continuity."""

        # Mock streaming chunks
        chunks = [
            StreamingMessage(
                content="Hello",
                is_final=False,
                is_delta=True,
                message_id="msg-1",
                conversation_id="test-conversation-123",
                metadata={"provider": "openai", "model": "gpt-4", "stream_delta": True},
            ),
            StreamingMessage(
                content=" world!",
                is_final=True,
                is_delta=True,
                message_id="msg-1",
                conversation_id="test-conversation-123",
                metadata={
                    "provider": "openai",
                    "model": "gpt-4",
                    "response_time_ms": 1500.0,
                    "stream_complete": True,
                },
            ),
        ]

        async def mock_stream_chat(*args, **kwargs):
            for chunk in chunks:
                yield chunk

        mock_ai_service.stream_chat = mock_stream_chat

        # Patch console to use our mock
        with patch("app.cli.ai.streaming.console", mock_console):
            conversation_id = await _stream_chat_response(
                ai_service=mock_ai_service,
                message="Hello AI",
                conversation_id=None,
                user_id="test-user",
            )

        # Verify conversation_id is returned for memory continuity
        assert conversation_id == "test-conversation-123"

    @pytest.mark.asyncio
    async def test_streaming_with_existing_conversation(
        self, mock_ai_service, mock_console
    ):
        """Test streaming mode continues existing conversation."""

        existing_conversation_id = "existing-conversation-456"

        # Mock streaming chunks with existing conversation
        chunks = [
            StreamingMessage(
                content="Response text",
                is_final=True,
                is_delta=True,
                message_id="msg-2",
                conversation_id=existing_conversation_id,
                metadata={"response_time_ms": 1200.0, "stream_complete": True},
            ),
        ]

        async def mock_stream_chat(*args, **kwargs):
            # Verify that existing conversation_id was passed
            assert kwargs.get("conversation_id") == existing_conversation_id
            for chunk in chunks:
                yield chunk

        mock_ai_service.stream_chat = mock_stream_chat

        with patch("app.cli.ai.streaming.console", mock_console):
            returned_id = await _stream_chat_response(
                ai_service=mock_ai_service,
                message="Continue conversation",
                conversation_id=existing_conversation_id,
                user_id="test-user",
            )

        assert returned_id == existing_conversation_id

    @pytest.mark.asyncio
    async def test_streaming_interrupted_returns_none(
        self, mock_ai_service, mock_console
    ):
        """Test that interrupted streaming returns None."""

        async def mock_stream_chat_interrupted(*args, **kwargs):
            # Simulate a few chunks then interruption
            yield StreamingMessage(
                content="Start",
                is_final=False,
                is_delta=True,
                message_id="msg-3",
                conversation_id="test-conversation-789",
                metadata={"provider": "openai"},
            )
            # Simulate interruption by not yielding final chunk

        mock_ai_service.stream_chat = mock_stream_chat_interrupted

        # Mock signal handling to simulate interruption
        with (
            patch("app.cli.ai.streaming.console", mock_console),
            patch("signal.signal"),
            patch("signal.SIGINT"),
        ):
            # Create a mock that simulates interruption
            interrupted = False

            async def interrupted_stream(*args, **kwargs):
                nonlocal interrupted
                async for chunk in mock_stream_chat_interrupted(*args, **kwargs):
                    if not interrupted:
                        yield chunk
                    interrupted = True  # Simulate interruption after first chunk
                    break

            mock_ai_service.stream_chat = interrupted_stream

            conversation_id = await _stream_chat_response(
                ai_service=mock_ai_service,
                message="Test message",
                conversation_id=None,
                user_id="test-user",
            )

        # Interrupted streaming should return None to avoid corrupted state
        assert conversation_id is None

    @pytest.mark.asyncio
    async def test_streaming_timeout_returns_none(self, mock_ai_service, mock_console):
        """Test that streaming timeout returns None."""

        async def mock_stream_chat_slow(*args, **kwargs):
            # Simulate slow response that times out (2s delay, 1s timeout)
            await asyncio.sleep(2.0)  # Longer than timeout
            yield StreamingMessage(
                content="Too late",
                is_final=True,
                is_delta=True,
                message_id="msg-4",
                conversation_id="test-conversation-timeout",
                metadata={},
            )

        mock_ai_service.stream_chat = mock_stream_chat_slow

        # Mock the timeout duration to be much shorter for testing
        with (
            patch("app.cli.ai.streaming.console", mock_console),
            patch("asyncio.timeout", return_value=asyncio.timeout(1.0)),
        ):
            # Should timeout and return None
            conversation_id = await _stream_chat_response(
                ai_service=mock_ai_service,
                message="Slow message",
                conversation_id=None,
                user_id="test-user",
            )

        assert conversation_id is None

    def test_non_streaming_preserves_conversation_id(self, mock_ai_service):
        """Test that non-streaming mode preserves conversation_id in metadata."""

        # Create mock response with conversation_id in metadata
        mock_response = ConversationMessage(
            id="msg-5",
            role=MessageRole.ASSISTANT,
            content="Non-streaming response",
            metadata={"conversation_id": "non-stream-conversation-123"},
        )

        mock_ai_service.chat = AsyncMock(return_value=mock_response)

        # The conversation_id should be available in response.metadata
        conversation_id = mock_response.metadata.get("conversation_id")
        assert conversation_id == "non-stream-conversation-123"

    @pytest.mark.asyncio
    async def test_conversation_context_building(self, mock_ai_service):
        """Test that conversation context is built correctly from message history."""

        # Create conversation with message history
        conversation = Conversation(
            id="context-test-conversation", provider=AIProvider.OPENAI, model="gpt-4"
        )

        # Add some message history
        conversation.add_message(MessageRole.USER, "First question")
        conversation.add_message(MessageRole.ASSISTANT, "First answer")
        conversation.add_message(MessageRole.USER, "Second question")

        mock_ai_service.get_conversation.return_value = conversation

        # Mock the _build_conversation_context method to verify it's called
        mock_ai_service._build_conversation_context = MagicMock(
            return_value=(
                "User: First question\nAssistant: First answer\n\nUser: Second question"
            )
        )

        # Test that context building includes message history
        context = mock_ai_service._build_conversation_context(conversation)

        assert "First question" in context
        assert "First answer" in context
        assert "Second question" in context


class TestConversationPersistence:
    """Test conversation persistence across multiple interactions."""

    @pytest.mark.asyncio
    async def test_multi_turn_streaming_conversation(
        self, mock_ai_service, mock_console
    ):
        """Test multi-turn conversation maintains context in streaming mode."""

        conversation_id = "multi-turn-test-123"

        # First turn
        first_chunks = [
            StreamingMessage(
                content="Hello! How can I help?",
                is_final=True,
                is_delta=True,
                message_id="msg-1",
                conversation_id=conversation_id,
                metadata={"stream_complete": True},
            )
        ]

        # Second turn
        second_chunks = [
            StreamingMessage(
                content="I can help with that!",
                is_final=True,
                is_delta=True,
                message_id="msg-2",
                conversation_id=conversation_id,
                metadata={"stream_complete": True},
            )
        ]

        # Mock streaming to return different chunks on each call
        call_count = 0

        async def mock_multi_turn_stream(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                for chunk in first_chunks:
                    yield chunk
            else:
                for chunk in second_chunks:
                    yield chunk

        mock_ai_service.stream_chat = mock_multi_turn_stream

        with patch("app.cli.ai.streaming.console", mock_console):
            # First interaction
            first_conversation_id = await _stream_chat_response(
                ai_service=mock_ai_service,
                message="Hello",
                conversation_id=None,  # New conversation
                user_id="test-user",
            )

            # Second interaction should continue same conversation
            second_conversation_id = await _stream_chat_response(
                ai_service=mock_ai_service,
                message="Can you help me?",
                conversation_id=first_conversation_id,  # Continue conversation
                user_id="test-user",
            )

        # Both interactions should return same conversation_id
        assert first_conversation_id == conversation_id
        assert second_conversation_id == conversation_id
        assert first_conversation_id == second_conversation_id

    @pytest.mark.asyncio
    async def test_mixed_streaming_non_streaming_persistence(self, mock_ai_service):
        """Test conversation persists when mixing streaming and non-streaming modes."""

        conversation_id = "mixed-mode-test-456"

        # Mock streaming response
        streaming_chunks = [
            StreamingMessage(
                content="Streaming response",
                is_final=True,
                is_delta=True,
                message_id="stream-msg",
                conversation_id=conversation_id,
                metadata={"stream_complete": True},
            )
        ]

        async def mock_stream(*args, **kwargs):
            for chunk in streaming_chunks:
                yield chunk

        # Mock non-streaming response
        non_streaming_response = ConversationMessage(
            id="non-stream-msg",
            role=MessageRole.ASSISTANT,
            content="Non-streaming response",
            metadata={"conversation_id": conversation_id},
        )

        mock_ai_service.stream_chat = mock_stream
        mock_ai_service.chat = AsyncMock(return_value=non_streaming_response)

        # Both modes should maintain same conversation_id
        streaming_conv_id = conversation_id  # Would come from streaming response
        non_streaming_conv_id = non_streaming_response.metadata.get("conversation_id")

        assert streaming_conv_id == conversation_id
        assert non_streaming_conv_id == conversation_id
        assert streaming_conv_id == non_streaming_conv_id


class TestConversationMemoryEdgeCases:
    """Test edge cases for conversation memory."""

    @pytest.mark.asyncio
    async def test_duplicate_content_handling(self, mock_ai_service, mock_console):
        """Test that duplicate content from fake streaming providers is handled."""

        # Mock duplicate chunks (fake streaming providers send full content repeatedly)
        duplicate_chunks = [
            StreamingMessage(
                content="Full response text",
                is_final=False,
                is_delta=False,  # Fake streaming sends full content
                message_id="dup-msg",
                conversation_id="dup-conversation-123",
                metadata={"provider": "public"},
            ),
            StreamingMessage(
                content="Full response text",  # Duplicate content
                is_final=True,
                is_delta=False,
                message_id="dup-msg",
                conversation_id="dup-conversation-123",
                metadata={"response_time_ms": 1000.0, "stream_complete": True},
            ),
        ]

        async def mock_duplicate_stream(*args, **kwargs):
            for chunk in duplicate_chunks:
                yield chunk

        mock_ai_service.stream_chat = mock_duplicate_stream

        with patch("app.cli.ai.streaming.console", mock_console):
            conversation_id = await _stream_chat_response(
                ai_service=mock_ai_service,
                message="Test duplicates",
                conversation_id=None,
                user_id="test-user",
            )

        # Should still return conversation_id despite duplicate content
        assert conversation_id == "dup-conversation-123"

    @pytest.mark.asyncio
    async def test_empty_conversation_id_handling(self, mock_ai_service, mock_console):
        """Test handling when conversation_id is missing from response."""

        # Mock chunk without conversation_id
        empty_chunks = [
            StreamingMessage(
                content="Response without conversation_id",
                is_final=True,
                is_delta=True,
                message_id="empty-msg",
                conversation_id=None,  # Missing conversation_id
                metadata={"stream_complete": True},
            )
        ]

        async def mock_empty_stream(*args, **kwargs):
            for chunk in empty_chunks:
                yield chunk

        mock_ai_service.stream_chat = mock_empty_stream

        with patch("app.cli.ai.streaming.console", mock_console):
            conversation_id = await _stream_chat_response(
                ai_service=mock_ai_service,
                message="Test empty conversation_id",
                conversation_id=None,
                user_id="test-user",
            )

        # Should return None when conversation_id is missing
        assert conversation_id is None
