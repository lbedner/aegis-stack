"""Transaction and cashflow shapes.

A topic module of the ``schemas`` package; every name here is
re-exported from the package root, which stays the one import path.
Money fields are integer minor units (cents); the frontend formats them.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from app.services.finance.models import FinanceTransaction

from app.services.finance.schemas.categorization import TagRef


class SplitLineResponse(BaseModel):
    """One line of a split transaction, category name resolved by the
    list endpoint like ``TransactionResponse.category``."""

    id: int
    amount: int
    category_id: int | None = None
    category: str | None = None
    memo: str | None = None


class TransactionResponse(BaseModel):
    """A single ledger transaction — full detail.

    Every user-meaningful field ships in one payload so the register, hover
    tooltips, and the click-through detail dialog all read from the same row
    without a per-interaction fetch."""

    id: int
    account_id: int
    date: date
    authorized_date: date | None = None
    posted_at: datetime | None = None
    name: str | None = None
    original_description: str | None = None
    merchant_name: str | None = None
    amount: int
    raw_amount: int | None = None
    currency: str
    source: str
    external_id: str | None = None
    category_id: int | None = None
    # Resolved name for ``category_id``, filled by the list endpoint so a
    # register can show the category without a lookup per row.
    category: str | None = None
    category_source: str = "unset"
    # The assigned payee (FinanceMerchant) and its resolved name - same
    # id + filled-by-the-list-endpoint shape as category above. None means
    # no payee assigned yet, and the register falls back to showing the raw
    # descriptor.
    merchant_id: int | None = None
    merchant: str | None = None
    # Base64 PNG for the payee's brand icon (merchant_icon.py).
    icon_b64: str | None = None
    pfc_primary: str | None = None
    pfc_detailed: str | None = None
    memo: str | None = None
    check_number: str | None = None
    payment_channel: str | None = None
    pending: bool = False
    status: str = "posted"
    dedup_status: str = "unique"
    is_transfer: bool = False
    excluded_from_reports: bool = False
    is_reversal: bool = False
    is_split: bool = False
    # Filled by the list endpoint (batched), like ``category``/``merchant``.
    tags: list[TagRef] = Field(default_factory=list)
    splits: list[SplitLineResponse] = Field(default_factory=list)

    @classmethod
    def from_row(cls, row: FinanceTransaction) -> TransactionResponse:
        return cls(
            id=row.id,
            account_id=row.account_id,
            date=row.date_,
            authorized_date=row.authorized_date,
            posted_at=row.datetime_,
            name=row.name,
            original_description=row.original_description,
            merchant_name=row.merchant_name,
            amount=row.amount,
            raw_amount=row.raw_amount,
            currency=row.currency,
            source=row.source,
            external_id=row.external_id,
            category_id=row.category_id,
            category_source=row.category_source,
            merchant_id=row.merchant_id,
            pfc_primary=row.pfc_primary,
            pfc_detailed=row.pfc_detailed,
            memo=row.memo,
            check_number=row.check_number,
            payment_channel=row.payment_channel,
            pending=row.pending,
            status=row.status,
            dedup_status=row.dedup_status,
            is_transfer=row.is_transfer,
            excluded_from_reports=row.excluded_from_reports,
            is_reversal=row.is_reversal,
            is_split=row.is_split,
        )


class TransactionListResponse(BaseModel):
    items: list[TransactionResponse]
    total: int


class SplitPart(BaseModel):
    """One requested line of a transaction split.

    ``amount`` is a positive magnitude in minor units; the service applies
    the parent's sign and fills any unclaimed difference with a remainder
    line, so callers only state what they know."""

    amount: int
    category_id: int | None = None
    memo: str | None = None


class TransactionSplitRequest(BaseModel):
    parts: list[SplitPart]


class SplitListResponse(BaseModel):
    items: list[SplitLineResponse]


class UnsplitResponse(BaseModel):
    removed: int


class SpendingCategory(BaseModel):
    """One row of the spending-by-category breakdown."""

    category: str
    amount: int  # positive minor units (outflow magnitude)


class TransactionCreate(BaseModel):
    account_id: int
    amount: int
    date: date
    name: str | None = None
    category_id: int | None = None


class TransactionCategorize(BaseModel):
    category_id: int


class SpendingSummaryResponse(BaseModel):
    """Per-category spend for a month (transfers excluded)."""

    month: str  # YYYY-MM
    categories: list[SpendingCategory]
    total: int  # cents


class CashflowMonth(BaseModel):
    """One month of income vs spend, both positive magnitudes."""

    month: str  # YYYY-MM
    income: int  # cents
    expense: int  # cents, positive
    net: int  # cents, signed


class CashflowResponse(BaseModel):
    items: list[CashflowMonth]
    total: int


class TransactionDelete(BaseModel):
    """Bulk soft-delete from the register's selection row."""

    transaction_ids: list[int]


class SimilarTransaction(BaseModel):
    """One payee-less lookalike, for the "also apply to N similar" offer -
    a suggestion the user confirms, never applied on its own."""

    id: int
    date: date
    name: str
    amount: int


class SimilarTransactionListResponse(BaseModel):
    items: list[SimilarTransaction]
    total: int


class TransactionDeleteResult(BaseModel):
    deleted: int
