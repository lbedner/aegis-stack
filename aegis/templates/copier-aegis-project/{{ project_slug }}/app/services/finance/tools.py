"""Finance host tools: the data surface code-mode agents compute over.

Deliberately few and wide: results land in the code-mode sandbox rather
than the prompt, so a broad payload the model slices in code beats a
catalog of narrow question-shaped tools. Each tool is a thin, fully-typed
composition of existing domain queries, registered into the agent tool
registry at import time. A code-mode agent granted these names calls them
as functions from inside its sandboxed script; a plain agent calls them
as ordinary tools.

Returns are typed models (``schemas.answers``: cents-integer money,
dates): code mode hands its sandbox their JSON, and their schemas type the
script's stubs.

Owner scoping: a tool reads the turn's owner (``current_owner_user_id``),
so a signed-in turn sees only its own household; a turn without one
(a single-tenant install) reads every row.
"""

from datetime import date, timedelta
from typing import Any

from app.core.db import get_async_session
from app.core.tools import current_owner_user_id, register_tool
from app.services.finance.constants import UNCATEGORIZED_CATEGORY_NAMES
from app.services.finance.domains.investments import queries as investment_queries
from app.services.finance.domains.investments.securities import (
    list_current_holdings,
)
from app.services.finance.domains.ledger.accounts import (
    account_transaction_totals,
    effective_balance,
    liability_details,
)
from app.services.finance.domains.ledger.properties import (
    PROPERTY_ACCOUNT_TYPE,
    property_metadata,
    secured_position,
)
from app.services.finance.domains.ledger.queries.accounts import accounts_page
from app.services.finance.domains.ledger.queries.categories import (
    category_names_by_id,
)
from app.services.finance.domains.ledger.queries.transactions import (
    transactions_window_with_payees,
)
from app.services.finance.domains.ledger.transactions import (
    monthly_cashflow,
    transaction_tags,
)
from app.services.finance.domains.ledger.valuations import preferred_valuation_row
from app.services.finance.domains.planning.envelopes import envelope_metadata
from app.services.finance.domains.planning.goals import goal_metadata
from app.services.finance.domains.planning.recurring import (
    queries as recurring_queries,
)
from app.services.finance.models.accounts import (
    FinanceAccount,
    FinanceLiabilityDetail,
    FinanceValuation,
)
from app.services.finance.schemas.answers import (
    AccountFacts,
    BalanceSheet,
    Cashflow,
    Envelope,
    GoalFacts,
    Holding,
    LedgerRow,
    LiabilityFacts,
    Lien,
    MonthFlow,
    PropertyFacts,
    Quote,
    Transactions,
    Upcoming,
)
from app.services.finance.utils import current_date

# Sized for years of a personal ledger (a few thousand rows/year); rows
# land in the code-mode sandbox, not the model's context, so the cost of
# a big window is a few ms of marshaling. ``total`` in the payload still
# exposes truncation, so a capped result never reads as complete.
_TRANSACTIONS_ROW_CAP = 5000

# How far ahead accounts() reports scheduled flows: one full monthly
# cycle with margin, so a mid-month plan sees next month's rent.
_UPCOMING_WINDOW_DAYS = 35


