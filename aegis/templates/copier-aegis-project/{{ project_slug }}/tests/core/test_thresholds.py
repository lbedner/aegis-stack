"""Where a figure's warning and alert begin (``app.core.thresholds``): the
one rule the host's checks, a container's figures and any chart's guides
read, its warning share a setting."""

import pytest

from app.core import thresholds
from app.core.config import settings
from app.services.system.models import ComponentStatusType


@pytest.fixture(autouse=True)
def warn_at_80(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "WARNING_PERCENT_OF_THRESHOLD", 80.0)


@pytest.mark.parametrize(
    ("value", "found"),
    [
        (79.0, ComponentStatusType.HEALTHY),
        (80.0, ComponentStatusType.WARNING),
        (100.0, ComponentStatusType.UNHEALTHY),
    ],
)
def test_a_figure_warns_short_of_its_alert(
    value: float, found: ComponentStatusType
) -> None:
    assert thresholds.status(value, 100.0) is found


def test_a_charts_levels_are_where_warning_and_alert_begin() -> None:
    assert thresholds.levels(50.0) == [
        {"value": 40.0, "tone": "warn"},
        {"value": 50.0, "tone": "error"},
    ]


def test_the_warning_share_is_a_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "WARNING_PERCENT_OF_THRESHOLD", 50.0)
    assert thresholds.status(50.0, 100.0) is ComponentStatusType.WARNING
    assert thresholds.levels(100.0)[0]["value"] == 50.0
