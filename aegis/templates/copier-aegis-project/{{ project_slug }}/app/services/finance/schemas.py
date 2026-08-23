"""Finance service request/response schemas (plain Pydantic DTOs).

Mirrors ``payment/schemas.py``: flat response DTOs with a ``from_row`` mapper,
list responses wrapping ``items`` + ``total``, and request models for writes.
Money fields are integer minor units (cents); the frontend formats them.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field
from app.services.finance.constants import CadenceKey
# Re-exported: goal_schemas owns the definitions, this module stays the
# one import path every caller already uses.
from app.services.finance.goal_schemas import (  # noqa: F401
    GoalContribute,
    GoalCreate,
    GoalListResponse,
    GoalResponse,
    GoalTargetPreview,
    GoalUpdate,
)

if TYPE_CHECKING:
    from app.services.finance.models import (
        FinanceAccount,
        FinanceConnection,
        FinanceHolding,
        FinanceImportBatch,
        FinanceImportBatchRow,
        FinanceInsight,
        FinanceLiabilityDetail,
        FinanceNetWorthSnapshot,
        FinanceRecurringStream,
        FinanceSecurity,
        FinanceTrade,
        FinanceTransaction,
        FinanceTransfer,
        FinanceValuation,
    )

# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class LiabilitySummary(BaseModel):
    """Credit-account liability detail (statement/payment/APR). Present on an
    account only when the institution reports it — absent fields stay None."""

    last_statement_balance: int | None = None
    last_statement_issue_date: date | None = None
    minimum_payment_amount: int | None = None
    next_payment_due_date: date | None = None
    last_payment_amount: int | None = None
    last_payment_date: date | None = None
    is_overdue: bool | None = None
    aprs: list[Any] = Field(default_factory=list)

    @classmethod
    def from_row(cls, row: FinanceLiabilityDetail) -> LiabilitySummary:
        return cls(
            last_statement_balance=row.last_statement_balance,
            last_statement_issue_date=row.last_statement_issue_date,
            minimum_payment_amount=row.minimum_payment_amount,
            next_payment_due_date=row.next_payment_due_date,
            last_payment_amount=row.last_payment_amount,
            last_payment_date=row.last_payment_date,
            is_overdue=row.is_overdue,
            aprs=row.aprs or [],
        )


class AccountResponse(BaseModel):
    """A single account (manual or provider-linked)."""

    id: int
    name: str
    account_type: str
    classification: str
    current_balance: int | None
    # When a real balance write last happened (provider sync, statement
    # import, valuation). Accounts are created with ``current_balance=0``,
    # so a bare zero WITHOUT this stamp means "never set", and the UI
    # falls back to the register sum instead of rendering $0.00.
    balance_as_of: datetime | None = None
    # Balance derived from the sum of imported transactions (the register
    # balance Quicken shows). Useful when no valuation/statement balance was
    # set. Falls back to 0 when there are no transactions.
    activity_balance: int = 0
    currency: str
    is_manual: bool
    institution_id: int | None = None
    connection_id: int | None = None
    liability: LiabilitySummary | None = None

    @classmethod
    def from_row(
        cls,
        row: FinanceAccount,
        *,
        activity_balance: int = 0,
        liability: FinanceLiabilityDetail | None = None,
    ) -> AccountResponse:
        return cls(
            id=row.id,
            name=row.name,
            account_type=row.account_type,
            classification=row.classification,
            current_balance=row.current_balance,
            balance_as_of=row.balance_as_of,
            activity_balance=activity_balance,
            currency=row.currency,
            is_manual=row.is_manual,
            institution_id=row.institution_id,
            connection_id=row.connection_id,
            liability=(
                LiabilitySummary.from_row(liability) if liability is not None else None
            ),
        )


class AccountListResponse(BaseModel):
    items: list[AccountResponse]
    total: int


class ConnectionResponse(BaseModel):
    """A provider connection (e.g. a Plaid Item) the user can disconnect. Its
    accounts are matched client-side by ``connection_id`` on the account list."""

    id: int
    provider: str
    environment: str
    status: str
    status_detail: str | None = None
    label: str | None = None
    institution_id: int | None = None
    last_successful_sync_at: datetime | None = None
    created_at: datetime

    @classmethod
    def from_row(cls, row: FinanceConnection) -> ConnectionResponse:
        return cls(
            id=row.id,
            provider=row.provider,
            environment=row.environment,
            status=row.status,
            status_detail=row.status_detail,
            label=row.label,
            institution_id=row.institution_id,
            last_successful_sync_at=row.last_successful_sync_at,
            created_at=row.created_at,
        )


class ConnectionListResponse(BaseModel):
    items: list[ConnectionResponse]
    total: int


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
    # Filled by the list endpoint (batched), like ``category``/``merchant``.
    tags: list[TagRef] = Field(default_factory=list)

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
        )


class TransactionListResponse(BaseModel):
    items: list[TransactionResponse]
    total: int


class SpendingCategory(BaseModel):
    """One row of the spending-by-category breakdown."""

    category: str
    amount: int  # positive minor units (outflow magnitude)


class NetWorthResponse(BaseModel):
    """Live net worth = assets - liabilities (signed integer minor units)."""

    net_worth_amount: int
    total_assets_amount: int
    total_liabilities_amount: int
    currency: str


class FinanceStatusSummary(BaseModel):
    """Headline numbers for the dashboard card / health check / CLI status."""

    net_worth_amount: int
    total_assets_amount: int
    total_liabilities_amount: int
    account_count: int
    connection_count: int
    new_insight_count: int = 0
    # Whether this build shipped the analyst agent, so the dashboard can hide
    # the Notes tab rather than offer a surface that cannot be filled.
    analyst_enabled: bool = False
    currency: str


class NetWorthPoint(BaseModel):
    """One day of the net-worth-over-time series (off the snapshot table)."""

    as_of_date: date
    net_worth_amount: int
    total_assets_amount: int
    total_liabilities_amount: int

    @classmethod
    def from_row(cls, row: FinanceNetWorthSnapshot) -> NetWorthPoint:
        return cls(
            as_of_date=row.as_of_date,
            net_worth_amount=row.net_worth_amount,
            total_assets_amount=row.total_assets_amount,
            total_liabilities_amount=row.total_liabilities_amount,
        )


class FinanceHealth(BaseModel):
    """Liveness summary returned by ``GET /api/v1/finance/health``.

    ``status`` is ``"ok"`` when no connection needs the user's attention,
    otherwise ``"attention"``.
    """

    status: str
    accounts: int
    connections: int
    connections_needing_action: int = 0


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class ValuationResponse(BaseModel):
    """A dated value mark on a manual/off-aggregator account."""

    id: int
    account_id: int
    as_of_date: date
    value: int
    source: str
    note: str | None = None

    @classmethod
    def from_row(cls, row: FinanceValuation) -> ValuationResponse:
        return cls(
            id=row.id,
            account_id=row.account_id,
            as_of_date=row.as_of_date,
            value=row.value,
            source=row.source,
            note=row.note,
        )


class ValuationListResponse(BaseModel):
    items: list[ValuationResponse]
    total: int


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


class ReconcileRequest(BaseModel):
    """Reconcile an account to a statement (FIN-37).

    ``preview=True`` computes the register-vs-statement delta without
    writing anything; the commit call re-sends the same fields."""

    statement_date: date
    statement_balance: int  # signed cents, as the statement puts it
    preview: bool = False


class ReconcileResponse(BaseModel):
    account_id: int
    # 'adjustment' (transfer-flagged transaction absorbs the delta) or
    # 'valuation' (no register: the statement posts as a valuation).
    route: str
    statement_date: date
    statement_balance: int
    register_balance: int
    delta: int
    applied: bool = False
    adjustment_transaction_id: int | None = None
    reconciled_through: date | None = None


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


class ManualAccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    account_type: str
    classification: str
    current_balance: int = 0
    currency: str = "usd"
    institution_id: int | None = None


class AccountUpdate(BaseModel):
    """Partial update — only provided fields change."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_hidden: bool | None = None
    is_closed: bool | None = None


