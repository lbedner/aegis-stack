"""What the finance tools hand an agent (``finance.tools``): money in
integer cents, dates as dates. A section that does not apply to an
account is left out, not sent as a null (``absent``)."""

from datetime import date

from pydantic import BaseModel

from app.core.figures import FIGURES, absent


class MonthFlow(BaseModel):
    model_config = FIGURES

    month: str  # YYYY-MM
    income_cents: int
    spend_cents: int
    net_cents: int


class Cashflow(BaseModel):
    """Months of cash flow, oldest first."""

    model_config = FIGURES

    months: list[MonthFlow]


class LedgerRow(BaseModel):
    """One transaction, as the register shows it."""

    model_config = FIGURES

    id: int  # what a transaction.categorize proposal's transaction_id takes
    date: date
    payee: str | None  # the curated name first, then the provider's
    amount_cents: int  # signed: negative is an outflow
    category: str | None
    category_id: int | None
    # Either shape of uncategorized: no category, or an import catch-all.
    uncategorized: bool
    account: str | None
    tags: list[str]  # the label axis, orthogonal to category
    pending: bool


class Transactions(BaseModel):
    """Transactions newest first; fewer ``returned`` than ``total`` means
    the page was capped."""

    model_config = FIGURES

    total: int
    returned: int
    transactions: list[LedgerRow]


class Upcoming(BaseModel):
    """A scheduled flow inside the next weeks."""

    model_config = FIGURES

    name: str
    date: date
    amount_cents: int  # signed: inflows positive, bills negative


class Holding(BaseModel):
    model_config = FIGURES

    ticker: str | None
    name: str | None
    quantity: float
    market_value_cents: int


class Envelope(BaseModel):
    model_config = FIGURES

    credit_cents: int | None  # booked once per cadence period
    cadence: str
    auto_credit: bool


class Lien(BaseModel):
    model_config = FIGURES

    account: str
    lien_position: int | None


class PropertyFacts(BaseModel):
    """A property, its valuation's provenance with it. Equity, LTV and
    liens are there only when a liability is linked to it."""

    model_config = FIGURES

    kind: str
    valuation_source: str | None
    valuation_as_of: date | None
    is_estimate: bool | None
    purchase_price_cents: int | None
    purchase_date: date | None
    ownership_share_bps: int
    include_in_net_worth: bool
    equity_cents: int | None = absent()
    ltv_bps: int | None = absent()
    liens: list[Lien] | None = absent()


class GoalFacts(BaseModel):
    model_config = FIGURES

    target_cents: int
    status: str
    monthly_contribution_cents: int | None
    priority: int


class LiabilityFacts(BaseModel):
    """Card or loan terms on file."""

    model_config = FIGURES

    type: str | None
    interest_rate_bps: int | None
    minimum_payment_cents: int | None
    next_payment_due: date | None
    last_statement_balance_cents: int | None
    last_payment_cents: int | None
    last_payment_date: date | None
    ytd_interest_paid_cents: int | None
    ytd_principal_paid_cents: int | None


class AccountFacts(BaseModel):
    """An account with its balance and role, and each section that
    applies to it."""

    model_config = FIGURES

    id: int
    name: str
    account_type: str
    classification: str
    balance_cents: int  # liabilities negative: owed
    hidden: bool
    envelope: Envelope | None = absent()
    property: PropertyFacts | None = absent()
    goal: GoalFacts | None = absent()
    holdings: list[Holding] | None = absent()
    upcoming: list[Upcoming] | None = absent()
    liability: LiabilityFacts | None = absent()


class BalanceSheet(BaseModel):
    model_config = FIGURES

    accounts: list[AccountFacts]


class Quote(BaseModel):
    """A ticker's latest stored close, when the catalog has one."""

    model_config = FIGURES

    found: bool
    ticker: str
    name: str | None = absent()
    close_cents: int | None = absent()
    as_of: date | None = absent()


# The ids a finance proposal is built from (``domains.writes.lookups``).


class CategoryRef(BaseModel):
    model_config = FIGURES

    id: int  # what a transaction.categorize proposal's category_id takes
    name: str
    classification: str  # expense, income or transfer


class Categories(BaseModel):
    model_config = FIGURES

    categories: list[CategoryRef]


class Bill(BaseModel):
    """A live bill or income stream."""

    model_config = FIGURES

    id: int  # what a recurring.match proposal's stream_id takes
    name: str
    direction: str  # outflow or inflow
    frequency: str
    amount: int  # cents, never null: declared, else measured from payments
    amount_is_declared: bool
    next_expected_date: date | None
    last_date: date | None


class Bills(BaseModel):
    model_config = FIGURES

    bills: list[Bill]


class BillCandidate(BaseModel):
    """An unclaimed transaction that could be the bill's payment."""

    model_config = FIGURES

    id: int  # what a recurring.match proposal's transaction_id takes
    date: date
    payee: str | None
    amount: int
    account_id: int | None


class BillCandidates(BaseModel):
    model_config = FIGURES

    stream_id: int
    candidates: list[BillCandidate]


class TagUse(BaseModel):
    model_config = FIGURES

    id: int
    name: str
    count: int  # transactions wearing it


class Tags(BaseModel):
    model_config = FIGURES

    tags: list[TagUse]
