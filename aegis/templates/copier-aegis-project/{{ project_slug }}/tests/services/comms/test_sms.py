"""
Tests for SMS service functionality.
"""

from unittest.mock import MagicMock, patch

import pytest
from app.services.comms.models import MessageStatus, SendSMSRequest
from app.services.comms.sms import (
    SMSConfigurationError,
    get_sms_status,
    send_sms,
    send_sms_simple,
    validate_sms_config,
)


class TestSMSConfiguration:
    """Test SMS service configuration validation."""

    def test_get_sms_status_configured(self) -> None:
        """Test status when fully configured."""
        with patch("app.services.comms.sms.settings") as mock_settings:
            mock_settings.TWILIO_ACCOUNT_SID = "ACtest123"
            mock_settings.TWILIO_AUTH_TOKEN = "auth_token"
            mock_settings.TWILIO_PHONE_NUMBER = "+15551234567"

            status = get_sms_status()

            assert status["configured"] is True
            assert status["account_sid_set"] is True
            assert status["auth_token_set"] is True
            assert status["phone_number_set"] is True
            assert status["phone_number"] == "+15551234567"

    def test_get_sms_status_not_configured(self) -> None:
        """Test status when not configured."""
        with patch("app.services.comms.sms.settings") as mock_settings:
            mock_settings.TWILIO_ACCOUNT_SID = None
            mock_settings.TWILIO_AUTH_TOKEN = None
            mock_settings.TWILIO_PHONE_NUMBER = None

            status = get_sms_status()

            assert status["configured"] is False
            assert status["account_sid_set"] is False
            assert status["auth_token_set"] is False

    def test_validate_sms_config_valid(self) -> None:
        """Test validation with valid configuration."""
        with patch("app.services.comms.sms.settings") as mock_settings:
            mock_settings.TWILIO_ACCOUNT_SID = "ACtest123"
            mock_settings.TWILIO_AUTH_TOKEN = "auth_token"
            mock_settings.TWILIO_PHONE_NUMBER = "+15551234567"

            errors = validate_sms_config()

            assert len(errors) == 0

    def test_validate_sms_config_missing_credentials(self) -> None:
        """Test validation when credentials are missing.

        ``validate_sms_config`` accepts EITHER a Messaging Service SID OR
        a raw phone number as the sender (preferring the former). Both
        must be unset to trigger the sender-missing error — mocking only
        ``TWILIO_PHONE_NUMBER`` leaves ``TWILIO_MESSAGING_SERVICE_SID``
        as a truthy MagicMock, suppressing one error and failing the
        ``len(errors) == 3`` assertion.
        """
        with patch("app.services.comms.sms.settings") as mock_settings:
            mock_settings.TWILIO_ACCOUNT_SID = None
            mock_settings.TWILIO_AUTH_TOKEN = None
            mock_settings.TWILIO_PHONE_NUMBER = None
            mock_settings.TWILIO_MESSAGING_SERVICE_SID = None

            errors = validate_sms_config()

            assert len(errors) == 3


class TestSendSMS:
    """Test SMS sending functionality."""

    @pytest.mark.asyncio
    async def test_send_sms_success(self) -> None:
        """Test successful SMS send."""
        with (
            patch("app.services.comms.sms.settings") as mock_settings,
            patch("app.services.comms.twilio.Client") as mock_client_class,
        ):
            mock_settings.TWILIO_ACCOUNT_SID = "ACtest123"
            mock_settings.TWILIO_AUTH_TOKEN = "auth_token"
            mock_settings.TWILIO_PHONE_NUMBER = "+15551234567"

            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_message = MagicMock()
            mock_message.sid = "SM123456"
            mock_client.messages.create.return_value = mock_message

            request = SendSMSRequest(
                to="+15559876543",
                body="Test message",
            )

            result = await send_sms(request)

            assert result.sid == "SM123456"
            assert result.to == "+15559876543"
            assert result.status == MessageStatus.SENT

    @pytest.mark.asyncio
    async def test_send_sms_calculates_segments(self) -> None:
        """Test that SMS segments are calculated correctly."""
        with (
            patch("app.services.comms.sms.settings") as mock_settings,
            patch("app.services.comms.twilio.Client") as mock_client_class,
        ):
            mock_settings.TWILIO_ACCOUNT_SID = "ACtest123"
            mock_settings.TWILIO_AUTH_TOKEN = "auth_token"
            mock_settings.TWILIO_PHONE_NUMBER = "+15551234567"

            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_message = MagicMock()
            mock_message.sid = "SM123456"
            mock_client.messages.create.return_value = mock_message

            # 320 characters = 2 segments
            long_message = "A" * 320
            request = SendSMSRequest(
                to="+15559876543",
                body=long_message,
            )

            result = await send_sms(request)

            assert result.segments == 2

    @pytest.mark.asyncio
    async def test_send_sms_missing_credentials(self) -> None:
        """Test SMS send fails when credentials are missing."""
        with patch("app.services.comms.sms.settings") as mock_settings:
            mock_settings.TWILIO_ACCOUNT_SID = None
            mock_settings.TWILIO_AUTH_TOKEN = None
            mock_settings.TWILIO_PHONE_NUMBER = "+15551234567"

            request = SendSMSRequest(
                to="+15559876543",
                body="Test",
            )

            with pytest.raises(SMSConfigurationError) as exc_info:
                await send_sms(request)

            assert "credentials" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_send_sms_missing_phone_number(self) -> None:
        """Test SMS send fails when phone number is missing."""
        with (
            patch("app.services.comms.sms.settings") as mock_settings,
            patch("app.services.comms.twilio.Client"),
        ):
            mock_settings.TWILIO_ACCOUNT_SID = "ACtest123"
            mock_settings.TWILIO_AUTH_TOKEN = "auth_token"
            mock_settings.TWILIO_PHONE_NUMBER = None

            request = SendSMSRequest(
                to="+15559876543",
                body="Test",
                from_number=None,  # Also not provided in request
            )

            with pytest.raises(SMSConfigurationError) as exc_info:
                await send_sms(request)

            assert "phone number" in str(exc_info.value).lower()


class TestSendSMSSimple:
    """Test simplified SMS sending function."""

    @pytest.mark.asyncio
    async def test_send_sms_simple_success(self) -> None:
        """Test simple SMS send."""
        with (
            patch("app.services.comms.sms.settings") as mock_settings,
            patch("app.services.comms.twilio.Client") as mock_client_class,
        ):
            mock_settings.TWILIO_ACCOUNT_SID = "ACtest123"
            mock_settings.TWILIO_AUTH_TOKEN = "auth_token"
            mock_settings.TWILIO_PHONE_NUMBER = "+15551234567"

            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_message = MagicMock()
            mock_message.sid = "SM789"
            mock_client.messages.create.return_value = mock_message

            result = await send_sms_simple(
                to="+15559876543",
                body="Simple test message",
            )

            assert result.sid == "SM789"