class TransactionCreate(BaseModel):
    account_id: int
    amount: int
    date: date
    name: str | None = None
    category_id: int | None = None


class TransactionCategorize(BaseModel):
    category_id: int


class CategorySuggestion(BaseModel):
    """A payee-precedent category guess for one still-uncategorized
    transaction - a preview, not a write. The caller decides whether to
    apply it (via the ordinary categorize endpoint)."""

    transaction_id: int
    category_id: int
    category_name: str


class CategorySuggestionListResponse(BaseModel):
    items: list[CategorySuggestion]
    skipped: int


class SuggestCategoriesRequest(BaseModel):
    """POST body for /transactions/auto-categorize. Omitted or empty
    ``transaction_ids`` sweeps the full uncategorized backlog, unchanged
    from before this existed; a non-empty list scopes the sweep to a
    caller-chosen subset (e.g. a checkbox selection)."""

    transaction_ids: list[int] | None = None


class ValuationCreateRequest(BaseModel):
    """POST body for /accounts/{id}/valuations (account comes from the path)."""

    as_of_date: date
    value: int
    source: str = "manual"
    note: str | None = None


# ---------------------------------------------------------------------------
# Investments (securities + holdings)
# ---------------------------------------------------------------------------
class SecurityResponse(BaseModel):
    """A catalog security (equity, ETF, fund, crypto, ...)."""

    id: int
    ticker: str | None
    name: str | None
    security_type: str | None
    currency: str | None

    @classmethod
    def from_row(cls, row: FinanceSecurity) -> SecurityResponse:
        return cls(
            id=row.id,
            ticker=row.ticker,
            name=row.name,
            security_type=row.security_type,
            currency=row.currency,
        )


class HoldingResponse(BaseModel):
    """A current position with its computed market value (cents)."""

    id: int
    account_id: int
    security_id: int
    ticker: str | None = None
    name: str | None = None
    security_type: str | None = None
    as_of_date: date
    quantity: float  # shares = quantity_e8 / 1e8
    price: int | None  # unit price in scaled minor units
    price_scale: int
    cost_basis: int | None
    market_value: int  # cents
    currency: str
    icon_b64: str | None = None  # set by the router; from_parts has no async access

    @classmethod
    def from_parts(
        cls,
        holding: FinanceHolding,
        security: FinanceSecurity | None,
        market_value: int,
    ) -> HoldingResponse:
        return cls(
            id=holding.id,
            account_id=holding.account_id,
            security_id=holding.security_id,
            ticker=security.ticker if security else None,
            name=security.name if security else None,
            security_type=security.security_type if security else None,
            as_of_date=holding.as_of_date,
            quantity=holding.quantity_e8 / 100_000_000,
            price=holding.price,
            price_scale=holding.price_scale,
            cost_basis=holding.cost_basis,
            market_value=market_value,
            currency=holding.currency,
        )


