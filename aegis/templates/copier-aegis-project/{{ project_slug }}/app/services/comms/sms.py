"""
SMS service using Twilio SDK.

Provides SMS sending functionality with direct Twilio SDK usage.
No abstraction layers - just clean async functions.
"""

from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.core.log import logger
from app.services.comms.twilio import credential_errors, twilio_client
from twilio.base.exceptions import TwilioRestException

from .models import MessageStatus, SendSMSRequest, SMSResponse


class SMSError(Exception):
    """Exception raised when SMS operations fail."""

    pass


class SMSConfigurationError(SMSError):
    """Exception raised when SMS is not properly configured."""

    pass



async def send_sms(request: SendSMSRequest) -> SMSResponse:
    """
    Send an SMS using Twilio.

    Args:
        request: SMS request with recipient and message body

    Returns:
        SMSResponse: Response with message SID and status

    Raises:
        SMSConfigurationError: If Twilio is not configured
        SMSError: If sending fails
    """
    client = twilio_client(settings, SMSConfigurationError)

    # Determine sender phone number
    from_number = request.from_number or settings.TWILIO_PHONE_NUMBER
    if not from_number:
        raise SMSConfigurationError(
            "No sender phone number specified. "
            "Set TWILIO_PHONE_NUMBER or provide from_number in request."
        )

    try:
        # Build message params
        params: dict[str, Any] = {
            "body": request.body,
            "to": request.to,
        }

        # Use Messaging Service SID if configured (required for toll-free numbers)
        # Otherwise fall back to direct phone number
        if settings.TWILIO_MESSAGING_SERVICE_SID:
            params["messaging_service_sid"] = settings.TWILIO_MESSAGING_SERVICE_SID
        else:
            params["from_"] = from_number

        # Add optional status callback
        if request.status_callback:
            params["status_callback"] = request.status_callback

        # Send SMS via Twilio
        message = client.messages.create(**params)

        logger.info(f"SMS sent successfully: {message.sid} to {request.to}")

        # Calculate number of segments (160 chars per segment for GSM-7)
        segments = len(request.body) // 160 + (1 if len(request.body) % 160 else 0)

        return SMSResponse(
            sid=message.sid,
            to=request.to,
            status=MessageStatus.SENT,
            sent_at=datetime.now(UTC),
            segments=segments,
        )

    except TwilioRestException as e:
        logger.error(f"Twilio API error: {e.msg}")
        raise SMSError(f"Failed to send SMS: {e.msg}") from e
    except Exception as e:
        logger.error(f"Unexpected SMS error: {e}")
        raise SMSError(f"SMS operation failed: {e}") from e


async def send_sms_simple(to: str, body: str) -> SMSResponse:
    """
    Send an SMS with simplified parameters.

    Convenience function for common use cases.

    Args:
        to: Recipient phone number in E.164 format
        body: Message content

    Returns:
        SMSResponse: Response with message SID and status

    Raises:
        SMSConfigurationError: If Twilio is not configured
        SMSError: If sending fails
    """
    request = SendSMSRequest(to=to, body=body)
    return await send_sms(request)


def get_sms_status() -> dict[str, Any]:
    """
    Get SMS service configuration status.

    Returns:
        dict: Status information including configuration state
    """
    account_sid_set = bool(settings.TWILIO_ACCOUNT_SID)
    auth_token_set = bool(settings.TWILIO_AUTH_TOKEN)
    phone_number_set = bool(settings.TWILIO_PHONE_NUMBER)
    messaging_service_sid_set = bool(settings.TWILIO_MESSAGING_SERVICE_SID)

    # SMS is configured if we have credentials and either a messaging
    # service or a phone number
    configured = (
        account_sid_set
        and auth_token_set
        and (messaging_service_sid_set or phone_number_set)
    )

    return {
        "service": "sms",
        "provider": "twilio",
        "configured": configured,
        "account_sid_set": account_sid_set,
        "auth_token_set": auth_token_set,
        "phone_number_set": phone_number_set,
        "messaging_service_sid_set": messaging_service_sid_set,
        "phone_number": settings.TWILIO_PHONE_NUMBER if phone_number_set else None,
    }


def validate_sms_config() -> list[str]:
    """
    Validate SMS service configuration.

    Returns:
        list[str]: List of configuration errors (empty if valid)
    """
    errors = credential_errors(settings)

    # Need either Messaging Service SID (preferred) or phone number
    if not settings.TWILIO_MESSAGING_SERVICE_SID and not settings.TWILIO_PHONE_NUMBER:
        errors.append(
            "TWILIO_MESSAGING_SERVICE_SID or TWILIO_PHONE_NUMBER must be set. "
            "Messaging Service SID is required for toll-free numbers."
        )

    return errors
