"""
Voice call service using Twilio SDK.

Provides voice call functionality with direct Twilio SDK usage.
No abstraction layers - just clean async functions.
"""

from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.core.log import logger
from app.services.comms.twilio import credential_errors, twilio_client
from twilio.base.exceptions import TwilioRestException

from .models import CallResponse, CallStatus, MakeCallRequest


class CallError(Exception):
    """Exception raised when voice call operations fail."""

    pass


class CallConfigurationError(CallError):
    """Exception raised when voice call is not properly configured."""

    pass



async def make_call(request: MakeCallRequest) -> CallResponse:
    """
    Make a voice call using Twilio.

    Args:
        request: Call request with recipient and TwiML URL

    Returns:
        CallResponse: Response with call SID and status

    Raises:
        CallConfigurationError: If Twilio is not configured
        CallError: If call initiation fails
    """
    client = twilio_client(settings, CallConfigurationError)

    # Determine caller ID phone number
    from_number = request.from_number or settings.TWILIO_PHONE_NUMBER
    if not from_number:
        raise CallConfigurationError(
            "No caller ID phone number specified. "
            "Set TWILIO_PHONE_NUMBER or provide from_number in request."
        )

    try:
        # Build call params
        params: dict[str, Any] = {
            "url": request.twiml_url,
            "from_": from_number,
            "to": request.to,
            "timeout": request.timeout,
        }

        # Add optional status callback
        if request.status_callback:
            params["status_callback"] = request.status_callback
            params["status_callback_event"] = [
                "initiated",
                "ringing",
                "answered",
                "completed",
            ]

        # Initiate call via Twilio
        call = client.calls.create(**params)

        logger.info(f"Call initiated successfully: {call.sid} to {request.to}")

        return CallResponse(
            sid=call.sid,
            to=request.to,
            status=CallStatus.QUEUED,
            started_at=datetime.now(UTC),
        )

    except TwilioRestException as e:
        logger.error(f"Twilio API error: {e.msg}")
        raise CallError(f"Failed to make call: {e.msg}") from e
    except Exception as e:
        logger.error(f"Unexpected call error: {e}")
        raise CallError(f"Call operation failed: {e}") from e


async def make_call_simple(to: str, twiml_url: str) -> CallResponse:
    """
    Make a voice call with simplified parameters.

    Convenience function for common use cases.

    Args:
        to: Recipient phone number in E.164 format
        twiml_url: URL returning TwiML instructions

    Returns:
        CallResponse: Response with call SID and status

    Raises:
        CallConfigurationError: If Twilio is not configured
        CallError: If call initiation fails
    """
    request = MakeCallRequest(to=to, twiml_url=twiml_url)
    return await make_call(request)


def get_call_status() -> dict[str, Any]:
    """
    Get voice call service configuration status.

    Returns:
        dict: Status information including configuration state
    """
    account_sid_set = bool(settings.TWILIO_ACCOUNT_SID)
    auth_token_set = bool(settings.TWILIO_AUTH_TOKEN)
    phone_number_set = bool(settings.TWILIO_PHONE_NUMBER)

    return {
        "service": "voice",
        "provider": "twilio",
        "configured": account_sid_set and auth_token_set and phone_number_set,
        "account_sid_set": account_sid_set,
        "auth_token_set": auth_token_set,
        "phone_number_set": phone_number_set,
        "phone_number": settings.TWILIO_PHONE_NUMBER if phone_number_set else None,
    }


def validate_call_config() -> list[str]:
    """
    Validate voice call service configuration.

    Returns:
        list[str]: List of configuration errors (empty if valid)
    """
    errors = credential_errors(settings)

    if not settings.TWILIO_PHONE_NUMBER:
        errors.append(
            "TWILIO_PHONE_NUMBER is not set. "
            "This should be a Twilio phone number capable of making calls."
        )

    return errors