class HoldingListResponse(BaseModel):
    items: list[HoldingResponse]
    total: int
    portfolio_value: int  # cents


class BudgetMonthOutlook(BaseModel):
    """One future month's header equation, bills at face value on their
    real cadence - the month the annual premium lands looks like itself."""

    period_month: int  # YYYYMM
    income_due: int
    bills_due: int
    budgets: int
    goals: int
    envelopes: int
    everything_else: int = 0
    month_net: int
    # The level under the rates: cash compounded from today's balance.
    start_balance: int = 0
    end_balance: int = 0


class BudgetOutlookResponse(BaseModel):
    items: list[BudgetMonthOutlook]
    total: int


class EnvelopeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    monthly_credit: int | None = Field(default=None, ge=0)
    cadence: Literal["weekly", "monthly"] = "monthly"
    starting_balance: int = Field(default=0, ge=0)


class EnvelopeUpdate(BaseModel):
    """Whole-state update: both fields, every time (an envelope has two)."""

    monthly_credit: int | None = Field(default=None, ge=0)
    auto_credit: bool = False
    cadence: Literal["weekly", "monthly"] = "monthly"


class EnvelopeMove(BaseModel):
    """A credit or a spend - always positive; the endpoint carries the sign."""

    amount: int = Field(gt=0)
    note: str | None = Field(default=None, max_length=255)
    when: date | None = None


class EnvelopeResponse(BaseModel):
    account_id: int
    name: str
    balance: int  # cents; may be negative (borrowed against next month)
    monthly_credit: int | None
    auto_credit: bool
    cadence: str


class EnvelopeListResponse(BaseModel):
    items: list[EnvelopeResponse]
    total: int


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


class TradeResponse(BaseModel):
    """One investment trade / security movement (buy/sell/dividend/...).

    ``amount`` is in cents, negative when cash left the account (a buy/fee)
    and positive when it arrived (a sell/dividend) — the same convention as
    cash transactions.
    """

    id: int
    account_id: int
    security_id: int | None = None
    type: str
    subtype: str | None = None
    trade_date: date
    quantity: float | None  # shares = quantity_e8 / 1e8
    price: int | None  # unit price in scaled minor units
    price_scale: int
    amount: int  # cents (signed: negative = cash out)
    fees: int | None
    name: str | None = None
    currency: str

    @classmethod
    def from_row(cls, trade: FinanceTrade) -> TradeResponse:
        return cls(
            id=trade.id,
            account_id=trade.account_id,
            security_id=trade.security_id,
            type=trade.type,
            subtype=trade.subtype,
            trade_date=trade.trade_date,
            quantity=(
                trade.quantity_e8 / 100_000_000
                if trade.quantity_e8 is not None
                else None
            ),
            price=trade.price,
            price_scale=trade.price_scale,
            amount=trade.amount,
            fees=trade.fees,
            name=trade.name,
            currency=trade.currency,
        )


class TradeListResponse(BaseModel):
    items: list[TradeResponse]
    total: int


class TransferResponse(BaseModel):
    """A matched internal transfer between two of the user's own accounts."""

    id: int
    from_account_id: int | None
    to_account_id: int | None
    from_transaction_id: int | None
    to_transaction_id: int | None
    amount: int | None  # cents
    currency: str
    transfer_date: date | None
    is_credit_card_payment: bool
    match_method: str
    confidence: int | None
    status: str  # suggested | confirmed | rejected
    # The full leg transactions — the decisive context for a review decision
    # ("Starbucks -> INTRST PYMNT" is obviously not a transfer), and the same
    # payload the click-through detail dialog renders.
    from_transaction: TransactionResponse | None = None
    to_transaction: TransactionResponse | None = None

    @classmethod
    def from_row(
        cls,
        transfer: FinanceTransfer,
        *,
        from_txn: FinanceTransaction | None = None,
        to_txn: FinanceTransaction | None = None,
    ) -> TransferResponse:
        return cls(
            id=transfer.id,
            from_account_id=transfer.from_account_id,
            to_account_id=transfer.to_account_id,
            from_transaction_id=transfer.from_transaction_id,
            to_transaction_id=transfer.to_transaction_id,
            amount=transfer.amount,
            currency=transfer.currency,
            transfer_date=transfer.transfer_date,
            is_credit_card_payment=transfer.is_credit_card_payment,
            match_method=transfer.match_method,
            confidence=transfer.confidence,
            status=transfer.status,
            from_transaction=(
                TransactionResponse.from_row(from_txn) if from_txn else None
            ),
            to_transaction=(TransactionResponse.from_row(to_txn) if to_txn else None),
        )


class TransferListResponse(BaseModel):
    items: list[TransferResponse]
    total: int


