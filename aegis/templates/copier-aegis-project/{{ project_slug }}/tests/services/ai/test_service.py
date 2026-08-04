"""Tests for AI service core functionality."""

import pytest
from app.core.config import settings
from app.services.ai.models import AIProvider
from app.services.ai.service import AIService


class TestAIServiceInitialization:
    """Test AI service initialization."""

    def test_service_initialization(self) -> None:
        """Test that AIService initializes correctly."""
        service = AIService(settings)

        assert service.settings == settings
        assert service.config is not None
        assert service.conversation_manager is not None

    def test_service_config_loaded(self) -> None:
        """Test that configuration is loaded from settings."""
        service = AIService(settings)

        assert hasattr(service.config, "enabled")
        assert hasattr(service.config, "provider")
        assert hasattr(service.config, "model")


class TestAIServiceStatus:
    """Test AI service status reporting."""

    def test_get_service_status_structure(self) -> None:
        """Test that service status has expected structure."""
        service = AIService(settings)
        status = service.get_service_status()

        assert isinstance(status, dict)
        assert "enabled" in status
        assert "provider" in status
        assert "model" in status
        assert "agent_initialized" in status
        assert "total_conversations" in status
        assert "configuration_valid" in status

    def test_get_service_status_provider_type(self) -> None:
        """Test that provider in status is returned as string for serialization."""
        service = AIService(settings)
        status = service.get_service_status()

        provider = status["provider"]

        # Provider should be string for JSON serialization
        assert isinstance(provider, str)
        # Should be a valid provider value
        assert provider in [p.value for p in AIProvider]

    def test_get_service_status_enabled_bool(self) -> None:
        """Test that enabled is a boolean."""
        service = AIService(settings)
        status = service.get_service_status()

        assert isinstance(status["enabled"], bool)

    def test_get_service_status_agent_initialized(self) -> None:
        """Test that agent_initialized is always True."""
        service = AIService(settings)
        status = service.get_service_status()

        # Agents created per request, always available
        assert status["agent_initialized"] is True

    def test_get_service_status_configuration_valid(self) -> None:
        """Test that configuration_valid reflects validation state."""
        service = AIService(settings)
        status = service.get_service_status()

        assert isinstance(status["configuration_valid"], bool)

    def test_get_service_status_conversation_count(self) -> None:
        """Test that total_conversations is a non-negative integer."""
        service = AIService(settings)
        status = service.get_service_status()

        # In SQLite mode, database may contain data from previous runs
        # Just verify it's a valid non-negative count
        assert isinstance(status["total_conversations"], int)
        assert status["total_conversations"] >= 0


class TestAIServiceValidation:
    """Test AI service validation."""

    def test_validate_service_returns_list(self) -> None:
        """Test that validate_service returns list of errors."""
        service = AIService(settings)
        errors = service.validate_service()

        assert isinstance(errors, list)
        assert all(isinstance(e, str) for e in errors)

    def test_validate_service_with_valid_config(self) -> None:
        """Test validation with valid configuration."""
        service = AIService(settings)
        errors = service.validate_service()

        # PUBLIC provider should have no errors (no API key required)
        if service.config.provider == AIProvider.PUBLIC:
            assert len(errors) == 0


class TestAIServiceConversationManagement:
    """Test conversation management methods."""

    def test_get_conversation_not_found(self) -> None:
        """Test getting non-existent conversation."""
        service = AIService(settings)
        conversation = service.get_conversation("nonexistent-id")

        assert conversation is None

    def test_list_conversations_returns_list(self) -> None:
        """Test that list_conversations returns a list.

        In SQLite mode, database may contain data from previous test runs,
        so we use a unique user ID that should have no conversations.
        """
        import uuid

        service = AIService(settings)
        unique_user = f"test-user-{uuid.uuid4()}"
        conversations = service.list_conversations(unique_user)

        assert isinstance(conversations, list)
        # New unique user should have no conversations
        assert len(conversations) == 0

    def test_conversation_manager_integration(self) -> None:
        """Test that conversation manager is properly integrated."""
        service = AIService(settings)

        # ConversationManager should be accessible
        assert hasattr(service, "conversation_manager")
        # Manager should have get_stats method
        stats = service.conversation_manager.get_stats()
        assert isinstance(stats, dict)
        assert "total_conversations" in stats


class TestAIServiceConfigIntegration:
    """Test integration with configuration."""

    def test_config_provider_is_enum(self) -> None:
        """Test that config provider is an enum instance.

        Provider should be an AIProvider enum for clean typed usage.
        Use .value when string representation is needed.
        """
        service = AIService(settings)

        # Config provider is an AIProvider enum
        assert isinstance(service.config.provider, AIProvider)

        # Should be able to get a string value with .value. Which provider the
        # project is pointed at is deployment configuration, not a property of
        # the code, so pinning one here would fail the moment anyone set
        # AI_PROVIDER to something else.
        assert service.config.provider.value in {p.value for p in AIProvider}

    def test_service_uses_config_correctly(self) -> None:
        """Test that service uses config values correctly."""
        service = AIService(settings)

        # Service should use config values
        assert service.config.enabled is not None
        assert service.config.model is not None
        assert service.config.temperature is not None


class TestAIServiceErrorHandling:
    """Test error handling in AI service."""

    @pytest.mark.asyncio
    async def test_chat_disabled_service_error(self, mock_ai_settings) -> None:
        """Test that chat raises error when service is disabled."""
        # Disable AI service
        mock_ai_settings.AI_ENABLED = False

        service = AIService(mock_ai_settings)

        with pytest.raises(Exception) as exc_info:
            await service.chat("test message")

        assert "disabled" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_stream_chat_disabled_service_error(self, mock_ai_settings) -> None:
        """Test that stream_chat raises error when service is disabled."""
        # Disable AI service
        mock_ai_settings.AI_ENABLED = False

        service = AIService(mock_ai_settings)

        with pytest.raises(Exception) as exc_info:
            async for _ in service.stream_chat("test message"):
                pass

        assert "disabled" in str(exc_info.value).lower()
