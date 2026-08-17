"""Forward-looking money: streams, budgets, baselines, insights.

What the ledger's past implies about the future, and the rows the
rule engine writes about it.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    Index,
)
from sqlmodel import Field, SQLModel

from app.services.finance.models.base import (
    _FK,
    _SCHEMA,
    _bigint,
    _utcnow,
)

# ---------------------------------------------------------------------------
# Group F (analytics / import) — recurring streams, budgets, baselines,
# insights, import pipeline, attachments, changelog
# ---------------------------------------------------------------------------
#
# finance_transaction.recurring_stream_id / import_batch_id and
# finance_trade.import_batch_id are plain columns on those models; their FK
# constraints to the tables below are added in the generated migration's
# alter_tables (all resolved now that these targets exist).


class FinanceRecurringStream(SQLModel, table=True):
    """Detected recurring streams (subscriptions, bills, paychecks) — the
    "wasting money" engine. Plaid Recurring add-on plus local heuristics.
    Confidence/maturity, not a boolean (annual charges are invisible for a
    year). Transactions back-link via ``finance_transaction.recurring_stream_id``
    (no join table)."""

    __tablename__ = "finance_recurring_stream"
    __table_args__ = (
        Index("ix_finance_recurring_owner", "owner_user_id"),
        Index("ix_finance_recurring_account", "account_id"),
        Index("ix_finance_recurring_merchant", "merchant_id"),
        Index("ix_finance_recurring_category", "category_id"),
        Index("ix_finance_recurring_connection", "connection_id"),
        Index("ix_finance_recurring_next", "owner_user_id", "next_expected_date"),
        Index("ix_finance_recurring_status", "status"),
        Index("ix_finance_recurring_deleted", "deleted_at"),
        Index(
            "uq_finance_recurring_provider",
            "connection_id",
            "provider_stream_id",
            unique=True,
            sqlite_where=Column("provider_stream_id").isnot(None),
            postgresql_where=Column("provider_stream_id").isnot(None),
        ),
        Index(
            "uq_finance_recurring_detected",
            "owner_user_id",
            "account_id",
            "direction",
            "normalized_payee",
            unique=True,
            sqlite_where=Column("provider_stream_id").is_(None),
            postgresql_where=Column("provider_stream_id").is_(None),
        ),
        CheckConstraint(
            "direction IN ('inflow', 'outflow')",
            name="ck_finance_recurring_direction",
        ),
        CheckConstraint(
            "frequency IN ('weekly', 'biweekly', 'semi_monthly', 'monthly', "
            "'bimonthly', 'quarterly', 'semi_annually', 'annually', "
            "'once', 'irregular', 'unknown')",
            name="ck_finance_recurring_frequency",
        ),
        CheckConstraint(
            "status IN ('early_detection', 'mature', 'inactive', 'cancelled')",
            name="ck_finance_recurring_status",
        ),
        CheckConstraint(
            "source IN ('plaid', 'derived', 'user')",
            name="ck_finance_recurring_source",
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int = Field()
    organization_id: int | None = Field(default=None)
    account_id: int | None = Field(default=None, foreign_key=f"{_FK}finance_account.id")
    merchant_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_merchant.id"
    )
    category_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_category.id"
    )
    connection_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_connection.id"
    )
    provider_stream_id: str | None = Field(default=None)
    name: str = Field(max_length=255)
    normalized_payee: str | None = Field(default=None)
    direction: str = Field(max_length=8)
    frequency: str = Field(max_length=16)
    average_amount: int | None = _bigint("average_amount")
    last_amount: int | None = _bigint("last_amount")
    expected_amount: int | None = _bigint("expected_amount")
    amount_is_variable: bool = Field(default=False)
    amount_tolerance_bps: int | None = Field(default=None)
    currency: str = Field(
        default="usd", foreign_key=f"{_FK}finance_currency.code", max_length=16
    )
    first_date: date | None = Field(default=None)
    last_date: date | None = Field(default=None)
    next_expected_date: date | None = Field(default=None)
    occurrence_count: int = Field(default=0)
    status: str = Field(default="early_detection", max_length=16)
    confidence: int | None = Field(default=None)
    is_subscription: bool = Field(default=False)
    is_active: bool = Field(default=True)
    is_user_confirmed: bool = Field(default=False)
    is_muted: bool = Field(default=False)
    # Paused while this date is in the future ("skip my investments for a
    # few months"): a stated fact the rollup can trust, where a pushed
    # next_expected_date is ambiguous - the monthly-equivalent math is
    # deliberately date-blind and cannot tell "annual bill, due later"
    # from "not paying this for a while". Lazy by design: nothing unsets
    # it; the day it passes, every consumer's comparison flips on its own.
    # Reserved - no consumer reads it yet.
    paused_until: date | None = Field(default=None)
    service_type: str | None = Field(default=None)
    source: str = Field(max_length=12)
    deleted_at: datetime | None = Field(default=None)
    metadata_: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON)
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class FinanceBudget(SQLModel, table=True):
    """Budget definition scoped to a period. Reserved until the budgeting UI
    ships."""

    __tablename__ = "finance_budget"
    __table_args__ = (
        Index("ix_finance_budget_owner", "owner_user_id"),
        Index("ix_finance_budget_org", "organization_id"),
        Index("ix_finance_budget_deleted", "deleted_at"),
        Index(
            "uq_finance_budget_owner_name_start",
            "owner_user_id",
            "name",
            "start_date",
            unique=True,
        ),
        CheckConstraint(
            "period IN ('monthly', 'weekly', 'quarterly', 'yearly', 'custom')",
            name="ck_finance_budget_period",
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int = Field()
    organization_id: int | None = Field(default=None)
    name: str = Field(max_length=128)
    period: str = Field(max_length=16)
    start_date: date
    end_date: date | None = Field(default=None)
    currency: str = Field(
        default="usd", foreign_key=f"{_FK}finance_currency.code", max_length=16
    )
    philosophy: str | None = Field(default=None)
    rollover: bool = Field(default=False)
    is_active: bool = Field(default=True)
    deleted_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class FinanceBudgetCategory(SQLModel, table=True):
    """Per-category budgeted amount per ``period_month`` (YYYYMM), with
    carryover/goal so envelope and flex budgeting never need a new table.
    Actuals derive live from transactions/splits."""

    __tablename__ = "finance_budget_category"
    __table_args__ = (
        Index("ix_finance_budgetcat_owner", "owner_user_id"),
        Index("ix_finance_budgetcat_budget", "budget_id"),
        Index("ix_finance_budgetcat_category", "category_id"),
        Index("ix_finance_budgetcat_month", "period_month"),
        # A NULL column in a composite unique index never collides with
        # another NULL - three partial indexes, one per target shape,
        # instead of one 4-column index that would silently allow
        # duplicate payee/overall rows.
        Index(
            "uq_finance_budgetcat_category",
            "budget_id",
            "category_id",
            "period_month",
            unique=True,
            sqlite_where=Column("category_id").isnot(None),
            postgresql_where=Column("category_id").isnot(None),
        ),
        Index(
            "uq_finance_budgetcat_payee",
            "budget_id",
            "payee_key",
            "period_month",
            unique=True,
            sqlite_where=Column("payee_key").isnot(None),
            postgresql_where=Column("payee_key").isnot(None),
        ),
        Index(
            "uq_finance_budgetcat_overall",
            "budget_id",
            "period_month",
            unique=True,
            sqlite_where=(
                Column("category_id").is_(None) & Column("payee_key").is_(None)
            ),
            postgresql_where=(
                Column("category_id").is_(None) & Column("payee_key").is_(None)
            ),
        ),
        CheckConstraint(
            "category_id IS NULL OR payee_key IS NULL",
            name="ck_finance_budgetcat_target",
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int = Field()
    budget_id: int = Field(foreign_key=f"{_FK}finance_budget.id")
    # NULL category + NULL payee_key = the budget's overall line.
    category_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_category.id"
    )
    # First-4-normalized-token payee grouping key (see
    # ``transaction_payee_key`` in utils.py) - a payee-scoped
    # target ("Starbucks") when category_id is NULL.
    payee_key: str | None = Field(default=None, max_length=96)
    payee_label: str | None = Field(default=None, max_length=191)
    period_month: int | None = Field(default=None)
    allocated_amount: int = _bigint("allocated_amount", nullable=False, default=0)
    goal_amount: int | None = _bigint("goal_amount")
    carryover_amount: int = _bigint("carryover_amount", nullable=False, default=0)
    rollover_enabled: bool = Field(default=False)
    currency: str = Field(
        default="usd", foreign_key=f"{_FK}finance_currency.code", max_length=16
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class FinanceSpendingBaseline(SQLModel, table=True):
    """Materialized trailing 3/6/12-month averages per category (and optional
    merchant) — powers anomaly-vs-your-own-baseline "wasting money" insights.
    Computed by a job once history matures."""

    __tablename__ = "finance_spending_baseline"
    __table_args__ = (
        Index("ix_finance_baseline_owner", "owner_user_id"),
        Index("ix_finance_baseline_category", "category_id"),
        Index("ix_finance_baseline_merchant", "merchant_id"),
        Index(
            "uq_finance_baseline",
            "owner_user_id",
            "category_id",
            "merchant_id",
            "window_months",
            "period_month",
            unique=True,
        ),
        CheckConstraint(
            "window_months IN (3, 6, 12)", name="ck_finance_baseline_window"
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int = Field()
    category_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_category.id"
    )
    merchant_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_merchant.id"
    )
    window_months: int
    period_month: int
    trailing_avg_amount: int = _bigint("trailing_avg_amount", nullable=False, default=0)
    currency: str = Field(
        default="usd", foreign_key=f"{_FK}finance_currency.code", max_length=16
    )
    computed_at: datetime = Field(default_factory=_utcnow)


class FinanceInsight(SQLModel, table=True):
    """Finance-specific insight/alert rows (price_hike, duplicate_service,
    inactive_subscription, fee_charged, overspend, spending_anomaly,
    low_yield_cash). ``dedup_key`` prevents regenerating the same insight daily.
    Reserved — v1 signals emit through the shared insight_event system; this
    exists for finance dedup idempotency, typed related_* FKs, and AI-readiness
    (Illiana) when that surface matures."""

    __tablename__ = "finance_insight"
    __table_args__ = (
        Index("ix_finance_insight_owner", "owner_user_id"),
        Index("ix_finance_insight_org", "organization_id"),
        Index("ix_finance_insight_type", "insight_type"),
        Index("ix_finance_insight_status", "status"),
        Index("ix_finance_insight_account", "related_account_id"),
        Index("ix_finance_insight_transaction", "related_transaction_id"),
        Index("ix_finance_insight_category", "related_category_id"),
        Index("ix_finance_insight_stream", "related_stream_id"),
        Index("ix_finance_insight_owner_read", "owner_user_id", "is_read"),
        Index(
            "uq_finance_insight_dedup",
            "owner_user_id",
            "dedup_key",
            unique=True,
        ),
        CheckConstraint(
            "severity IN ('info', 'warning', 'critical')",
            name="ck_finance_insight_severity",
        ),
        CheckConstraint(
            "status IN ('new', 'seen', 'dismissed', 'actioned')",
            name="ck_finance_insight_status",
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int = Field()
    organization_id: int | None = Field(default=None)
    insight_type: str
    severity: str = Field(max_length=16)
    title: str
    body: str | None = Field(default=None)
    related_account_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_account.id"
    )
    related_transaction_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_transaction.id"
    )
    related_category_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_category.id"
    )
    related_stream_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_recurring_stream.id"
    )
    detected_amount: int | None = _bigint("detected_amount")
    currency: str | None = Field(
        default=None, foreign_key=f"{_FK}finance_currency.code", max_length=16
    )
    dedup_key: str
    period_start: date | None = Field(default=None)
    period_end: date | None = Field(default=None)
    data: dict[str, Any] = Field(default_factory=dict, sa_column=Column("data", JSON))
    status: str = Field(default="new", max_length=12)
    is_read: bool = Field(default=False)
    dismissed_at: datetime | None = Field(default=None)
    metadata_: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON)
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