class SpendingSummaryResponse(BaseModel):
    """Per-category spend for a month (transfers excluded)."""

    month: str  # YYYY-MM
    categories: list[SpendingCategory]
    total: int  # cents


class RecurringStreamResponse(BaseModel):
    """A detected recurring stream (subscription, bill, or paycheck)."""

    id: int
    account_id: int | None
    name: str
    direction: str  # inflow | outflow
    frequency: str
    average_amount: int | None  # cents (magnitude)
    last_amount: int | None
    amount_is_variable: bool
    currency: str
    next_expected_date: date | None
    last_date: date | None  # last transaction actually matched to this stream
    occurrence_count: int
    status: str
    confidence: int | None
    is_subscription: bool
    is_muted: bool
    # Paused while this date is ahead: out of the forecast, the Bills
    # total, the verdict and every nag until then - and back by itself
    # the day it passes. ``pause_note`` is the why, for the future
    # reader who forgot.
    paused_until: date | None = None
    pause_note: str | None = None
    # A card/loan payment stream: charged by the cash forecast, excluded
    # from the Bills total (the swipes already counted), tagged in the UI
    # so "it's a transfer" and "it's a payment" stop being a riddle.
    is_payment: bool = False
    is_user_confirmed: bool
    source: str  # "derived" (detector) | "provider" | "user" (hand-entered)
    expected_amount: int | None  # cents; set for declared bills/income
    # Display names, resolved by the list endpoint in one query each; None
    # on single-row responses (create/update), where the UI reloads the list.
    account_name: str | None = None
    category_name: str | None = None
    # The category set ON THE BILL, if any - distinct from category_name,
    # which falls back to the one inferred from its transactions. The edit
    # dialog needs the id to prefill its dropdown, and needs it empty when
    # the shown name is only an inference.
    category_id: int | None = None
    # Also list-endpoint-only (same reasoning as above): a favicon guess
    # (merchant_icon.py) and the "fresh"/"overdue"/"stale" recency read
    # (categorize.insights.stream_staleness) - both need context (today,
    # the lookback floor) the single-row create/update/mute endpoints have
    # no reason to compute for a response the UI immediately discards.
    # Base64 PNG, inlined by the list endpoint - see merchant_icon.py
    # for why the bytes travel rather than a URL.
    icon_b64: str | None = None
    staleness: str = "fresh"

    @classmethod
    def from_row(
        cls,
        row: FinanceRecurringStream,
        *,
        account_name: str | None = None,
        category_name: str | None = None,
        icon_b64: str | None = None,
        staleness: str = "fresh",
        is_payment: bool = False,
    ) -> RecurringStreamResponse:
        return cls(
            id=row.id,
            account_id=row.account_id,
            name=row.name,
            direction=row.direction,
            frequency=row.frequency,
            average_amount=row.average_amount,
            last_amount=row.last_amount,
            amount_is_variable=row.amount_is_variable,
            currency=row.currency,
            next_expected_date=row.next_expected_date,
            last_date=row.last_date,
            occurrence_count=row.occurrence_count,
            status=row.status,
            confidence=row.confidence,
            is_subscription=row.is_subscription,
            is_muted=row.is_muted,
            paused_until=row.paused_until,
            pause_note=(row.metadata_ or {}).get("pause_note"),
            is_payment=is_payment,
            is_user_confirmed=row.is_user_confirmed,
            source=row.source,
            expected_amount=row.expected_amount,
            category_id=row.category_id,
            account_name=account_name,
            category_name=category_name,
            icon_b64=icon_b64,
            staleness=staleness,
        )


class RecurringStreamCreate(BaseModel):
    """A hand-entered bill (outflow) or income (inflow) stream."""

    name: str
    direction: Literal["inflow", "outflow"]
    frequency: CadenceKey
    expected_amount: int  # cents (magnitude)
    next_expected_date: date
    account_id: int | None = None
    is_subscription: bool = False


class RecurringAttach(BaseModel):
    """Reconcile one transaction with the bill it paid."""

    transaction_id: int


class RecurringPause(BaseModel):
    """Pause a stream until a date, with an optional why."""

    until: date
    note: str | None = Field(default=None, max_length=500)


class RecurringStreamUpdate(BaseModel):
    """Edits to a stream's declared facts; omitted fields stay as they are."""

    name: str | None = None
    frequency: CadenceKey | None = None
    expected_amount: int | None = None  # cents (magnitude)
    next_expected_date: date | None = None
    # Stated about the BILL and stops there - its transactions keep the
    # categories they have (see FinanceService.update_recurring).
    category_id: int | None = None
    # Which account it is paid from. A hand-entered bill can be created
    # without one, and then it cannot reach the forecast at all.
    account_id: int | None = None


class RecurringCategorize(BaseModel):
    """Set one category across several bills at once."""

    stream_ids: list[int]
    category_id: int


class RecurringListResponse(BaseModel):
    items: list[RecurringStreamResponse]
    total: int
    monthly_cost: int  # cents — monthly-equivalent of recurring outflows


class PayeeTotal(BaseModel):
    """One payee's outflow over a window (positive magnitude)."""

    payee: str
    amount: int  # cents, positive
    transaction_count: int


class PayeeListResponse(BaseModel):
    items: list[PayeeTotal]
    total: int


