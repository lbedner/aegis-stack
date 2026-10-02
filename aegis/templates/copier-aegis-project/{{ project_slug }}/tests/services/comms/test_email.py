"""
Tests for email service functionality.
"""

from unittest.mock import patch

import pytest

from app.services.comms.email import (
    EmailConfigurationError,
    EmailError,
    get_email_status,
    send_email,
    send_email_simple,
    validate_email_config,
)
from app.services.comms.models import MessageStatus, SendEmailRequest
from tests.services.comms._settings import secret_settings


class TestEmailConfiguration:
    """Test email service configuration validation."""

    async def test_get_email_status_configured(self) -> None:
        """Test status when fully configured."""
        with secret_settings() as mock_settings:
            mock_settings.RESEND_API_KEY = "re_test_key"
            mock_settings.RESEND_FROM_EMAIL = "test@example.com"

            status = await get_email_status()

            assert status["configured"] is True
            assert status["api_key_set"] is True
            assert status["from_email_set"] is True
            assert status["from_email"] == "test@example.com"

    async def test_get_email_status_not_configured(self) -> None:
        """Test status when not configured."""
        with secret_settings() as mock_settings:
            mock_settings.RESEND_API_KEY = None
            mock_settings.RESEND_FROM_EMAIL = None

            status = await get_email_status()

            assert status["configured"] is False
            assert status["api_key_set"] is False
            assert status["from_email_set"] is False

    async def test_validate_email_config_valid(self) -> None:
        """Test validation with valid configuration."""
        with secret_settings() as mock_settings:
            mock_settings.RESEND_API_KEY = "re_test_key"
            mock_settings.RESEND_FROM_EMAIL = "test@example.com"

            errors = await validate_email_config()

            assert len(errors) == 0

    async def test_validate_email_config_missing_api_key(self) -> None:
        """Test validation when API key is missing."""
        with secret_settings() as mock_settings:
            mock_settings.RESEND_API_KEY = None
            mock_settings.RESEND_FROM_EMAIL = "test@example.com"

            errors = await validate_email_config()

            assert len(errors) == 1
            assert "RESEND_API_KEY" in errors[0]

    async def test_validate_email_config_missing_from_email(self) -> None:
        """Test validation when from email is missing."""
        with secret_settings() as mock_settings:
            mock_settings.RESEND_API_KEY = "re_test_key"
            mock_settings.RESEND_FROM_EMAIL = None

            errors = await validate_email_config()

            assert len(errors) == 1
            assert "RESEND_FROM_EMAIL" in errors[0]


class TestSendEmail:
    """Test email sending functionality."""

    @pytest.mark.asyncio
    async def test_send_email_success(self) -> None:
        """Test successful email send."""
        with (
            secret_settings() as mock_settings,
            patch("app.services.comms.email.resend") as mock_resend,
        ):
            mock_settings.RESEND_API_KEY = "re_test_key"
            mock_settings.RESEND_FROM_EMAIL = "test@example.com"
            mock_resend.Emails.send.return_value = {"id": "email-123"}

            request = SendEmailRequest(
                to=["user@example.com"],
                subject="Test Subject",
                text="Test body",
            )

            result = await send_email(request)

            assert result.id == "email-123"
            assert result.to == ["user@example.com"]
            assert result.status == MessageStatus.SENT

    @pytest.mark.asyncio
    async def test_send_email_with_html(self) -> None:
        """Test email send with HTML body."""
        with (
            secret_settings() as mock_settings,
            patch("app.services.comms.email.resend") as mock_resend,
        ):
            mock_settings.RESEND_API_KEY = "re_test_key"
            mock_settings.RESEND_FROM_EMAIL = "test@example.com"
            mock_resend.Emails.send.return_value = {"id": "email-456"}

            request = SendEmailRequest(
                to=["user@example.com"],
                subject="Test Subject",
                html="<h1>Test</h1>",
            )

            result = await send_email(request)

            assert result.id == "email-456"
            # Verify HTML was passed to resend
            call_args = mock_resend.Emails.send.call_args[0][0]
            assert "html" in call_args

    @pytest.mark.asyncio
    async def test_send_email_missing_api_key(self) -> None:
        """Test email send fails when API key is missing."""
        with secret_settings() as mock_settings:
            mock_settings.RESEND_API_KEY = None
            mock_settings.RESEND_FROM_EMAIL = "test@example.com"

            request = SendEmailRequest(
                to=["user@example.com"],
                subject="Test",
                text="Test",
            )

            with pytest.raises(EmailConfigurationError) as exc_info:
                await send_email(request)

            assert "RESEND_API_KEY" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_send_email_missing_from_email(self) -> None:
        """Test email send fails when from email is missing."""
        with secret_settings() as mock_settings:
            mock_settings.RESEND_API_KEY = "re_test_key"
            mock_settings.RESEND_FROM_EMAIL = None

            request = SendEmailRequest(
                to=["user@example.com"],
                subject="Test",
                text="Test",
                from_email=None,  # Also not provided in request
            )

            with pytest.raises(EmailConfigurationError) as exc_info:
                await send_email(request)

            assert "sender email" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_send_email_missing_content(self) -> None:
        """Test email send fails when no content is provided."""
        with secret_settings() as mock_settings:
            mock_settings.RESEND_API_KEY = "re_test_key"
            mock_settings.RESEND_FROM_EMAIL = "test@example.com"

            request = SendEmailRequest(
                to=["user@example.com"],
                subject="Test",
                # No text or html
            )

            with pytest.raises(EmailError) as exc_info:
                await send_email(request)

            assert (
                "text" in str(exc_info.value).lower()
                or "html" in str(exc_info.value).lower()
            )


class TestSendEmailSimple:
    """Test simplified email sending function."""

    @pytest.mark.asyncio
    async def test_send_email_simple_with_string_recipient(self) -> None:
        """Test simple send with single string recipient."""
        with (
            secret_settings() as mock_settings,
            patch("app.services.comms.email.resend") as mock_resend,
        ):
            mock_settings.RESEND_API_KEY = "re_test_key"
            mock_settings.RESEND_FROM_EMAIL = "test@example.com"
            mock_settings.SUPPORT_REPLY_TO_EMAIL = None
            mock_resend.Emails.send.return_value = {"id": "email-789"}

            result = await send_email_simple(
                to="user@example.com",
                subject="Test",
                text="Test body",
            )

            assert result.id == "email-789"

    @pytest.mark.asyncio
    async def test_send_email_simple_with_list_recipient(self) -> None:
        """Test simple send with list of recipients."""
        with (
            secret_settings() as mock_settings,
            patch("app.services.comms.email.resend") as mock_resend,
        ):
            mock_settings.RESEND_API_KEY = "re_test_key"
            mock_settings.RESEND_FROM_EMAIL = "test@example.com"
            mock_settings.SUPPORT_REPLY_TO_EMAIL = None
            mock_resend.Emails.send.return_value = {"id": "email-101"}

            result = await send_email_simple(
                to=["user1@example.com", "user2@example.com"],
                subject="Test",
                html="<p>Test</p>",
            )

            assert result.id == "email-101"
