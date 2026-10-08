"""What every ``Settings`` is besides its fields: a repr that never shows a
credential (``app.core.credential.shown``: a log line, a traceback, a failing
assert), and a setting nothing reads any more dropped from an old ``.env``
(``RETIRED_SETTINGS``) rather than refused."""

from collections.abc import Iterable
from typing import Any

from pydantic import model_validator

from app.core.credential import shown
from app.core.settings_errors import ErrorTrackingSettings

# Settings nothing reads any more. A .env written before still sets them,
# and Settings refuses unknown names, so they are dropped on the way in.
RETIRED_SETTINGS = frozenset(
    {
        "ALERTING_ENABLED",
        "ALERT_COOLDOWN_MINUTES",
        "HEALTH_CHECK_ENABLED",
        "HEALTH_CHECK_INTERVAL_MINUTES",
    }
)


class SettingsBase(ErrorTrackingSettings):
    """``Settings``' base, in place of ``BaseSettings``."""

    @model_validator(mode="before")
    @classmethod
    def _drop_retired(cls, values: Any) -> Any:
        """Ignore the ``RETIRED_SETTINGS`` an old ``.env`` still sets."""
        if not isinstance(values, dict):
            return values
        return {k: v for k, v in values.items() if k.upper() not in RETIRED_SETTINGS}

    def __repr_args__(self) -> Iterable[tuple[str | None, Any]]:
        """Every field but a credential."""
        return shown(super().__repr_args__())
