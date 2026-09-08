"""
Shared fixtures for communications service tests.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from app.services.comms.models import (
    CallResponse,
    CallStatus,
    EmailResponse,
    MessageStatus,
    SMSResponse,
)


@pytest.fixture
def mock_resend_settings():
    """Create mock settings with Resend configuration."""
    settings = MagicMock()
    settings.RESEND_API_KEY = "re_test_key_123"
    settings.RESEND_FROM_EMAIL = "test@example.com"
    return settings


@pytest.fixture
def mock_twilio_settings():
    """Create mock settings with Twilio configuration."""
    settings = MagicMock()
    settings.TWILIO_ACCOUNT_SID = "ACtest123"
    settings.TWILIO_AUTH_TOKEN = "auth_token_123"
    settings.TWILIO_PHONE_NUMBER = "+15551234567"
    return settings


@pytest.fixture
def mock_full_settings(mock_resend_settings, mock_twilio_settings):
    """Create mock settings with full communications configuration."""
    settings = MagicMock()
    # Resend settings
    settings.RESEND_API_KEY = mock_resend_settings.RESEND_API_KEY
    settings.RESEND_FROM_EMAIL = mock_resend_settings.RESEND_FROM_EMAIL
    # Twilio settings
    settings.TWILIO_ACCOUNT_SID = mock_twilio_settings.TWILIO_ACCOUNT_SID
    settings.TWILIO_AUTH_TOKEN = mock_twilio_settings.TWILIO_AUTH_TOKEN
    settings.TWILIO_PHONE_NUMBER = mock_twilio_settings.TWILIO_PHONE_NUMBER
    return settings


@pytest.fixture
def mock_unconfigured_settings():
    """Create mock settings with no communications configuration."""
    settings = MagicMock()
    settings.RESEND_API_KEY = None
    settings.RESEND_FROM_EMAIL = None
    settings.TWILIO_ACCOUNT_SID = None
    settings.TWILIO_AUTH_TOKEN = None
    settings.TWILIO_PHONE_NUMBER = None
    return settings


@pytest.fixture
def sample_email_response():
    """Create a sample email response for testing."""
    return EmailResponse(
        id="email-123",
        to=["user@example.com"],
        status=MessageStatus.SENT,
        sent_at=datetime.now(UTC),
    )


@pytest.fixture
def sample_sms_response():
    """Create a sample SMS response for testing."""
    return SMSResponse(
        sid="SM123456",
        to="+15559876543",
        status=MessageStatus.SENT,
        sent_at=datetime.now(UTC),
        segments=1,
    )


@pytest.fixture
def sample_call_response():
    """Create a sample call response for testing."""
    return CallResponse(
        sid="CA123456",
        to="+15559876543",
        status=CallStatus.QUEUED,
        started_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_resend():
    """Mock the resend module."""
    with patch("app.services.comms.email.resend") as mock:
        mock.Emails.send.return_value = {"id": "email-123"}
        yield mock


@pytest.fixture
def mock_twilio_client():
    """Mock the Twilio Client."""
    with patch("app.services.comms.twilio.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Mock SMS response
        mock_message = MagicMock()
        mock_message.sid = "SM123456"
        mock_client.messages.create.return_value = mock_message

        # Mock Call response
        mock_call = MagicMock()
        mock_call.sid = "CA123456"
        mock_client.calls.create.return_value = mock_call

        yield mock_client