class CashflowMonth(BaseModel):
    """One month of income vs spend, both positive magnitudes."""

    month: str  # YYYY-MM
    income: int  # cents
    expense: int  # cents, positive
    net: int  # cents, signed


class CashflowResponse(BaseModel):
    items: list[CashflowMonth]
    total: int


class CategoryUsageResponse(BaseModel):
    """A category plus how it is actually used, for the Categories tab."""

    id: int
    name: str  # flattened "Parent:Child" path as the import produced it
    classification: str  # expense | income | transfer
    is_system: bool
    transaction_count: int
    total: int  # signed cents (negative = net outflow)
    last_used: date | None = None


class CategoryListResponse(BaseModel):
    items: list[CategoryUsageResponse]
    total: int


class CategoryOption(BaseModel):
    """id + name only, for a picker - no usage aggregation."""

    id: int
    name: str


class CategoryOptionListResponse(BaseModel):
    items: list[CategoryOption]


class CategoryCreate(BaseModel):
    """A category typed by hand, in the house ``Parent:Child`` shape.

    Resolved through the same get-or-create the importer uses, so a
    spacing or case variant lands on the row that already exists rather
    than beside it - which is the whole reason inline creation was
    withheld from the picker for so long.
    """

    name: str = Field(min_length=1, max_length=128)


class MerchantResponse(BaseModel):
    """A payee: the stable identity behind a raw bank descriptor.

    The usage fields are how the payee directory shows weight rather than
    a bare list of names - which payee is worth correcting depends on how
    much money runs through it. They default to zero so the assign picker,
    which asks for the same list, is unaffected.
    """

    id: int
    name: str
    website_url: str | None = None
    logo_url: str | None = None
    default_category_id: int | None = None
    transaction_count: int = 0
    total_amount: int = 0
    last_date: date | None = None
    # Resolved brand icon, so the directory can SHOW the logo it exists to
    # let you correct. Same base64 inlining the register uses.
    icon_b64: str | None = None


class MerchantListResponse(BaseModel):
    items: list[MerchantResponse]
    total: int


class MerchantCreate(BaseModel):
    name: str
    # Optional real address ("aegis-stack.io") - used for the
    # brand icon instead of guessing <name>.com.
    website_url: str | None = None


class MerchantUpdate(BaseModel):
    """A partial edit of a payee.

    Every field is optional AND nullable, which are different things here:
    omitting ``website_url`` leaves it alone, sending ``""`` clears it.
    The route passes only what the client actually set
    (``exclude_unset``), so a patch that fixes an address cannot blank the
    default category by saying nothing about it.
    """

    name: str | None = None
    website_url: str | None = None
    default_category_id: int | None = None


class MerchantMerge(BaseModel):
    """Fold ``source_ids`` into the payee in the path. Losers are soft
    deleted; their transactions and bills repoint to the survivor."""

    source_ids: list[int]


class TagRef(BaseModel):
    """A tag as it rides a transaction row - identity plus display facts."""

    id: int
    name: str
    color: str | None = None


class TagResponse(TagRef):
    """One row of the tag directory: the tag plus how many transactions
    wear it."""

    transaction_count: int = 0


class TagAssign(BaseModel):
    """Attach one tag (created on first use) to many transactions - the
    bulk-selection verb, same shape as ``MerchantAssign``."""

    transaction_ids: list[int]
    name: str


class TransactionDelete(BaseModel):
    """Bulk soft-delete from the register's selection row."""

    transaction_ids: list[int]


class MerchantAssign(BaseModel):
    """``merchant_id=None`` clears the payee off the given transactions.

    ``category_id``, when given, also files those transactions under that
    category AND remembers it on the payee (``default_category_id``) - the
    moment you name a payee is the moment you know what it is, and a payee
    that carries its own category is what stops the categorizer guessing
    at the same descriptor forever.
    """

    transaction_ids: list[int]
    merchant_id: int | None = None
    category_id: int | None = None


class DeclareRecurring(BaseModel):
    """Mark the selected transactions as a recurring bill or income.

    Cadence, amount, direction and next date are all measured from the
    transactions themselves, the same way detection measures them, so
    there is nothing here for the caller to get wrong or for the two paths
    to disagree about. ``names`` is the one exception, because a bill's
    NAME cannot be measured: it is keyed by ``RecurringPlanGroup.key`` from
    the preview, and anything left out keeps the name the preview proposed.
    """

    transaction_ids: list[int]
    names: dict[str, str] = Field(default_factory=dict)
    # Category for the bills this creates, keyed the same way as ``names``.
    # Set on the STREAM only - the transactions rolling into it keep
    # whatever categories they already carry.
    categories: dict[str, int] = Field(default_factory=dict)
    # What the bill actually costs, keyed like ``names``. Stating it pins
    # the stream fixed-amount, beating a median taken over whatever the
    # sweep rounded up.
    amounts: dict[str, int] = Field(default_factory=dict)
    # The cadence, keyed like ``names``. Measuring it only works for the
    # six canonical gaps detection knows: a semiannual premium measures as
    # "irregular", which the forecast cannot step, so the bill never
    # appears in it. A label the forecast cannot step is ignored.
    frequencies: dict[str, str] = Field(default_factory=dict)
    # Rows unticked in the preview. They stay out of the bill AND stay out
    # of it afterwards: a confirmed bill owns its membership, so detection
    # will not quietly re-add them on its next pass.
    exclude_transaction_ids: list[int] = Field(default_factory=list)


