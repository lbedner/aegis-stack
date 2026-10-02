"""
Communications service health check functions.

Health monitoring for email (Resend), SMS (Twilio), and voice call functionality.
Checks provider configuration, API key validation, and service readiness.
"""

from app.core import secrets
from app.core.log import logger
from app.services.system.models import ComponentStatus, ComponentStatusType


async def check_comms_service_health() -> ComponentStatus:
    """
    Check communications service health including provider configuration.

    Returns:
        ComponentStatus indicating comms service health
    """
    try:
        cfg = await secrets.get_many(
            "RESEND_API_KEY",
            "RESEND_FROM_EMAIL",
            "TWILIO_ACCOUNT_SID",
            "TWILIO_AUTH_TOKEN",
            "TWILIO_PHONE_NUMBER",
            "TWILIO_MESSAGING_SERVICE_SID",
        )
        config_errors: list[str] = []
        config_warnings: list[str] = []

        # Check Email (Resend) configuration
        email_configured = False
        if cfg["RESEND_API_KEY"]:
            if cfg["RESEND_FROM_EMAIL"]:
                email_configured = True
            else:
                config_warnings.append("RESEND_FROM_EMAIL not configured")
        else:
            config_warnings.append(
                "Email (Resend) not configured - RESEND_API_KEY missing"
            )

        # Check SMS/Voice (Twilio) configuration
        sms_configured = False
        voice_configured = False
        twilio_configured = all(
            [
                cfg["TWILIO_ACCOUNT_SID"],
                cfg["TWILIO_AUTH_TOKEN"],
                cfg["TWILIO_PHONE_NUMBER"],
            ]
        )

        if twilio_configured:
            sms_configured = True
            voice_configured = True
        else:
            missing_twilio = []
            if not cfg["TWILIO_ACCOUNT_SID"]:
                missing_twilio.append("TWILIO_ACCOUNT_SID")
            if not cfg["TWILIO_AUTH_TOKEN"]:
                missing_twilio.append("TWILIO_AUTH_TOKEN")
            if not cfg["TWILIO_PHONE_NUMBER"]:
                missing_twilio.append("TWILIO_PHONE_NUMBER")
            if missing_twilio:
                missing_str = ", ".join(missing_twilio)
                config_warnings.append(
                    f"SMS/Voice (Twilio) not configured - missing: {missing_str}"
                )

        # Determine overall status
        providers_configured = sum([email_configured, sms_configured, voice_configured])

        if providers_configured == 0:
            status = ComponentStatusType.WARNING
            message = "No communication providers configured"
        elif config_errors:
            status = ComponentStatusType.UNHEALTHY
            message = f"Comms service errors: {'; '.join(config_errors)}"
        elif config_warnings and providers_configured < 3:
            status = ComponentStatusType.INFO
            channels = f"{providers_configured}/3"
            message = f"Comms service partially configured ({channels} channels)"
        else:
            status = ComponentStatusType.HEALTHY
            message = "Communications service fully configured"

        # Build capabilities list
        capabilities = []
        if email_configured:
            capabilities.append("email")
        if sms_configured:
            capabilities.append("sms")
        if voice_configured:
            capabilities.append("voice")

        # Collect metadata
        metadata = {
            "service_type": "comms",
            # Email provider info
            "email_provider": "resend" if email_configured else None,
            "email_configured": email_configured,
            "email_from": cfg["RESEND_FROM_EMAIL"] if email_configured else None,
            # SMS/Voice provider info
            "sms_provider": "twilio" if sms_configured else None,
            "sms_configured": sms_configured,
            "voice_provider": "twilio" if voice_configured else None,
            "voice_configured": voice_configured,
            # Summary
            "capabilities": capabilities,
            "channels_configured": providers_configured,
            "channels_total": 3,
            # Dependencies
            "dependencies": {
                "backend": "required",
                "worker": "optional",  # For async message sending
            },
            # Email (Resend) detailed config
            "resend_api_key_configured": bool(cfg["RESEND_API_KEY"]),
            "resend_from_email": cfg["RESEND_FROM_EMAIL"] or "Not configured",
            # Twilio detailed config
            "twilio_account_sid_configured": bool(cfg["TWILIO_ACCOUNT_SID"]),
            "twilio_account_sid_preview": (
                f"...{str(cfg['TWILIO_ACCOUNT_SID'])[-4:]}"
                if cfg["TWILIO_ACCOUNT_SID"]
                else "Not configured"
            ),
            "twilio_auth_token_configured": bool(cfg["TWILIO_AUTH_TOKEN"]),
            "twilio_phone_number": cfg["TWILIO_PHONE_NUMBER"] or "Not configured",
            "twilio_messaging_service_configured": bool(
                cfg["TWILIO_MESSAGING_SERVICE_SID"]
            ),
        }

        # Add configuration issues to metadata if any
        if config_warnings:
            metadata["configuration_warnings"] = config_warnings
        if config_errors:
            metadata["configuration_errors"] = config_errors

        return ComponentStatus(
            name="comms",
            status=status,
            message=message,
            response_time_ms=None,  # Will be set by caller
            metadata=metadata,
        )

    except Exception as e:
        logger.error(f"Comms service health check failed: {e}")
        return ComponentStatus(
            name="comms",
            status=ComponentStatusType.UNHEALTHY,
            message=f"Comms service health check failed: {str(e)}",
            response_time_ms=None,
            metadata={
                "service_type": "comms",
                "error": str(e),
                "error_type": "health_check_failure",
            },
        )
