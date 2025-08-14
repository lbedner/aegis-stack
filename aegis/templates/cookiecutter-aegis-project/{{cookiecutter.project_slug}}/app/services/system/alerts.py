"""
System alert management functions.

Pure functions for sending alerts, managing notifications, and rate limiting.
All functions use Pydantic models for type safety and validation.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from app.core.log import logger

from .models import Alert, SystemStatus, alert_severity

if TYPE_CHECKING:
    pass


# Global state for alert rate limiting
_last_alerts: dict[str, datetime] = {}
_rate_limit_seconds = 300  # 5 minutes between similar alerts


def _should_send_alert(alert_key: str) -> bool:
    """Check if we should send this alert based on rate limiting."""
    if alert_key not in _last_alerts:
        return True

    time_since_last = datetime.utcnow() - _last_alerts[alert_key]
    return time_since_last.total_seconds() > _rate_limit_seconds


async def send_alert(alert: Alert) -> None:
    """Send an alert through configured channels."""
    alert_key = f"{alert.severity}:{alert.title}"

    if not _should_send_alert(alert_key):
        logger.debug(f"Rate limiting alert: {alert_key}")
        return

    _last_alerts[alert_key] = datetime.utcnow()

    # Log-based alerting (always available)
    log_level = {
        alert_severity.INFO: logger.info,
        alert_severity.WARNING: logger.warning,
        alert_severity.ERROR: logger.error,
        alert_severity.CRITICAL: logger.critical,
    }.get(alert.severity, logger.info)

    log_level(
        f"🚨 ALERT [{alert.severity.upper()}]: {alert.title}",
        extra={
            "alert_message": alert.message,
            "alert_metadata": alert.metadata,
            "alert_timestamp": alert.timestamp.isoformat(),
        },
    )

    # TODO: Add integrations for:
    # - Slack/Discord webhooks
    # - Email notifications
    # - PagerDuty/Opsgenie
    # - Custom webhook endpoints


async def send_health_alert(status: SystemStatus) -> None:
    """Send health-related alerts."""
    if not status.overall_healthy:
        alert = Alert(
            severity=alert_severity.WARNING,
            title="System Health Issues Detected",
            message=(
                f"{len(status.unhealthy_components)} components unhealthy: "
                f"{', '.join(status.unhealthy_components)}"
            ),
            timestamp=status.timestamp,
            metadata={
                "unhealthy_components": status.unhealthy_components,
                "health_percentage": status.health_percentage,
            },
        )
        await send_alert(alert)


async def send_critical_alert(title: str, message: str) -> None:
    """Send a critical system alert."""
    alert = Alert(
        severity=alert_severity.CRITICAL,
        title=title,
        message=message,
        timestamp=datetime.utcnow(),
    )
    await send_alert(alert)
