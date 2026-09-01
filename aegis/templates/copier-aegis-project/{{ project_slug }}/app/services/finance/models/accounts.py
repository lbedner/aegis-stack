"""Accounts and what they are worth.

The account row itself, the liability detail a card carries, and the
three ways a balance gets recorded over time.
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
# Group B — accounts & balances
# ---------------------------------------------------------------------------


class FinanceAccount(SQLModel, table=True):
    """One row per provider account AND per manual asset (``is_manual``).

    The provider-reported balance is authoritative. ``account_type`` and
    ``classification`` are normalized and STORED so net-worth signing is a
    simple column read; Plaid ``type``/``subtype`` are kept raw. A NULL
    ``connection_id`` marks a manually-tracked asset (house, car, crypto).
    """

    __tablename__ = "finance_account"
    __table_args__ = (
        Index("ix_finance_account_owner_type", "owner_user_id", "account_type"),
        Index(
            "ix_finance_account_owner_classification",
            "owner_user_id",
            "classification",
        ),
        Index(
            "uq_finance_account_provider",
            "connection_id",
            "provider_account_id",
            unique=True,
            sqlite_where=(
                Column("provider_account_id").isnot(None)
                & Column("deleted_at").is_(None)
            ),
            postgresql_where=(
                Column("provider_account_id").isnot(None)
                & Column("deleted_at").is_(None)
            ),
        ),
        CheckConstraint(
            "account_type IN ('checking', 'savings', 'credit_card', 'loan', "
            "'investment', 'brokerage', 'crypto', 'property', 'vehicle', "
            "'cash', 'goal', 'envelope', 'other_asset', 'other_liability')",
            name="ck_finance_account_type",
        ),
        CheckConstraint(
            "classification IN ('asset', 'liability')",
            name="ck_finance_account_classification",
        ),
        CheckConstraint(
            "provider IN ('plaid', 'snaptrade', 'coinbase', 'exchange_key', "
            "'onchain', 'manual')",
            name="ck_finance_account_provider",
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int | None = Field(default=None, index=True)
    # WHOSE money this is, when it is not the household's own. Null
    # means ours, so an existing ledger is unchanged.
    subject_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_subject.id", index=True
    )
    organization_id: int | None = Field(default=None, index=True)
    connection_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_connection.id", index=True
    )
    institution_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_institution.id", index=True
    )
    provider: str = Field(max_length=16)
    provider_account_id: str | None = Field(default=None)
    persistent_account_id: str | None = Field(default=None, index=True)
    name: str = Field(max_length=255)
    official_name: str | None = Field(default=None, max_length=255)
    mask: str | None = Field(default=None, max_length=8)
    type: str | None = Field(default=None)
    subtype: str | None = Field(default=None)
    account_type: str = Field(max_length=24)
    classification: str = Field(max_length=12)
    currency: str = Field(
        default="usd", foreign_key=f"{_FK}finance_currency.code", max_length=16
    )
    current_balance: int | None = _bigint("current_balance")
    available_balance: int | None = _bigint("available_balance")
    credit_limit: int | None = _bigint("credit_limit")
    balance_as_of: datetime | None = Field(default=None)
    is_manual: bool = Field(default=False)
    is_hidden: bool = Field(default=False)
    is_closed: bool = Field(default=False)
    is_on_budget: bool = Field(default=True)
    linked_at: datetime | None = Field(default=None)
    last_synced_at: datetime | None = Field(default=None)
    deleted_at: datetime | None = Field(default=None, index=True)
    metadata_: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON)
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class FinanceLiabilityDetail(SQLModel, table=True):
    """1:1 per credit/loan account — statement/payment/APR detail (Chase; AMEX
    fields stay NULL). APRs are a JSON array (APR-by-type is not relational).
    Rates are basis points (int) to avoid Decimal."""

    __tablename__ = "finance_liability_detail"
    __table_args__ = (
        Index("ix_finance_liability_owner", "owner_user_id"),
        Index("ix_finance_liability_account", "account_id", unique=True),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int | None = Field(default=None)
    account_id: int = Field(foreign_key=f"{_FK}finance_account.id")
    liability_type: str | None = Field(default=None)
    last_statement_balance: int | None = _bigint("last_statement_balance")
    last_statement_issue_date: date | None = Field(default=None)
    last_payment_amount: int | None = _bigint("last_payment_amount")
    last_payment_date: date | None = Field(default=None)
    minimum_payment_amount: int | None = _bigint("minimum_payment_amount")
    next_payment_due_date: date | None = Field(default=None)
    origination_date: date | None = Field(default=None)
    origination_principal: int | None = _bigint("origination_principal")
    outstanding_balance: int | None = _bigint("outstanding_balance")
    interest_rate_bps: int | None = Field(default=None)
    ytd_interest_paid: int | None = _bigint("ytd_interest_paid")
    ytd_principal_paid: int | None = _bigint("ytd_principal_paid")
    loan_term_months: int | None = Field(default=None)
    is_overdue: bool | None = Field(default=None)
    # FW-04: which property secures this liability, as CONFIRMED by the
    # user - lien priority is never inferred. 1 = first mortgage,
    # 2 = second/HELOC. Equity and LTV derive from the link at read
    # time and are never stored.
    secured_by_account_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_account.id"
    )
    lien_position: int | None = Field(default=None)
    aprs: list[Any] = Field(default_factory=list, sa_column=Column("aprs", JSON))
    currency: str = Field(
        default="usd", foreign_key=f"{_FK}finance_currency.code", max_length=16
    )
    raw: dict[str, Any] = Field(default_factory=dict, sa_column=Column("raw", JSON))
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class FinanceBalanceSnapshot(SQLModel, table=True):
    """The net-worth-over-time primitive: one materialized balance per account
    per day, upserted by a background job (carried forward on gap days)."""

    __tablename__ = "finance_balance_snapshot"
    __table_args__ = (
        Index("ix_finance_balsnap_account_date", "account_id", "balance_date"),
        Index("ix_finance_balsnap_owner_date", "owner_user_id", "balance_date"),
        Index("uq_finance_balsnap", "account_id", "balance_date", unique=True),
        CheckConstraint(
            "source IN ('sync', 'provider', 'computed', 'carried_forward', 'manual')",
            name="ck_finance_balsnap_source",
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key=f"{_FK}finance_account.id")
    owner_user_id: int | None = Field(default=None)
    organization_id: int | None = Field(default=None)
    balance_date: date
    balance: int = _bigint("balance", nullable=False, default=0)
    available_balance: int | None = _bigint("available_balance")
    cash_balance: int | None = _bigint("cash_balance")
    holdings_value: int | None = _bigint("holdings_value")
    currency: str = Field(
        default="usd", foreign_key=f"{_FK}finance_currency.code", max_length=16
    )
    base_currency_value: int | None = _bigint("base_currency_value")
    source: str = Field(default="sync", max_length=16)
    is_estimated: bool = Field(default=False)


class FinanceNetWorthSnapshot(SQLModel, table=True):
    """Per-user daily net-worth rollup so the headline chart is O(1)."""

    __tablename__ = "finance_net_worth_snapshot"
    __table_args__ = (
        Index("ix_finance_networth_owner_date", "owner_user_id", "as_of_date"),
        Index("ix_finance_networth_org_date", "organization_id", "as_of_date"),
        Index(
            "uq_finance_networth",
            "owner_user_id",
            "as_of_date",
            "currency",
            unique=True,
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int | None = Field(default=None)
    organization_id: int | None = Field(default=None)
    as_of_date: date
    total_assets_amount: int = _bigint("total_assets_amount", nullable=False, default=0)
    total_liabilities_amount: int = _bigint(
        "total_liabilities_amount", nullable=False, default=0
    )
    net_worth_amount: int = _bigint("net_worth_amount", nullable=False, default=0)
    cash_amount: int | None = _bigint("cash_amount")
    investments_amount: int | None = _bigint("investments_amount")
    other_assets_amount: int | None = _bigint("other_assets_amount")
    currency: str = Field(
        default="usd", foreign_key=f"{_FK}finance_currency.code", max_length=16
    )
    breakdown: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("breakdown", JSON)
    )
    is_estimated: bool = Field(default=False)


class FinanceValuation(SQLModel, table=True):
    """Source-tagged dated-value series for manual/off-aggregator assets (real
    estate, vehicles, crypto marks). Feeds the balance-snapshot recompute for
    non-transactional assets; carries staleness tracking."""

    __tablename__ = "finance_valuation"
    __table_args__ = (
        Index("ix_finance_valuation_owner_date", "owner_user_id", "as_of_date"),
        Index("ix_finance_valuation_account_date", "account_id", "as_of_date"),
        Index("ix_finance_valuation_source", "source"),
        Index(
            "uq_finance_valuation", "account_id", "as_of_date", "source", unique=True
        ),
        CheckConstraint(
            "source IN ('manual', 'zillow', 'kbb', 'exchange_api', 'onchain', "
            "'plaid', 'snaptrade', 'coingecko', 'reconciliation', 'goal_auto', 'envelope_auto')",
            name="ck_finance_valuation_source",
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int | None = Field(default=None)
    organization_id: int | None = Field(default=None)
    account_id: int = Field(foreign_key=f"{_FK}finance_account.id")
    as_of_date: date
    value: int = _bigint("value", nullable=False, default=0)
    currency: str = Field(
        default="usd", foreign_key=f"{_FK}finance_currency.code", max_length=16
    )
    source: str = Field(default="manual", max_length=16)
    source_ref: str | None = Field(default=None)
    is_estimate: bool = Field(default=False)
    fetched_at: datetime | None = Field(default=None)
    is_stale: bool = Field(default=False)
    stale_after_days: int | None = Field(default=None)
    note: str | None = Field(default=None)
    metadata_: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON)
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