def _months_back_start(today: date, span: int) -> date:
    """First day of the month ``span - 1`` calendar months before today."""
    total_months = today.year * 12 + today.month - 1 - (span - 1)
    return date(total_months // 12, total_months % 12 + 1, 1)


async def ledger(months: int = 12, detail: str = "monthly") -> Cashflow | Transactions:
    """Cash flow from the transaction ledger.

    Args:
        months: How many months back to include (1-24).
        detail: "monthly" or "transactions".

    Monthly detail answers 'months': a list, oldest first, of entries
    carrying 'month', 'income_cents', 'spend_cents' and 'net_cents'.
    Transaction detail answers 'total', 'returned' and 'transactions': a
    list, newest first, of entries carrying 'id' (what a proposal's
    'transaction_id' takes), 'date', 'payee', 'amount_cents' (signed,
    negative = outflow), 'category', 'category_id', 'uncategorized'
    (no category, or an import catch-all), 'account', 'tags' and
    'pending'; fewer returned rows than 'total' means the page was
    capped.
    """
    if detail == "monthly":
        span = max(1, min(int(months), 24))
        async with get_async_session() as session:
            rows = await monthly_cashflow(
                session, owner_user_id=current_owner_user_id.get(), months=span
            )
        return Cashflow(
            months=[
                MonthFlow(
                    month=row.month,
                    income_cents=row.income,
                    spend_cents=row.expense,
                    net_cents=row.net,
                )
                for row in rows
            ]
        )
    if detail != "transactions":
        raise ValueError('detail must be "monthly" or "transactions"')

    span = max(1, min(int(months), 24))
    from_date = _months_back_start(current_date(), span)
    async with get_async_session() as session:
        rows, total = await transactions_window_with_payees(
            session,
            owner_user_id=current_owner_user_id.get(),
            from_date=from_date,
            limit=_TRANSACTIONS_ROW_CAP,
        )
        category_names = await category_names_by_id(
            session,
            {t.category_id for t, _name in rows if t.category_id is not None},
        )
        account_rows, _count = await accounts_page(
            session,
            owner_user_id=current_owner_user_id.get(),
            include_hidden=True,
            page=1,
            page_size=500,
        )
        tags_by_txn = await transaction_tags(
            session, [t.id for t, _name in rows if t.id is not None]
        )
    account_names = {account.id: account.name for account in account_rows}
    return Transactions(
        total=total,
        returned=len(rows),
        transactions=[
            LedgerRow(
                # What a transaction.categorize proposal's transaction_id
                # takes - names alone cannot propose.
                id=txn.id,
                date=txn.date_,
                # Curated merchant name first - what the register shows -
                # then the provider's merchant string, then the raw
                # descriptor. A renamed payee that only lived in the
                # curation layer was invisible to the assistant.
                payee=curated_name or txn.merchant_name or txn.name,
                amount_cents=txn.amount,
                category=category_names.get(txn.category_id),
                category_id=txn.category_id,
                # True for BOTH shapes of uncategorized: no category at
                # all, or the import catch-all bucket ("Uncategorized",
                # "Misc", ...). Filtering category is None alone misses
                # the second shape - a model burned four runs on that.
                uncategorized=txn.category_id is None
                or (category_names.get(txn.category_id) or "").lower()
                in UNCATEGORIZED_CATEGORY_NAMES,
                account=account_names.get(txn.account_id),
                # The label axis, orthogonal to category ("Business" on
                # a Software row) - what tag rollups compute over.
                tags=sorted(t.name for t in tags_by_txn.get(txn.id, [])),
                pending=txn.pending,
            )
            for txn, curated_name in rows
        ],
    )


async def accounts() -> BalanceSheet:
    """The full balance sheet: every account with its balance and role.

    Answers 'accounts': a list where every entry
    carries 'id', 'name', 'account_type', 'classification',
    'balance_cents' (liabilities are negative = owed) and 'hidden'.
    Investment accounts add 'holdings', a list of entries with 'ticker',
    'name', 'quantity' and 'market_value_cents'. Envelope accounts add
    'envelope' with 'credit_cents', 'cadence' and 'auto_credit'. Goal
    accounts add 'goal' with 'target_cents', 'status',
    'monthly_contribution_cents' and 'priority'. Liability accounts add
    'liability' with 'type', 'interest_rate_bps',
    'minimum_payment_cents', 'next_payment_due',
    'last_statement_balance_cents', 'last_payment_cents',
    'last_payment_date', 'ytd_interest_paid_cents' and
    'ytd_principal_paid_cents' when card terms are on file. A property
    that secures linked liabilities adds 'equity_cents', 'ltv_bps'
    (basis points) and 'liens' (account name + lien_position) - derived
    from the confirmed links, absent when nothing is linked. Accounts
    with scheduled activity inside the next 35 days add 'upcoming': a
    date-ordered list of entries with 'name', 'date' and 'amount_cents'
    (signed - inflows positive, bills negative), from the same recurring
    streams the briefing's EXPECTED section reads. Use it to check that
    a plan survives every touched account's near-term debits.
    """
    async with get_async_session() as session:
        account_rows, _count = await accounts_page(
            session,
            owner_user_id=current_owner_user_id.get(),
            include_hidden=True,
            page=1,
            page_size=500,
        )
        holdings = await list_current_holdings(
            session, owner_user_id=current_owner_user_id.get()
        )
        account_ids = [account.id for account in account_rows]
        activity_totals = await account_transaction_totals(
            session, account_ids=account_ids
        )
        liabilities = await liability_details(session, account_ids)
        # The row that actually drives each property's balance: its source
        # and date are the provenance worth quoting, and they outrank the
        # typed metadata whenever a dated series exists.
        valuation_rows = {
            account.id: await preferred_valuation_row(session, account)
            for account in account_rows
            if account.account_type == PROPERTY_ACCOUNT_TYPE
        }
        streams = await recurring_queries.active_streams(
            session, owner_user_id=current_owner_user_id.get()
        )

    today = current_date()
    horizon = today + timedelta(days=_UPCOMING_WINDOW_DAYS)
    upcoming_by_account: dict[int, list[Upcoming]] = {}
    for stream in streams:
        when = stream.next_expected_date
        if stream.account_id is None or when is None:
            continue
        if not today <= when <= horizon:
            continue
        amount = stream.amount
        sign = 1 if stream.direction == "inflow" else -1
        upcoming_by_account.setdefault(stream.account_id, []).append(
            Upcoming(name=stream.name, date=when, amount_cents=sign * abs(amount))
        )

    balances = {
        account.id: effective_balance(
            current_balance=account.current_balance,
            balance_as_of=account.balance_as_of,
            classification=account.classification,
            activity_balance=activity_totals.get(account.id, 0),
        )
        for account in account_rows
    }
    account_names = {account.id: account.name for account in account_rows}
    # FW-04: liens by the property they encumber. The link is what the
    # user CONFIRMED on the liability (never inferred); equity and LTV
    # derive from it at read time and are never stored.
    liens_by_property: dict[int, list[tuple[int, str, int, int | None]]] = {}
    for detail in liabilities.values():
        if detail.secured_by_account_id is None:
            continue
        liens_by_property.setdefault(detail.secured_by_account_id, []).append(
            (
                detail.lien_position or 99,
                account_names.get(detail.account_id, f"account {detail.account_id}"),
                abs(balances.get(detail.account_id, 0)),
                detail.lien_position,
            )
        )

    holdings_by_account: dict[int, list[Holding]] = {}
    for holding, security, market_value_cents in holdings:
        holdings_by_account.setdefault(holding.account_id, []).append(
            Holding(
                ticker=security.ticker if security else None,
                name=security.name if security else None,
                quantity=holding.quantity_e8 / 1e8,
                market_value_cents=market_value_cents,
            )
        )

    return BalanceSheet(
        accounts=[
            AccountFacts(
                id=account.id,
                name=account.name,
                account_type=account.account_type,
                classification=account.classification,
                # Same rule the accounts tab renders: authoritative balance
                # writes win; a never-written 0 falls back to the register sum.
                balance_cents=balances[account.id],
                hidden=account.is_hidden,
                envelope=_envelope(account.metadata_),
                property=_property(
                    account,
                    valuation_rows.get(account.id),
                    sorted(liens_by_property.get(account.id, [])),
                    balances[account.id],
                ),
                goal=_goal(account.metadata_),
                holdings=holdings_by_account.get(account.id),
                upcoming=upcoming_by_account.get(account.id),
                liability=_liability(liabilities.get(account.id)),
            )
            for account in account_rows
        ]
    )


def _envelope(metadata: dict[str, Any] | None) -> Envelope | None:
    meta = envelope_metadata(metadata)
    if meta is None:
        return None
    # The domain field is named monthly_credit, but the amount is booked
    # once per cadence period - a "monthly" key next to cadence="weekly"
    # reads as a contradiction, and models have mis-stated the allowance
    # because of it.
    return Envelope(
        credit_cents=meta.monthly_credit, cadence=meta.cadence, auto_credit=meta.auto_credit
    )


def _property(
    account: FinanceAccount,
    valuation: FinanceValuation | None,
    liens: list[tuple[int, str, int, int | None]],
    balance: int,
) -> PropertyFacts | None:
    meta = property_metadata(account.metadata_)
    if meta is None:
        return None
    # Provenance rides with the number: an owner's estimate and an
    # appraisal are not interchangeable in a lending conversation, and a
    # bare figure invites the model to present one as the other.
    position = secured_position(balance, [owed for _, _, owed, _ in liens])
    # Equity, LTV and liens are absent entirely when nothing is linked: an
    # unlinked property must not read as a 100%-equity claim.
    return PropertyFacts(
        kind=meta.property_kind,
        valuation_source=valuation.source if valuation else meta.valuation_source,
        valuation_as_of=valuation.as_of_date if valuation else meta.valuation_as_of,
        is_estimate=valuation.is_estimate if valuation else None,
        purchase_price_cents=meta.purchase_price,
        purchase_date=meta.purchase_date,
        ownership_share_bps=meta.ownership_share_bps,
        include_in_net_worth=meta.include_in_net_worth,
        equity_cents=position.equity if position else None,
        ltv_bps=position.ltv_bps if position else None,
        liens=[Lien(account=name, lien_position=at) for _, name, _, at in liens]
        if position
        else None,
    )


def _goal(metadata: dict[str, Any] | None) -> GoalFacts | None:
    meta = goal_metadata(metadata)
    if meta is None:
        return None
    return GoalFacts(
        target_cents=meta.target_amount,
        status=meta.status,
        monthly_contribution_cents=meta.monthly_contribution,
        priority=meta.priority,
    )


def _liability(detail: FinanceLiabilityDetail | None) -> LiabilityFacts | None:
    if detail is None:
        return None
    return LiabilityFacts(
        type=detail.liability_type,
        interest_rate_bps=detail.interest_rate_bps,
        minimum_payment_cents=detail.minimum_payment_amount,
        next_payment_due=detail.next_payment_due_date,
        last_statement_balance_cents=detail.last_statement_balance,
        last_payment_cents=detail.last_payment_amount,
        last_payment_date=detail.last_payment_date,
        ytd_interest_paid_cents=detail.ytd_interest_paid,
        ytd_principal_paid_cents=detail.ytd_principal_paid,
    )


async def quote(ticker: str) -> Quote:
    """Latest stored closing price for a ticker in the security catalog.

    Args:
        ticker: The security's ticker symbol, case-insensitive.
    """
    symbol = ticker.strip().upper()
    async with get_async_session() as session:
        security = await investment_queries.security_by_ticker(session, symbol)
        if security is None or security.id is None:
            return Quote(found=False, ticker=symbol)
        price = await investment_queries.latest_price_for_security(session, security.id)
    if price is None:
        return Quote(found=False, ticker=symbol)
    # Normalize to cents in integer arithmetic regardless of the row's
    # stored scale; float exponents would drift on sub-cent scales.
    if price.price_scale > 2:
        divisor = 10 ** (price.price_scale - 2)
        close_cents = (price.close_price + divisor // 2) // divisor
    else:
        close_cents = price.close_price * 10 ** (2 - price.price_scale)
    as_of: date = price.price_date
    return Quote(
        found=True, ticker=symbol, name=security.name, close_cents=close_cents, as_of=as_of
    )


# Built-in registration: importing this module makes the tools grantable
# via the agent registry. replace=True keeps re-imports idempotent.


register_tool(
    "ledger",
    ledger,
    description="Cash flow: monthly rollups or individual transactions",
    replace=True,
    effect="read",
)
register_tool(
    "accounts",
    accounts,
    description="All accounts with balances, holdings, envelopes and goals",
    replace=True,
    effect="read",
)
register_tool(
    "quote",
    quote,
    description="Latest stored closing price for a ticker",
    replace=True,
    effect="read",
)

# The id lookups proposals need live in their own module; importing it
# here keeps "import tools" the one line that registers the whole
# finance tool surface. Filing a proposal is the shared queue's job
# (``change_queue.tools``), which ``load_tools`` registers.
from app.services.finance.domains.writes import lookups  # noqa: E402,F401

