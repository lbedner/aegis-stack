"""The register: transactions, their splits, and transfer pairs.

The highest-volume tables in the service - most indexes here exist
for one query on one screen.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    Date,
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
# Group C (core) — transactions, splits, transfers
# ---------------------------------------------------------------------------
#
# Forward/circular FK columns (``category_id``, ``merchant_id``,
# ``recurring_stream_id``, ``import_batch_id``, ``transfer_group_id``) are plain
# integer columns here — NO model-level ``foreign_key=``. Their target tables
# are defined in later tickets (categories/merchants FIN-08, recurring/import
# FIN-10) or would form a create_all cycle (transfer_group_id <-> finance_
# transfer). The FK constraints live in the generated migration's alter_tables
# (transfer_group_id in FINANCE_MIGRATION, the rest in later tickets), so the
# generated project enforces them; ``create_all`` in tests stays acyclic.


class FinanceTransaction(SQLModel, table=True):
    """A normalized money movement — the ledger fact table.

    Two-lane provider/import dedup: LANE 1 is (account_id, source, external_id)
    for provider rows; LANE 2 is (account_id, import_hash) for file imports with
    no stable id. ``ck_finance_txn_dedup_lane`` forbids a row from carrying both
    an ``external_id`` and an ``import_hash``. ``amount`` is sign-normalized
    (negative = outflow) integer minor units; ``raw_amount`` keeps the provider
    value as delivered. Self-FKs thread pending->posted, canonical dedup, the
    transfer pair, and reversal linkage. ``owner_user_id`` has no model FK (the
    finance_auth_link migration adds it only when auth is present).
    """

    __tablename__ = "finance_transaction"
    __table_args__ = (
        Index("ix_finance_txn_owner_date", "owner_user_id", "date"),
        Index("ix_finance_txn_account_date", "account_id", "date"),
        Index("ix_finance_txn_owner_cat_date", "owner_user_id", "category_id", "date"),
        Index("ix_finance_txn_merchant", "merchant_id"),
        Index("ix_finance_txn_merchant_entity", "merchant_entity_id"),
        Index("ix_finance_txn_category", "category_id"),
        Index("ix_finance_txn_connection", "connection_id"),
        Index("ix_finance_txn_batch", "import_batch_id"),
        Index("ix_finance_txn_recurring", "recurring_stream_id"),
        Index("ix_finance_txn_transfer_group", "transfer_group_id"),
        Index("ix_finance_txn_canonical", "canonical_transaction_id"),
        Index("ix_finance_txn_pending_link", "pending_transaction_id"),
        Index("ix_finance_txn_pair", "transfer_pair_transaction_id"),
        Index("ix_finance_txn_reverses", "reverses_transaction_id"),
        Index("ix_finance_txn_pending", "pending"),
        Index("ix_finance_txn_is_transfer", "is_transfer"),
        Index("ix_finance_txn_deleted", "deleted_at"),
        Index(
            "uq_finance_txn_external",
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
            "uq_finance_txn_hash",
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
            "source IN ('plaid', 'snaptrade', 'ofx', 'qfx', 'qif', 'csv', "
            "'manual', 'coinbase', 'onchain', 'simplefin', 'teller')",
            name="ck_finance_txn_source",
        ),
        CheckConstraint(
            "status IN ('pending', 'posted', 'removed')",
            name="ck_finance_txn_status",
        ),
        CheckConstraint(
            "dedup_status IN ('unique', 'primary', 'duplicate', 'linked')",
            name="ck_finance_txn_dedup_status",
        ),
        CheckConstraint(
            "category_source IN ('provider', 'ml', 'rule', 'user', 'unset')",
            name="ck_finance_txn_category_source",
        ),
        CheckConstraint(
            "reconciled_status IN ('uncleared', 'cleared', 'reconciled')",
            name="ck_finance_txn_reconciled",
        ),
        CheckConstraint(
            "NOT (external_id IS NOT NULL AND import_hash IS NOT NULL)",
            name="ck_finance_txn_dedup_lane",
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int | None = Field(default=None)
    organization_id: int | None = Field(default=None)
    account_id: int = Field(foreign_key=f"{_FK}finance_account.id")
    connection_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_connection.id"
    )
    # Forward FK (finance_import_batch, FIN-10) — plain column here.
    import_batch_id: int | None = Field(default=None)
    source: str = Field(max_length=16)
    external_id: str | None = Field(default=None)
    external_id_source: str | None = Field(default=None)
    import_hash: str | None = Field(default=None, max_length=64)
    within_day_ordinal: int = Field(default=0)
    dedup_status: str = Field(default="unique", max_length=16)
    canonical_transaction_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_transaction.id"
    )
    source_precedence: int = Field(default=0)
    amount: int = _bigint("amount", nullable=False, default=0)
    raw_amount: int | None = _bigint("raw_amount")
    raw_sign_convention: str | None = Field(default=None)
    currency: str = Field(
        default="usd", foreign_key=f"{_FK}finance_currency.code", max_length=16
    )
    unofficial_currency_code: str | None = Field(default=None)
    # Column is literally named "date"/"datetime"; the sa_column keeps the DB
    # name while the Python attribute avoids shadowing the imported types.
    date_: date = Field(sa_column=Column("date", Date, nullable=False))
    authorized_date: date | None = Field(default=None)
    datetime_: datetime | None = Field(
        default=None, sa_column=Column("datetime", DateTime)
    )
    name: str | None = Field(default=None)
    original_description: str | None = Field(default=None)
    # Forward FK (finance_merchant, FIN-08) — plain column here.
    merchant_id: int | None = Field(default=None)
    merchant_name: str | None = Field(default=None)
    merchant_entity_id: str | None = Field(default=None)
    memo: str | None = Field(default=None)
    check_number: str | None = Field(default=None, max_length=32)
    payment_channel: str | None = Field(default=None)
    pfc_primary: str | None = Field(default=None)
    pfc_detailed: str | None = Field(default=None)
    pfc_confidence_level: str | None = Field(default=None)
    # Forward FK (finance_category, FIN-08) — plain column here.
    category_id: int | None = Field(default=None)
    category_source: str = Field(default="unset", max_length=12)
    is_user_categorized: bool = Field(default=False)
    is_reviewed: bool = Field(default=False)
    pending: bool = Field(default=False)
    pending_provider_id: str | None = Field(default=None)
    pending_transaction_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_transaction.id"
    )
    status: str = Field(default="posted", max_length=12)
    is_transfer: bool = Field(default=False)
    # Circular FK (finance_transfer) — plain column; constraint via alter_tables.
    transfer_group_id: int | None = Field(default=None)
    transfer_pair_transaction_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_transaction.id"
    )
    is_split: bool = Field(default=False)
    excluded_from_reports: bool = Field(default=False)
    is_reversal: bool = Field(default=False)
    reverses_transaction_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_transaction.id"
    )
    # Forward FK (finance_recurring_stream, FIN-10) — plain column here.
    recurring_stream_id: int | None = Field(default=None)
    reconciled_status: str = Field(default="uncleared", max_length=12)
    location: dict[str, Any] | None = Field(
        default=None, sa_column=Column("location", JSON)
    )
    counterparties: list[Any] | None = Field(
        default=None, sa_column=Column("counterparties", JSON)
    )
    raw_payload: dict[str, Any] | None = Field(
        default=None, sa_column=Column("raw_payload", JSON)
    )
    is_removed: bool = Field(default=False)
    removed_at: datetime | None = Field(default=None)
    deleted_at: datetime | None = Field(default=None)
    metadata_: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON)
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class FinanceTransactionSplit(SQLModel, table=True):
    """A line item that carves one transaction into multiple categories.

    The parent's ``is_split`` flag is set when splits exist; each split has its
    own category/merchant and signed ``amount`` (integer minor units). Splits
    should sum to the parent amount, enforced in the service layer. Deleting the
    parent cascades to its splits.
    """

    __tablename__ = "finance_transaction_split"
    __table_args__ = (
        Index("ix_finance_split_parent", "parent_transaction_id"),
        Index("ix_finance_split_owner", "owner_user_id"),
        Index("ix_finance_split_category", "category_id"),
        Index("ix_finance_split_merchant", "merchant_id"),
        Index(
            "uq_finance_split_parent_sort",
            "parent_transaction_id",
            "sort_order",
            unique=True,
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int | None = Field(default=None)
    parent_transaction_id: int = Field(foreign_key=f"{_FK}finance_transaction.id")
    # Forward FKs (finance_category / finance_merchant, FIN-08) — plain columns.
    category_id: int | None = Field(default=None)
    merchant_id: int | None = Field(default=None)
    amount: int = _bigint("amount", nullable=False, default=0)
    currency: str = Field(
        default="usd", foreign_key=f"{_FK}finance_currency.code", max_length=16
    )
    memo: str | None = Field(default=None)
    sort_order: int = Field(default=0)
    note: str | None = Field(default=None)


class FinanceTransfer(SQLModel, table=True):
    """A matched internal transfer between two of the user's own accounts.

    Pairs the outflow (``from_transaction_id``) and inflow
    (``to_transaction_id``) legs so a transfer is excluded from spend/income
    exactly once. ``transfer_group_id`` on the transaction points back here
    (the circular FK closed in the migration's alter_tables). Credit-card
    payments are the common case (``is_credit_card_payment``). A leg id is
    unique across transfers (partial-unique) so a transaction pairs at most one
    transfer per direction.
    """

    __tablename__ = "finance_transfer"
    __table_args__ = (
        Index("ix_finance_transfer_owner", "owner_user_id"),
        Index("ix_finance_transfer_from_account", "from_account_id"),
        Index("ix_finance_transfer_to_account", "to_account_id"),
        Index("ix_finance_transfer_from_txn", "from_transaction_id"),
        Index("ix_finance_transfer_to_txn", "to_transaction_id"),
        Index("ix_finance_transfer_group_key", "transfer_group_key"),
        Index(
            "uq_finance_transfer_from",
            "from_transaction_id",
            unique=True,
            sqlite_where=Column("from_transaction_id").isnot(None),
            postgresql_where=Column("from_transaction_id").isnot(None),
        ),
        Index(
            "uq_finance_transfer_to",
            "to_transaction_id",
            unique=True,
            sqlite_where=Column("to_transaction_id").isnot(None),
            postgresql_where=Column("to_transaction_id").isnot(None),
        ),
        CheckConstraint(
            "match_method IN ('auto_amount_date', 'plaid_transfer', "
            "'user_manual', 'rule', 'payment_history')",
            name="ck_finance_transfer_method",
        ),
        CheckConstraint(
            "status IN ('suggested', 'confirmed', 'rejected')",
            name="ck_finance_transfer_status",
        ),
        CheckConstraint(
            "from_transaction_id IS NULL OR to_transaction_id IS NULL "
            "OR from_transaction_id <> to_transaction_id",
            name="ck_finance_transfer_distinct",
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int | None = Field(default=None)
    organization_id: int | None = Field(default=None)
    from_account_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_account.id"
    )
    to_account_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_account.id"
    )
    from_transaction_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_transaction.id"
    )
    to_transaction_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_transaction.id"
    )
    amount: int | None = _bigint("amount")
    currency: str = Field(
        default="usd", foreign_key=f"{_FK}finance_currency.code", max_length=16
    )
    transfer_date: date | None = Field(default=None)
    transfer_group_key: str | None = Field(default=None)
    is_credit_card_payment: bool = Field(default=False)
    match_method: str = Field(max_length=20)
    confidence: int | None = Field(default=None)
    status: str = Field(default="suggested", max_length=12)
