"""
Email service using Resend SDK.

Provides email sending functionality with direct Resend SDK usage.
No abstraction layers - just clean async functions.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

import resend

from app.core import secrets
from app.core.config import settings
from app.core.log import logger
from app.core.secrets import Secret, SecretRejectedError, SecretUncheckedError, probe

from .models import EmailResponse, MessageStatus, SendEmailRequest


async def _verify_resend(key: str) -> None:
    """Listing domains needs a full-access key; a send-only key is refused
    as ``restricted_api_key``, which still proves it is a real key."""
    await probe(
        "https://api.resend.com/domains",
        headers={"Authorization": f"Bearer {key}"},
        passes=lambda r: r.is_success or "restricted_api_key" in r.text,
    )


async def _resend_domains() -> list[Any]:
    """The account's domains, or why Resend could not list them (a
    send-only key cannot)."""
    from app.services.ops.adapters.resend import ResendAdapter

    try:
        return await ResendAdapter().list_domains()
    except Exception as exc:  # noqa: BLE001 - the reason is the answer
        raise SecretUncheckedError(f"Resend did not list domains ({exc}).") from None


async def _from_address_choices() -> list[tuple[str, str]]:
    """An address on each verified domain, to pick and then edit."""
    return [
        (f"hello@{d.domain}", f"{d.domain} (verified in Resend)")
        for d in await _resend_domains()
        if d.verified
    ]


async def _verify_from_address(address: str) -> None:
    """Resend only sends from a verified domain: check this one is."""
    from email.utils import parseaddr

    domain = parseaddr(address)[1].rpartition("@")[2].lower()
    if not domain:
        raise SecretRejectedError("that is not an email address.")
    match = next(
        (d for d in await _resend_domains() if d.domain.lower() == domain), None
    )
    if match is None:
        raise SecretRejectedError(f"{domain} is not a domain in your Resend account.")
    if not match.verified:
        raise SecretRejectedError(
            f"{domain} is not verified in Resend yet ({match.status})."
        )


# What this module reads (``app.core.secrets``).
SECRETS = (
    Secret(
        "RESEND_API_KEY", owner="Email (Resend)", needed=True, verify=_verify_resend
    ),
    Secret(
        "RESEND_FROM_EMAIL",
        owner="Email (Resend)",
        label="From address",
        secret=False,
        needed=True,
        choices=_from_address_choices,
        verify=_verify_from_address,
    ),
)


RESEND_KEYS = ("RESEND_API_KEY", "RESEND_FROM_EMAIL")


async def _resend() -> dict[str, str | None]:
    """The key and the sender, read now (``.env``, then the secrets store)."""
    return await secrets.get_many(*RESEND_KEYS)


class EmailError(Exception):
    """Exception raised when email operations fail."""

    pass


class EmailConfigurationError(EmailError):
    """Exception raised when email is not properly configured."""

    pass


async def send_email(request: SendEmailRequest) -> EmailResponse:
    """
    Send an email using Resend.

    Args:
        request: Email request with recipients, subject, and content

    Returns:
        EmailResponse: Response with message ID and status

    Raises:
        EmailConfigurationError: If Resend is not configured
        EmailError: If sending fails
    """
    config = await _resend()
    if not config["RESEND_API_KEY"]:
        raise EmailConfigurationError(
            "RESEND_API_KEY is not set. "
            "Sign up at https://resend.com and set your API key."
        )

    resend.api_key = config["RESEND_API_KEY"]

    # Determine sender email
    from_email = request.from_email or config["RESEND_FROM_EMAIL"]
    if not from_email:
        raise EmailConfigurationError(
            "No sender email specified. "
            "Set RESEND_FROM_EMAIL or provide from_email in request."
        )

    try:
        # Build email params
        params: dict[str, Any] = {
            "from": from_email,
            "to": request.to,
            "subject": request.subject,
        }

        # Add content (at least one required)
        if request.html:
            params["html"] = request.html
        if request.text:
            params["text"] = request.text

        if not request.html and not request.text:
            raise EmailError("Either 'text' or 'html' content is required")

        # Add optional fields
        if request.reply_to:
            params["reply_to"] = request.reply_to
        if request.cc:
            params["cc"] = request.cc
        if request.bcc:
            params["bcc"] = request.bcc
        if request.tags:
            params["tags"] = [{"name": tag} for tag in request.tags]

        # Send email via Resend
        # The SDK blocks on the network; keep the event loop free.
        response = await asyncio.to_thread(resend.Emails.send, params)

        logger.info(f"Email sent successfully: {response['id']} to {request.to}")

        return EmailResponse(
            id=response["id"],
            to=[str(email) for email in request.to],
            status=MessageStatus.SENT,
            sent_at=datetime.now(UTC),
        )

    except resend.exceptions.ResendError as e:
        logger.error(f"Resend API error: {e}")
        raise EmailError(f"Failed to send email: {e}") from e
    except Exception as e:
        logger.error(f"Unexpected email error: {e}")
        raise EmailError(f"Email operation failed: {e}") from e


async def send_email_simple(
    to: str | list[str],
    subject: str,
    text: str | None = None,
    html: str | None = None,
    reply_to: str | None = None,
) -> EmailResponse:
    """
    Send an email with simplified parameters.

    Convenience function for common use cases.

    Args:
        to: Recipient email(s)
        subject: Email subject
        text: Plain text body
        html: HTML body
        reply_to: Optional Reply-To header. When set, recipients clicking
            "Reply" route their response here instead of to the FROM
            address. Useful when FROM lives on a send-only verified
            subdomain but you want replies to land at a real inbox via
            the registrar's email forwarding. Falls back to
            ``settings.SUPPORT_REPLY_TO_EMAIL`` when not passed
            explicitly, so every send-site is opted in by default.

    Returns:
        EmailResponse: Response with message ID and status

    Raises:
        EmailConfigurationError: If Resend is not configured
        EmailError: If sending fails
    """
    # Normalize 'to' to list
    recipients = [to] if isinstance(to, str) else to
    # Default to the project-wide support address so individual call
    # sites don't have to thread it through. Explicit reply_to= still
    # wins for callers that want to override per-send.
    effective_reply_to = reply_to or settings.SUPPORT_REPLY_TO_EMAIL
    # SendEmailRequest expects a list (Resend allows multiple Reply-To
    # addresses on a single message). Wrap our single-string convenience
    # input on the way in.
    reply_to_list = [effective_reply_to] if effective_reply_to else None

    request = SendEmailRequest(
        to=recipients,  # type: ignore[arg-type]
        subject=subject,
        text=text,
        html=html,
        reply_to=reply_to_list,  # type: ignore[arg-type]
    )

    return await send_email(request)


async def get_email_status() -> dict[str, Any]:
    """
    Get email service configuration status.

    Returns:
        dict: Status information including configuration state
    """
    config = await _resend()
    api_key_set = bool(config["RESEND_API_KEY"])
    from_email_set = bool(config["RESEND_FROM_EMAIL"])

    return {
        "service": "email",
        "provider": "resend",
        "configured": api_key_set and from_email_set,
        "api_key_set": api_key_set,
        "from_email_set": from_email_set,
        "from_email": config["RESEND_FROM_EMAIL"] if from_email_set else None,
    }


async def validate_email_config() -> list[str]:
    """
    Validate email service configuration.

    Returns:
        list[str]: List of configuration errors (empty if valid)
    """
    config = await _resend()
    errors = []

    if not config["RESEND_API_KEY"]:
        errors.append(
            "RESEND_API_KEY is not set. "
            "Sign up at https://resend.com to get your API key."
        )

    if not config["RESEND_FROM_EMAIL"]:
        errors.append(
            "RESEND_FROM_EMAIL is not set. "
            "This should be a verified sender email in your Resend account."
        )

    return errors
