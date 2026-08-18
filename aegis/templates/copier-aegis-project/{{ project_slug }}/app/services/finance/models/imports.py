"""Import batches, their rows, profiles, and attachments.

One batch per uploaded file, one row per record in it - the audit
trail that makes a re-upload a no-op instead of a duplicate.
"""

from __future__ import annotations

from datetime import datetime
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
    _utcnow,
)


class FinanceImportProfile(SQLModel, table=True):
    """Data-driven CSV/OFX column mapping plus header signature (auto-detect
    Chase-CC vs Chase-checking vs AMEX variants) and sign convention.
    ``owner_user_id`` NULL is a system seed. Not hardcoded parsers — the
    difference between "add a data row" and "add a parser + migrate" when AMEX
    ships yet another layout."""

    __tablename__ = "finance_import_profile"
    __table_args__ = (
        Index("ix_finance_importprofile_owner", "owner_user_id"),
        Index("ix_finance_importprofile_org", "organization_id"),
        Index("ix_finance_importprofile_institution", "institution_id"),
        Index("ix_finance_importprofile_deleted", "deleted_at"),
        Index(
            "uq_finance_importprofile_owner_name",
            "owner_user_id",
            "name",
            unique=True,
        ),
        CheckConstraint(
            "source_format IN ('csv', 'ofx', 'qfx', 'qif')",
            name="ck_finance_importprofile_format",
        ),
        CheckConstraint(
            "amount_sign_convention IN ('outflow_negative', 'outflow_positive', "
            "'split_debit_credit')",
            name="ck_finance_importprofile_sign",
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int | None = Field(default=None)
    organization_id: int | None = Field(default=None)
    institution_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_institution.id"
    )
    name: str = Field(max_length=128)
    source_format: str = Field(max_length=8)
    header_signature: list[Any] = Field(
        default_factory=list, sa_column=Column("header_signature", JSON)
    )
    column_mapping: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("column_mapping", JSON)
    )
    date_format: str | None = Field(default=None)
    amount_sign_convention: str = Field(max_length=20)
    decimal_separator: str | None = Field(default=None, max_length=1)
    thousands_separator: str | None = Field(default=None, max_length=1)
    currency: str = Field(
        default="usd", foreign_key=f"{_FK}finance_currency.code", max_length=16
    )
    is_system: bool = Field(default=False)
    deleted_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class FinanceImportBatch(SQLModel, table=True):
    """One row per ingestion run (a Plaid/SnapTrade sync pass, an uploaded
    QIF/QFX/OFX/CSV file, or a manual bulk). Reversible unit plus counts and
    ``file_sha256`` whole-file dedup (blocks identical re-upload before row
    parsing). Every imported transaction/trade FKs back here."""

    __tablename__ = "finance_import_batch"
    __table_args__ = (
        Index("ix_finance_importbatch_owner", "owner_user_id"),
        Index("ix_finance_importbatch_org", "organization_id"),
        Index("ix_finance_importbatch_connection", "connection_id"),
        Index("ix_finance_importbatch_account", "account_id"),
        Index("ix_finance_importbatch_profile", "import_profile_id"),
        Index("ix_finance_importbatch_status", "status"),
        Index(
            "ix_finance_importbatch_owner_started",
            "owner_user_id",
            "started_at",
        ),
        Index(
            "uq_finance_importbatch_file",
            "owner_user_id",
            "file_sha256",
            unique=True,
            sqlite_where=Column("file_sha256").isnot(None),
            postgresql_where=Column("file_sha256").isnot(None),
        ),
        CheckConstraint(
            "source_type IN ('plaid_sync', 'snaptrade_sync', 'ofx', 'qfx', "
            "'qif', 'csv', 'manual')",
            name="ck_finance_importbatch_source",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'committed', 'failed', 'rolled_back')",
            name="ck_finance_importbatch_status",
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int = Field()
    organization_id: int | None = Field(default=None)
    connection_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_connection.id"
    )
    account_id: int | None = Field(default=None, foreign_key=f"{_FK}finance_account.id")
    import_profile_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_import_profile.id"
    )
    source_type: str = Field(max_length=16)
    file_name: str | None = Field(default=None, max_length=255)
    file_sha256: str | None = Field(default=None)
    sync_cursor_before: str | None = Field(default=None)
    sync_cursor_after: str | None = Field(default=None)
    rows_total: int = Field(default=0)
    rows_inserted: int = Field(default=0)
    rows_updated: int = Field(default=0)
    rows_duplicate: int = Field(default=0)
    rows_error: int = Field(default=0)
    status: str = Field(default="pending", max_length=16)
    error: str | None = Field(default=None)
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class FinanceImportBatchRow(SQLModel, table=True):
    """Staging: one raw parsed record per file row with parse status, match link,
    and content hash. Powers review-before-commit, reversible batches, and
    precise dup/error reporting."""

    __tablename__ = "finance_import_batch_row"
    __table_args__ = (
        Index("ix_finance_importrow_batch", "import_batch_id"),
        Index("ix_finance_importrow_owner", "owner_user_id"),
        Index("ix_finance_importrow_account", "account_id"),
        Index("ix_finance_importrow_matched_txn", "matched_transaction_id"),
        Index("ix_finance_importrow_matched_trade", "matched_trade_id"),
        Index("ix_finance_importrow_hash", "content_hash"),
        Index(
            "uq_finance_importrow_batch_num",
            "import_batch_id",
            "row_number",
            unique=True,
        ),
        CheckConstraint(
            "parsed_status IN ('parsed', 'inserted', 'updated', 'duplicate', "
            "'error', 'matched', 'skipped')",
            name="ck_finance_importrow_status",
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    import_batch_id: int = Field(foreign_key=f"{_FK}finance_import_batch.id")
    owner_user_id: int = Field()
    account_id: int | None = Field(default=None, foreign_key=f"{_FK}finance_account.id")
    row_number: int
    raw_line: str | None = Field(default=None)
    parsed: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("parsed", JSON)
    )
    content_hash: str | None = Field(default=None, max_length=64)
    fitid: str | None = Field(default=None)
    parsed_status: str = Field(max_length=12)
    matched_transaction_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_transaction.id"
    )
    matched_trade_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_trade.id"
    )
    reason: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)


class FinanceAttachment(SQLModel, table=True):
    """Receipts/documents per transaction or account (object-store key).
    Reserved to avoid a later add."""

    __tablename__ = "finance_attachment"
    __table_args__ = (
        Index("ix_finance_attachment_owner", "owner_user_id"),
        Index("ix_finance_attachment_org", "organization_id"),
        Index("ix_finance_attachment_transaction", "transaction_id"),
        Index("ix_finance_attachment_account", "account_id"),
        Index("ix_finance_attachment_deleted", "deleted_at"),
        Index(
            "uq_finance_attachment_owner_sha",
            "owner_user_id",
            "sha256",
            unique=True,
            sqlite_where=Column("sha256").isnot(None),
            postgresql_where=Column("sha256").isnot(None),
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int = Field()
    organization_id: int | None = Field(default=None)
    transaction_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_transaction.id"
    )
    account_id: int | None = Field(default=None, foreign_key=f"{_FK}finance_account.id")
    file_name: str
    content_type: str | None = Field(default=None)
    byte_size: int | None = Field(default=None)
    storage_key: str
    sha256: str | None = Field(default=None)
    deleted_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
