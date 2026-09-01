"""Reference data: currencies, FX rates, merchant icons.

Slow-moving lookup rows nothing else can be read without.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Index,
)
from sqlmodel import Field, SQLModel

from app.services.finance.models.base import (
    _FK,
    _SCHEMA,
    _utcnow,
)

# ---------------------------------------------------------------------------
# Group F — reference data
# ---------------------------------------------------------------------------


class FinanceCurrency(SQLModel, table=True):
    """A unit of account (fiat or crypto).

    Money columns elsewhere store integer minor units; ``decimals`` says how
    many minor units make one whole unit (usd=2, jpy=0, btc=8), so amounts can
    be rendered without hardcoding per-currency scale.
    """

    __tablename__ = "finance_currency"
    __table_args__ = (
        CheckConstraint("kind IN ('fiat', 'crypto')", name="ck_finance_currency_kind"),
        CheckConstraint(
            "decimals BETWEEN 0 AND 18", name="ck_finance_currency_decimals"
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    # ISO-4217 or crypto ticker, stored lowercase (usd, eur, btc, usdc).
    code: str = Field(index=True, unique=True, max_length=16)
    name: str = Field(max_length=64)
    symbol: str | None = Field(default=None, max_length=8)
    decimals: int = Field(default=2)
    kind: str = Field(default="fiat", max_length=8, index=True)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class FinanceFxRate(SQLModel, table=True):
    """Historical FX rate for base-currency net-worth rollups.

    ``rate_e8`` is the rate scaled by 1e8 (1 base = ``rate_e8`` / 1e8 quote) so
    conversion stays integer-exact. Convert at display time against dated rates.
    """

    __tablename__ = "finance_fx_rate"
    __table_args__ = (
        Index(
            "ix_finance_fxrate_pair_date",
            "base_currency",
            "quote_currency",
            "rate_date",
        ),
        Index(
            "uq_finance_fxrate",
            "base_currency",
            "quote_currency",
            "rate_date",
            "source",
            unique=True,
        ),
        CheckConstraint(
            "source IN ('manual', 'ecb', 'exchange_api', 'coingecko', "
            "'provider', 'derived')",
            name="ck_finance_fxrate_source",
        ),
        CheckConstraint(
            "base_currency <> quote_currency", name="ck_finance_fxrate_distinct"
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    # currency FKs are intentionally unindexed (low cardinality); the composite
    # index above covers base_currency as its leading column.
    base_currency: str = Field(foreign_key=f"{_FK}finance_currency.code", max_length=16)
    quote_currency: str = Field(
        foreign_key=f"{_FK}finance_currency.code", max_length=16
    )
    rate_date: date
    rate_e8: int = Field(sa_column=Column("rate_e8", BigInteger, nullable=False))
    source: str = Field(default="manual", max_length=16)
    created_at: datetime = Field(default_factory=_utcnow)


class FinanceIcon(SQLModel, table=True):
    """A resolved brand favicon, keyed by domain - the durable mirror of the
    render-path memory cache in ``domains/ledger/merchant_icon.py``.

    Global reference data, not user-scoped: a favicon carries nothing about
    who asked for it. ``icon_b64`` NULL is a NEGATIVE entry (the domain is
    known not to resolve); it suppresses refetching until ``fetched_at``
    ages past the retry window, because most guessed domains never resolve
    and retrying them every render is exactly the cost this table removes.
    """

    __tablename__ = "finance_icon"
    __table_args__ = ({"schema": _SCHEMA},)

    id: int | None = Field(default=None, primary_key=True)
    domain: str = Field(index=True, unique=True, max_length=255)
    icon_b64: str | None = Field(default=None)
    fetched_at: datetime = Field(default_factory=_utcnow)


class FinanceSubject(SQLModel, table=True):
    """Whose money a row describes, when it is not the household's own.

    Deliberately small. A subject identifies a person, trust, or estate
    whose accounts, income, and property this household tracks - a parent
    in care, a child's savings, an estate being settled - and nothing
    more. It is not a contacts model and not an access control boundary:
    saying whose money a row is says nothing about who may see it.

    Null on a row means the household's own money, so every ledger that
    predates subjects reads exactly as it did.
    """

    __tablename__ = "finance_subject"
    __table_args__ = (
        Index("ix_finance_subject_owner", "owner_user_id"),
        CheckConstraint(
            "kind IN ('person', 'trust', 'estate', 'entity')",
            name="ck_finance_subject_kind",
        ),
        {"schema": _SCHEMA} if _SCHEMA else {},
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int | None = Field(default=None)
    name: str = Field(max_length=128)
    kind: str = Field(default="person", max_length=16)
    note: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime | None = None
    deleted_at: datetime | None = None
