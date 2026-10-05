"""Where a figure's warning and alert begin: the one rule. A figure is
unhealthy at its alert, a warning from ``WARNING_PERCENT_OF_THRESHOLD`` of
it (Overseer > Settings, Health), healthy below. The host's checks, a
container's figures, the charts' dashed guides and their tones all read
it, and any chart can mark it (``series.chart(..., thresholds=levels(...))``)."""

from typing import Any

from app.core.config import settings
from app.services.system.models import ComponentStatusType


def warning_at(alert: float) -> float:
    """Where a warning starts short of ``alert``, in its units."""
    return alert * settings.WARNING_PERCENT_OF_THRESHOLD / 100


def status(value: float, alert: float) -> ComponentStatusType:
    """``value`` against ``alert`` (both in the figure's units)."""
    if value >= alert:
        return ComponentStatusType.UNHEALTHY
    if value >= warning_at(alert):
        return ComponentStatusType.WARNING
    return ComponentStatusType.HEALTHY


def levels(alert: float) -> list[dict[str, Any]]:
    """A chart's guides for ``alert``: where warning and alert begin."""
    return [
        {"value": warning_at(alert), "tone": "warn"},
        {"value": alert, "tone": "error"},
    ]
