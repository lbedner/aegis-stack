"""Securities, prices, holdings and trades.

Quantities and per-unit prices are ``*_e8`` scaled integers, which is
why they are BigInteger columns.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
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
# Group E (investments) — securities, prices, holdings, trades
# ---------------------------------------------------------------------------
#
# ``finance_trade.import_batch_id`` is a plain column (its FK to
# finance_import_batch is added in the generated migration's alter_tables in
# FIN-10). Quantities are scaled integers (``quantity_e8`` = units x 1e8);
# prices are integer minor units x ``price_scale``.


class FinanceSecurity(SQLModel, table=True):
    """Global (un-owned) securities catalog: equities, ETFs, funds, bonds,
    options, crypto. Per-provider ids reconcile to shared FIGI/CUSIP/ISIN so one
    instrument merges across users/providers. Taxonomy fields are plain text."""

    __tablename__ = "finance_security"
    __table_args__ = (
        Index("ix_finance_security_ticker", "ticker"),
        Index("ix_finance_security_cusip", "cusip"),
        Index("ix_finance_security_isin", "isin"),
        Index("ix_finance_security_provider_secid", "provider_security_id"),
        Index("ix_finance_security_type", "security_type"),
        Index(
            "uq_finance_security_provider",
            "provider",
            "provider_security_id",
            unique=True,
            sqlite_where=Column("provider_security_id").isnot(None),
            postgresql_where=Column("provider_security_id").isnot(None),
        ),
        Index(
            "uq_finance_security_figi",
            "figi",
            unique=True,
            sqlite_where=Column("figi").isnot(None),
            postgresql_where=Column("figi").isnot(None),
        ),
        Index(
            "uq_finance_security_cusip",
            "cusip",
            unique=True,
            sqlite_where=Column("cusip").isnot(None),
            postgresql_where=Column("cusip").isnot(None),
        ),
        Index(
            "uq_finance_security_isin",
            "isin",
            unique=True,
            sqlite_where=Column("isin").isnot(None),
            postgresql_where=Column("isin").isnot(None),
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    provider: str | None = Field(default=None)
    provider_security_id: str | None = Field(default=None)
    figi: str | None = Field(default=None)
    cusip: str | None = Field(default=None, max_length=16)
    isin: str | None = Field(default=None, max_length=16)
    sedol: str | None = Field(default=None, max_length=16)
    ticker: str | None = Field(default=None, max_length=32)
    name: str | None = Field(default=None)
    security_type: str | None = Field(default=None)
    exchange_mic: str | None = Field(default=None, max_length=10)
    exchange_operating_mic: str | None = Field(default=None, max_length=10)
    country_code: str | None = Field(default=None, max_length=2)
    currency: str | None = Field(
        default=None, foreign_key=f"{_FK}finance_currency.code", max_length=16
    )
    is_cash_equivalent: bool = Field(default=False)
    is_crypto: bool = Field(default=False)
    coingecko_id: str | None = Field(default=None)
    onchain_contract: str | None = Field(default=None)
    onchain_chain: str | None = Field(default=None)
    close_price: int | None = _bigint("close_price")
    price_scale: int = Field(default=2)
    close_price_as_of: date | None = Field(default=None)
    metadata_: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON)
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class FinanceSecurityPrice(SQLModel, table=True):
    """Price time series feeding holding valuation and charts. One price per
    security/day/source. Sub-cent/crypto precision via ``price_scale``."""

    __tablename__ = "finance_security_price"
    __table_args__ = (
        Index("ix_finance_secprice_security_date", "security_id", "price_date"),
        Index(
            "uq_finance_secprice",
            "security_id",
            "price_date",
            "source",
            unique=True,
        ),
        CheckConstraint(
            "source IN ('plaid', 'snaptrade', 'exchange_api', 'onchain', "
            "'coingecko', 'manual', 'market_data')",
            name="ck_finance_secprice_source",
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    security_id: int = Field(foreign_key=f"{_FK}finance_security.id")
    price_date: date
    close_price: int = _bigint("close_price", nullable=False, default=0)
    price_scale: int = Field(default=2)
    currency: str = Field(
        default="usd", foreign_key=f"{_FK}finance_currency.code", max_length=16
    )
    source: str = Field(max_length=16)


class FinanceHolding(SQLModel, table=True):
    """Dated position snapshot per (account, security, as_of_date) — upsert, not
    append. Current = latest date; historical rows feed allocation-over-time.
    Quantity is a scaled integer ``quantity_e8`` (units x 1e8)."""

    __tablename__ = "finance_holding"
    __table_args__ = (
        Index("ix_finance_holding_owner", "owner_user_id"),
        Index("ix_finance_holding_account", "account_id"),
        Index("ix_finance_holding_security", "security_id"),
        Index("ix_finance_holding_account_date", "account_id", "as_of_date"),
        Index("ix_finance_holding_deleted", "deleted_at"),
        Index(
            "uq_finance_holding",
            "account_id",
            "security_id",
            "as_of_date",
            unique=True,
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int = Field()
    organization_id: int | None = Field(default=None)
    account_id: int = Field(foreign_key=f"{_FK}finance_account.id")
    security_id: int = Field(foreign_key=f"{_FK}finance_security.id")
    as_of_date: date
    quantity_e8: int = _bigint("quantity_e8", nullable=False, default=0)
    cost_basis: int | None = _bigint("cost_basis")
    average_cost: int | None = _bigint("average_cost")
    price: int | None = _bigint("price")
    price_scale: int = Field(default=2)
    institution_value: int | None = _bigint("institution_value")
    vested_quantity_e8: int | None = _bigint("vested_quantity_e8")
    currency: str = Field(
        default="usd", foreign_key=f"{_FK}finance_currency.code", max_length=16
    )
    source: str | None = Field(default=None)
    deleted_at: datetime | None = Field(default=None)
    metadata_: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON)
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class FinanceTrade(SQLModel, table=True):
    """Investment / security-movement events (buy/sell/dividend/reinvest/fee/
    transfer). Same dual-lane dedup + soft-delete as cash transactions, with an
    optional link to the cash-leg ``finance_transaction``. ``type`` is a
    normalized coarse type; ``subtype`` is provider text."""

    __tablename__ = "finance_trade"
    __table_args__ = (
        Index("ix_finance_trade_owner_date", "owner_user_id", "trade_date"),
        Index("ix_finance_trade_account_date", "account_id", "trade_date"),
        Index("ix_finance_trade_security", "security_id"),
        Index("ix_finance_trade_transaction", "transaction_id"),
        Index("ix_finance_trade_connection", "connection_id"),
        Index("ix_finance_trade_batch", "import_batch_id"),
        Index("ix_finance_trade_deleted", "deleted_at"),
        Index(
            "uq_finance_trade_external",
            "account_id",
            "source",
            "external_id",
            unique=True,
            sqlite_where=(
                Column("external_id").isnot(None) & Column("deleted_at").is_(None)
            ),
            postgresql_where=(
                Column("external_id").isnot(None) & Column("deleted_at").is_(None)
            ),
        ),
        Index(
            "uq_finance_trade_hash",
            "account_id",
            "import_hash",
            unique=True,
            sqlite_where=(
                Column("external_id").is_(None)
                & Column("import_hash").isnot(None)
                & Column("deleted_at").is_(None)
            ),
            postgresql_where=(
                Column("external_id").is_(None)
                & Column("import_hash").isnot(None)
                & Column("deleted_at").is_(None)
            ),
        ),
        CheckConstraint(
            "source IN ('plaid', 'snaptrade', 'ofx', 'qfx', 'csv', 'manual', "
            "'coinbase', 'onchain')",
            name="ck_finance_trade_source",
        ),
        CheckConstraint(
            "type IN ('buy', 'sell', 'dividend', 'interest', 'fee', 'tax', "
            "'transfer_in', 'transfer_out', 'deposit', 'withdrawal', "
            "'reinvest', 'split', 'cancel', 'other')",
            name="ck_finance_trade_type",
        ),
        CheckConstraint(
            "NOT (external_id IS NOT NULL AND import_hash IS NOT NULL)",
            name="ck_finance_trade_dedup_lane",
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int = Field()
    organization_id: int | None = Field(default=None)
    account_id: int = Field(foreign_key=f"{_FK}finance_account.id")
    security_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_security.id"
    )
    transaction_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_transaction.id"
    )
    connection_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_connection.id"
    )
    # Forward FK (finance_import_batch, FIN-10) — plain column here.
    import_batch_id: int | None = Field(default=None)
    source: str = Field(max_length=16)
    external_id: str | None = Field(default=None)
    external_id_source: str | None = Field(default=None)
    import_hash: str | None = Field(default=None, max_length=64)
    type: str = Field(max_length=16)
    subtype: str | None = Field(default=None)
    quantity_e8: int | None = _bigint("quantity_e8")
    price: int | None = _bigint("price")
    price_scale: int = Field(default=2)
    amount: int = _bigint("amount", nullable=False, default=0)
    raw_amount: int | None = _bigint("raw_amount")
    fees: int | None = _bigint("fees")
    currency: str = Field(
        default="usd", foreign_key=f"{_FK}finance_currency.code", max_length=16
    )
    trade_date: date
    settle_date: date | None = Field(default=None)
    datetime_: datetime | None = Field(
        default=None, sa_column=Column("datetime", DateTime)
    )
    name: str | None = Field(default=None)
    pending: bool = Field(default=False)
    raw_payload: dict[str, Any] | None = Field(
        default=None, sa_column=Column("raw_payload", JSON)
    )
    is_removed: bool = Field(default=False)
    deleted_at: datetime | None = Field(default=None)
    metadata_: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON)
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
