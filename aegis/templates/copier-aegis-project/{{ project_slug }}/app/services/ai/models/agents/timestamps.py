"""Timestamp helper for the agent registry models.

Mirrors the same helper in the finance and blog services. Columns are declared
``timestamp without time zone``, so a timezone-aware value cannot be bound:
asyncpg refuses it outright with "can't subtract offset-naive and offset-aware
datetimes", which surfaces as a 500 on any async write. The sync path coerces
quietly, so an aware default can sit in a model looking fine until the first
update comes through the API.
"""

from datetime import UTC, datetime


def utcnow_naive() -> datetime:
    """UTC timestamp stored as a naive datetime, for SQLite/Postgres parity."""
    return datetime.now(UTC).replace(tzinfo=None)
