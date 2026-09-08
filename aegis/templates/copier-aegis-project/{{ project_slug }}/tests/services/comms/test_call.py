"""
Tests for voice call service functionality.
"""

from unittest.mock import MagicMock, patch

import pytest
from app.services.comms.calls import (
    CallConfigurationError,
    get_call_status,
    make_call,
    make_call_simple,
    validate_call_config,
)
from app.services.comms.models import CallStatus, MakeCallRequest


class TestCallConfiguration:
    """Test voice call service configuration validation."""

    def test_get_call_status_configured(self) -> None:
        """Test status when fully configured."""
        with patch("app.services.comms.calls.settings") as mock_settings:
            mock_settings.TWILIO_ACCOUNT_SID = "ACtest123"
            mock_settings.TWILIO_AUTH_TOKEN = "auth_token"
            mock_settings.TWILIO_PHONE_NUMBER = "+15551234567"

            status = get_call_status()

            assert status["configured"] is True
            assert status["account_sid_set"] is True
            assert status["auth_token_set"] is True
            assert status["phone_number_set"] is True

    def test_get_call_status_not_configured(self) -> None:
        """Test status when not configured."""
        with patch("app.services.comms.calls.settings") as mock_settings:
            mock_settings.TWILIO_ACCOUNT_SID = None
            mock_settings.TWILIO_AUTH_TOKEN = None
            mock_settings.TWILIO_PHONE_NUMBER = None

            status = get_call_status()

            assert status["configured"] is False

    def test_validate_call_config_valid(self) -> None:
        """Test validation with valid configuration."""
        with patch("app.services.comms.calls.settings") as mock_settings:
            mock_settings.TWILIO_ACCOUNT_SID = "ACtest123"
            mock_settings.TWILIO_AUTH_TOKEN = "auth_token"
            mock_settings.TWILIO_PHONE_NUMBER = "+15551234567"

            errors = validate_call_config()

            assert len(errors) == 0

    def test_validate_call_config_missing_credentials(self) -> None:
        """Test validation when credentials are missing."""
        with patch("app.services.comms.calls.settings") as mock_settings:
            mock_settings.TWILIO_ACCOUNT_SID = None
            mock_settings.TWILIO_AUTH_TOKEN = None
            mock_settings.TWILIO_PHONE_NUMBER = None

            errors = validate_call_config()

            assert len(errors) == 3


class TestMakeCall:
    """Test voice call initiation functionality."""

    @pytest.mark.asyncio
    async def test_make_call_success(self) -> None:
        """Test successful call initiation."""
        with (
            patch("app.services.comms.calls.settings") as mock_settings,
            patch("app.services.comms.twilio.Client") as mock_client_class,
        ):
            mock_settings.TWILIO_ACCOUNT_SID = "ACtest123"
            mock_settings.TWILIO_AUTH_TOKEN = "auth_token"
            mock_settings.TWILIO_PHONE_NUMBER = "+15551234567"

            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_call = MagicMock()
            mock_call.sid = "CA123456"
            mock_client.calls.create.return_value = mock_call

            request = MakeCallRequest(
                to="+15559876543",
                twiml_url="https://example.com/twiml",
            )

            result = await make_call(request)

            assert result.sid == "CA123456"
            assert result.to == "+15559876543"
            assert result.status == CallStatus.QUEUED

    @pytest.mark.asyncio
    async def test_make_call_with_timeout(self) -> None:
        """Test call initiation with custom timeout."""
        with (
            patch("app.services.comms.calls.settings") as mock_settings,
            patch("app.services.comms.twilio.Client") as mock_client_class,
        ):
            mock_settings.TWILIO_ACCOUNT_SID = "ACtest123"
            mock_settings.TWILIO_AUTH_TOKEN = "auth_token"
            mock_settings.TWILIO_PHONE_NUMBER = "+15551234567"

            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_call = MagicMock()
            mock_call.sid = "CA789"
            mock_client.calls.create.return_value = mock_call

            request = MakeCallRequest(
                to="+15559876543",
                twiml_url="https://example.com/twiml",
                timeout=60,
            )

            result = await make_call(request)

            # Verify timeout was passed to Twilio
            call_kwargs = mock_client.calls.create.call_args[1]
            assert call_kwargs["timeout"] == 60
            assert result.sid == "CA789"

    @pytest.mark.asyncio
    async def test_make_call_missing_credentials(self) -> None:
        """Test call fails when credentials are missing."""
        with patch("app.services.comms.calls.settings") as mock_settings:
            mock_settings.TWILIO_ACCOUNT_SID = None
            mock_settings.TWILIO_AUTH_TOKEN = None
            mock_settings.TWILIO_PHONE_NUMBER = "+15551234567"

            request = MakeCallRequest(
                to="+15559876543",
                twiml_url="https://example.com/twiml",
            )

            with pytest.raises(CallConfigurationError) as exc_info:
                await make_call(request)

            assert "credentials" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_make_call_missing_phone_number(self) -> None:
        """Test call fails when phone number is missing."""
        with (
            patch("app.services.comms.calls.settings") as mock_settings,
            patch("app.services.comms.twilio.Client"),
        ):
            mock_settings.TWILIO_ACCOUNT_SID = "ACtest123"
            mock_settings.TWILIO_AUTH_TOKEN = "auth_token"
            mock_settings.TWILIO_PHONE_NUMBER = None

            request = MakeCallRequest(
                to="+15559876543",
                twiml_url="https://example.com/twiml",
                from_number=None,  # Also not provided in request
            )

            with pytest.raises(CallConfigurationError) as exc_info:
                await make_call(request)

            assert "phone number" in str(exc_info.value).lower()


class TestMakeCallSimple:
    """Test simplified call making function."""

    @pytest.mark.asyncio
    async def test_make_call_simple_success(self) -> None:
        """Test simple call initiation."""
        with (
            patch("app.services.comms.calls.settings") as mock_settings,
            patch("app.services.comms.twilio.Client") as mock_client_class,
        ):
            mock_settings.TWILIO_ACCOUNT_SID = "ACtest123"
            mock_settings.TWILIO_AUTH_TOKEN = "auth_token"
            mock_settings.TWILIO_PHONE_NUMBER = "+15551234567"

            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_call = MagicMock()
            mock_call.sid = "CA999"
            mock_client.calls.create.return_value = mock_call

            result = await make_call_simple(
                to="+15559876543",
                twiml_url="https://example.com/twiml",
            )

            assert result.sid == "CA999"
