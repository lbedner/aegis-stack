"""The analyst snapshot and the transaction changelog.

Two audit-shaped tables: what the agent was told, and what a human
changed by hand.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Index,
)
from sqlmodel import Field, SQLModel

from app.services.finance.models.base import (
    _FK,
    _SCHEMA,
    _bigint,
    _utcnow,
)


class FinanceAnalystSnapshot(SQLModel, table=True):
    """One row per owner per day: the figures the analyst note was built from.

    The note itself is a ``finance_insight`` row and its ``body`` is prose.
    This is the same day's numbers kept in typed columns instead, so a later
    note can ask what MOVED rather than only what is. Typed rather than a
    JSON blob on the note because the interesting questions are ranged ones
    ("has the runway slipped every week this month"), and a blob answers
    only the one-step case.

    Every money column is minor units (cents) and BigInteger, same as
    everywhere else here. Written after the note succeeds, so a failed model
    run leaves no snapshot and tomorrow simply diffs against the last good
    day.
    """

    __tablename__ = "finance_analyst_snapshot"
    __table_args__ = (
        Index("ix_finance_analyst_snapshot_owner", "owner_user_id"),
        Index("ix_finance_analyst_snapshot_day", "as_of_date"),
        Index(
            "uq_finance_analyst_snapshot_owner_day",
            "owner_user_id",
            "as_of_date",
            unique=True,
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int = Field()
    as_of_date: date = Field()

    net_worth: int | None = _bigint("net_worth")
    cash_today: int | None = _bigint("cash_today")
    portfolio_total: int | None = _bigint("portfolio_total")
    positions: int = Field(default=0)

    # The forecast, split into the three figures worth trending: where it
    # ends, how low it dips, and the date it first crosses zero - the last
    # being the one a reader actually feels.
    projection_end_date: date | None = Field(default=None)
    projection_end_amount: int | None = _bigint("projection_end_amount")
    projection_low_date: date | None = Field(default=None)
    projection_low_amount: int | None = _bigint("projection_low_amount")
    first_negative_date: date | None = Field(default=None)
    first_negative_name: str | None = Field(default=None, max_length=255)

    open_critical: int = Field(default=0)
    open_warning: int = Field(default=0)
    goals_total_saved: int | None = _bigint("goals_total_saved")

    created_at: datetime = Field(default_factory=_utcnow)


class FinanceTransactionChangelog(SQLModel, table=True):
    """Append-only field-level audit of Plaid ``modified[]`` and user edits, kept
    separate from the mutable transaction row (the queryable row stays an upsert;
    audit is immutable). Reserved until an audit/undo surface is built."""

    __tablename__ = "finance_transaction_changelog"
    __table_args__ = (
        Index("ix_finance_changelog_transaction", "transaction_id"),
        Index("ix_finance_changelog_owner", "owner_user_id"),
        Index("ix_finance_changelog_changed", "changed_at"),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    transaction_id: int = Field(foreign_key=f"{_FK}finance_transaction.id")
    owner_user_id: int = Field()
    field: str
    old_value: str | None = Field(default=None)
    new_value: str | None = Field(default=None)
    change_source: str
    sync_cursor: str | None = Field(default=None)
    changed_at: datetime = Field(default_factory=_utcnow)
