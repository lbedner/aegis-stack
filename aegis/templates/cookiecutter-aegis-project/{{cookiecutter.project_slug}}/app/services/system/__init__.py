"""
System domain - health monitoring, alerts, and system management.

This domain provides functions for:
- System health checking and monitoring
- Component status validation
- Alert management and notifications
- System resource monitoring

All functions use Pydantic models for type safety and validation.
"""

from .alerts import (
    send_alert,
    send_critical_alert,
    send_health_alert,
)
from .health import (
    check_system_status,
    get_system_status,
    is_system_healthy,
    register_health_check,
)
from .models import (
    Alert,
    AlertSeverity,
    ComponentStatus,
    DetailedHealthResponse,
    HealthResponse,
    SystemStatus,
)

__all__ = [
    # Health functions
    "check_system_status",
    "get_system_status",
    "is_system_healthy",
    "register_health_check",
    # Alert functions
    "send_alert",
    "send_critical_alert",
    "send_health_alert",
    # Models
    "Alert",
    "AlertSeverity",
    "ComponentStatus",
    "SystemStatus",
    "HealthResponse",
    "DetailedHealthResponse",
]