class RecurringPlanMember(BaseModel):
    """One transaction that would roll up into a planned bill."""

    id: int
    date: str
    name: str
    amount: int


class RecurringPlanEntry(BaseModel):
    """One bill the selection would produce. Everything the confirm step
    needs to show what is about to happen before it happens."""

    key: str
    name: str
    account_id: int
    account_name: str | None = None
    direction: str
    frequency: str
    average_amount: int
    last_amount: int
    first_date: str | None = None
    last_date: str | None = None
    next_expected_date: str | None = None
    amount_is_variable: bool = False
    # ``occurrence_count`` is the roll-up; ``selected_count`` is what the
    # user actually ticked. Showing both is the point of the preview.
    occurrence_count: int
    selected_count: int
    # Median of the rows actually ticked - what the Amount field prefills
    # with, since it is the only figure the user can vouch for.
    selected_amount: int = 0
    # Streams already describing this bill that would fold into it.
    absorbs: list[str] = Field(default_factory=list)
    # True when this becomes a SECOND bill for a payee that already has a
    # confirmed one on this account (Anthropic: a subscription and API
    # usage), rather than being merged into it.
    creates_new_bill: bool = False
    existing_bill_name: str | None = None
    members: list[RecurringPlanMember] = Field(default_factory=list)


class RecurringPlanResponse(BaseModel):
    items: list[RecurringPlanEntry]
    total_transactions: int = 0


class MerchantCategorySummary(BaseModel):
    """What categories a payee's transactions currently use - the basis
    for pre-filling the "also set category" offer, and for saying out loud
    when a payee's own history disagrees with itself."""

    merchant_id: int
    default_category_id: int | None = None
    # Most-used category across this payee's transactions (None when it has
    # none categorized yet), plus how lopsided that is.
    dominant_category_id: int | None = None
    dominant_category_name: str | None = None
    dominant_count: int = 0
    total: int = 0
    distinct_categories: int = 0


class PayeeGroup(BaseModel):
    """Payee-less transactions sharing one descriptor key - the unit the
    No-payee queue is actually worked in."""

    key: str
    suggested_name: str
    count: int
    sample: str
    total_amount: int


class PayeeGroupListResponse(BaseModel):
    """``items`` is a page (biggest groups first); the totals describe the
    whole backlog behind it, so the UI can say what the page leaves out."""

    items: list[PayeeGroup]
    total: int  # distinct groups overall, NOT len(items)
    total_transactions: int = 0


class PayeeGroupAssign(BaseModel):
    """Name one or more groups at once. ``merchant_id`` attaches an
    existing payee; ``name`` creates (or reuses) one by name.

    ``keys`` is a LIST because one brand routinely splits across many
    groups - the descriptor carries a store, a city and a transaction id,
    so "DOORDASH*CROWN FRIEDSAN...", "BT*DD *DOORDASH MCDOSAN..." and
    "VENMO *DOORDASH XXX-XXX-4430" land in 48 separate groups for a
    single payee. Naming them one dialog at a time is 48 decisions for
    one fact, so the caller selects the whole set and sends it together.
    """

    keys: list[str]
    merchant_id: int | None = None
    name: str | None = None
    website_url: str | None = None
    category_id: int | None = None


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


class BudgetSuggestion(BaseModel):
    """A budget line your own spending already implies."""

    category_id: int
    category_name: str | None = None
    suggested_amount: int  # cents/month, the MEDIAN of complete months
    months_seen: int
    # Months out of the six that did not look like the others (outside
    # +/-50% of the median). 0 is a category that never varies; more than
    # one and it is not suggested at all.
    unusual_months: int


class DismissedBudgetSuggestion(BaseModel):
    """A suggestion the user declined - excluded until restored."""

    category_id: int
    category_name: str | None = None


class BudgetSuggestionListResponse(BaseModel):
    items: list[BudgetSuggestion]
    total: int
    dismissed: list[DismissedBudgetSuggestion] = Field(default_factory=list)


class BudgetSuggestionIds(BaseModel):
    """Request body for dismissing or restoring suggestions."""

    category_ids: list[int]


class ProjectionPoint(BaseModel):
    """One scheduled occurrence in the projected-balance walk.

    Either a recurring stream or a budget drawdown - the everyday spending
    nobody bills you for. A budget point has no ``stream_id``.
    """

    date: date
    stream_id: int | None = None
    name: str
    direction: str  # inflow | outflow
    amount: int  # signed cents (+income, -bill)
    balance: int  # projected running balance after this occurrence, cents
    account: str | None = None  # account name, when the stream is account-bound
    category: str | None = None  # category name, when the stream carries one


class ProjectionResponse(BaseModel):
    """Today's cash balance walked forward through scheduled bills/income."""

    as_of: date
    horizon_days: int
    start_balance: int  # cents
    upcoming_total: int  # signed cents — net of everything in the window
    end_balance: int  # cents
    points: list[ProjectionPoint]
    total: int


