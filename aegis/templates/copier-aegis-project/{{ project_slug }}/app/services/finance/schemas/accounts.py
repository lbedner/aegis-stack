"""Account, connection, valuation, and net-worth shapes.

A topic module of the ``schemas`` package; every name here is
re-exported from the package root, which stays the one import path.
Money fields are integer minor units (cents); the frontend formats them.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from app.services.finance.models import (
        FinanceAccount,
        FinanceConnection,
        FinanceLiabilityDetail,
        FinanceNetWorthSnapshot,
        FinanceValuation,
    )

from app.services.finance.schemas.categorization import PayeeListResponse
from app.services.finance.schemas.properties import PropertySummary
from app.services.finance.schemas.recurring import ProjectionResponse
from app.services.finance.schemas.transactions import (
    CashflowResponse,
    SpendingCategory,
    TransactionListResponse,
)


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
    # FW-04: the property this liability encumbers, as the user confirmed
    # it (1 = first mortgage, 2 = second/HELOC). None = unlinked.
    secured_by_account_id: int | None = None
    lien_position: int | None = None

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
            secured_by_account_id=row.secured_by_account_id,
            lien_position=row.lien_position,
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
    # Present only on property accounts. The stored metadata blob is
    # parsed through its own model, so a client never sees raw keys.
    property: PropertySummary | None = None

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
            property=PropertySummary.from_metadata(row.metadata_),
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


class ValuationCreateRequest(BaseModel):
    """POST body for /accounts/{id}/valuations (account comes from the path)."""

    as_of_date: date
    value: int
    source: str = "manual"
    note: str | None = None


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


class SecuredDebtUpdate(BaseModel):
    """PATCH body for /accounts/{id}/secured-by: the confirmed lien link.

    ``secured_by_account_id=None`` unlinks (and clears the position);
    ``lien_position`` defaults to 1 (first mortgage) when linking.
    """

    secured_by_account_id: int | None
    lien_position: int | None = None
