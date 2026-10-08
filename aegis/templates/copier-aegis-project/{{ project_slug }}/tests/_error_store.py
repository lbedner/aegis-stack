"""An error occurrence to store, for the error tracking tests (the
``store`` fixture is in conftest)."""

from datetime import UTC, datetime, timedelta

from app.services.system.errors.models import ErrorOccurrence


def occurrence(identity: str, seconds: int = 0, group: str = "same") -> ErrorOccurrence:
    return ErrorOccurrence(
        id=identity,
        fingerprint=group,
        timestamp=datetime.now(UTC) + timedelta(seconds=seconds),
        source_timestamp=None,
        ordinal=0,
        page="server",
        service="webserver",
        container_id="one",
        container_name="server",
        stream="stderr",
        level="error",
        logger=None,
        message="failed",
        exception_type="ValueError",
        traceback="ValueError: failed",
        fields={},
    )