class InsightResponse(BaseModel):
    """A rule-based "wasting money" insight."""

    id: int
    insight_type: str
    severity: str
    title: str
    body: str | None
    detected_amount: int | None
    related_stream_id: int | None
    related_transaction_id: int | None
    related_category_id: int | None
    status: str
    # Analyst notes record which model wrote them here; rule findings leave it
    # empty. The Notes tab shows it so a re-tuned model is visible in the UI.
    metadata: dict[str, Any] = {}

    @classmethod
    def from_row(cls, row: FinanceInsight) -> InsightResponse:
        return cls(
            id=row.id,
            insight_type=row.insight_type,
            severity=row.severity,
            title=row.title,
            body=row.body,
            detected_amount=row.detected_amount,
            related_stream_id=row.related_stream_id,
            related_transaction_id=row.related_transaction_id,
            related_category_id=row.related_category_id,
            status=row.status,
            metadata=row.metadata_ or {},
        )


class InsightListResponse(BaseModel):
    items: list[InsightResponse]
    total: int


class SecurityCreate(BaseModel):
    """POST body for /securities."""

    ticker: str
    name: str | None = None
    security_type: str | None = None
    currency: str = "usd"


class HoldingCreate(BaseModel):
    """POST body for /accounts/{id}/holdings (account from the path).

    ``ticker`` resolves or creates the security; ``quantity`` is in shares;
    ``price`` is the unit price in minor units (cents, price_scale 2).
    """

    ticker: str
    name: str | None = None
    security_type: str | None = None
    as_of_date: date | None = None
    quantity: float
    price: int | None = None
    cost_basis: int | None = None


# ---------------------------------------------------------------------------
# Provider connectivity (Plaid + SnapTrade)
# ---------------------------------------------------------------------------
class LinkTokenResponse(BaseModel):
    """A Plaid Link token the frontend hands to Plaid Link."""

    link_token: str


class PlaidExchangeRequest(BaseModel):
    """POST body for /plaid/exchange — the public token from Plaid Link."""

    public_token: str
    label: str | None = None


class SyncResultResponse(BaseModel):
    """Outcome of a connection sync."""

    connection_id: int
    accounts: int
    added: int
    updated: int
    removed: int
    holdings: int = 0
    trades: int = 0


class SyncSummaryResponse(BaseModel):
    """Aggregate outcome of syncing every connection for the caller."""

    connections: int
    results: list[SyncResultResponse]


class HostedLinkResponse(BaseModel):
    """A Plaid Hosted Link session — open the URL, poll with the token."""

    hosted_link_url: str
    link_token: str


class HostedLinkCompleteRequest(BaseModel):
    """POST body for /plaid/hosted-link/complete."""

    link_token: str


class SnapTradeConnectResponse(BaseModel):
    """A SnapTrade connection-portal session — open the URL in a new tab
    (expires in ~5 minutes) and poll ``/snaptrade/connect/complete``."""

    redirect_uri: str
    connection_id: int


# -- Budget -------------------------------------------------------------


class BudgetLineUpsert(BaseModel):
    """POST body for /budget/lines - exactly one of category_id/payee_key."""

    category_id: int | None = None
    payee_key: str | None = None
    payee_label: str | None = None
    allocated_amount: int
    rollover_enabled: bool = False


class BudgetLineResponse(BaseModel):
    """A Flexible line is a chosen limit: ``status`` reads spend against
    ``allocated_amount``. A Fixed/Non-monthly line is a detected bill
    shown for context, not a limit anyone set - ``allocated_amount`` is
    just what it typically costs, ``status`` reads ``variance_amount``
    (this period's actual vs. last period's) instead, and never goes
    ``critical`` - a bill can't be "over budget" on itself."""

    id: int
    category_id: int | None
    category_name: str | None
    payee_key: str | None
    payee_label: str | None
    allocated_amount: int
    spent_amount: int
    status: Literal["good", "warn", "critical"]
    # Fixed/Non-monthly only: this period's actual vs. last period's
    # (signed cents); None for Flexible lines and for a bill with no
    # prior-period data yet.
    variance_amount: int | None = None


class BudgetBucketResponse(BaseModel):
    """One of the three Budget-tab sections."""

    name: Literal["fixed", "non_monthly", "flexible"]
    total_allocated: int
    total_spent: int
    lines: list[BudgetLineResponse]


class BudgetStatsResponse(BaseModel):
    """The Budget tab's 4-cell summary strip."""

    flexible_spent: int
    flexible_allocated: int
    days_left_in_period: int
    flexible_count: int
    on_track_count: int
    over_budget_count: int
    over_budget_labels: list[str]
    fixed_total: int
    fixed_count: int
    # The month's bottom line: confirmed income minus confirmed bills
    # minus budget allocations, monthly-equivalent throughout - the same
    # gate and factors the forecast uses, so the two cannot disagree.
    income_total: int = 0
    income_count: int = 0
    # Active goals' evaluated monthly ask - month_net subtracts it, and
    # the Budgets cell captions it.
    goals_total: int = 0
    goals_count: int = 0
    # What the goals ask for and the month does not have. Only fixed and
    # percent rules can produce one; a surplus sweep cannot overspend.
    goals_shortfall: int = 0
    envelopes_total: int = 0
    envelopes_count: int = 0
    # Observed spending no bill and no limit covers (trailing 3-month
    # average) - the term that keeps the verdict honest.
    everything_else: int = 0
    month_net: int = 0
    # Deficit left over even after trimming every budget to its floor -
    # the part of a negative month that belongs to bills or income.
    trim_residual: int = 0


