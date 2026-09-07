"""CSV/OFX and investment import pipeline shapes.

A topic module of the ``schemas`` package; every name here is
re-exported from the package root, which stays the one import path.
Money fields are integer minor units (cents); the frontend formats them.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from app.services.finance.models import (
        FinanceImportBatch,
        FinanceImportBatchRow,
    )


class ImportResultResponse(BaseModel):
    """Summary returned right after an import run."""

    batch_id: int | None
    rows_total: int
    rows_inserted: int
    rows_updated: int
    rows_duplicate: int
    rows_error: int
    # Not posted money (scheduled / future-dated): recorded, never ledgered.
    rows_skipped: int = 0
    # Rows for accounts the user removed - never written, never resurrected.
    rows_ignored: int = 0


class ImportPreviewEdit(BaseModel):
    """One transaction an import would update in place, with the exact
    field changes — shown to the user BEFORE anything is written."""

    transaction_id: int
    date: date
    amount: int
    name: str | None = None
    account: str | None = None
    changes: list[str]
    # The source app re-categorized this row but the user set the category
    # by hand here, so the import keeps the user's choice.
    category_kept: bool = False


class ImportPreviewResponse(BaseModel):
    """A dry-run classification of an import file: what a commit would do.

    Produced from the same plan the commit executes, and writing nothing —
    counts here match the subsequent ``ImportResultResponse`` exactly."""

    file_name: str | None = None
    rows_total: int
    # Set when these exact bytes were already imported: re-importing is a
    # no-op, so there is nothing to preview.
    identical_batch_id: int | None = None
    # A single-account layout previewed with no target account: the client
    # asks which account the statement belongs to, then previews again.
    needs_account: bool = False
    layout: str | None = None
    account_name: str | None = None
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_duplicate: int = 0
    rows_error: int = 0
    rows_skipped: int = 0
    # Rows for accounts the user removed - never written, never resurrected.
    rows_ignored: int = 0
    insert_date_start: date | None = None
    insert_date_end: date | None = None
    # Account display name -> how many new transactions land there.
    inserts_by_account: dict[str, int] = Field(default_factory=dict)
    # Accounts / categories the commit would create.
    new_accounts: list[str] = Field(default_factory=list)
    removed_accounts: list[str] = Field(default_factory=list)
    new_categories: list[str] = Field(default_factory=list)
    edits: list[ImportPreviewEdit] = Field(default_factory=list)
    category_kept_count: int = 0


class ImportBatchSummary(BaseModel):
    """An import batch without its rows — for the batch list."""

    id: int
    source_type: str
    file_name: str | None
    status: str
    rows_total: int
    rows_inserted: int
    rows_duplicate: int
    rows_error: int

    @classmethod
    def from_row(cls, batch: FinanceImportBatch) -> ImportBatchSummary:
        return cls(
            id=batch.id,
            source_type=batch.source_type,
            file_name=batch.file_name,
            status=batch.status,
            rows_total=batch.rows_total,
            rows_inserted=batch.rows_inserted,
            rows_duplicate=batch.rows_duplicate,
            rows_error=batch.rows_error,
        )


class ImportBatchRowResponse(BaseModel):
    row_number: int
    parsed_status: str
    matched_transaction_id: int | None = None
    fitid: str | None = None
    reason: str | None = None

    @classmethod
    def from_row(cls, row: FinanceImportBatchRow) -> ImportBatchRowResponse:
        return cls(
            row_number=row.row_number,
            parsed_status=row.parsed_status,
            matched_transaction_id=row.matched_transaction_id,
            fitid=row.fitid,
            reason=row.reason,
        )


class ImportBatchResponse(BaseModel):
    """An import batch plus its per-row outcomes (the review view)."""

    id: int
    source_type: str
    file_name: str | None
    status: str
    rows_total: int
    rows_inserted: int
    rows_duplicate: int
    rows_error: int
    rows: list[ImportBatchRowResponse]

    @classmethod
    def from_batch(
        cls, batch: FinanceImportBatch, rows: list[FinanceImportBatchRow]
    ) -> ImportBatchResponse:
        return cls(
            id=batch.id,
            source_type=batch.source_type,
            file_name=batch.file_name,
            status=batch.status,
            rows_total=batch.rows_total,
            rows_inserted=batch.rows_inserted,
            rows_duplicate=batch.rows_duplicate,
            rows_error=batch.rows_error,
            rows=[ImportBatchRowResponse.from_row(r) for r in rows],
        )


class InvestmentImportPosition(BaseModel):
    """One security's replayed ending position - what the ledger says you
    hold once every row is applied. ``value`` is cents at the security's
    LAST price seen in the ledger - the freshest mark the file itself can
    honestly claim, not a live quote."""

    name: str
    shares: float
    value: int


class InvestmentImportPreviewResponse(BaseModel):
    """Parse-only look at an activity ledger: what it carries and what it
    replays to, before any account is chosen or anything is written."""

    activities_parsed: int
    first_date: date
    last_date: date
    total_value: int  # cents, sum of position values
    positions: list[InvestmentImportPosition]


class InvestmentImportResultResponse(BaseModel):
    """Outcome of a custodian activity-ledger import (investments lane)."""

    activities_parsed: int
    trades_inserted: int
    trades_updated: int
    securities_created: int
    securities_matched: int
    account_id: int
    account_name: str
    account_created: bool