class BudgetTrimResponse(BaseModel):
    """One row of the close-the-gap plan, in either kind.

    ``pause_goal`` rows carry account_id/recovered (pausing recovers the
    goal's whole ask); ``cut_budget`` rows carry the line fields - the
    floor is what the line already spent this period, and ``suggested``
    never goes below it. Applying one is a status PATCH or the ordinary
    line upsert respectively."""

    kind: Literal["pause_goal", "cut_budget"] = "cut_budget"
    label: str
    # cut_budget fields
    id: int | None = None
    category_id: int | None = None
    payee_key: str | None = None
    allocated_amount: int | None = None
    spent_amount: int | None = None
    cut: int | None = None
    suggested_amount: int | None = None
    # pause_goal fields
    account_id: int | None = None
    recovered: int | None = None


class GoalAsk(BaseModel):
    """One active goal's evaluated monthly ask - what the month equation
    subtracts for it, and what pausing it would recover."""

    account_id: int
    label: str
    monthly_need: int


class BudgetTrimPlan(BaseModel):
    """The close-the-gap plan: pause/cut rows plus the residual neither
    tier covers (the part of the gap that belongs to bills or income)."""

    cuts: list[BudgetTrimResponse] = Field(default_factory=list)
    residual: int = 0


class BudgetSummaryResponse(BaseModel):
    period_month: int  # YYYYMM
    buckets: list[BudgetBucketResponse]
    stats: BudgetStatsResponse
    # Present (non-empty) exactly when the month lands negative and the
    # budgets have slack to give.
    trims: list[BudgetTrimResponse] = Field(default_factory=list)


class StatDetailRow(BaseModel):
    """One row of a header cell's click-through detail.

    Data only - the popup composes its own captions from these fields
    (a sub-monthly bill's cadence and face value; the row count behind
    an everything-else average).
    """

    label: str
    value: int  # cents
    frequency: str | None = None
    per_period_amount: int | None = None  # cents, sub-monthly bills only
    transaction_count: int | None = None


class BudgetStatDetailsResponse(BaseModel):
    """Per-row backup for the Budget header's fetched cells.

    ``window_start``/``window_end`` bound the everything-else average
    (``[start, end)``); the popup renders the human label.
    """

    income: list[StatDetailRow]
    bills: list[StatDetailRow]
    everything_else: list[StatDetailRow]
    window_start: date
    window_end: date


class FinanceOverviewResponse(BaseModel):
    """One payload for the Overview surface - the composite the modal
    fetches in a single round trip instead of eight.

    Sections reuse the granular endpoints' response models verbatim, so
    a widget reads the same shape whether it came from the composite or
    from a targeted refresh of the matching granular endpoint.
    ``account_ids`` filtering applies to net_worth, cashflow, and
    spending (the windowed aggregates), mirroring how the surface used
    the granular endpoints.
    """

    accounts: AccountListResponse
    net_worth: list[NetWorthPoint]
    cashflow: CashflowResponse
    top_payees: PayeeListResponse
    projection: ProjectionResponse
    recent_transactions: TransactionListResponse
    uncategorized: TransactionListResponse
    spending: list[SpendingCategory]


class GoalParseRequest(BaseModel):
    text: str


class GoalParseResponse(BaseModel):
    """A deterministic, substring+regex reading of a natural-language goal
    ("I wanna cut back on Starbucks") - a preview, not a write. The caller
    decides whether to apply it (via POST /budget/lines)."""

    matched: bool
    target_type: Literal["category", "payee"] | None = None
    category_id: int | None = None
    payee_key: str | None = None
    payee_label: str | None = None
    baseline_monthly: int | None = None
    suggested_limit: int | None = None
    # Display name of whatever matched (payee label or category name) and
    # the cut fraction applied - the frontend writes the sentence.
    label: str | None = None
    fraction: float | None = None


# -- Action acknowledgements ------------------------------------------------
#
# What a mutating endpoint reports back: how much it changed. Named models
# rather than bare dicts so the OpenAPI schema (and any generated client)
# carries the field names instead of a free-form map.


class MerchantMergeResult(BaseModel):
    """Transactions repointed onto the surviving payee, and how many
    source payees were folded in."""

    moved: int
    merged: int


class MerchantAssignResult(BaseModel):
    updated: int


class TransactionDeleteResult(BaseModel):
    deleted: int


class TagRemoveResult(BaseModel):
    removed: int


class PayeeGroupAssignResult(BaseModel):
    """``merchant_id`` echoes the payee the groups landed on - it may have
    been created by this same call, so the caller cannot know it up front."""

    updated: int
    merchant_id: int


class SuggestionDismissResult(BaseModel):
    dismissed: int


class SuggestionRestoreResult(BaseModel):
    restored: int


class RecurringRescanResult(BaseModel):
    """A detection sweep: rhythms found, plus stale streams pruned."""

    detected: int
    pruned: int


class RecurringCategorizeResult(BaseModel):
    updated: int


class WebhookAckResult(BaseModel):
    """What a verified inbound provider webhook did, for the provider's own
    delivery log - never a client-facing payload."""

    status: str
