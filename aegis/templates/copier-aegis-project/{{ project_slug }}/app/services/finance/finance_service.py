"""Finance service: manual accounts, transactions, valuations, net worth.

Mirrors ``payment_service.py``: a plain class taking an ``AsyncSession`` in
``__init__`` (the FastAPI dependency wrapper lives in ``deps.py``). Reads go
through ``self.db.exec(select(...))``; writes ``self.db.add(...)`` +
``self.db.flush()`` but do NOT commit — the caller (route / CLI / scheduler
job) owns the transaction boundary.

Rows are owner-scoped by ``owner_user_id``; the FK to the auth ``user`` table
is added only when auth is present (via the finance_auth_link migration), so
methods take ``owner_user_id`` as a plain, optional filter. Money is integer
minor units. Provider integration (Plaid/SnapTrade) lands in later tickets;
this layer is manual + import only.
"""

from __future__ import annotations

import calendar
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from functools import partial
import re
import statistics
from typing import Any

from sqlalchemy import and_, case, func
from sqlmodel import or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.constants import (
    ANALYST_NOTE_INSIGHT_TYPE,
    CADENCE_KEYS,
    CADENCES,
    CASH_ACCOUNT_TYPES,
    ONE_TIME_FREQUENCY,
    UNCATEGORIZED_CATEGORY_NAMES,
    Provider,
    add_months,
    step_cadence,
)
from app.services.finance.envelopes import (
    ENVELOPE_ACCOUNT_TYPE,
    envelope_metadata,
    set_envelope_metadata,
)
from app.services.finance.goals import (
    DEFAULT_PRIORITY,
    GOAL_ACCOUNT_TYPE,
    MonthlyFigures,
    allocate_month,
    clear_goal_metadata,
    goal_auto_contribute,
    goal_metadata,
    set_auto_contribute,
    set_goal_metadata,
)
from app.services.finance.models import (
    FinanceAccount,
    FinanceBalanceSnapshot,
    FinanceBudget,
    FinanceBudgetCategory,
    FinanceCategory,
    FinanceCategoryAlias,
    FinanceConnection,
    FinanceCurrency,
    FinanceHolding,
    FinanceImportBatch,
    FinanceImportBatchRow,
    FinanceInsight,
    FinanceInstitution,
    FinanceLiabilityDetail,
    FinanceMerchant,
    FinanceRecurringStream,
    FinanceSecurity,
    FinanceSecurityPrice,
    FinanceTag,
    FinanceTrade,
    FinanceTransaction,
    FinanceTransactionSplit,
    FinanceTransactionTag,
    FinanceTransfer,
    FinanceValuation,
)
from app.services.finance.schemas import (
    FinanceHealth,
    FinanceStatusSummary,
    NetWorthResponse,
    ProjectionPoint,
    ProjectionResponse,
)

_DEFAULT_CURRENCY = "usd"

# ``external_id_source`` value marking a reconciliation adjustment (FIN-37).
# A plain-column discriminator: the import pipeline's LANE-3 edit matching
# and the source CHECK constraint both stay untouched by it.
RECONCILE_MARKER = "reconcile"

# Kept as a module alias so existing references read the shared definition.
_CASH_ACCOUNT_TYPES = CASH_ACCOUNT_TYPES


# The month step lives with the cadence table; aliased so the many call
# sites below keep reading the same way.
_add_months = add_months


def _month_bounds(period_month: int) -> tuple[date, date]:
    """``[start, end)`` date range for a YYYYMM period."""
    year, month = divmod(period_month, 100)
    start = date(year, month, 1)
    return start, _add_months(start, 1)


# Appended to the month that absorbs a prior overage. A budget line
# smaller than its allocation, with nothing to explain it, reads as a bug
# in the forecast rather than as the overage being made up.
_BUDGET_CARRY_NOTE = " (tightened by last month's overspend)"


def _period_month_for(day: date) -> int:
    """The YYYYMM period a date falls in."""
    return day.year * 100 + day.month


def _month_end(day: date) -> date:
    """The last day of ``day``'s month."""
    return date(day.year, day.month, calendar.monthrange(day.year, day.month)[1])


def _current_period_month() -> int:
    today = date.today()
    return today.year * 100 + today.month


def _display_cash_balance(accounts: list[Any], totals: dict[int, int]) -> int:
    """Today's spendable cash: the sidebar's own display rule - the
    authoritative ``current_balance`` when a real balance write happened,
    else the register sum. One rule, shared by the projection walk and
    the budget outlook, so "today's balance" can never mean two things."""
    balance = 0
    for account in accounts:
        current = account.current_balance
        authoritative = current is not None and (current != 0 or account.balance_as_of)
        balance += current if authoritative else totals.get(account.id, 0)
    return balance


def _monthly_income(streams: list[Any]) -> tuple[int, int]:
    """(monthly-equivalent confirmed income, source count) - the one income
    figure the header, the goal allocation engine, and the verdict all
    share, so a percent-of-income goal and the Income cell can never
    disagree about what "income" means."""
    from app.services.finance.categorize.insights import (
        _MONTHLY_FACTOR,
        is_commitment,
        is_paused,
    )

    rows = [
        (s, _MONTHLY_FACTOR.get(s.frequency, 0.0))
        for s in streams
        if s.direction == "inflow"
        and not s.is_muted
        and not is_paused(s)
        and is_commitment(s)
    ]
    rows = [(s, f) for s, f in rows if f > 0]
    total = int(sum((s.expected_amount or s.average_amount or 0) * f for s, f in rows))
    return total, len(rows)


def plan_budget_trims(
    lines: list[dict[str, Any]],
    *,
    deficit: int,
    goals: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Deterministic cuts that close a negative month.

    The rules, stated once so the UI and any later decision layer share
    them. TIER 1: pause a goal before cutting a budget - a dream
    deferred beats groceries squeezed. Goals pause largest-need-first
    (fewest dreams disturbed), each recovering its whole monthly need
    (a pause is all-or-nothing), until the gap is covered or goals run
    out. TIER 2: a line's FLOOR is what it has already spent this period
    (a budget below money already gone is a lie, not a plan); cuts
    distribute proportionally to each line's slack above its floor,
    largest-remainder rounded so they sum exactly. Whatever neither tier
    covers is returned as ``residual`` - the part of the gap that
    belongs to bills or income. Every row carries ``kind``
    (``pause_goal`` | ``cut_budget``).
    """
    if deficit <= 0:
        return {"cuts": [], "residual": 0}
    pauses: list[dict[str, Any]] = []
    for goal in sorted(
        goals or [],
        key=lambda g: (-g["monthly_need"], str(g.get("label", "")).casefold()),
    ):
        if deficit <= 0:
            break
        need = goal["monthly_need"]
        if need <= 0:
            continue
        pauses.append(
            {
                "kind": "pause_goal",
                "account_id": goal["account_id"],
                "label": goal.get("label") or "Goal",
                "recovered": need,
            }
        )
        deficit -= need
    if deficit <= 0:
        return {"cuts": pauses, "residual": 0}
    slack = [
        (line, max(0, line["allocated_amount"] - max(line["spent_amount"], 0)))
        for line in lines
    ]
    slack = [(line, room) for line, room in slack if room > 0]
    total_slack = sum(room for _line, room in slack)
    if total_slack == 0:
        return {"cuts": pauses, "residual": deficit}
    take = min(deficit, total_slack)
    raw = [(line, room, take * room / total_slack) for line, room in slack]
    cuts = [(line, room, int(share)) for line, room, share in raw]
    remainder = take - sum(cut for _l, _r, cut in cuts)
    # Largest fractional parts absorb the leftover cents, never past slack.
    by_fraction = sorted(
        range(len(cuts)), key=lambda i: raw[i][2] - cuts[i][2], reverse=True
    )
    for i in by_fraction:
        if remainder <= 0:
            break
        line, room, cut = cuts[i]
        if cut < room:
            cuts[i] = (line, room, cut + 1)
            remainder -= 1
    return {
        "cuts": pauses
        + [
            {
                "kind": "cut_budget",
                "id": line["id"],
                "label": line.get("category_name")
                or line.get("payee_label")
                or line.get("label")
                or "Overall",
                "category_id": line.get("category_id"),
                "payee_key": line.get("payee_key"),
                "allocated_amount": line["allocated_amount"],
                "spent_amount": line["spent_amount"],
                "cut": cut,
                "suggested_amount": line["allocated_amount"] - cut,
            }
            for line, _room, cut in cuts
            if cut > 0
        ],
        "residual": deficit - take,
    }


def _budget_line_status(allocated_amount: int, spent_amount: int) -> str:
    """good / warn / critical - budgets warn at 80% spent, not the 70% a
    resource-utilization card would use (see backend_modal's CPU/Memory
    thresholds - a different domain, not reused here on purpose)."""
    if allocated_amount <= 0:
        return "critical" if spent_amount > 0 else "good"
    pct = spent_amount / allocated_amount
    if pct >= 1.0:
        return "critical"
    if pct >= 0.8:
        return "warn"
    return "good"


def _prior_period_month(period_month: int) -> int:
    start, _ = _month_bounds(period_month)
    prior_start = _add_months(start, -1)
    return prior_start.year * 100 + prior_start.month


def _commitment_variance_status(
    actual: int, prior: int | None
) -> tuple[str, int | None]:
    """A Fixed/Non-monthly line reads variance against what it cost LAST
    period, not against a limit - it isn't one. Never "critical": a bill
    can't be over budget on itself, only worth a second look if it moved.
    Nothing to compare yet (no prior-period charge, or this period hasn't
    posted) reads as "good"/on schedule rather than a false swing."""
    if not actual or prior is None:
        return "good", None
    variance = actual - prior
    tolerance = max(200, round(prior * 0.02))  # $2 floor or 2%, whichever's bigger
    return ("warn" if abs(variance) > tolerance else "good"), variance


# Derived from the cadence table - see app/services/finance/constants.py.
_FREQUENCY_STEPS: dict[str, Callable[[date], date]] = {
    key: partial(step_cadence, key) for key in CADENCE_KEYS
}
# Holdings store quantity as units x 1e8 (``quantity_e8``); prices are scaled
# integers (``price / 10**price_scale`` = unit price).
_QUANTITY_SCALE = 10**8


def _utcnow() -> datetime:
    """Naive-UTC timestamp (matches the models' convention)."""
    return datetime.now(UTC).replace(tzinfo=None)


def transaction_search_filter(query: str):
    """One OR across every column the register actually shows.

    Searching only ``FinanceTransaction.name`` meant a query matching what
    was ON SCREEN could still return nothing: the Payee column shows the
    assigned merchant (not the descriptor), and the Category and Account
    columns are joins. An empty result then reads as "no such data"
    rather than "that column is not searched".

    Written once and used by both list paths - it was two copies of the
    same one-column ilike before, which is how they would have drifted.

    Amount and date are deliberately left out: they have their own
    affordances (column sort, the range chips), and substring-matching a
    formatted number finds "50" inside "$1,502.00".
    """
    like = f"%{query}%"
    return or_(
        FinanceTransaction.name.ilike(like),
        FinanceTransaction.merchant_name.ilike(like),
        FinanceTransaction.original_description.ilike(like),
        FinanceTransaction.memo.ilike(like),
        # Subqueries rather than joins: these callers build a filter LIST
        # for an existing select, and a join would mean restructuring both.
        FinanceTransaction.merchant_id.in_(
            select(FinanceMerchant.id).where(FinanceMerchant.name.ilike(like))
        ),
        FinanceTransaction.category_id.in_(
            select(FinanceCategory.id).where(FinanceCategory.name.ilike(like))
        ),
        FinanceTransaction.account_id.in_(
            select(FinanceAccount.id).where(FinanceAccount.name.ilike(like))
        ),
    )


def transaction_payee_key(
    merchant_name: str | None,
    original_description: str | None,
    name: str | None,
) -> str:
    """First-4-normalized-token payee grouping key for a transaction.

    ``normalize_payee`` only folds case/accents/punctuation - it doesn't know
    a bank-generated descriptor's trailing tokens (a masked card ref,
    city/state, or date) vary per swipe even for the exact same merchant
    ("SHPRTE NTH RD&WNSW GT XXX-XXX-6086 NY 06/28" vs "...GT POUGHKEEPSIE
    NYXX8683 07/22" - same store, different card/day). The merchant name is
    reliably at the START of these descriptors; the noise is reliably
    appended at the END, so a first-N-token prefix groups them without a
    real merchant-recognition step. Verified against this app's real
    imported data: 395 Shoprite transactions were splitting into 201
    distinct "payees" under the full normalized string; a 4-token prefix
    collapses them to 6 (the genuine variants - in-store vs. Apple Pay vs.
    Google Pay). Shared by ``suggest_categories`` and the Budget goal
    parser/summary, so a payee grouping never drifts between the two.
    """
    from app.services.finance.importers.base import normalize_payee

    normalized = normalize_payee(merchant_name or original_description or name or "")
    return " ".join(normalized.split()[:4])


def market_value_cents(quantity_e8: int, price: int | None, price_scale: int) -> int:
    """Position value in integer cents: shares x unit-price, rounded.

    ``shares = quantity_e8 / 1e8``; ``unit_price = price / 10**price_scale``;
    value in cents = shares * unit_price * 100.

    Stays in integer arithmetic (Python ints are arbitrary-precision) so large
    positions never lose precision to float rounding; the result is rounded to
    the nearest cent, half away from zero.
    """
    if not price:
        return 0
    denom = _QUANTITY_SCALE * (10**price_scale)
    numerator = quantity_e8 * price * 100
    if numerator < 0:
        return -((-numerator + denom // 2) // denom)
    return (numerator + denom // 2) // denom


def analyst_available() -> bool:
    """Whether this build shipped the finance analyst agent.

    The analyst module is pruned entirely from a project generated without the
    AI service, so a failed import is the answer rather than an error: this is
    feature detection, and False is the whole handling. Asking the code beats
    keeping a second record of which capabilities were selected, which would
    only ever drift from the truth.

    Imported inside the function because the analyst imports this module.
    """
    try:
        from app.services.finance import analyst
    except ImportError:
        return False

    return hasattr(analyst, "run_analyst_note")


def _owner_clause_txn(column, owner_user_id: int | None):
    """NULL-owner (standalone) rows match IS NULL, same convention the
    categorize package uses."""
    return column.is_(None) if owner_user_id is None else column == owner_user_id


class FinanceService:
    """Manual account / transaction / valuation CRUD + the net-worth read."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    # Reference data (get-or-create)
    # ------------------------------------------------------------------ #
    async def get_or_create_currency(
        self,
        code: str = _DEFAULT_CURRENCY,
        *,
        name: str | None = None,
        symbol: str | None = None,
        decimals: int = 2,
    ) -> FinanceCurrency:
        code = code.lower()
        existing = (
            await self.db.exec(
                select(FinanceCurrency).where(FinanceCurrency.code == code)
            )
        ).first()
        if existing:
            return existing
        currency = FinanceCurrency(
            code=code, name=name or code.upper(), symbol=symbol, decimals=decimals
        )
        self.db.add(currency)
        await self.db.flush()
        return currency

    async def get_or_create_institution(
        self,
        *,
        provider: str,
        name: str,
        provider_institution_id: str | None = None,
    ) -> FinanceInstitution:
        if provider_institution_id is not None:
            existing = (
                await self.db.exec(
                    select(FinanceInstitution).where(
                        FinanceInstitution.provider == provider,
                        FinanceInstitution.provider_institution_id
                        == provider_institution_id,
                    )
                )
            ).first()
            if existing:
                return existing
        inst = FinanceInstitution(
            provider=provider,
            name=name,
            provider_institution_id=provider_institution_id,
        )
        self.db.add(inst)
        await self.db.flush()
        return inst

    # ------------------------------------------------------------------ #
    # Accounts
    # ------------------------------------------------------------------ #
    async def create_manual_account(
        self,
        *,
        name: str,
        account_type: str,
        classification: str,
        owner_user_id: int | None = None,
        organization_id: int | None = None,
        current_balance: int = 0,
        currency: str = _DEFAULT_CURRENCY,
        institution_id: int | None = None,
    ) -> FinanceAccount:
        await self.get_or_create_currency(currency)
        account = FinanceAccount(
            owner_user_id=owner_user_id,
            organization_id=organization_id,
            provider=Provider.MANUAL,
            name=name,
            account_type=account_type,
            classification=classification,
            current_balance=current_balance,
            currency=currency,
            institution_id=institution_id,
            is_manual=True,
        )
        self.db.add(account)
        await self.db.flush()
        return account

    async def get_account(
        self, account_id: int, *, owner_user_id: int | None = None
    ) -> FinanceAccount | None:
        query = select(FinanceAccount).where(
            FinanceAccount.id == account_id,
            FinanceAccount.deleted_at.is_(None),
        )
        if owner_user_id is not None:
            query = query.where(FinanceAccount.owner_user_id == owner_user_id)
        return (await self.db.exec(query)).first()

    async def list_accounts(
        self,
        *,
        owner_user_id: int | None = None,
        include_hidden: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[FinanceAccount], int]:
        query = select(FinanceAccount).where(FinanceAccount.deleted_at.is_(None))
        count_query = (
            select(func.count())
            .select_from(FinanceAccount)
            .where(FinanceAccount.deleted_at.is_(None))
        )
        if owner_user_id is not None:
            query = query.where(FinanceAccount.owner_user_id == owner_user_id)
            count_query = count_query.where(
                FinanceAccount.owner_user_id == owner_user_id
            )
        if not include_hidden:
            query = query.where(~FinanceAccount.is_hidden)
            count_query = count_query.where(~FinanceAccount.is_hidden)
        total = (await self.db.exec(count_query)).one()
        query = (
            query.order_by(FinanceAccount.classification, FinanceAccount.name)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list((await self.db.exec(query)).all()), total

    async def update_account_balance(
        self,
        account_id: int,
        *,
        current_balance: int,
        owner_user_id: int | None = None,
    ) -> FinanceAccount | None:
        account = await self.get_account(account_id, owner_user_id=owner_user_id)
        if account is None:
            return None
        account.current_balance = current_balance
        account.balance_as_of = _utcnow()
        account.updated_at = _utcnow()
        self.db.add(account)
        await self.db.flush()
        return account

    # ------------------------------------------------------------------ #
    # Transactions (with two-lane dedup)
    # ------------------------------------------------------------------ #
    async def transaction_exists(
        self,
        *,
        account_id: int,
        source: str,
        external_id: str | None = None,
        import_hash: str | None = None,
    ) -> bool:
        """Two-lane dedup probe.

        LANE 1 keys on ``(account_id, source, external_id)`` for provider rows;
        LANE 2 keys on ``(account_id, import_hash)`` for id-less file imports.
        Soft-deleted rows don't count (they release the key).
        """
        query = select(FinanceTransaction.id).where(
            FinanceTransaction.account_id == account_id,
            FinanceTransaction.deleted_at.is_(None),
        )
        if external_id is not None:
            query = query.where(
                FinanceTransaction.source == source,
                FinanceTransaction.external_id == external_id,
            )
        elif import_hash is not None:
            query = query.where(FinanceTransaction.import_hash == import_hash)
        else:
            return False
        return (await self.db.exec(query)).first() is not None

    async def find_transaction(
        self,
        *,
        account_id: int,
        source: str,
        external_id: str | None = None,
        import_hash: str | None = None,
    ) -> FinanceTransaction | None:
        """Return the existing two-lane-dedup match, or None (for importers)."""
        query = select(FinanceTransaction).where(
            FinanceTransaction.account_id == account_id,
            FinanceTransaction.deleted_at.is_(None),
        )
        if external_id is not None:
            query = query.where(
                FinanceTransaction.source == source,
                FinanceTransaction.external_id == external_id,
            )
        elif import_hash is not None:
            query = query.where(FinanceTransaction.import_hash == import_hash)
        else:
            return None
        return (await self.db.exec(query)).first()

    async def create_transaction(
        self,
        *,
        account_id: int,
        amount: int,
        txn_date: date,
        owner_user_id: int | None = None,
        name: str | None = None,
        source: str = Provider.MANUAL,
        external_id: str | None = None,
        external_id_source: str | None = None,
        import_hash: str | None = None,
        within_day_ordinal: int = 0,
        import_batch_id: int | None = None,
        connection_id: int | None = None,
        raw_amount: int | None = None,
        raw_sign_convention: str | None = None,
        original_description: str | None = None,
        memo: str | None = None,
        check_number: str | None = None,
        currency: str = _DEFAULT_CURRENCY,
        category_id: int | None = None,
        category_source: str = "unset",
        is_split: bool = False,
        pending: bool = False,
        pending_provider_id: str | None = None,
    ) -> FinanceTransaction:
        txn = FinanceTransaction(
            owner_user_id=owner_user_id,
            account_id=account_id,
            connection_id=connection_id,
            amount=amount,
            date_=txn_date,
            name=name,
            source=source,
            external_id=external_id,
            external_id_source=external_id_source,
            import_hash=import_hash,
            within_day_ordinal=within_day_ordinal,
            import_batch_id=import_batch_id,
            raw_amount=raw_amount,
            raw_sign_convention=raw_sign_convention,
            original_description=original_description,
            memo=memo,
            check_number=check_number,
            currency=currency,
            category_id=category_id,
            category_source=category_source,
            is_split=is_split,
            pending=pending,
            pending_provider_id=pending_provider_id,
            status="pending" if pending else "posted",
        )
        self.db.add(txn)
        await self.db.flush()
        return txn

    async def create_split(
        self,
        *,
        parent_transaction_id: int,
        amount: int,
        owner_user_id: int | None = None,
        category_id: int | None = None,
        memo: str | None = None,
        sort_order: int = 0,
        currency: str = _DEFAULT_CURRENCY,
    ) -> FinanceTransactionSplit:
        split = FinanceTransactionSplit(
            owner_user_id=owner_user_id,
            parent_transaction_id=parent_transaction_id,
            amount=amount,
            category_id=category_id,
            memo=memo,
            sort_order=sort_order,
            currency=currency,
        )
        self.db.add(split)
        await self.db.flush()
        return split

    async def resolve_category_alias(self, category_hint: str | None) -> int | None:
        """Map a free-text category string to a category id via
        finance_category_alias (normalized lookup). None if unmatched.

        Prefers a user alias over a global (owner NULL) seed when both match.
        """
        if not category_hint:
            return None
        from app.services.finance.importers.base import normalize_payee

        normalized = normalize_payee(category_hint)
        if not normalized:
            return None
        query = (
            select(FinanceCategoryAlias.category_id)
            .where(FinanceCategoryAlias.normalized_alias == normalized)
            .order_by(FinanceCategoryAlias.owner_user_id.desc())
        )
        return (await self.db.exec(query)).first()

    async def get_or_create_category_from_hint(
        self, hint: str | None
    ) -> FinanceCategory | None:
        """Turn a free-text import category (a Quicken path) into a category.

        ``"Bills & Utilities:Streaming:Television:Netflix"`` becomes the
        category ``"Bills & Utilities:Streaming"`` - the first two path
        segments. Deeper segments are payee-grade detail (a category named
        Netflix is a merchant, not a category), while one segment alone
        lumps streaming with the electric bill. The full path is written to
        the alias table so every later spelling resolves without re-deriving.

        Bracketed hints (``"[TOTAL CHECKING]"``) are Quicken transfer
        markers, not categories. Classification comes from the top segment:
        income-ish -> income, transfer-ish -> transfer, else expense.
        Categories are global rows (owner NULL), like the PFC seeds.
        """
        if not hint:
            return None
        text = hint.strip()
        if not text or (text.startswith("[") and text.endswith("]")):
            return None
        from app.services.finance.importers.base import normalize_payee

        segments = [part.strip() for part in text.split(":") if part.strip()]
        if not segments:
            return None
        name = ":".join(segments[:2])
        slug = normalize_payee(name).lower().replace(" ", "_")[:96]
        if not slug:
            return None

        top = segments[0].lower()
        classification = (
            "income"
            if "income" in top or "paycheck" in top
            else "transfer"
            if "transfer" in top
            else "expense"
        )

        category = (
            await self.db.exec(
                select(FinanceCategory).where(
                    FinanceCategory.slug == slug,
                    FinanceCategory.owner_user_id.is_(None),
                )
            )
        ).first()
        if category is None:
            category = FinanceCategory(
                name=name, slug=slug, classification=classification
            )
            self.db.add(category)
            await self.db.flush()

        normalized = normalize_payee(text)
        existing_alias = (
            await self.db.exec(
                select(FinanceCategoryAlias).where(
                    FinanceCategoryAlias.normalized_alias == normalized,
                    FinanceCategoryAlias.owner_user_id.is_(None),
                )
            )
        ).first()
        if existing_alias is None:
            self.db.add(
                FinanceCategoryAlias(
                    category_id=category.id,
                    alias_text=text,
                    normalized_alias=normalized,
                    source="import",
                )
            )
            await self.db.flush()
        return category

    async def get_or_create_tag(
        self, name: str, *, owner_user_id: int | None = None
    ) -> FinanceTag:
        """Fetch (or create) a tag by normalized name.

        Tags are always user-owned; standalone (NULL-owner) installs use the
        ``0`` sentinel, like insights and recurring streams.
        """
        from app.services.finance.importers.base import normalize_payee

        store_owner = 0 if owner_user_id is None else owner_user_id
        normalized = normalize_payee(name)
        existing = (
            await self.db.exec(
                select(FinanceTag).where(
                    FinanceTag.owner_user_id == store_owner,
                    FinanceTag.normalized_name == normalized,
                    FinanceTag.deleted_at.is_(None),
                )
            )
        ).first()
        if existing is not None:
            return existing
        tag = FinanceTag(
            owner_user_id=store_owner, name=name.strip(), normalized_name=normalized
        )
        self.db.add(tag)
        await self.db.flush()
        return tag

    async def list_tags(
        self, *, owner_user_id: int | None = None
    ) -> list[tuple[FinanceTag, int]]:
        """Every live tag with how many transactions wear it, name order.

        The count is what turns the list into a directory - which flags
        are live versus leftovers - computed in ONE outer-joined query."""
        store_owner = 0 if owner_user_id is None else owner_user_id
        rows = (
            await self.db.exec(
                select(FinanceTag, func.count(FinanceTransactionTag.tag_id))
                .join(
                    FinanceTransactionTag,
                    FinanceTransactionTag.tag_id == FinanceTag.id,
                    isouter=True,
                )
                .where(
                    FinanceTag.owner_user_id == store_owner,
                    FinanceTag.deleted_at.is_(None),
                )
                .group_by(FinanceTag.id)
                .order_by(FinanceTag.name)
            )
        ).all()
        return [(tag, int(count)) for tag, count in rows]

    async def tag_transactions(
        self, transaction_ids: list[int], name: str, *, owner_user_id: int | None = None
    ) -> FinanceTag:
        """Attach a tag (created on first use) to every given transaction.

        Idempotent: rows already wearing it are left alone, so re-flagging
        a mixed selection never trips the composite PK."""
        tag = await self.get_or_create_tag(name, owner_user_id=owner_user_id)
        already = set(
            (
                await self.db.exec(
                    select(FinanceTransactionTag.transaction_id).where(
                        FinanceTransactionTag.tag_id == tag.id,
                        FinanceTransactionTag.transaction_id.in_(transaction_ids),
                    )
                )
            ).all()
        )
        for txn_id in transaction_ids:
            if txn_id not in already:
                self.db.add(FinanceTransactionTag(transaction_id=txn_id, tag_id=tag.id))
        await self.db.flush()
        return tag

    async def untag_transactions(
        self,
        transaction_ids: list[int],
        tag_id: int,
        *,
        owner_user_id: int | None = None,
    ) -> int:
        """Detach one tag from the given transactions; the tag itself and
        its other attachments stay. Returns how many rows were removed."""
        links = (
            await self.db.exec(
                select(FinanceTransactionTag).where(
                    FinanceTransactionTag.tag_id == tag_id,
                    FinanceTransactionTag.transaction_id.in_(transaction_ids),
                )
            )
        ).all()
        for link in links:
            await self.db.delete(link)
        await self.db.flush()
        return len(links)

    async def soft_delete_transactions(
        self, transaction_ids: list[int], *, owner_user_id: int | None = None
    ) -> int:
        """Soft-delete transactions (``deleted_at``), returning how many.

        Every read path already filters ``deleted_at``, so the rows leave
        the register, budgets, and projections with no recompute step.
        Linked-row rules: a transfer pair's SURVIVING leg is unpaired and
        comes back into view (the money movement on its account still
        happened); a split parent takes its split lines with it.
        """
        query = select(FinanceTransaction).where(
            FinanceTransaction.id.in_(transaction_ids),
            FinanceTransaction.deleted_at.is_(None),
        )
        if owner_user_id is not None:
            query = query.where(FinanceTransaction.owner_user_id == owner_user_id)
        rows = (await self.db.exec(query)).all()
        if not rows:
            return 0
        now = _utcnow()
        deleting = {txn.id for txn in rows}
        for txn in rows:
            txn.deleted_at = now
            txn.updated_at = now
            self.db.add(txn)
            pair_id = txn.transfer_pair_transaction_id
            if pair_id is not None and pair_id not in deleting:
                survivor = await self.db.get(FinanceTransaction, pair_id)
                if survivor is not None:
                    survivor.is_transfer = False
                    survivor.transfer_pair_transaction_id = None
                    survivor.transfer_group_id = None
                    survivor.updated_at = now
                    self.db.add(survivor)
            if txn.is_split:
                splits = (
                    await self.db.exec(
                        select(FinanceTransactionSplit).where(
                            FinanceTransactionSplit.parent_transaction_id == txn.id
                        )
                    )
                ).all()
                for split in splits:
                    await self.db.delete(split)
        await self.db.flush()
        return len(rows)

    async def transaction_tags(
        self, transaction_ids: list[int] | set[int]
    ) -> dict[int, list[FinanceTag]]:
        """Tags per transaction, batched for a register page - every id
        gets a key (empty list when untagged), one query for the lot."""
        by_txn: dict[int, list[FinanceTag]] = {txn_id: [] for txn_id in transaction_ids}
        if not by_txn:
            return by_txn
        rows = (
            await self.db.exec(
                select(FinanceTransactionTag.transaction_id, FinanceTag)
                .join(FinanceTag, FinanceTag.id == FinanceTransactionTag.tag_id)
                .where(
                    FinanceTransactionTag.transaction_id.in_(list(by_txn)),
                    FinanceTag.deleted_at.is_(None),
                )
                .order_by(FinanceTag.name)
            )
        ).all()
        for txn_id, tag in rows:
            by_txn[txn_id].append(tag)
        return by_txn

    async def get_or_create_pfc_category(self, pfc_primary: str) -> FinanceCategory:
        """Fetch (or create) the system category for a Plaid personal-finance
        category primary (e.g. ``FOOD_AND_DRINK``). Categories are global/system
        seeds (owner NULL), shared across users and created on first sight."""
        slug = pfc_primary.strip().lower()
        existing = (
            await self.db.exec(
                select(FinanceCategory).where(
                    FinanceCategory.slug == slug,
                    FinanceCategory.owner_user_id.is_(None),
                )
            )
        ).first()
        if existing is not None:
            return existing
        upper = pfc_primary.strip().upper()
        classification = (
            "income"
            if upper == "INCOME"
            else "transfer"
            if upper.startswith("TRANSFER")
            else "expense"
        )
        category = FinanceCategory(
            name=pfc_primary.replace("_", " ").title(),
            slug=slug,
            classification=classification,
            plaid_pfc_primary=upper,
            is_system=True,
        )
        self.db.add(category)
        await self.db.flush()
        return category

    async def uncategorized_transactions(
        self,
        *,
        owner_user_id: int | None = None,
        limit: int | None = 7,
        query: str | None = None,
        from_date: date | None = None,
        account_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Transactions nothing has classified, newest first, plus a count.

        Uncategorized means EITHER no category or a source app's own
        catch-all bucket (see ``UNCATEGORIZED_CATEGORY_NAMES``). Checking
        for NULL alone reports a clean ledger on an import that carried a
        thousand "Uncategorized" rows straight through.

        ``limit=None`` returns every match, unbounded - used internally by
        the auto-categorize sweep, which needs the full backlog rather than
        a preview page. The public endpoint keeps its own bound.

        ``query`` is the exact same payee search ``list_transactions``
        already does (case-insensitive substring on ``name`` only) - not a
        new search behavior, the same one the Accounts register uses.
        ``from_date`` is the same trailing-window filter too (``>=``, no
        upper bound - this is a backlog, not a historical register).
        ``account_ids`` is the same account-scope filter Overview's charts
        use - an explicit empty list means "nothing selected" (the
        frontend's ``AccountFilter`` "Remove all" state) and short-circuits
        to zero results rather than reading as "no filter".
        """
        if account_ids is not None and not account_ids:
            return {"items": [], "total": 0}
        live_accounts = select(FinanceAccount.id).where(
            FinanceAccount.deleted_at.is_(None)
        )
        catchall = select(FinanceCategory.id).where(
            func.lower(FinanceCategory.name).in_(list(UNCATEGORIZED_CATEGORY_NAMES))
        )
        filters = [
            FinanceTransaction.deleted_at.is_(None),
            FinanceTransaction.dedup_status != "duplicate",
            # A work queue, not a register: a row excluded from reports
            # (a transfer leg, an issuer-adjustment pair) can never change
            # a figure whatever it is categorized as, so asking is
            # busywork - nine adjustment legs sat here nagging until this
            # filter existed.
            FinanceTransaction.excluded_from_reports.is_(False),
            FinanceTransaction.account_id.in_(live_accounts),
            or_(
                FinanceTransaction.category_id.is_(None),
                FinanceTransaction.category_id.in_(catchall),
            ),
        ]
        if owner_user_id is not None:
            filters.append(FinanceTransaction.owner_user_id == owner_user_id)
        if query:
            filters.append(transaction_search_filter(query))
        if account_ids is not None:
            filters.append(FinanceTransaction.account_id.in_(account_ids))
        if from_date is not None:
            filters.append(FinanceTransaction.date_ >= from_date)

        total = (
            await self.db.exec(
                select(func.count()).select_from(FinanceTransaction).where(*filters)
            )
        ).one()
        select_query = (
            select(FinanceTransaction)
            .where(*filters)
            .order_by(FinanceTransaction.date_.desc())
        )
        if limit is not None:
            select_query = select_query.limit(limit)
        rows = (await self.db.exec(select_query)).all()
        return {"items": list(rows), "total": int(total or 0)}

    async def top_payees(
        self,
        *,
        owner_user_id: int | None = None,
        days: int = 90,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        """Who took the most money over the window, biggest first.

        Outflows only, transfers excluded - a card payment is money moved
        between your own accounts, and it would otherwise top the list
        forever. Grouped by merchant when the source names one, else by
        the raw payee: a bank's description varies per charge, and the
        merchant field is the one the provider already normalized.
        """
        live_accounts = select(FinanceAccount.id).where(
            FinanceAccount.deleted_at.is_(None)
        )
        payee = func.coalesce(FinanceTransaction.merchant_name, FinanceTransaction.name)
        filters = [
            FinanceTransaction.deleted_at.is_(None),
            FinanceTransaction.dedup_status != "duplicate",
            FinanceTransaction.excluded_from_reports.is_(False),
            FinanceTransaction.is_transfer.is_(False),
            FinanceTransaction.account_id.in_(live_accounts),
            FinanceTransaction.amount < 0,
            FinanceTransaction.date_ >= date.today() - timedelta(days=days),
            payee.is_not(None),
        ]
        if owner_user_id is not None:
            filters.append(FinanceTransaction.owner_user_id == owner_user_id)
        rows = (
            await self.db.exec(
                select(
                    payee,
                    func.sum(FinanceTransaction.amount),
                    func.count(FinanceTransaction.id),
                )
                .where(*filters)
                .group_by(payee)
                .order_by(func.sum(FinanceTransaction.amount))
                .limit(limit)
            )
        ).all()
        return [
            {
                "payee": name,
                # Positive magnitude: the chart asks "how much", and every
                # row is an outflow, so the minus sign carries no signal.
                "amount": -int(total or 0),
                "transaction_count": int(count or 0),
            }
            for name, total, count in rows
        ]

    async def monthly_cashflow(
        self,
        *,
        owner_user_id: int | None = None,
        months: int = 6,
        today: date | None = None,
        account_ids: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        """Income and spend per calendar month, oldest first.

        Transfers and report-excluded rows are out: a card payment is money
        moved, and counting it as both income and spend would double the
        bars. Months with no activity are still returned at zero so the
        chart keeps an even time axis instead of skipping a quiet month.
        ``account_ids`` narrows the bars to those accounts.

        Bucketing runs in Python rather than SQL date-truncation, which is
        dialect-specific - and at a few thousand rows the loop costs less
        than a millisecond.
        """
        today = today or date.today()
        span = max(1, months)
        first_year, first_month = today.year, today.month - (span - 1)
        while first_month <= 0:
            first_month += 12
            first_year -= 1
        start = date(first_year, first_month, 1)

        live_accounts = select(FinanceAccount.id).where(
            FinanceAccount.deleted_at.is_(None)
        )
        filters = [
            FinanceTransaction.deleted_at.is_(None),
            FinanceTransaction.dedup_status != "duplicate",
            FinanceTransaction.excluded_from_reports.is_(False),
            FinanceTransaction.is_transfer.is_(False),
            FinanceTransaction.account_id.in_(live_accounts),
            FinanceTransaction.date_ >= start,
            FinanceTransaction.date_ <= today,
        ]
        if account_ids is not None:
            filters.append(FinanceTransaction.account_id.in_(account_ids))
        if owner_user_id is not None:
            filters.append(FinanceTransaction.owner_user_id == owner_user_id)
        rows = (
            await self.db.exec(
                select(FinanceTransaction.date_, FinanceTransaction.amount).where(
                    *filters
                )
            )
        ).all()

        buckets: dict[str, dict[str, int]] = {}
        year, month = first_year, first_month
        for _ in range(span):
            buckets[f"{year:04d}-{month:02d}"] = {"income": 0, "expense": 0}
            month += 1
            if month > 12:
                month = 1
                year += 1
        for txn_date, amount in rows:
            bucket = buckets.get(f"{txn_date.year:04d}-{txn_date.month:02d}")
            if bucket is None:
                continue
            if amount >= 0:
                bucket["income"] += amount
            else:
                bucket["expense"] += -amount  # positive magnitude for the bar
        return [
            {
                "month": key,
                "income": value["income"],
                "expense": value["expense"],
                "net": value["income"] - value["expense"],
            }
            for key, value in buckets.items()
        ]

    async def category_names(self, ids: set[int] | list[int]) -> dict[int, str]:
        """Category names by id, in one query.

        Rows carry ``category_id``; a table that wants to SHOW the category
        would otherwise fetch one name per row.
        """
        wanted = [i for i in set(ids) if i is not None]
        if not wanted:
            return {}
        rows = (
            await self.db.exec(
                select(FinanceCategory).where(FinanceCategory.id.in_(wanted))
            )
        ).all()
        return {row.id: row.name for row in rows}

    # -- payees (merchants) --------------------------------------------------
    #
    # ``FinanceMerchant`` is the stable payee identity behind the raw bank
    # descriptor: "Google" for every one of "YOUTUBEPREMI G.CO/HELPPAY# CA
    # XXXX3007", "YOUTUBEPREMIG.CO/HELPPAY# CA XXXX--X3007", and
    # "YouTubePremi g.co/helppay# CA 07/19". Its own docstring calls it "the
    # prerequisite for recurring/subscription detection" - detection keys off
    # merchant_id when one is assigned (categorize/recurring.py), so a bank
    # changing its descriptor format stops splitting one bill into several
    # (confirmed live: those three variants were 2 dead streams plus a live
    # one that was never detected at all, because the embedded statement date
    # made every month's string unique).

    async def list_merchants(
        self, *, owner_user_id: int | None = None
    ) -> list[FinanceMerchant]:
        """The payees available to this owner - their own plus any global
        (NULL-owner) seeds, name-sorted for the picker."""
        query = select(FinanceMerchant).where(FinanceMerchant.deleted_at.is_(None))
        if owner_user_id is not None:
            query = query.where(
                or_(
                    FinanceMerchant.owner_user_id == owner_user_id,
                    FinanceMerchant.owner_user_id.is_(None),
                )
            )
        else:
            query = query.where(FinanceMerchant.owner_user_id.is_(None))
        rows = (await self.db.exec(query.order_by(FinanceMerchant.name))).all()
        return list(rows)

    async def create_merchant(
        self,
        name: str,
        *,
        owner_user_id: int | None = None,
        website_url: str | None = None,
    ) -> FinanceMerchant:
        """Create a payee, or return the existing one with the same
        normalized name - the unique index (uq_finance_merchant_user /
        _global) makes a duplicate an error rather than a second row, and a
        picker's "+ Create" is exactly where a user retypes a name they
        already have."""
        from app.services.finance.importers.base import normalize_payee

        display = (name or "").strip()
        normalized = normalize_payee(display)
        if not normalized:
            raise ValueError("A payee needs a name.")
        existing = (
            await self.db.exec(
                select(FinanceMerchant).where(
                    FinanceMerchant.normalized_name == normalized,
                    FinanceMerchant.deleted_at.is_(None),
                    FinanceMerchant.owner_user_id == owner_user_id
                    if owner_user_id is not None
                    else FinanceMerchant.owner_user_id.is_(None),
                )
            )
        ).first()
        if existing is not None:
            # A domain supplied now fills a gap, but never silently
            # replaces one the user already set.
            if website_url and not existing.website_url:
                existing.website_url = website_url
                self.db.add(existing)
                await self.db.flush()
            return existing
        merchant = FinanceMerchant(
            owner_user_id=owner_user_id,
            name=display,
            normalized_name=normalized,
            source="user",
            website_url=website_url or None,
        )
        self.db.add(merchant)
        await self.db.flush()
        return merchant

    async def set_merchant_website(
        self, merchant_id: int, website_url: str | None
    ) -> FinanceMerchant | None:
        """Point a payee at its real address. The icon resolver prefers
        this over guessing ``<name>.com`` - see merchant_icon.py."""
        merchant = await self.db.get(FinanceMerchant, merchant_id)
        if merchant is None:
            return None
        merchant.website_url = (website_url or "").strip() or None
        merchant.updated_at = _utcnow()
        self.db.add(merchant)
        await self.db.flush()
        return merchant

    # Sentinel for "caller did not mention this field", so that None can
    # keep its own meaning of "clear it". Without the distinction a patch
    # that only sets a website would blank the default category with it.
    _UNSET: Any = object()

    async def update_merchant(
        self,
        merchant_id: int,
        *,
        name: str | None = None,
        website_url: str | None | Any = _UNSET,
        default_category_id: int | None | Any = _UNSET,
        owner_user_id: int | None = None,
    ) -> FinanceMerchant | None:
        """Edit a payee in place, without touching its transactions.

        Correcting a logo is not a filing decision. The only path that
        could set a website ran through ``/payee-groups/assign``, which
        re-files every transaction in the group it was opened on - so
        fixing an address meant moving rows, and a payee whose backlog was
        already empty could not be edited at all.
        """
        merchant = await self.db.get(FinanceMerchant, merchant_id)
        if merchant is None:
            return None
        if owner_user_id is not None and merchant.owner_user_id not in (
            owner_user_id,
            None,
        ):
            return None
        if name is not None and name.strip():
            from app.services.finance.importers.base import normalize_payee

            merchant.name = name.strip()
            # The dedup key travels WITH the name. Leaving it stale means
            # the payee is no longer findable under the name it now shows,
            # so the picker's "+ Create" mints a duplicate beside it - the
            # exact mess merge_merchants exists to clean up. (A pure
            # punctuation fix, "Mcdonald S" -> "McDonald's", normalizes to
            # the same key anyway; a real rename does not.)
            merchant.normalized_name = normalize_payee(merchant.name)
        if website_url is not self._UNSET:
            merchant.website_url = (website_url or "").strip() or None
        if default_category_id is not self._UNSET:
            merchant.default_category_id = default_category_id
        merchant.updated_at = _utcnow()
        self.db.add(merchant)
        await self.db.flush()
        return merchant

    async def merge_merchants(
        self,
        source_ids: list[int],
        target_id: int,
        *,
        owner_user_id: int | None = None,
    ) -> int:
        """Fold payees into one, returning how many transactions moved.

        Two payees for one merchant is the normal end state of naming
        things by hand ("Shop Rite" and "ShopRite", 248 and 219
        transactions here). Renaming one to match the other does NOT join
        them - they are still two rows with two ids - so this is the
        deliberate action that does.

        Everything pointing at a loser is repointed rather than deleted:
        its transactions, and its recurring streams (a bill still pointing
        at a payee that no longer exists loses its name and its icon).
        Curation transfers only into a GAP - the survivor's own website
        and default category always win, because merging is not an edit of
        the payee you chose to keep.
        """
        target = await self.db.get(FinanceMerchant, target_id)
        if target is None or target.deleted_at is not None:
            return 0
        losers = [
            m
            for m in (
                await self.db.exec(
                    select(FinanceMerchant).where(
                        FinanceMerchant.id.in_([i for i in source_ids if i]),
                        FinanceMerchant.deleted_at.is_(None),
                    )
                )
            ).all()
            # Self-merge would soft-delete the survivor and strand every
            # transaction it had just moved onto a deleted row.
            if m.id != target_id
        ]
        if not losers:
            return 0
        loser_ids = [m.id for m in losers]

        moved = 0
        rows = (
            await self.db.exec(
                select(FinanceTransaction).where(
                    FinanceTransaction.merchant_id.in_(loser_ids),
                    FinanceTransaction.deleted_at.is_(None),
                )
            )
        ).all()
        for txn in rows:
            txn.merchant_id = target_id
            self.db.add(txn)
            moved += 1

        streams = (
            await self.db.exec(
                select(FinanceRecurringStream).where(
                    FinanceRecurringStream.merchant_id.in_(loser_ids),
                    FinanceRecurringStream.deleted_at.is_(None),
                )
            )
        ).all()
        for stream in streams:
            stream.merchant_id = target_id
            self.db.add(stream)

        now = _utcnow()
        for loser in losers:
            if not target.website_url and loser.website_url:
                target.website_url = loser.website_url
            if target.default_category_id is None:
                target.default_category_id = loser.default_category_id
            loser.deleted_at = now
            self.db.add(loser)
        target.updated_at = now
        self.db.add(target)
        await self.db.flush()
        return moved

    async def merchant_usage(
        self,
        *,
        owner_user_id: int | None = None,
        account_ids: list[int] | None = None,
    ) -> dict[int, dict[str, Any]]:
        """``{merchant id: {count, total_amount, last_date}}``.

        Which payee is worth correcting is a function of how much money
        runs through it, so the directory shows weight rather than a bare
        list of names. Grouped in one query; a payee with no transactions
        is simply absent, and the caller defaults it.
        """
        query = (
            select(
                FinanceTransaction.merchant_id,
                func.count(FinanceTransaction.id),
                func.sum(FinanceTransaction.amount),
                func.max(FinanceTransaction.date_),
            )
            .where(
                FinanceTransaction.deleted_at.is_(None),
                FinanceTransaction.merchant_id.is_not(None),
            )
            .group_by(FinanceTransaction.merchant_id)
        )
        if owner_user_id is not None:
            query = query.where(FinanceTransaction.owner_user_id == owner_user_id)
        if account_ids is not None:
            query = query.where(FinanceTransaction.account_id.in_(account_ids))
        return {
            merchant_id: {
                "count": count or 0,
                "total_amount": int(total or 0),
                "last_date": last_date,
            }
            for merchant_id, count, total, last_date in (
                await self.db.exec(query)
            ).all()
            if merchant_id is not None
        }

    async def merchant_websites(self, ids: set[int] | list[int]) -> dict[int, str]:
        """Stored websites by merchant id, for the icon resolver."""
        wanted = [i for i in set(ids) if i is not None]
        if not wanted:
            return {}
        rows = (
            await self.db.exec(
                select(FinanceMerchant).where(FinanceMerchant.id.in_(wanted))
            )
        ).all()
        return {r.id: r.website_url for r in rows if r.website_url}

    async def merchant_names(self, ids: set[int] | list[int]) -> dict[int, str]:
        """Payee names by id, in one query - same shape (and same reason) as
        ``category_names``."""
        wanted = [i for i in set(ids) if i is not None]
        if not wanted:
            return {}
        rows = (
            await self.db.exec(
                select(FinanceMerchant).where(FinanceMerchant.id.in_(wanted))
            )
        ).all()
        return {row.id: row.name for row in rows}

    async def assign_merchant(
        self,
        transaction_ids: Sequence[int],
        merchant_id: int | None,
        *,
        owner_user_id: int | None = None,
        category_id: int | None = None,
    ) -> int:
        """Point transactions at a payee (``None`` clears it). Returns how
        many rows were actually updated - a caller's id list is user input
        (a checkbox selection), so ids that aren't found/owned are skipped
        rather than failing the whole batch.

        ``category_id`` also files those rows under that category and
        remembers it as the payee's default, so the SAME decision covers
        the history in front of you and everything that arrives later.
        Confirmed worth having on real data: 7 of 79 GreenSky loan
        payments had been auto-filed as "Food & Dining:Restaurants".
        """
        ids = [i for i in set(transaction_ids) if i is not None]
        if not ids:
            return 0
        query = select(FinanceTransaction).where(
            FinanceTransaction.id.in_(ids),
            FinanceTransaction.deleted_at.is_(None),
        )
        if owner_user_id is not None:
            query = query.where(FinanceTransaction.owner_user_id == owner_user_id)
        rows = (await self.db.exec(query)).all()
        for txn in rows:
            txn.merchant_id = merchant_id
            if category_id is not None:
                txn.category_id = category_id
                txn.category_source = "user"
                txn.is_user_categorized = True
                txn.is_reviewed = True
            txn.updated_at = _utcnow()
            self.db.add(txn)
        if category_id is not None and merchant_id is not None:
            merchant = await self.db.get(FinanceMerchant, merchant_id)
            if merchant is not None:
                merchant.default_category_id = category_id
                merchant.updated_at = _utcnow()
                self.db.add(merchant)
        if rows:
            await self.db.flush()
        return len(rows)

    async def merchant_category_summary(
        self, merchant_id: int, *, owner_user_id: int | None = None
    ) -> dict[str, Any]:
        """How this payee's transactions are currently categorized - what
        the "also set category" offer pre-fills from, and how it can say
        "72 of 79 already use this" instead of asking blind."""
        merchant = await self.db.get(FinanceMerchant, merchant_id)
        query = select(FinanceTransaction).where(
            FinanceTransaction.merchant_id == merchant_id,
            FinanceTransaction.deleted_at.is_(None),
        )
        if owner_user_id is not None:
            query = query.where(FinanceTransaction.owner_user_id == owner_user_id)
        rows = (await self.db.exec(query)).all()
        tally = Counter(t.category_id for t in rows if t.category_id is not None)
        dominant_id, dominant_count = tally.most_common(1)[0] if tally else (None, 0)
        names = await self.category_names({dominant_id} if dominant_id else set())
        return {
            "merchant_id": merchant_id,
            "default_category_id": (
                merchant.default_category_id if merchant is not None else None
            ),
            "dominant_category_id": dominant_id,
            "dominant_category_name": names.get(dominant_id),
            "dominant_count": dominant_count,
            "total": len(rows),
            "distinct_categories": len(tally),
        }

    async def payee_groups(
        self, *, owner_user_id: int | None = None, limit: int = 200
    ) -> tuple[list[dict[str, Any]], int, int]:
        """Payee-less transactions collapsed into named-able groups, biggest
        first, as ``(page, total_groups, total_transactions)``.

        The two totals describe the WHOLE backlog, not the returned page -
        the caller needs them to say honestly how much is left behind the
        limit.

        The backlog is not a list to work through row by row: EVERY
        transaction starts without a payee, so a real import opens at tens
        of thousands (17,675 here) - but they collapse into ~2,473 distinct
        ``transaction_payee_key`` groups, and the largest 15 alone cover
        5,805 rows. Naming a group is one decision that settles all of it.

        The key IS the grouping - nothing is guessed. ``suggested_name``
        is only a suggestion (see ``suggested_payee_name``: the sample's
        own spelling where it reads like a name, else the title-cased
        key); the caller confirms or edits it, because a group can be a
        merchant the key mangles or not a merchant at all
        ("NON CHASE ATM WITHDRAW").
        """
        query = select(FinanceTransaction).where(
            FinanceTransaction.deleted_at.is_(None),
            FinanceTransaction.merchant_id.is_(None),
        )
        if owner_user_id is not None:
            query = query.where(FinanceTransaction.owner_user_id == owner_user_id)
        rows = (await self.db.exec(query)).all()

        groups: dict[str, dict[str, Any]] = {}
        for txn in rows:
            key = transaction_payee_key(
                txn.merchant_name, txn.original_description, txn.name
            )
            if not key:
                continue
            entry = groups.setdefault(
                key,
                {
                    "key": key,
                    "count": 0,
                    "sample": txn.name or txn.original_description or "",
                    "total_amount": 0,
                },
            )
            entry["count"] += 1
            entry["total_amount"] += txn.amount
        from app.services.finance.importers.base import suggested_payee_name

        ordered = sorted(groups.values(), key=lambda g: -g["count"])[:limit]
        for entry in ordered:
            # From the SAMPLE where it reads like a name, not the key -
            # the key has already had its punctuation and case stripped
            # (see suggested_payee_name).
            entry["suggested_name"] = suggested_payee_name(
                entry["key"], entry.get("sample")
            )
        # The TRUE totals travel alongside the truncated page. Reporting
        # len(ordered) as the total is a lie that reads as good news -
        # "300 groups" when there are 2,436 - and it silently caps at
        # whatever limit the caller happened to pass.
        return ordered, len(groups), sum(g["count"] for g in groups.values())

    async def assign_payee_group(
        self,
        keys: Sequence[str],
        merchant_id: int,
        *,
        owner_user_id: int | None = None,
        category_id: int | None = None,
    ) -> int:
        """Give every payee-less transaction in ``keys`` this payee.

        Resolved server-side from the keys rather than an id list: a single
        group runs to a thousand transactions, and shipping those ids to
        the browser and back just to name one merchant is pure weight.

        Takes the whole set of keys in ONE call because the alternative -
        the caller looping per group - re-reads every payee-less row each
        time. That scan is the expensive half (10,707 rows here), so
        naming a 48-group brand cost 48 full scans instead of one.
        """
        wanted = {k for k in keys if k}
        if not wanted:
            return 0
        query = select(FinanceTransaction).where(
            FinanceTransaction.deleted_at.is_(None),
            FinanceTransaction.merchant_id.is_(None),
        )
        if owner_user_id is not None:
            query = query.where(FinanceTransaction.owner_user_id == owner_user_id)
        rows = (await self.db.exec(query)).all()
        ids = [
            t.id
            for t in rows
            if transaction_payee_key(t.merchant_name, t.original_description, t.name)
            in wanted
        ]
        if not ids:
            return 0
        return await self.assign_merchant(
            ids, merchant_id, owner_user_id=owner_user_id, category_id=category_id
        )

    async def similar_unassigned(
        self, transaction_id: int, *, owner_user_id: int | None = None
    ) -> list[FinanceTransaction]:
        """Other payee-less transactions whose descriptor looks like this
        one's, for the picker's "also apply to N similar" offer.

        Uses ``transaction_payee_key``'s loose 4-token prefix, which is a
        HEURISTIC - deliberately so, and deliberately only here: the user
        confirms the list before anything is written, so a false match costs
        a glance rather than a silently mis-grouped bill. Detection itself
        never relies on it; it keys off the assigned ``merchant_id``.
        """
        txn = await self._get_transaction(transaction_id, owner_user_id=owner_user_id)
        if txn is None:
            return []
        key = transaction_payee_key(
            txn.merchant_name, txn.original_description, txn.name
        )
        if not key:
            return []
        query = select(FinanceTransaction).where(
            FinanceTransaction.deleted_at.is_(None),
            FinanceTransaction.merchant_id.is_(None),
            FinanceTransaction.id != transaction_id,
        )
        if owner_user_id is not None:
            query = query.where(FinanceTransaction.owner_user_id == owner_user_id)
        return [
            row
            for row in (await self.db.exec(query)).all()
            if transaction_payee_key(
                row.merchant_name, row.original_description, row.name
            )
            == key
        ]

    async def list_categories(self) -> list[FinanceCategory]:
        """The full taxonomy, name-sorted, nothing joined.

        For pickers that only need id + name (the uncategorized-transactions
        dropdown). ``category_usage`` also lists every category but LEFT
        JOINs + GROUPs BY over the *entire* transaction history to compute
        usage stats a picker never shows - measurably slow once there's a
        real amount of transaction data. This is a plain, single-table
        select instead.
        """
        rows = (
            await self.db.exec(select(FinanceCategory).order_by(FinanceCategory.name))
        ).all()
        return list(rows)

    async def category_usage(
        self,
        *,
        owner_user_id: int | None = None,
        days: int | None = None,
    ) -> list[dict[str, Any]]:
        """Every category with how it is actually used.

        Unlike ``spending_by_category`` this keeps INFLOWS and transfers,
        reports a signed total, and lists categories that saw no activity
        in the window - the point is the taxonomy itself, not a spend
        ranking. ``days=None`` covers all time.
        """
        filters = [
            FinanceTransaction.deleted_at.is_(None),
            FinanceTransaction.dedup_status != "duplicate",
            FinanceTransaction.excluded_from_reports.is_(False),
        ]
        if owner_user_id is not None:
            filters.append(FinanceTransaction.owner_user_id == owner_user_id)
        if days is not None:
            filters.append(
                FinanceTransaction.date_ >= date.today() - timedelta(days=days)
            )
        # LEFT join: an unused category still belongs in the list, so the
        # user can see (and prune) taxonomy the import brought over.
        rows = (
            await self.db.exec(
                select(
                    FinanceCategory.id,
                    FinanceCategory.name,
                    FinanceCategory.classification,
                    FinanceCategory.is_system,
                    func.count(FinanceTransaction.id),
                    func.coalesce(func.sum(FinanceTransaction.amount), 0),
                    func.max(FinanceTransaction.date_),
                )
                .join(
                    FinanceTransaction,
                    and_(
                        FinanceTransaction.category_id == FinanceCategory.id,
                        *filters,
                    ),
                    isouter=True,
                )
                .group_by(
                    FinanceCategory.id,
                    FinanceCategory.name,
                    FinanceCategory.classification,
                    FinanceCategory.is_system,
                )
            )
        ).all()
        return [
            {
                "id": category_id,
                "name": name,
                "classification": classification,
                "is_system": is_system,
                "transaction_count": int(count or 0),
                "total": int(total or 0),
                "last_used": last_used,
            }
            for (
                category_id,
                name,
                classification,
                is_system,
                count,
                total,
                last_used,
            ) in rows
        ]

    async def spending_by_category(
        self,
        *,
        owner_user_id: int | None = None,
        days: int = 30,
        account_ids: list[int] | None = None,
    ) -> list[tuple[str, int]]:
        """Total outflow per PARENT category over the recent window — the
        spending breakdown. Expense outflows only (amount < 0), on live
        accounts, returned largest-first as positive cents.

        Rolled up to the parent segment of a "Parent:Child" category name
        (the part before the first ":") - a flat name (no colon, e.g. a
        Plaid-PFC-seeded "Food And Drink") rolls up to itself unchanged.
        Grouping by the full LEAF name instead (the original behavior)
        fragments spending across every sub-category a user or import ever
        created, which is what was pushing the Overview pie's "Other"
        slice past 30% on a real ledger - most of "Other" wasn't
        miscellaneous spend, it was several mid-size siblings (three or
        four "Food & Dining:*" rows, say) each too small on its own to
        crack the top N, that together are a top category once combined.
        Confirmed against live data: 30.7% "Other" leaf-grouped vs 16.3%
        parent-rolled-up, same 30-day window, same ledger.

        The GROUP BY itself stays on the leaf name (portable SQL - no
        string-splitting function that works identically on both SQLite,
        used in tests, and Postgres); the rollup happens in Python after,
        over what's normally a few dozen rows at most, not a per-row cost
        that scales with transaction count.

        ``account_ids`` narrows the breakdown to those accounts (still
        intersected with live accounts and the owner scope, so a stray id can
        never widen the view)."""
        cutoff = date.today() - timedelta(days=days)
        live_accounts = select(FinanceAccount.id).where(
            FinanceAccount.deleted_at.is_(None)
        )
        filters = [
            FinanceTransaction.deleted_at.is_(None),
            FinanceTransaction.dedup_status != "duplicate",
            FinanceTransaction.excluded_from_reports.is_(False),
            FinanceTransaction.account_id.in_(live_accounts),
            FinanceTransaction.category_id.is_not(None),
            FinanceTransaction.amount < 0,
            FinanceTransaction.date_ >= cutoff,
        ]
        if account_ids is not None:
            filters.append(FinanceTransaction.account_id.in_(account_ids))
        if owner_user_id is not None:
            filters.append(FinanceTransaction.owner_user_id == owner_user_id)
        rows = (
            await self.db.exec(
                select(
                    FinanceCategory.name,
                    func.sum(FinanceTransaction.amount),
                )
                .join(
                    FinanceCategory,
                    FinanceTransaction.category_id == FinanceCategory.id,
                )
                .where(*filters)
                .group_by(FinanceCategory.name)
            )
        ).all()
        totals: dict[str, int] = {}
        for name, total in rows:
            parent = name.split(":", 1)[0]
            totals[parent] = totals.get(parent, 0) - int(total)
        result = sorted(totals.items(), key=lambda pair: pair[1], reverse=True)
        return result

    async def spending_transactions(
        self,
        *,
        owner_user_id: int | None = None,
        days: int = 30,
        account_ids: list[int] | None = None,
        categories: list[str] | None = None,
    ) -> list[FinanceTransaction]:
        """The actual rows behind a ``spending_by_category`` slice - the
        SAME filters, verbatim, minus the ``GROUP BY``/``SUM``, so drilling
        into a slice shows exactly the transactions that summed to its
        dollar total (a mismatched filter set here would show a table that
        doesn't add up to the number the user just clicked).

        ``categories`` matches each name exactly OR as a "name:" prefix -
        spending_by_category already rolls a leaf category up to its
        PARENT before a caller ever sees it, so passing a parent name like
        "Food & Dining" pulls every "Food & Dining:*" leaf transaction
        too. Pass the full list of names folded into "Other" (everything
        past the slice cutoff) to drill into THAT slice the same way - it
        spans multiple unrelated parents, which is exactly why this takes
        a list instead of one name.
        """
        cutoff = date.today() - timedelta(days=days)
        live_accounts = select(FinanceAccount.id).where(
            FinanceAccount.deleted_at.is_(None)
        )
        filters = [
            FinanceTransaction.deleted_at.is_(None),
            FinanceTransaction.dedup_status != "duplicate",
            FinanceTransaction.excluded_from_reports.is_(False),
            FinanceTransaction.account_id.in_(live_accounts),
            FinanceTransaction.category_id.is_not(None),
            FinanceTransaction.amount < 0,
            FinanceTransaction.date_ >= cutoff,
        ]
        if account_ids is not None:
            filters.append(FinanceTransaction.account_id.in_(account_ids))
        if owner_user_id is not None:
            filters.append(FinanceTransaction.owner_user_id == owner_user_id)
        if categories:
            matching_ids = select(FinanceCategory.id).where(
                or_(
                    *[
                        or_(
                            FinanceCategory.name == name,
                            FinanceCategory.name.like(f"{name}:%"),
                        )
                        for name in categories
                    ]
                )
            )
            filters.append(FinanceTransaction.category_id.in_(matching_ids))
        rows = (
            await self.db.exec(
                select(FinanceTransaction)
                .where(*filters)
                .order_by(FinanceTransaction.date_.desc())
            )
        ).all()
        return list(rows)

    async def spending_summary(
        self, *, owner_user_id: int | None = None, month: str | None = None
    ) -> list[tuple[str, int]]:
        """Per-category spend for one calendar month (default: current month),
        transfers excluded. ``month`` is ``YYYY-MM``. This is the report the
        insights + UI consume, so a card payment never inflates a category."""
        if month:
            year, mon = (int(part) for part in month.split("-", 1))
            start = date(year, mon, 1)
        else:
            today = date.today()
            start = date(today.year, today.month, 1)
        end = (
            date(start.year + 1, 1, 1)
            if start.month == 12
            else date(start.year, start.month + 1, 1)
        )
        live_accounts = select(FinanceAccount.id).where(
            FinanceAccount.deleted_at.is_(None)
        )
        filters = [
            FinanceTransaction.deleted_at.is_(None),
            FinanceTransaction.dedup_status != "duplicate",
            FinanceTransaction.excluded_from_reports.is_(False),
            FinanceTransaction.account_id.in_(live_accounts),
            FinanceTransaction.category_id.is_not(None),
            FinanceTransaction.amount < 0,
            FinanceTransaction.date_ >= start,
            FinanceTransaction.date_ < end,
        ]
        if owner_user_id is not None:
            filters.append(FinanceTransaction.owner_user_id == owner_user_id)
        rows = (
            await self.db.exec(
                select(FinanceCategory.name, func.sum(FinanceTransaction.amount))
                .join(
                    FinanceCategory,
                    FinanceTransaction.category_id == FinanceCategory.id,
                )
                .where(*filters)
                .group_by(FinanceCategory.name)
            )
        ).all()
        result = [(name, -int(total)) for name, total in rows]
        result.sort(key=lambda pair: pair[1], reverse=True)
        return result

    async def _get_transfer(
        self, transfer_id: int, *, owner_user_id: int | None
    ) -> FinanceTransfer | None:
        query = select(FinanceTransfer).where(FinanceTransfer.id == transfer_id)
        if owner_user_id is not None:
            query = query.where(FinanceTransfer.owner_user_id == owner_user_id)
        return (await self.db.exec(query)).first()

    async def _get_transaction(
        self, transaction_id: int, *, owner_user_id: int | None = None
    ) -> FinanceTransaction | None:
        query = select(FinanceTransaction).where(
            FinanceTransaction.id == transaction_id,
            FinanceTransaction.deleted_at.is_(None),
        )
        if owner_user_id is not None:
            query = query.where(FinanceTransaction.owner_user_id == owner_user_id)
        return (await self.db.exec(query)).first()

    async def categorize_transaction(
        self,
        transaction_id: int,
        category_id: int,
        *,
        owner_user_id: int | None = None,
        source: str = "user",
    ) -> FinanceTransaction | None:
        """Set a transaction's category. ``source`` is ``"user"`` for a
        manual pick, ``"rule"`` for the payee-precedent auto-categorize
        sweep. Returns None if the transaction isn't found/owned."""
        txn = await self._get_transaction(transaction_id, owner_user_id=owner_user_id)
        if txn is None:
            return None
        txn.category_id = category_id
        txn.category_source = source
        txn.is_user_categorized = source == "user"
        txn.is_reviewed = True
        # The transfer flag follows the category, in the same gesture -
        # fixing a miscategorized card payment must fix the numbers now,
        # not on the next import. Only CATEGORY-driven flags are undone
        # (transfer_group_id NULL): a pairing is evidence from both sides
        # of the money, and dissolving it is Review's reject, which
        # restores both legs together.
        category = await self.db.get(FinanceCategory, category_id)
        to_transfer = category is not None and category.classification == "transfer"
        if to_transfer and not txn.is_transfer:
            txn.is_transfer = True
            txn.excluded_from_reports = True
        elif not to_transfer and txn.is_transfer and txn.transfer_group_id is None:
            txn.is_transfer = False
            txn.excluded_from_reports = False
        txn.updated_at = _utcnow()
        self.db.add(txn)
        await self.db.flush()
        return txn

    async def suggest_categories(
        self,
        *,
        owner_user_id: int | None = None,
        transaction_ids: list[int] | set[int] | None = None,
    ) -> dict[str, Any]:
        """Preview a category by payee precedent - computes, does not write.

        If this owner has categorized other transactions from the same
        payee before, and one category clearly dominates (no tie), that
        transaction gets a suggestion. No ML, no new tables - just the
        owner's own past corrections, the same normalize_payee-based
        grouping recurring-stream detection already uses
        (categorize/recurring.py). A caller applies an accepted suggestion
        through the ordinary ``categorize_transaction`` (``source="rule"``)
        - this method only computes candidates, on purpose: an earlier
        version applied matches directly, which meant nothing was left to
        review before it hit the ledger.

        ``transaction_ids``, when given, narrows candidates to that set
        (e.g. a user's checkbox selection) - the precedent tally itself
        still covers the owner's FULL categorized history (a narrower
        candidate list shouldn't mean weaker precedent matching), only
        which uncategorized rows get a suggestion computed is scoped.
        """

        def payee_key(txn: FinanceTransaction) -> str:
            return transaction_payee_key(
                txn.merchant_name, txn.original_description, txn.name
            )

        catchall = select(FinanceCategory.id).where(
            func.lower(FinanceCategory.name).in_(list(UNCATEGORIZED_CATEGORY_NAMES))
        )
        base_filters = [
            FinanceTransaction.deleted_at.is_(None),
            FinanceTransaction.dedup_status != "duplicate",
        ]
        if owner_user_id is not None:
            base_filters.append(FinanceTransaction.owner_user_id == owner_user_id)

        # One batched fetch of the owner's already-categorized history,
        # tallied in Python by payee key -> {category_id: count}.
        categorized_rows = (
            await self.db.exec(
                select(FinanceTransaction).where(
                    *base_filters,
                    FinanceTransaction.category_id.is_not(None),
                    FinanceTransaction.category_id.not_in(catchall),
                )
            )
        ).all()
        tally: dict[str, Counter[int]] = defaultdict(Counter)
        for row in categorized_rows:
            key = payee_key(row)
            if key:
                tally[key][row.category_id] += 1

        uncategorized = await self.uncategorized_transactions(
            owner_user_id=owner_user_id, limit=None
        )
        candidates = uncategorized["items"]
        if transaction_ids is not None:
            wanted = set(transaction_ids)
            candidates = [t for t in candidates if t.id in wanted]

        suggestions: list[dict[str, int]] = []
        skipped = 0
        for txn in candidates:
            key = payee_key(txn)
            counts = tally.get(key)
            if not counts:
                skipped += 1
                continue
            (best_category, best_n), *rest = counts.most_common()
            if rest and rest[0][1] == best_n:
                # Tied precedent - ambiguous, leave it for a manual pick.
                skipped += 1
                continue
            suggestions.append({"transaction_id": txn.id, "category_id": best_category})

        names = await self.category_names({s["category_id"] for s in suggestions})
        return {
            "items": [
                {**s, "category_name": names.get(s["category_id"], "")}
                for s in suggestions
            ],
            "skipped": skipped,
        }

    async def list_transfers(
        self, *, owner_user_id: int | None = None, status: str | None = None
    ) -> list[FinanceTransfer]:
        """Transfers for an owner (optionally one ``status``), newest first."""
        query = select(FinanceTransfer)
        if owner_user_id is not None:
            query = query.where(FinanceTransfer.owner_user_id == owner_user_id)
        if status is not None:
            query = query.where(FinanceTransfer.status == status)
        query = query.order_by(
            FinanceTransfer.transfer_date.desc(), FinanceTransfer.id.desc()
        )
        return list((await self.db.exec(query)).all())

    async def transactions_by_ids(
        self, ids: list[int]
    ) -> dict[int, FinanceTransaction]:
        """Fetch transactions by id in one query, keyed by id (for enrichment)."""
        if not ids:
            return {}
        rows = (
            await self.db.exec(
                select(FinanceTransaction).where(FinanceTransaction.id.in_(ids))
            )
        ).all()
        return {t.id: t for t in rows}

    # -- Recurring streams ---------------------------------------------------

    async def list_recurring(
        self, *, owner_user_id: int | None = None
    ) -> list[FinanceRecurringStream]:
        """Active recurring streams, soonest-due first."""
        query = select(FinanceRecurringStream).where(
            FinanceRecurringStream.deleted_at.is_(None),
            FinanceRecurringStream.status != "cancelled",
        )
        if owner_user_id is not None:
            query = query.where(FinanceRecurringStream.owner_user_id == owner_user_id)
        query = query.order_by(FinanceRecurringStream.next_expected_date)
        return list((await self.db.exec(query)).all())

    _STREAM_DIRECTIONS = frozenset({"inflow", "outflow"})
    # DERIVED, never re-listed. This was a hand-written copy of the same
    # six cadences and it drifted: the menus and the forecast grew
    # bimonthly and semiannual, this did not, so the edit dialog offered
    # cadences that raised on save. A stream may be stored with exactly
    # the cadences the forecast can step - anything else is a bill that
    # cannot appear in it.
    _STREAM_FREQUENCIES = frozenset(CADENCE_KEYS) | {ONE_TIME_FREQUENCY}

    async def create_recurring_stream(
        self,
        *,
        owner_user_id: int | None,
        name: str,
        direction: str,
        frequency: str,
        expected_amount: int,
        next_expected_date: date,
        account_id: int | None = None,
        is_subscription: bool = False,
    ) -> FinanceRecurringStream:
        """Create a user-declared bill (outflow) or income (inflow) stream.

        Hand-entered rows are commitments by definition: ``source="user"``,
        confirmed, mature, fixed-amount - the missed-payment rule chases
        them at any cadence. Streams use the ``0`` owner sentinel in
        standalone (NULL-owner) installs, like insights.
        """
        if direction not in self._STREAM_DIRECTIONS:
            raise ValueError(
                f"direction must be one of {sorted(self._STREAM_DIRECTIONS)}"
            )
        if frequency not in self._STREAM_FREQUENCIES:
            raise ValueError(
                f"frequency must be one of {sorted(self._STREAM_FREQUENCIES)}"
            )
        await self.get_or_create_currency(_DEFAULT_CURRENCY)
        stream = FinanceRecurringStream(
            owner_user_id=0 if owner_user_id is None else owner_user_id,
            account_id=account_id,
            name=name,
            normalized_payee=name.strip().upper(),
            direction=direction,
            frequency=frequency,
            average_amount=expected_amount,
            expected_amount=expected_amount,
            amount_is_variable=False,
            currency=_DEFAULT_CURRENCY,
            next_expected_date=next_expected_date,
            status="mature",
            source="user",
            confidence=100,
            is_subscription=is_subscription,
            is_user_confirmed=True,
        )
        self.db.add(stream)
        await self.db.flush()
        return stream

    async def transfer_stream_ids(self, stream_ids: Sequence[int]) -> set[int]:
        """Streams with any transfer-flagged member transaction.

        Detection can build a stream out of a recurring INTERNAL transfer
        (a monthly card autopay) before pairing flags the legs. Such a
        stream is money moved, not a bill: the Bills & Income surface and
        its monthly rollup exclude it, the same way the missed-payment
        rule skips it.
        """
        if not stream_ids:
            return set()
        rows = (
            await self.db.exec(
                select(FinanceTransaction.recurring_stream_id)
                .where(
                    FinanceTransaction.recurring_stream_id.in_(list(stream_ids)),
                    FinanceTransaction.is_transfer.is_(True),
                )
                .distinct()
            )
        ).all()
        return {int(row) for row in rows}

    async def payment_stream_ids(self, stream_ids: Sequence[int]) -> set[int]:
        """The subset of streams that are card/loan PAYMENTS: their
        members are the cash side of confirmed transfers into a liability
        account.

        A payment is a transfer, but it is a payment first. The split
        matters because the two halves of the app disagree about it: the
        cash forecast must charge it (it genuinely drains checking every
        month), while the Bills total and spending math must not (the
        card swipes already counted - adding the payment double-counts
        every dollar on the card).
        """
        if not stream_ids:
            return set()
        to_txn = select(FinanceTransaction.account_id).where(
            FinanceTransaction.id == FinanceTransfer.to_transaction_id
        )
        rows = (
            await self.db.exec(
                select(FinanceTransaction.recurring_stream_id)
                .where(
                    FinanceTransaction.recurring_stream_id.in_(list(stream_ids)),
                    select(FinanceTransfer.id)
                    .join(
                        FinanceAccount,
                        FinanceAccount.id == to_txn.scalar_subquery(),
                    )
                    .where(
                        FinanceTransfer.from_transaction_id == FinanceTransaction.id,
                        FinanceTransfer.status == "confirmed",
                        FinanceAccount.classification == "liability",
                    )
                    .exists(),
                )
                .distinct()
            )
        ).all()
        return {int(row) for row in rows}

    async def _get_recurring(
        self, stream_id: int, owner_user_id: int | None
    ) -> FinanceRecurringStream | None:
        query = select(FinanceRecurringStream).where(
            FinanceRecurringStream.id == stream_id
        )
        if owner_user_id is not None:
            query = query.where(FinanceRecurringStream.owner_user_id == owner_user_id)
        return (await self.db.exec(query)).first()

    async def mute_recurring(
        self, stream_id: int, *, owner_user_id: int | None = None
    ) -> FinanceRecurringStream | None:
        """Mute a stream so it stops raising price-hike insights."""
        stream = await self._get_recurring(stream_id, owner_user_id)
        if stream is None:
            return None
        stream.is_muted = True
        self.db.add(stream)
        await self.db.flush()
        return stream

    async def unmute_recurring(
        self, stream_id: int, *, owner_user_id: int | None = None
    ) -> FinanceRecurringStream | None:
        """Reverse a mute."""
        stream = await self._get_recurring(stream_id, owner_user_id)
        if stream is None:
            return None
        stream.is_muted = False
        self.db.add(stream)
        await self.db.flush()
        return stream

    async def attach_transaction_to_stream(
        self,
        transaction_id: int,
        stream_id: int,
        *,
        owner_user_id: int | None = None,
    ) -> FinanceRecurringStream | None:
        """Reconcile a stray transaction with the bill it paid.

        The automatic matcher unites the two when the payee key lines up;
        this is the manual verb for when it cannot (a changed descriptor,
        a hand-entered bill no bank string resembles). It does BOTH
        halves of the job: consumes the occurrence (membership, due date
        stepped from the payment's date - the same rule the matcher
        follows - occurrence counted), and TEACHES the payee key by
        aligning merchant between the two, so future months match on
        their own instead of putting the user on a mark-as-paid
        treadmill. The due date never moves backward: attaching June's
        charge for the record must not re-arm July's nag.
        """
        stream = await self._get_recurring(stream_id, owner_user_id)
        if stream is None:
            return None
        txn_query = select(FinanceTransaction).where(
            FinanceTransaction.id == transaction_id,
            FinanceTransaction.deleted_at.is_(None),
        )
        if owner_user_id is not None:
            txn_query = txn_query.where(
                FinanceTransaction.owner_user_id == owner_user_id
            )
        txn = (await self.db.exec(txn_query)).first()
        if txn is None:
            return None

        txn.recurring_stream_id = stream.id
        # Teach whichever side knows less.
        if txn.merchant_id is not None and stream.merchant_id is None:
            stream.merchant_id = txn.merchant_id
        elif stream.merchant_id is not None and txn.merchant_id is None:
            txn.merchant_id = stream.merchant_id

        # Backfill: claim the payee's OTHER unclaimed rows too. Teaching
        # the key only helps future months - without this, last
        # quarter's payments still read as unplanned spending and the
        # "Everything else" figure double-counts the bill (confirmed
        # live: a nursing-home bill counted once in BILLS and again in
        # the observed run rate). Strays only: rows a live stream
        # already claims are not re-litigated.
        if txn.merchant_id is not None:
            live_claim = select(FinanceRecurringStream.id).where(
                FinanceRecurringStream.id == FinanceTransaction.recurring_stream_id,
                FinanceRecurringStream.deleted_at.is_(None),
            )
            amount_clause = (
                FinanceTransaction.amount > 0
                if stream.direction == "inflow"
                else FinanceTransaction.amount < 0
            )
            strays = (
                await self.db.exec(
                    select(FinanceTransaction).where(
                        FinanceTransaction.id != txn.id,
                        FinanceTransaction.merchant_id == txn.merchant_id,
                        FinanceTransaction.deleted_at.is_(None),
                        FinanceTransaction.dedup_status != "duplicate",
                        amount_clause,
                        or_(
                            FinanceTransaction.recurring_stream_id.is_(None),
                            ~live_claim.exists(),
                        ),
                        _owner_clause_txn(
                            FinanceTransaction.owner_user_id, owner_user_id
                        ),
                    )
                )
            ).all()
            for stray in strays:
                stray.recurring_stream_id = stream.id
                self.db.add(stray)

        stream.occurrence_count += 1
        stream.last_amount = abs(txn.amount)
        if stream.last_date is None or txn.date_ > stream.last_date:
            stream.last_date = txn.date_
        if stream.frequency == ONE_TIME_FREQUENCY:
            # "Pay someone back" has no next occurrence - the payment
            # arriving is the end of it, not a reschedule.
            stream.next_expected_date = None
        else:
            step = _FREQUENCY_STEPS.get(stream.frequency)
            if step is not None:
                advanced = step(txn.date_)
                current = stream.next_expected_date
                if current is None or advanced > current:
                    stream.next_expected_date = advanced

        self.db.add(txn)
        self.db.add(stream)
        await self.db.flush()
        return stream

    async def recurring_match_candidates(
        self,
        stream_id: int,
        *,
        owner_user_id: int | None = None,
        limit: int = 20,
    ) -> list[FinanceTransaction]:
        """The shortlist a human would scan when reconciling a bill:
        unclaimed rows in the bill's direction whose amount lands in the
        neighborhood of what the bill costs, newest first.

        The amount band is deliberately loose (half to double the
        expected figure, or everything when the bill has no figure) -
        this feeds a picker where the user decides, not an auto-match,
        and a too-tight band hides exactly the changed-amount payment
        that broke the automatic match in the first place.
        """
        stream = await self._get_recurring(stream_id, owner_user_id)
        if stream is None:
            return []
        amount_clause = (
            FinanceTransaction.amount > 0
            if stream.direction == "inflow"
            else FinanceTransaction.amount < 0
        )
        # "Unclaimed" includes rows held by a DELETED stream: a dismissed
        # detector guess keeps claiming its pattern (that is how a
        # dismissal stays silent), but a human reconciling a confirmed
        # bill outranks a dead proposal - hiding those rows made the
        # Fidelity payment invisible here twice (confirmed live).
        live_claim = select(FinanceRecurringStream.id).where(
            FinanceRecurringStream.id == FinanceTransaction.recurring_stream_id,
            FinanceRecurringStream.deleted_at.is_(None),
        )
        filters = [
            FinanceTransaction.deleted_at.is_(None),
            FinanceTransaction.dedup_status != "duplicate",
            or_(
                FinanceTransaction.recurring_stream_id.is_(None),
                ~live_claim.exists(),
            ),
            amount_clause,
            _owner_clause_txn(FinanceTransaction.owner_user_id, owner_user_id),
        ]
        expected = stream.expected_amount or stream.average_amount
        if expected:
            filters.append(
                func.abs(FinanceTransaction.amount).between(
                    int(expected * 0.5), int(expected * 2)
                )
            )
        # This dialog answers "which payment was THIS due date" - last
        # year's identical charges are not answers to that question, and
        # six of them crowded out everything else (confirmed live). The
        # window scales with the cadence so an annual bill still sees a
        # sensible neighborhood.
        due = stream.next_expected_date
        if due is not None:
            cadence = CADENCES.get(stream.frequency)
            reach = max(45, int(cadence.detect_days * 1.5)) if cadence else 45
            window = timedelta(days=reach)
            filters.append(FinanceTransaction.date_.between(due - window, due + window))
        rows = (
            await self.db.exec(
                select(FinanceTransaction)
                .where(*filters)
                .order_by(FinanceTransaction.date_.desc())
                .limit(limit * 5)
            )
        ).all()

        # Likeliest first, not newest first: a small bill's band admits
        # every coffee in the register, and the real payment (exact
        # amount, dated near the due date) must not drown under a page
        # of newer lookalikes (confirmed live).
        today = date.today()
        # Name affinity outranks the figures: a candidate carrying the
        # bill's own payee (or its name in the descriptor) is the answer
        # even when a stranger's amount lands a dollar nearer - ranked
        # purely on figures, last year's Etsy outranked rows literally
        # named after the bill (confirmed live).
        stream_name = (stream.name or "").casefold()

        def named_alike(txn: FinanceTransaction) -> bool:
            if stream.merchant_id is not None and txn.merchant_id == stream.merchant_id:
                return True
            if not stream_name:
                return False
            haystack = f"{txn.name or ''} {txn.original_description or ''}".casefold()
            return stream_name in haystack

        def likelihood(txn: FinanceTransaction) -> tuple[int, int, int]:
            amount_distance = abs(abs(txn.amount) - expected) if expected else 0
            date_distance = abs((txn.date_ - (due or today)).days)
            return (0 if named_alike(txn) else 1, amount_distance, date_distance)

        # When rows carry the bill's own name, the strangers are noise
        # and stay out entirely ("it's so obviously Fidelity and not
        # AT&T"); the amount shortlist earns its keep only when the
        # payment arrived under an unrecognizable descriptor.
        named = [t for t in rows if named_alike(t)]
        pool = named if named else rows
        return sorted(pool, key=likelihood)[:limit]

    async def pause_recurring(
        self,
        stream_id: int,
        *,
        until: date,
        note: str | None = None,
        owner_user_id: int | None = None,
    ) -> FinanceRecurringStream | None:
        """Pause a stream until a date: out of the forecast, the Bills
        total, the month verdict and every nag until then - and back in
        all of them the day the date passes, by pure comparison (see
        ``is_paused``). ``note`` is the why, for the future reader who
        forgot ("waiting until the pool is paid off"); it rides in
        ``metadata_`` rather than a column because it is prose for one
        surface, not a fact anything computes on.
        """
        stream = await self._get_recurring(stream_id, owner_user_id)
        if stream is None:
            return None
        stream.paused_until = until
        if note and note.strip():
            stream.metadata_ = {**(stream.metadata_ or {}), "pause_note": note.strip()}
        self.db.add(stream)
        await self.db.flush()
        return stream

    async def resume_recurring(
        self, stream_id: int, *, owner_user_id: int | None = None
    ) -> FinanceRecurringStream | None:
        """End a pause early. Clears the note too - a stale reason
        explaining a pause that is no longer happening is worse than no
        note at all."""
        stream = await self._get_recurring(stream_id, owner_user_id)
        if stream is None:
            return None
        stream.paused_until = None
        if stream.metadata_ and "pause_note" in stream.metadata_:
            stream.metadata_ = {
                k: v for k, v in stream.metadata_.items() if k != "pause_note"
            }
        self.db.add(stream)
        await self.db.flush()
        return stream

    async def confirm_recurring(
        self, stream_id: int, *, owner_user_id: int | None = None
    ) -> FinanceRecurringStream | None:
        """Mark a detected stream as a real commitment (bill or income).

        Confirmation is what promotes a guess into something the missed-
        payment rule will chase regardless of amount variability.
        """
        stream = await self._get_recurring(stream_id, owner_user_id)
        if stream is None:
            return None
        stream.is_user_confirmed = True
        self.db.add(stream)
        await self.db.flush()
        return stream

    async def update_recurring(
        self,
        stream_id: int,
        *,
        owner_user_id: int | None = None,
        name: str | None = None,
        frequency: str | None = None,
        expected_amount: int | None = None,
        next_expected_date: date | None = None,
        category_id: int | None = None,
        account_id: int | None = None,
    ) -> FinanceRecurringStream | None:
        """Edit a stream's declared facts; ``None`` fields are left alone.

        ``category_id`` is stated ABOUT THE BILL and stops there: the
        member transactions keep whatever they already had. A bill's
        category is otherwise inferred from them (see
        ``stream_category_names``), and cascading would overwrite
        per-transaction corrections made by hand to fix an inference.

        Setting an expected amount pins the stream fixed-amount
        (``amount_is_variable`` off): the user is stating what the bill IS,
        which beats the detector's average. Renaming only re-keys
        ``normalized_payee`` on hand-entered streams - a detected stream's
        payee key is how the detector re-finds it, and changing it would
        make the next detection pass spawn a duplicate.
        """
        if frequency is not None and frequency not in self._STREAM_FREQUENCIES:
            raise ValueError(
                f"frequency must be one of {sorted(self._STREAM_FREQUENCIES)}"
            )
        stream = await self._get_recurring(stream_id, owner_user_id)
        if stream is None:
            return None
        if name is not None and name.strip():
            stream.name = name.strip()
            if stream.source == "user":
                stream.normalized_payee = name.strip().upper()
        if frequency is not None:
            stream.frequency = frequency
        if expected_amount is not None:
            stream.expected_amount = expected_amount
            stream.amount_is_variable = False
        if next_expected_date is not None:
            stream.next_expected_date = next_expected_date
        elif frequency in _FREQUENCY_STEPS and stream.next_expected_date is None:
            # A cadence with no date to apply it to still projects
            # nothing, so stating one has to complete the repair. This is
            # the shape a bill takes when it has been seen ONCE: no gap to
            # measure, so no cadence and no next date - it sits in Bills
            # reading "Active" and contributes zero to the forecast.
            # Stepped from the last occurrence when there is one; the
            # forecast rolls a past date forward on its own.
            step = _FREQUENCY_STEPS[frequency]
            stream.next_expected_date = step(stream.last_date or date.today())
        if category_id is not None:
            stream.category_id = category_id
        if account_id is not None and account_id != stream.account_id:
            # (owner, account, direction, normalized_payee) is unique - it
            # is the key detection re-finds a stream by. Moving accounts
            # can land on a bill already there, so check first and refuse
            # with something the API can turn into a 409 rather than
            # letting the index raise as a 500.
            # NOT filtered on deleted_at: the unique index has no such
            # predicate (only provider_stream_id IS NULL), so a retired
            # row still occupies the slot. Filtering it out here let the
            # UPDATE hit the index and surface as a 500.
            clash = (
                await self.db.exec(
                    select(FinanceRecurringStream).where(
                        FinanceRecurringStream.owner_user_id == stream.owner_user_id,
                        FinanceRecurringStream.account_id == account_id,
                        FinanceRecurringStream.direction == stream.direction,
                        FinanceRecurringStream.normalized_payee
                        == stream.normalized_payee,
                        FinanceRecurringStream.provider_stream_id.is_(None),
                        FinanceRecurringStream.id != stream.id,
                    )
                )
            ).first()
            if clash is not None and clash.deleted_at is None:
                raise ValueError(f'"{clash.name}" already exists on that account.')
            if clash is not None:
                # Retired, so refusing would block the move on a row the
                # user cannot see. Free the key instead of deleting the
                # history: the ghost stays for the record, it just stops
                # holding a slot it no longer uses.
                clash.normalized_payee = f"{clash.normalized_payee}#retired{clash.id}"
                self.db.add(clash)
                await self.db.flush()
            stream.account_id = account_id
        self.db.add(stream)
        await self.db.flush()
        return stream

    async def stream_category_names(
        self, stream_ids: Sequence[int] | set[int]
    ) -> dict[int, str]:
        """Each stream's category, derived from its member transactions.

        ``finance_recurring_stream.category_id`` is a provider field the
        local detector never fills, so the stream table itself has no
        category to show. The transactions DO carry one (import maps the
        Quicken category path), and a stream is one merchant's rhythm -
        so the most common category across its members is the stream's
        category. Ties break on the higher count, then category id.
        """
        ids = list(stream_ids)
        if not ids:
            return {}
        rows = (
            await self.db.exec(
                select(
                    FinanceTransaction.recurring_stream_id,
                    FinanceCategory.name,
                    func.count().label("hits"),
                )
                .join(
                    FinanceCategory,
                    FinanceCategory.id == FinanceTransaction.category_id,
                )
                .where(
                    FinanceTransaction.recurring_stream_id.in_(ids),
                    FinanceTransaction.deleted_at.is_(None),
                )
                .group_by(FinanceTransaction.recurring_stream_id, FinanceCategory.name)
            )
        ).all()
        best: dict[int, tuple[int, str]] = {}
        for stream_id, name, hits in rows:
            current = best.get(stream_id)
            if current is None or hits > current[0]:
                best[stream_id] = (hits, name)
        resolved = {stream_id: name for stream_id, (_, name) in best.items()}

        # A category set ON THE BILL outranks the inference. Without this
        # the edit saves to a column nothing reads, and Bills & Income
        # keeps showing whatever its transactions vote for - the change
        # looks accepted and does nothing.
        stored = (
            await self.db.exec(
                select(FinanceRecurringStream.id, FinanceCategory.name)
                .join(
                    FinanceCategory,
                    FinanceCategory.id == FinanceRecurringStream.category_id,
                )
                .where(FinanceRecurringStream.id.in_(ids))
            )
        ).all()
        resolved.update({stream_id: name for stream_id, name in stored if name})
        return resolved

    async def project_balances(
        self,
        *,
        owner_user_id: int | None = None,
        days: int = 180,
        today: date | None = None,
        account_ids: list[int] | None = None,
    ) -> ProjectionResponse:
        """Walk today's cash balance forward through scheduled bills/income.

        The starting point is the display balance of cash accounts
        (checking/savings/cash): the authoritative ``current_balance``
        when a balance write happened, else the register sum - the same
        rule the sidebar uses. Only COMMITMENTS project (the monthly-
        rollup gate), in both directions: detected merchant rhythms
        would fabricate a five-figure decline, and detected refund or
        transfer rhythms an equally fictional windfall. Muted and
        transfer streams are skipped. Occurrences already in the past
        are not re-charged - chasing a missed payment is the insight
        rules' job, not the forecast's.
        """
        from app.services.finance.categorize import is_commitment, is_paused

        today = today or date.today()
        horizon = today + timedelta(days=days)

        accounts, _ = await self.list_accounts(
            owner_user_id=owner_user_id, page_size=500
        )
        # The dialog-wide account filter reaches the forecast too: a
        # balance line that walks through bills on accounts you are not
        # viewing moves for reasons that are off screen.
        if account_ids is not None:
            allowed = set(account_ids)
            accounts = [a for a in accounts if a.id in allowed]
        cash = [
            a
            for a in accounts
            if a.classification != "liability" and a.account_type in _CASH_ACCOUNT_TYPES
        ]
        totals = await self.account_transaction_totals(
            owner_user_id=owner_user_id, account_ids=[a.id for a in cash]
        )
        start_balance = _display_cash_balance(cash, totals)

        streams = await self.list_recurring(owner_user_id=owner_user_id)
        transfer_ids = await self.transfer_stream_ids([s.id for s in streams])
        # Payment streams are the carve-out from the transfer exclusion:
        # the card autopay genuinely drains checking on a rhythm, and a
        # forecast that skips it runs optimistic by the whole payment
        # every month (confirmed live, ~$1,800/mo). The commitment gate
        # below still applies - a detector average poisoned by a one-off
        # paydown must not walk the forecast until the user pins it.
        payment_ids = await self.payment_stream_ids(list(transfer_ids))
        occurrences: list[tuple[date, FinanceRecurringStream, int]] = []
        for stream in streams:
            if (
                stream.is_muted
                or is_paused(stream, today)
                or (stream.id in transfer_ids and stream.id not in payment_ids)
            ):
                continue
            # ``account_id is None`` is a hand-entered bill that belongs
            # to no account, so no account selection is a statement about
            # it - the same rule AccountFilter.allows follows. Dropping
            # it here made every typed-in bill vanish from the forecast
            # the moment the view was narrowed.
            if (
                account_ids is not None
                and stream.account_id is not None
                and stream.account_id not in allowed
            ):
                continue
            if stream.next_expected_date is None:
                continue
            # Both directions pass the commitment gate. Detected inflows
            # include refunds and brokerage-transfer rhythms; projecting
            # those as income fabricates a six-figure windfall. A real
            # paycheck (fixed amount at a paycheck cadence) passes the
            # gate on its own; a variable one gets in once its amount is
            # pinned in the edit dialog.
            if not is_commitment(stream):
                continue
            amount = stream.expected_amount or stream.average_amount or 0
            if stream.frequency == ONE_TIME_FREQUENCY:
                # One occurrence, never stepped, never re-charged from the
                # past (chasing a missed payment is the insight rules' job).
                when = stream.next_expected_date
                if amount > 0 and today <= when <= horizon:
                    occurrences.append((when, stream, amount))
                continue
            step = _FREQUENCY_STEPS.get(stream.frequency)
            if step is None or amount <= 0:
                continue
            when = stream.next_expected_date
            guard = 0
            while when < today and guard < 400:
                when = step(when)
                guard += 1
            while when <= horizon and guard < 400:
                occurrences.append((when, stream, amount))
                when = step(when)
                guard += 1

        # Budget lines are the OTHER half of what leaves an account:
        # everyday spending nobody bills you for. A line draws down once a
        # month, on the same day of the month, for as far as the horizon
        # reaches.
        #
        # Bills win where they overlap. A category a recurring bill
        # already pays is spending the forecast has counted once already,
        # and adding the budget on top charges it twice - which reads as a
        # pessimistic balance nobody can account for.
        billed_categories = {
            stream.category_id
            for _when, stream, _amount in occurrences
            if stream.category_id is not None
        }
        budget_points = await self._budget_drawdowns(
            owner_user_id=owner_user_id,
            today=today,
            horizon=horizon,
            skip_categories=billed_categories,
        )

        occurrences.sort(key=lambda item: (item[0], item[1].name.casefold()))

        account_names = {a.id: a.name for a in accounts}
        stream_categories = await self.stream_category_names(
            {s.id for _, s, _ in occurrences}
        )

        # One timeline: bills and budgets interleaved by date, so the
        # running balance is the order money actually moves.
        walk: list[tuple[date, str, int, dict[str, Any]]] = [
            (
                when,
                stream.name,
                amount if stream.direction == "inflow" else -amount,
                {
                    "stream_id": stream.id,
                    "direction": stream.direction,
                    "account": account_names.get(stream.account_id),
                    "category": stream_categories.get(stream.id),
                },
            )
            for when, stream, amount in occurrences
        ]
        walk.extend(budget_points)
        # Active goals drain the walk too - committing to a dream visibly
        # costs the chart.
        walk.extend(
            await self._goal_drawdowns(
                owner_user_id=owner_user_id, today=today, horizon=horizon
            )
        )
        walk.sort(key=lambda item: (item[0], item[1].casefold()))

        balance = start_balance
        points: list[ProjectionPoint] = []
        for when, name, signed, extra in walk:
            balance += signed
            points.append(
                ProjectionPoint(
                    date=when,
                    stream_id=extra.get("stream_id"),
                    name=name,
                    direction=extra.get("direction", "outflow"),
                    amount=signed,
                    balance=balance,
                    account=extra.get("account"),
                    category=extra.get("category"),
                )
            )
        return ProjectionResponse(
            as_of=today,
            horizon_days=days,
            start_balance=start_balance,
            upcoming_total=balance - start_balance,
            end_balance=balance,
            points=points,
            total=len(points),
        )

    async def _goal_drawdowns(
        self,
        *,
        owner_user_id: int | None,
        today: date,
        horizon: date,
    ) -> list[tuple[date, str, int, dict[str, Any]]]:
        """Monthly goal contributions as forecast outflows, on the 1st
        (the day 's auto-contribute books). Paused/reached goals ask
        nothing (the pure-math contract). The linked-yield guard: a
        LINKED goal's synthetic month yields when a real inbound transfer
        to that account is already booked in that calendar month -
        without it, committing AND transferring double-drops the line.
        """
        goal_accounts = await self.list_goals(owner_user_id=owner_user_id)
        if not goal_accounts:
            return []
        linked_ids = [
            a.id for a in goal_accounts if a.account_type != GOAL_ACCOUNT_TYPE
        ]
        booked_months: dict[int, set[tuple[int, int]]] = {}
        if linked_ids:
            transfers = (
                await self.db.exec(
                    select(
                        FinanceTransaction.account_id, FinanceTransaction.date_
                    ).where(
                        FinanceTransaction.account_id.in_(linked_ids),
                        FinanceTransaction.is_transfer.is_(True),
                        FinanceTransaction.amount > 0,
                        FinanceTransaction.deleted_at.is_(None),
                        FinanceTransaction.date_ >= date(today.year, today.month, 1),
                        FinanceTransaction.date_ <= horizon,
                    )
                )
            ).all()
            for account_id, when in transfers:
                booked_months.setdefault(account_id, set()).add((when.year, when.month))
        allocations = await self.goal_allocations(
            owner_user_id=owner_user_id, today=today
        )
        out: list[tuple[date, str, int, dict[str, Any]]] = []
        for account in goal_accounts:
            meta = goal_metadata(account.metadata_)
            if meta is None:
                continue
            need = allocations.get(account.id, 0)
            if need <= 0:
                continue
            when = add_months(date(today.year, today.month, 1), 1)
            while when <= horizon:
                if (when.year, when.month) not in booked_months.get(account.id, set()):
                    out.append(
                        (
                            when,
                            account.name,
                            -need,
                            {"direction": "outflow", "goal_account_id": account.id},
                        )
                    )
                when = add_months(when, 1)
        return out

    async def _budget_drawdowns(
        self,
        *,
        owner_user_id: int | None,
        today: date,
        horizon: date,
        skip_categories: set[int],
    ) -> list[tuple[date, str, int, dict[str, Any]]]:
        """Monthly draws for each budget line, as forecast points.

        Dated on the same day of the month as today, which is a choice:
        everyday spending has no due date, and spreading it daily would
        bury the bills that DO. One visible step a month reads as "this is
        what I expect to spend", which is what a budget is.
        """
        budget = await self.get_or_create_budget(
            owner_user_id=owner_user_id, period_month=_current_period_month()
        )
        lines = (
            await self.db.exec(
                select(FinanceBudgetCategory).where(
                    FinanceBudgetCategory.budget_id == budget.id,
                    FinanceBudgetCategory.allocated_amount > 0,
                )
            )
        ).all()
        if not lines:
            return []
        names = {
            c.id: c.name for c in (await self.db.exec(select(FinanceCategory))).all()
        }
        out: list[tuple[date, str, int, dict[str, Any]]] = []
        for line in lines:
            if line.category_id is not None and line.category_id in skip_categories:
                continue
            label = (
                names.get(line.category_id)
                or getattr(line, "payee_label", None)
                or "Budget"
            )
            allocated = int(line.allocated_amount)
            extra = {"direction": "outflow", "category": names.get(line.category_id)}

            # What is LEFT of this month's envelope, not the whole of it.
            # Money already spent has left the account and is in the
            # starting balance; charging the allocation on top counts it
            # twice, and every new transaction widens the gap.
            spent = await self._spend_for_target(
                owner_user_id=owner_user_id,
                period_month=_period_month_for(today),
                category_id=line.category_id,
                payee_key=line.payee_key,
            )
            remaining = allocated - spent
            if remaining > 0:
                # Dated at month END: it has not happened yet, so it must
                # not dent the line today. Dating these at ``today`` also
                # piled every budget line onto the first point of the walk.
                out.append((_month_end(today), label, -remaining, extra))

            # Overspending is not a write-off. The overage carries into the
            # next envelope as a TIGHTER budget, so the forecast shows it
            # being made up without anyone editing the budget. Only the
            # next month: you make it up once, then the envelope is clean.
            # Underspend carries nothing, because the remainder above
            # already assumes this month's envelope gets used.
            carry = min(0, remaining)
            when = _month_end(_add_months(today, 1))
            first = True
            while when <= horizon:
                amount = max(0, allocated + carry) if first else allocated
                if amount > 0:
                    name = label + (_BUDGET_CARRY_NOTE if first and carry else "")
                    out.append((when, name, -amount, extra))
                first = False
                when = _month_end(_add_months(when, 1))
        return out

    async def delete_recurring(
        self, stream_id: int, *, owner_user_id: int | None = None
    ) -> bool:
        """Soft-delete a stream (the row survives; it drops from listings).

        A derived stream is also muted: the detector resurrects its row
        when the rhythm keeps firing on import, and mute survives that
        resurrection - a deleted guess can come back silent, never loud.
        """
        stream = await self._get_recurring(stream_id, owner_user_id)
        if stream is None:
            return False
        stream.deleted_at = _utcnow()
        if stream.source != "user":
            stream.is_muted = True
        # Free the members. Leaving them claimed by the corpse made them
        # invisible to Match (claimed) AND to re-detection (pinned), so a
        # confirmed twin of a deleted duplicate starved forever - 366
        # transactions sat zombie-claimed by 20 dead streams before this
        # released on delete (the purge path always did; this path
        # never had).
        members = (
            await self.db.exec(
                select(FinanceTransaction).where(
                    FinanceTransaction.recurring_stream_id == stream.id
                )
            )
        ).all()
        for member in members:
            member.recurring_stream_id = None
            self.db.add(member)
        self.db.add(stream)
        await self.db.flush()
        return True

    # -- Insights ------------------------------------------------------------

    async def list_insights(
        self,
        *,
        owner_user_id: int | None = None,
        status: str | None = "new",
        insight_type: str | None = None,
        exclude_types: Sequence[str] = (),
    ) -> list[FinanceInsight]:
        """Insights for an owner (default: only ``new``), newest first.

        ``insight_type`` narrows to one kind, ``exclude_types`` drops kinds.
        One table, two audiences: the anomaly list and the analyst's notes,
        each wanting the other filtered out at the query rather than in the UI.
        """
        query = select(FinanceInsight)
        if owner_user_id is not None:
            query = query.where(FinanceInsight.owner_user_id == owner_user_id)
        if status is not None:
            query = query.where(FinanceInsight.status == status)
        if insight_type is not None:
            query = query.where(FinanceInsight.insight_type == insight_type)
        if exclude_types:
            query = query.where(FinanceInsight.insight_type.notin_(list(exclude_types)))
        query = query.order_by(FinanceInsight.id.desc())
        return list((await self.db.exec(query)).all())

    async def count_new_insights(self, *, owner_user_id: int | None = None) -> int:
        """How many unseen insights — the finance card's badge count."""
        # Analyst notes are excluded: the badge means "things to act on", and a
        # note saying everything is fine is not one of them.
        query = (
            select(func.count())
            .select_from(FinanceInsight)
            .where(
                FinanceInsight.status == "new",
                FinanceInsight.insight_type != ANALYST_NOTE_INSIGHT_TYPE,
            )
        )
        if owner_user_id is not None:
            query = query.where(FinanceInsight.owner_user_id == owner_user_id)
        return (await self.db.exec(query)).one()

    async def dismiss_insight(
        self, insight_id: int, *, owner_user_id: int | None = None
    ) -> FinanceInsight | None:
        """Dismiss an insight (survives re-runs via its dedup_key)."""
        query = select(FinanceInsight).where(FinanceInsight.id == insight_id)
        if owner_user_id is not None:
            query = query.where(FinanceInsight.owner_user_id == owner_user_id)
        insight = (await self.db.exec(query)).first()
        if insight is None:
            return None
        insight.status = "dismissed"
        insight.is_read = True
        insight.dismissed_at = datetime.now(UTC).replace(tzinfo=None)
        self.db.add(insight)
        await self.db.flush()
        return insight

    async def confirm_transfer(
        self, transfer_id: int, *, owner_user_id: int | None = None
    ) -> FinanceTransfer | None:
        """Confirm a suggested transfer: flip to ``confirmed`` and flag both
        legs out of reports + cross-link them. Returns None if not found for
        this owner."""
        transfer = await self._get_transfer(transfer_id, owner_user_id=owner_user_id)
        if transfer is None:
            return None
        transfer.status = "confirmed"
        self.db.add(transfer)
        legs = [
            await self.db.get(FinanceTransaction, txn_id)
            for txn_id in (transfer.from_transaction_id, transfer.to_transaction_id)
            if txn_id is not None
        ]
        legs = [leg for leg in legs if leg is not None]
        for leg in legs:
            leg.is_transfer = True
            leg.excluded_from_reports = True
            leg.transfer_group_id = transfer.id
            self.db.add(leg)
        if len(legs) == 2:
            legs[0].transfer_pair_transaction_id = legs[1].id
            legs[1].transfer_pair_transaction_id = legs[0].id
        await self.db.flush()
        return transfer

    async def reject_transfer(
        self, transfer_id: int, *, owner_user_id: int | None = None
    ) -> FinanceTransfer | None:
        """Reject a transfer: mark ``rejected`` and restore both legs to normal
        spend/income. The row persists so the pair is never re-suggested."""
        transfer = await self._get_transfer(transfer_id, owner_user_id=owner_user_id)
        if transfer is None:
            return None
        transfer.status = "rejected"
        self.db.add(transfer)
        for txn_id in (transfer.from_transaction_id, transfer.to_transaction_id):
            if txn_id is None:
                continue
            leg = await self.db.get(FinanceTransaction, txn_id)
            if leg is not None and leg.transfer_group_id == transfer.id:
                leg.is_transfer = False
                leg.excluded_from_reports = False
                leg.transfer_group_id = None
                leg.transfer_pair_transaction_id = None
                self.db.add(leg)
        await self.db.flush()
        return transfer

    async def list_transactions(
        self,
        *,
        owner_user_id: int | None = None,
        account_id: int | None = None,
        account_ids: list[int] | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        category_id: int | None = None,
        merchant_id: int | None = None,
        without_merchant: bool = False,
        tag_id: int | None = None,
        query: str | None = None,
        include_transfers: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[FinanceTransaction], int]:
        # Default view: not soft-deleted, and never the losing side of a dedup.
        # Also hide transactions whose account was removed/disconnected — the
        # rows are kept for history + re-link reconciliation, but shouldn't show
        # in the register once the account is gone. Paired transfer legs are
        # hidden by default (``include_transfers``) so a checking->card payment
        # doesn't show as two lines of spend/income.
        filters = [
            FinanceTransaction.deleted_at.is_(None),
            FinanceTransaction.dedup_status != "duplicate",
            FinanceTransaction.account_id.in_(
                select(FinanceAccount.id).where(FinanceAccount.deleted_at.is_(None))
            ),
        ]
        if not include_transfers:
            filters.append(FinanceTransaction.is_transfer.is_(False))
        if owner_user_id is not None:
            filters.append(FinanceTransaction.owner_user_id == owner_user_id)
        if account_id is not None:
            filters.append(FinanceTransaction.account_id == account_id)
        if account_ids is not None:
            # The register's account-picker scope: same convention as
            # every other ``account_ids`` consumer (None = no filter).
            filters.append(FinanceTransaction.account_id.in_(account_ids))
        if from_date is not None:
            filters.append(FinanceTransaction.date_ >= from_date)
        if to_date is not None:
            filters.append(FinanceTransaction.date_ <= to_date)
        if category_id is not None:
            filters.append(FinanceTransaction.category_id == category_id)
        if merchant_id is not None:
            filters.append(FinanceTransaction.merchant_id == merchant_id)
        if without_merchant:
            # The payee work queue: rows nobody has named yet. Distinct from
            # merchant_id=None, which simply means "don't filter by payee".
            filters.append(FinanceTransaction.merchant_id.is_(None))
        if tag_id is not None:
            filters.append(
                FinanceTransaction.id.in_(
                    select(FinanceTransactionTag.transaction_id).where(
                        FinanceTransactionTag.tag_id == tag_id
                    )
                )
            )
        if query:
            filters.append(transaction_search_filter(query))
        select_query = select(FinanceTransaction).where(*filters)
        count_query = (
            select(func.count()).select_from(FinanceTransaction).where(*filters)
        )
        total = (await self.db.exec(count_query)).one()
        query_obj = (
            select_query.order_by(
                FinanceTransaction.date_.desc(), FinanceTransaction.id.desc()
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list((await self.db.exec(query_obj)).all()), total

    async def liability_details(
        self, account_ids: list[int]
    ) -> dict[int, FinanceLiabilityDetail]:
        """Liability rows for a page of accounts, keyed by account id.

        One ``IN`` query — never one per account. Accounts without a row
        (manual, or AMEX-style institutions that report nothing) are simply
        absent from the map.
        """
        if not account_ids:
            return {}
        rows = (
            await self.db.exec(
                select(FinanceLiabilityDetail).where(
                    FinanceLiabilityDetail.account_id.in_(account_ids)
                )
            )
        ).all()
        return {row.account_id: row for row in rows}

    async def account_transaction_totals(
        self,
        *,
        owner_user_id: int | None = None,
        account_ids: list[int] | None = None,
    ) -> dict[int, int]:
        """Sum of (non-duplicate, non-deleted) transaction amounts per account.

        The register-style balance shown per account in the UI when no
        statement balance/valuation is set. One aggregate query, keyed by
        account id — never one query per account. Pass ``account_ids`` to scope
        the aggregate to a page's accounts instead of the whole owner.
        """
        if account_ids is not None and not account_ids:
            return {}
        filters = [
            FinanceTransaction.deleted_at.is_(None),
            FinanceTransaction.dedup_status != "duplicate",
        ]
        if owner_user_id is not None:
            filters.append(FinanceTransaction.owner_user_id == owner_user_id)
        if account_ids is not None:
            filters.append(FinanceTransaction.account_id.in_(account_ids))
        query = (
            select(
                FinanceTransaction.account_id,
                func.coalesce(func.sum(FinanceTransaction.amount), 0),
            )
            .where(*filters)
            .group_by(FinanceTransaction.account_id)
        )
        return {
            account_id: int(total or 0)
            for account_id, total in (await self.db.exec(query)).all()
        }

    # ------------------------------------------------------------------ #
    # Valuations (manual / off-aggregator asset marks)
    # ------------------------------------------------------------------ #
    async def add_valuation(
        self,
        *,
        account_id: int,
        as_of_date: date,
        value: int,
        owner_user_id: int | None = None,
        source: str = "manual",
        source_ref: str | None = None,
    ) -> FinanceValuation:
        valuation = FinanceValuation(
            owner_user_id=owner_user_id,
            account_id=account_id,
            as_of_date=as_of_date,
            value=value,
            source=source,
            source_ref=source_ref,
        )
        self.db.add(valuation)
        await self.db.flush()
        return valuation

    # ------------------------------------------------------------------ #
    # Net worth
    # ------------------------------------------------------------------ #
    async def _account_rollup(
        self, *, owner_user_id: int | None = None
    ) -> tuple[int, int, int]:
        """(assets, liabilities, account_count) in a single aggregate query.

        Assets/liabilities sum only *visible* accounts; the count includes
        hidden ones — the two filters differ, so they're expressed as
        conditional sums over one scan rather than three separate queries.
        """
        query = (
            select(
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    FinanceAccount.classification == "asset",
                                    ~FinanceAccount.is_hidden,
                                ),
                                FinanceAccount.current_balance,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    FinanceAccount.classification == "liability",
                                    ~FinanceAccount.is_hidden,
                                ),
                                FinanceAccount.current_balance,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.count(),
            )
            .select_from(FinanceAccount)
            .where(FinanceAccount.deleted_at.is_(None))
        )
        if owner_user_id is not None:
            query = query.where(FinanceAccount.owner_user_id == owner_user_id)
        assets, liabilities, count = (await self.db.exec(query)).one()
        return int(assets or 0), int(liabilities or 0), int(count or 0)

    async def _connection_rollup(
        self, *, owner_user_id: int | None = None
    ) -> tuple[int, int]:
        """(connection_count, needs_action_count) in a single aggregate query."""
        query = (
            select(
                func.count(),
                func.coalesce(
                    func.sum(case((FinanceConnection.needs_user_action, 1), else_=0)),
                    0,
                ),
            )
            .select_from(FinanceConnection)
            .where(FinanceConnection.deleted_at.is_(None))
        )
        if owner_user_id is not None:
            query = query.where(FinanceConnection.owner_user_id == owner_user_id)
        connections, needs_action = (await self.db.exec(query)).one()
        return int(connections or 0), int(needs_action or 0)

    async def _asset_liability_totals(
        self, *, owner_user_id: int | None = None
    ) -> tuple[int, int]:
        """Live (assets, liabilities) totals summed across visible accounts."""
        assets, liabilities, _ = await self._account_rollup(owner_user_id=owner_user_id)
        return assets, liabilities

    async def get_net_worth(
        self, *, owner_user_id: int | None = None, currency: str = _DEFAULT_CURRENCY
    ) -> NetWorthResponse:
        assets, liabilities = await self._asset_liability_totals(
            owner_user_id=owner_user_id
        )
        return NetWorthResponse(
            net_worth_amount=assets - liabilities,
            total_assets_amount=assets,
            total_liabilities_amount=liabilities,
            currency=currency,
        )

    async def get_status_summary(
        self, *, owner_user_id: int | None = None, currency: str = _DEFAULT_CURRENCY
    ) -> FinanceStatusSummary:
        """Headline numbers for the dashboard card, health check, and CLI."""
        assets, liabilities, account_count = await self._account_rollup(
            owner_user_id=owner_user_id
        )
        connection_count, _ = await self._connection_rollup(owner_user_id=owner_user_id)
        new_insight_count = await self.count_new_insights(owner_user_id=owner_user_id)
        return FinanceStatusSummary(
            net_worth_amount=assets - liabilities,
            total_assets_amount=assets,
            total_liabilities_amount=liabilities,
            account_count=account_count,
            connection_count=connection_count,
            new_insight_count=new_insight_count,
            analyst_enabled=analyst_available(),
            currency=currency,
        )

    async def health(self, *, owner_user_id: int | None = None) -> FinanceHealth:
        """Liveness summary: account/connection counts + worst connection state.

        Backs ``GET /api/v1/finance/health``. ``status`` is ``"ok"`` unless a
        connection needs the user's attention (re-auth, consent expired, ...).
        """
        _, _, accounts = await self._account_rollup(owner_user_id=owner_user_id)
        connections, needs_action = await self._connection_rollup(
            owner_user_id=owner_user_id
        )
        return FinanceHealth(
            status="ok" if needs_action == 0 else "attention",
            accounts=accounts,
            connections=connections,
            connections_needing_action=needs_action,
        )

    # ------------------------------------------------------------------ #
    # Account edits (FIN-12)
    # ------------------------------------------------------------------ #
    async def update_account(
        self,
        account_id: int,
        *,
        owner_user_id: int | None = None,
        name: str | None = None,
        is_hidden: bool | None = None,
        is_closed: bool | None = None,
    ) -> FinanceAccount | None:
        """Rename / hide / close an account. Returns None if not found/owned."""
        account = await self.get_account(account_id, owner_user_id=owner_user_id)
        if account is None:
            return None
        if name is not None:
            account.name = name
        if is_hidden is not None:
            account.is_hidden = is_hidden
        if is_closed is not None:
            account.is_closed = is_closed
        account.updated_at = _utcnow()
        self.db.add(account)
        await self.db.flush()
        return account

    async def soft_delete_account(
        self, account_id: int, *, owner_user_id: int | None = None
    ) -> bool:
        """Soft-delete (set ``deleted_at``); never hard-delete. False if absent."""
        account = await self.get_account(account_id, owner_user_id=owner_user_id)
        if account is None:
            return False
        account.deleted_at = _utcnow()
        self.db.add(account)
        await self.db.flush()
        return True

    # ------------------------------------------------------------------ #
    # Valuations (dated value marks; current_balance tracks the latest)
    # ------------------------------------------------------------------ #
    async def upsert_valuation(
        self,
        *,
        account_id: int,
        as_of_date: date,
        value: int,
        owner_user_id: int | None = None,
        source: str = "manual",
        source_ref: str | None = None,
        note: str | None = None,
    ) -> FinanceValuation:
        """Insert or update the (account, date, source) valuation, then set the
        account's ``current_balance`` to the latest-dated valuation.

        Idempotent on ``uq_finance_valuation (account_id, as_of_date, source)``:
        a repeat write updates in place rather than duplicating.
        """
        existing = (
            await self.db.exec(
                select(FinanceValuation).where(
                    FinanceValuation.account_id == account_id,
                    FinanceValuation.as_of_date == as_of_date,
                    FinanceValuation.source == source,
                )
            )
        ).first()
        if existing is not None:
            existing.value = value
            existing.source_ref = source_ref
            existing.note = note
            existing.updated_at = _utcnow()
            valuation = existing
        else:
            valuation = FinanceValuation(
                owner_user_id=owner_user_id,
                account_id=account_id,
                as_of_date=as_of_date,
                value=value,
                source=source,
                source_ref=source_ref,
                note=note,
            )
        self.db.add(valuation)
        await self.db.flush()

        # current_balance for a manual asset = its latest-dated valuation.
        latest_value = (
            await self.db.exec(
                select(FinanceValuation.value)
                .where(FinanceValuation.account_id == account_id)
                .order_by(FinanceValuation.as_of_date.desc())
                .limit(1)
            )
        ).first()
        account = await self.get_account(account_id, owner_user_id=owner_user_id)
        if account is not None and latest_value is not None:
            account.current_balance = int(latest_value)
            account.balance_as_of = _utcnow()
            self.db.add(account)
            await self.db.flush()
        return valuation

    # -- Goals ----------------------------------------------------------------
    #
    # . A goal is an account wearing goal metadata -
    # no goal tables. Virtual goals are hidden manual accounts whose
    # assigned-so-far rides valuations; linked goals are real visible
    # accounts flagged via metadata, whose contributions are their own
    # transfers. The metadata shape lives in ``goals.py`` - these methods
    # are its only writers.

    async def list_goals(
        self, *, owner_user_id: int | None = None
    ) -> list[FinanceAccount]:
        """Every account wearing goal metadata - virtual (hidden) and
        linked alike. Filtered in Python: the goal keys live in JSON the
        SQL layer never reads, and the account population is tens, not
        thousands."""
        query = select(FinanceAccount).where(FinanceAccount.deleted_at.is_(None))
        if owner_user_id is not None:
            query = query.where(FinanceAccount.owner_user_id == owner_user_id)
        accounts = (await self.db.exec(query.order_by(FinanceAccount.id))).all()
        return [a for a in accounts if goal_metadata(a.metadata_) is not None]

    async def goal_allocations(
        self, *, owner_user_id: int | None, today: date
    ) -> dict[int, int]:
        """This month's evaluated ask per goal account id - the engine run
        once over the whole goal set, against the same income/committed
        figures the budget header shows."""
        goal_accounts = await self.list_goals(owner_user_id=owner_user_id)
        if not goal_accounts:
            return {}
        from app.services.finance.categorize import commitment_rollup

        streams = await self.list_recurring(owner_user_id=owner_user_id)
        income_total, _count = _monthly_income(streams)
        rollup = commitment_rollup(streams, today=today)
        budget = await self.get_or_create_budget(
            owner_user_id=owner_user_id, period_month=_current_period_month()
        )
        allocated = sum(
            line.allocated_amount
            for line in (
                await self.db.exec(
                    select(FinanceBudgetCategory).where(
                        FinanceBudgetCategory.budget_id == budget.id,
                        FinanceBudgetCategory.period_month == _current_period_month(),
                    )
                )
            ).all()
        )
        figures = MonthlyFigures(
            income_total=income_total,
            committed=rollup["monthly_total"] + allocated,
        )
        rows = [
            (str(account.id), meta, account.current_balance or 0)
            for account in goal_accounts
            if (meta := goal_metadata(account.metadata_)) is not None
        ]
        return {
            int(key): ask
            for key, ask in allocate_month(figures, rows, today=today).items()
        }

    async def goal_rate(self, account: FinanceAccount, *, today: date) -> int | None:
        """Cents/month the goal is actually growing at: the declared rate
        when one is set, else the trailing observed rate from the
        account's own balance-snapshot history (>=14 days of it within the
        last 120), else ``None`` - which renders as "never"."""
        meta = goal_metadata(account.metadata_)
        if meta is not None and meta.monthly_contribution:
            return meta.monthly_contribution
        window_start = today - timedelta(days=120)
        snapshots = (
            await self.db.exec(
                select(FinanceBalanceSnapshot)
                .where(
                    FinanceBalanceSnapshot.account_id == account.id,
                    FinanceBalanceSnapshot.balance_date >= window_start,
                )
                .order_by(FinanceBalanceSnapshot.balance_date)
            )
        ).all()
        if len(snapshots) < 2:
            return None
        first, last = snapshots[0], snapshots[-1]
        days = (last.balance_date - first.balance_date).days
        if days < 14:
            return None
        rate = round((last.balance - first.balance) * 30 / days)
        return rate if rate > 0 else None

    async def create_virtual_goal(
        self,
        *,
        owner_user_id: int | None,
        name: str,
        target_amount: int,
        target_date: date | None = None,
        monthly_contribution: int | None = None,
        contribution_kind: str = "fixed",
        contribution_bps: int | None = None,
        priority: int = DEFAULT_PRIORITY,
    ) -> FinanceAccount:
        """A virtual goal: hidden manual account (its money already sits in
        a cash account, so it must not count twice in net worth)."""
        account = await self.create_manual_account(
            owner_user_id=owner_user_id,
            name=name,
            account_type=GOAL_ACCOUNT_TYPE,
            classification="asset",
        )
        account.is_hidden = True
        account.metadata_ = set_goal_metadata(
            account.metadata_,
            target_amount=target_amount,
            target_date=target_date,
            monthly_contribution=monthly_contribution,
            contribution_kind=contribution_kind,
            contribution_bps=contribution_bps,
            priority=priority,
        )
        self.db.add(account)
        await self.db.flush()
        return account

    async def flag_account_as_goal(
        self,
        account_id: int,
        *,
        owner_user_id: int | None,
        target_amount: int,
        target_date: date | None = None,
        monthly_contribution: int | None = None,
        contribution_kind: str = "fixed",
        contribution_bps: int | None = None,
        priority: int = DEFAULT_PRIORITY,
    ) -> FinanceAccount | None:
        """A linked goal: an existing real account starts wearing goal
        metadata. It stays visible and keeps counting in net worth - the
        money is really there."""
        account = await self.get_account(account_id, owner_user_id=owner_user_id)
        if account is None:
            return None
        account.metadata_ = set_goal_metadata(
            account.metadata_,
            target_amount=target_amount,
            target_date=target_date,
            monthly_contribution=monthly_contribution,
            contribution_kind=contribution_kind,
            contribution_bps=contribution_bps,
            priority=priority,
        )
        self.db.add(account)
        await self.db.flush()
        return account

    async def unflag_goal(
        self, account_id: int, *, owner_user_id: int | None
    ) -> FinanceAccount | None:
        """Strip the goal keys; everything else about the account survives."""
        account = await self.get_account(account_id, owner_user_id=owner_user_id)
        if account is None:
            return None
        account.metadata_ = clear_goal_metadata(account.metadata_)
        self.db.add(account)
        await self.db.flush()
        return account

    async def contribute_to_goal(
        self,
        account_id: int,
        *,
        amount: int,
        owner_user_id: int | None,
        when: date | None = None,
    ) -> FinanceAccount:
        """Assign money to a VIRTUAL goal: a valuation at balance+amount
        (idempotent per date via upsert; ``upsert_valuation`` maintains
        ``current_balance``). Refused for linked goals - their
        contributions are their real transfers, and a manual top-up would
        double-count against the account's own register.
        """
        account = await self.get_account(account_id, owner_user_id=owner_user_id)
        if account is None:
            raise ValueError(f"No account {account_id}.")
        if account.account_type != GOAL_ACCOUNT_TYPE:
            raise ValueError(
                "Linked goals book contributions from their own transfers; "
                "manual contributions are for virtual goals only."
            )
        await self.upsert_valuation(
            account_id=account_id,
            as_of_date=when or _utcnow().date(),
            value=(account.current_balance or 0) + amount,
            owner_user_id=owner_user_id,
            note="Goal contribution",
        )
        refreshed = await self.get_account(account_id, owner_user_id=owner_user_id)
        assert refreshed is not None  # just written
        return refreshed

    async def set_goal_status(
        self, account_id: int, status: str, *, owner_user_id: int | None
    ) -> FinanceAccount | None:
        """active | paused | reached - validated by the metadata contract."""
        account = await self.get_account(account_id, owner_user_id=owner_user_id)
        if account is None:
            return None
        meta = goal_metadata(account.metadata_)
        if meta is None:
            raise ValueError(f"Account {account_id} is not a goal.")
        account.metadata_ = set_goal_metadata(
            account.metadata_,
            target_amount=meta.target_amount,
            target_date=meta.target_date,
            monthly_contribution=meta.monthly_contribution,
            status=status,
            contribution_kind=meta.contribution_kind,
            contribution_bps=meta.contribution_bps,
            priority=meta.priority,
        )
        self.db.add(account)
        await self.db.flush()
        return account

    async def set_goal_auto_contribute(
        self, account_id: int, enabled: bool, *, owner_user_id: int | None
    ) -> FinanceAccount | None:
        """Toggle 's monthly auto-booking for one goal."""
        account = await self.get_account(account_id, owner_user_id=owner_user_id)
        if account is None:
            return None
        if goal_metadata(account.metadata_) is None:
            raise ValueError(f"Account {account_id} is not a goal.")
        account.metadata_ = set_auto_contribute(account.metadata_, enabled)
        self.db.add(account)
        await self.db.flush()
        return account

    async def auto_contribute_goals(
        self, *, owner_user_id: int | None, today: date
    ) -> int:
        """'s monthly booking: each toggled-on, ACTIVE, VIRTUAL goal
        gets its declared amount as a ``goal_auto`` valuation dated the
        1st. Returns how many booked. Idempotent per month: the distinct
        source makes "already booked" a precise existence check, not a
        note-string match. Linked goals never book - reality does.
        """
        first = date(today.year, today.month, 1)
        allocations = await self.goal_allocations(
            owner_user_id=owner_user_id, today=today
        )
        booked = 0
        for account in await self.list_goals(owner_user_id=owner_user_id):
            meta = goal_metadata(account.metadata_)
            if (
                meta is None
                or meta.status != "active"
                or account.account_type != GOAL_ACCOUNT_TYPE
                or not goal_auto_contribute(account.metadata_)
            ):
                continue
            amount = allocations.get(account.id, 0)
            if amount <= 0:
                continue
            already = (
                await self.db.exec(
                    select(FinanceValuation.id).where(
                        FinanceValuation.account_id == account.id,
                        FinanceValuation.as_of_date == first,
                        FinanceValuation.source == "goal_auto",
                    )
                )
            ).first()
            if already is not None:
                continue
            await self.upsert_valuation(
                account_id=account.id,
                as_of_date=first,
                value=(account.current_balance or 0) + amount,
                owner_user_id=owner_user_id,
                source="goal_auto",
                note="Goal auto-contribution",
            )
            booked += 1
        return booked

    # -- Envelopes ------------------------------------------------------
    #
    # Virtual sub-accounts: a running balance inside real cash (an
    # allowance, a repairs pot). Hidden manual accounts whose balance and
    # dated history ride valuations - the goals design minus the target,
    # plus a spend-down verb. Balances may go negative (borrowing against
    # next month reads red; it is a fact, not an error).

    async def create_envelope(
        self,
        *,
        owner_user_id: int | None,
        name: str,
        monthly_credit: int | None = None,
        cadence: str = "monthly",
        starting_balance: int = 0,
    ) -> FinanceAccount:
        account = await self.create_manual_account(
            owner_user_id=owner_user_id,
            name=name,
            account_type=ENVELOPE_ACCOUNT_TYPE,
            classification="asset",
        )
        account.is_hidden = True
        account.metadata_ = set_envelope_metadata(
            account.metadata_, monthly_credit=monthly_credit, cadence=cadence
        )
        self.db.add(account)
        await self.db.flush()
        if starting_balance > 0:
            return await self.credit_envelope(
                account.id,
                amount=starting_balance,
                owner_user_id=owner_user_id,
                note="Starting balance",
            )
        return account

    async def list_envelopes(
        self, *, owner_user_id: int | None = None
    ) -> list[FinanceAccount]:
        query = select(FinanceAccount).where(
            FinanceAccount.deleted_at.is_(None),
            FinanceAccount.account_type == ENVELOPE_ACCOUNT_TYPE,
        )
        if owner_user_id is not None:
            query = query.where(FinanceAccount.owner_user_id == owner_user_id)
        return list((await self.db.exec(query.order_by(FinanceAccount.id))).all())

    async def _walk_envelope(
        self,
        account_id: int,
        *,
        delta: int,
        owner_user_id: int | None,
        when: date | None,
        note: str | None,
        source: str = "manual",
    ) -> FinanceAccount:
        account = await self.get_account(account_id, owner_user_id=owner_user_id)
        if account is None or envelope_metadata(account.metadata_) is None:
            raise ValueError(f"No envelope {account_id}.")
        await self.upsert_valuation(
            account_id=account_id,
            as_of_date=when or _utcnow().date(),
            value=(account.current_balance or 0) + delta,
            owner_user_id=owner_user_id,
            source=source,
            note=note,
        )
        refreshed = await self.get_account(account_id, owner_user_id=owner_user_id)
        assert refreshed is not None  # just written
        return refreshed

    async def credit_envelope(
        self,
        account_id: int,
        *,
        amount: int,
        owner_user_id: int | None,
        when: date | None = None,
        note: str | None = None,
    ) -> FinanceAccount:
        if amount <= 0:
            raise ValueError("Credit a positive amount.")
        return await self._walk_envelope(
            account_id,
            delta=amount,
            owner_user_id=owner_user_id,
            when=when,
            note=note or "Credit",
        )

    async def spend_from_envelope(
        self,
        account_id: int,
        *,
        amount: int,
        owner_user_id: int | None,
        when: date | None = None,
        note: str | None = None,
    ) -> FinanceAccount:
        if amount <= 0:
            raise ValueError("Spend a positive amount.")
        return await self._walk_envelope(
            account_id,
            delta=-amount,
            owner_user_id=owner_user_id,
            when=when,
            note=note or "Spent",
        )

    async def set_envelope_auto_credit(
        self, account_id: int, enabled: bool, *, owner_user_id: int | None
    ) -> FinanceAccount | None:
        account = await self.get_account(account_id, owner_user_id=owner_user_id)
        if account is None:
            return None
        meta = envelope_metadata(account.metadata_)
        if meta is None:
            raise ValueError(f"Account {account_id} is not an envelope.")
        account.metadata_ = set_envelope_metadata(
            account.metadata_,
            monthly_credit=meta.monthly_credit,
            auto_credit=enabled,
            cadence=meta.cadence,
        )
        self.db.add(account)
        await self.db.flush()
        return account

    async def update_envelope(
        self,
        account_id: int,
        *,
        owner_user_id: int | None,
        monthly_credit: int | None,
        auto_credit: bool,
        cadence: str = "monthly",
    ) -> FinanceAccount | None:
        account = await self.get_account(account_id, owner_user_id=owner_user_id)
        if account is None or envelope_metadata(account.metadata_) is None:
            return None
        account.metadata_ = set_envelope_metadata(
            account.metadata_,
            monthly_credit=monthly_credit,
            auto_credit=auto_credit,
            cadence=cadence,
        )
        self.db.add(account)
        await self.db.flush()
        return account

    async def auto_credit_envelopes(
        self, *, owner_user_id: int | None, today: date
    ) -> int:
        """The 1st-of-month booking: each auto-credit-on envelope's
        monthly credit as an ``envelope_auto`` valuation. Idempotent per
        month via the distinct source - catch-up safe."""
        booked = 0
        for account in await self.list_envelopes(owner_user_id=owner_user_id):
            meta = envelope_metadata(account.metadata_)
            if meta is None or not meta.auto_credit or not meta.monthly_credit:
                continue
            # The period's booking date IS the idempotency key: the 1st
            # for monthly, this week's Monday for weekly.
            if meta.cadence == "weekly":
                period_start = today - timedelta(days=today.weekday())
            else:
                period_start = date(today.year, today.month, 1)
            already = (
                await self.db.exec(
                    select(FinanceValuation.id).where(
                        FinanceValuation.account_id == account.id,
                        FinanceValuation.as_of_date == period_start,
                        FinanceValuation.source == "envelope_auto",
                    )
                )
            ).first()
            if already is not None:
                continue
            await self.upsert_valuation(
                account_id=account.id,
                as_of_date=period_start,
                value=(account.current_balance or 0) + meta.monthly_credit,
                owner_user_id=owner_user_id,
                source="envelope_auto",
                note="Weekly credit" if meta.cadence == "weekly" else "Monthly credit",
            )
            booked += 1
        return booked

    # -- Reconciliation -------------------------------------------------------
    #
    # FIN-37. Reconciliation lives in BALANCE-space, never spend-space: the
    # correction is either a transfer-flagged adjustment transaction (every
    # analytics consumer - spending summary, cashflow, detection, insight
    # rules, budget math - already excludes ``is_transfer``, while balance
    # walks include it) or, for an account with no register at all, a plain
    # valuation. ``external_id_source='reconcile'`` is the discriminator the
    # import pipeline uses to keep LANE-3 edit-matching away from
    # adjustments; ``external_id`` carries the statement date, which makes
    # re-reconciling a date REPLACE its adjustment instead of stacking.

    async def _register_balance_as_of(self, account_id: int, as_of: date) -> int:
        """Signed sum of the account's posted register through ``as_of``."""
        total = (
            await self.db.exec(
                select(func.coalesce(func.sum(FinanceTransaction.amount), 0)).where(
                    FinanceTransaction.account_id == account_id,
                    FinanceTransaction.deleted_at.is_(None),
                    FinanceTransaction.status == "posted",
                    FinanceTransaction.date_ <= as_of,
                )
            )
        ).one()
        return int(total or 0)

    async def _reconcile_adjustment_for(
        self, account_id: int, statement_date: date
    ) -> FinanceTransaction | None:
        return (
            await self.db.exec(
                select(FinanceTransaction).where(
                    FinanceTransaction.account_id == account_id,
                    FinanceTransaction.external_id_source == RECONCILE_MARKER,
                    FinanceTransaction.date_ == statement_date,
                    FinanceTransaction.deleted_at.is_(None),
                )
            )
        ).first()

    async def reconcile_preview(
        self,
        account_id: int,
        *,
        owner_user_id: int | None = None,
        statement_date: date,
        statement_balance: int,
    ) -> dict[str, Any] | None:
        """What reconciling WOULD do: the register-vs-statement delta.

        The register figure excludes any prior adjustment for this same
        statement date - re-reconciling replaces it, so the delta must be
        measured as if it were not there.
        """
        account = await self.get_account(account_id, owner_user_id=owner_user_id)
        if account is None:
            return None
        has_register = (
            await self.db.exec(
                select(FinanceTransaction.id)
                .where(
                    FinanceTransaction.account_id == account_id,
                    FinanceTransaction.deleted_at.is_(None),
                    # NULL-safe: ordinary rows carry a NULL source, and
                    # ``NULL != 'reconcile'`` is not true in SQL.
                    func.coalesce(FinanceTransaction.external_id_source, "")
                    != RECONCILE_MARKER,
                )
                .limit(1)
            )
        ).first() is not None
        register = await self._register_balance_as_of(account_id, statement_date)
        existing = await self._reconcile_adjustment_for(account_id, statement_date)
        if existing is not None:
            register -= existing.amount
        return {
            "account_id": account_id,
            "route": "adjustment" if has_register else "valuation",
            "statement_date": statement_date,
            "statement_balance": statement_balance,
            "register_balance": register,
            "delta": statement_balance - register,
            "adjustment_transaction_id": existing.id if existing else None,
            "applied": False,
        }

    async def reconcile_account(
        self,
        account_id: int,
        *,
        owner_user_id: int | None = None,
        statement_date: date,
        statement_balance: int,
    ) -> dict[str, Any] | None:
        """Reconcile the account to a statement. Idempotent per date.

        Adjustment route: one transfer-flagged transaction dated the
        statement day absorbs the delta (replaced on re-reconcile; removed
        when the delta reaches zero). Valuation route (no register): the
        statement balance is posted as a valuation. Either way the
        account's waterline (``metadata.reconciled_through``) and headline
        balance move, and net-worth snapshots recompute from the statement
        date FORWARD - history before it is untouched.
        """
        preview = await self.reconcile_preview(
            account_id,
            owner_user_id=owner_user_id,
            statement_date=statement_date,
            statement_balance=statement_balance,
        )
        if preview is None:
            return None
        account = await self.get_account(account_id, owner_user_id=owner_user_id)
        delta = preview["delta"]
        result = dict(preview)
        result["applied"] = True

        if preview["route"] == "valuation":
            await self.upsert_valuation(
                account_id=account_id,
                as_of_date=statement_date,
                value=statement_balance,
                owner_user_id=owner_user_id,
                note="Reconciled to statement",
            )
            result["adjustment_transaction_id"] = None
        else:
            existing = await self._reconcile_adjustment_for(account_id, statement_date)
            audit = (
                f"Reconciled to statement: {statement_balance / 100:,.2f} "
                f"(register showed {preview['register_balance'] / 100:,.2f})"
            )
            if delta == 0:
                if existing is not None:
                    await self.db.delete(existing)
                    await self.db.flush()
                result["adjustment_transaction_id"] = None
            elif existing is not None:
                existing.amount = delta
                existing.memo = audit
                existing.updated_at = _utcnow()
                self.db.add(existing)
                await self.db.flush()
                result["adjustment_transaction_id"] = existing.id
            else:
                txn = await self.create_transaction(
                    account_id=account_id,
                    amount=delta,
                    txn_date=statement_date,
                    owner_user_id=owner_user_id,
                    name="Balance adjustment",
                    external_id=f"reconcile:{statement_date.isoformat()}",
                    external_id_source=RECONCILE_MARKER,
                    memo=audit,
                )
                # Balance-space, not spend-space: every analytics consumer
                # filters transfers out; the balance walks keep them.
                txn.is_transfer = True
                self.db.add(txn)
                await self.db.flush()
                result["adjustment_transaction_id"] = txn.id
            # The statement is the freshest balance fact we hold unless a
            # later one is already stamped.
            if account.balance_as_of is None or (
                statement_date >= account.balance_as_of.date()
            ):
                account.current_balance = statement_balance
                account.balance_as_of = datetime(
                    statement_date.year, statement_date.month, statement_date.day
                )

        account.metadata_ = {
            **(account.metadata_ or {}),
            "reconciled_through": statement_date.isoformat(),
        }
        self.db.add(account)
        await self.db.flush()
        result["reconciled_through"] = statement_date

        from app.services.finance import networth_service

        await networth_service.recompute_snapshots(
            self.db, owner_user_id=owner_user_id, start_date=statement_date
        )
        return result

    async def list_valuations(
        self, account_id: int, *, owner_user_id: int | None = None
    ) -> list[FinanceValuation]:
        """Valuation series for an account, oldest first. Empty if not owned."""
        account = await self.get_account(account_id, owner_user_id=owner_user_id)
        if account is None:
            return []
        query = (
            select(FinanceValuation)
            .where(FinanceValuation.account_id == account_id)
            .order_by(FinanceValuation.as_of_date)
        )
        return list((await self.db.exec(query)).all())

    # ------------------------------------------------------------------ #
    # Import batches (review / audit; the ingest lives in import_service)
    # ------------------------------------------------------------------ #
    async def get_import_batch(
        self, batch_id: int, *, owner_user_id: int | None = None
    ) -> FinanceImportBatch | None:
        # finance_import_batch.owner_user_id is NOT NULL; standalone uses 0.
        batch_owner = 0 if owner_user_id is None else owner_user_id
        return (
            await self.db.exec(
                select(FinanceImportBatch).where(
                    FinanceImportBatch.id == batch_id,
                    FinanceImportBatch.owner_user_id == batch_owner,
                )
            )
        ).first()

    async def list_import_batches(
        self,
        *,
        owner_user_id: int | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> list[FinanceImportBatch]:
        batch_owner = 0 if owner_user_id is None else owner_user_id
        query = (
            select(FinanceImportBatch)
            .where(FinanceImportBatch.owner_user_id == batch_owner)
            .order_by(FinanceImportBatch.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list((await self.db.exec(query)).all())

    async def list_import_batch_rows(
        self, batch_id: int
    ) -> list[FinanceImportBatchRow]:
        query = (
            select(FinanceImportBatchRow)
            .where(FinanceImportBatchRow.import_batch_id == batch_id)
            .order_by(FinanceImportBatchRow.row_number)
        )
        return list((await self.db.exec(query)).all())

    # ------------------------------------------------------------------ #
    # Investments (manual securities + holdings)
    # ------------------------------------------------------------------ #
    async def get_or_create_security(
        self,
        *,
        ticker: str,
        name: str | None = None,
        security_type: str | None = None,
        currency: str = _DEFAULT_CURRENCY,
    ) -> FinanceSecurity:
        """Fetch a security by ticker (case-insensitive), else create it.

        Securities are global/un-owned — the catalog is shared across accounts.
        """
        normalized = ticker.strip().upper()
        existing = (
            await self.db.exec(
                select(FinanceSecurity).where(FinanceSecurity.ticker == normalized)
            )
        ).first()
        if existing is not None:
            return existing
        await self.get_or_create_currency(currency)  # security.currency FK
        security = FinanceSecurity(
            ticker=normalized,
            name=name or normalized,
            security_type=security_type,
            currency=currency,
            provider="manual",
        )
        self.db.add(security)
        await self.db.flush()
        return security

    async def upsert_provider_security(
        self,
        *,
        provider: str,
        provider_security_id: str,
        ticker: str | None = None,
        name: str | None = None,
        security_type: str | None = None,
        cusip: str | None = None,
        isin: str | None = None,
        figi: str | None = None,
        currency: str = _DEFAULT_CURRENCY,
        close_price: int | None = None,
        price_scale: int = 2,
    ) -> FinanceSecurity:
        """Resolve a provider-reported security to ONE catalog row and update it.

        Resolution order: ``(provider, provider_security_id)`` — the
        same-provider fast path — then FIGI, then CUSIP, then ISIN. The
        standard identifiers are the cross-provider merge keys (each is
        partial-unique on the table), so the same instrument reported by two
        aggregators lands on one row instead of two.

        A row matched through an identifier keeps its original
        ``provider``/``provider_security_id`` (first cataloger wins) and its
        descriptive fields are only filled where missing; the matching
        provider still finds the row again next sync via the identifier.
        Identifier columns themselves are fill-if-missing, never overwritten:
        a provider that stops sending (or disagrees about) a FIGI can neither
        null out the key nor collide with another row's.
        """
        await self.get_or_create_currency(currency)
        security = (
            await self.db.exec(
                select(FinanceSecurity).where(
                    FinanceSecurity.provider == provider,
                    FinanceSecurity.provider_security_id == provider_security_id,
                )
            )
        ).first()
        owns_row = security is not None
        if security is None:
            for column, value in (
                (FinanceSecurity.figi, figi),
                (FinanceSecurity.cusip, cusip),
                (FinanceSecurity.isin, isin),
            ):
                if not value:
                    continue
                security = (
                    await self.db.exec(select(FinanceSecurity).where(column == value))
                ).first()
                if security is not None:
                    break
        if security is None:
            security = FinanceSecurity(
                provider=provider, provider_security_id=provider_security_id
            )
            owns_row = True
        if owns_row:
            # Update only what the payload actually carries: partial payloads
            # (e.g. an activities row with no pricing) must not erase catalog
            # data a fuller sync already stored.
            if ticker is not None:
                security.ticker = ticker
            if name is not None:
                security.name = name
            if security_type is not None:
                security.security_type = security_type
            security.currency = currency
            if close_price is not None:
                security.close_price = close_price
                security.price_scale = price_scale
        else:
            security.ticker = security.ticker or ticker
            security.name = security.name or name
            security.security_type = security.security_type or security_type
            if close_price is not None:
                security.close_price = close_price
                security.price_scale = price_scale
        security.cusip = security.cusip or cusip
        security.isin = security.isin or isin
        security.figi = security.figi or figi
        self.db.add(security)
        await self.db.flush()
        return security

    async def upsert_security_price(
        self,
        *,
        security_id: int,
        price_date: date,
        close_price: int,
        price_scale: int = 2,
        currency: str = _DEFAULT_CURRENCY,
        source: str = "manual",
    ) -> FinanceSecurityPrice:
        """Insert/update the (security, date, source) price point."""
        existing = (
            await self.db.exec(
                select(FinanceSecurityPrice).where(
                    FinanceSecurityPrice.security_id == security_id,
                    FinanceSecurityPrice.price_date == price_date,
                    FinanceSecurityPrice.source == source,
                )
            )
        ).first()
        if existing is not None:
            existing.close_price = close_price
            existing.price_scale = price_scale
            existing.currency = currency
            self.db.add(existing)
            await self.db.flush()
            return existing
        await self.get_or_create_currency(currency)  # price.currency FK
        price = FinanceSecurityPrice(
            security_id=security_id,
            price_date=price_date,
            close_price=close_price,
            price_scale=price_scale,
            currency=currency,
            source=source,
        )
        self.db.add(price)
        await self.db.flush()
        return price

    async def upsert_holding(
        self,
        *,
        owner_user_id: int | None,
        account_id: int,
        security_id: int,
        as_of_date: date,
        quantity_e8: int,
        price: int | None = None,
        price_scale: int = 2,
        cost_basis: int | None = None,
        average_cost: int | None = None,
        currency: str = _DEFAULT_CURRENCY,
        source: str = "manual",
        sync_account_balance: bool = True,
    ) -> FinanceHolding:
        """Insert/update the (account, security, as_of_date) position snapshot.

        ``owner_user_id`` is NOT NULL on holdings, so standalone (no-auth) rows
        use the ``0`` sentinel — the same convention as import batches.

        ``sync_account_balance`` sets the account's ``current_balance`` to its
        holdings value (right for manual entry). Pass ``False`` when a provider
        already supplies an authoritative account balance (e.g. Plaid).
        """
        holding_owner = 0 if owner_user_id is None else owner_user_id
        existing = (
            await self.db.exec(
                select(FinanceHolding).where(
                    FinanceHolding.account_id == account_id,
                    FinanceHolding.security_id == security_id,
                    FinanceHolding.as_of_date == as_of_date,
                )
            )
        ).first()
        if existing is not None:
            existing.quantity_e8 = quantity_e8
            existing.price = price
            existing.price_scale = price_scale
            existing.cost_basis = cost_basis
            existing.average_cost = average_cost
            existing.currency = currency
            existing.source = source
            existing.deleted_at = None
            self.db.add(existing)
            result = existing
        else:
            await self.get_or_create_currency(currency)  # holding.currency FK
            result = FinanceHolding(
                owner_user_id=holding_owner,
                account_id=account_id,
                security_id=security_id,
                as_of_date=as_of_date,
                quantity_e8=quantity_e8,
                price=price,
                price_scale=price_scale,
                cost_basis=cost_basis,
                average_cost=average_cost,
                currency=currency,
                source=source,
            )
            self.db.add(result)
        await self.db.flush()
        # Reflect the position in net worth: an investment account's balance is
        # its holdings' market value (unless the provider supplies its own).
        if sync_account_balance:
            await self._sync_account_balance_from_holdings(
                account_id, owner_user_id=owner_user_id
            )
        return result

    async def upsert_trade(
        self,
        *,
        owner_user_id: int | None,
        account_id: int,
        trade_type: str,
        trade_date: date,
        amount: int,
        security_id: int | None = None,
        subtype: str | None = None,
        quantity_e8: int | None = None,
        price: int | None = None,
        price_scale: int = 2,
        fees: int | None = None,
        currency: str = _DEFAULT_CURRENCY,
        source: str = Provider.MANUAL,
        external_id: str | None = None,
        external_id_source: str | None = None,
        name: str | None = None,
        connection_id: int | None = None,
        raw_payload: dict[str, Any] | None = None,
    ) -> FinanceTrade:
        """Insert/update one investment trade (buy/sell/dividend/...).

        Provider rows dedup on the external-id lane ``(account, source,
        external_id)``; manual/imported rows without an ``external_id`` always
        insert (the import-hash lane is the importers' job, not this path).
        ``owner_user_id`` is NOT NULL, so standalone (no-auth) rows use the
        ``0`` sentinel — same convention as holdings and import batches.
        """
        trade_owner = 0 if owner_user_id is None else owner_user_id
        existing: FinanceTrade | None = None
        if external_id is not None:
            existing = (
                await self.db.exec(
                    select(FinanceTrade).where(
                        FinanceTrade.account_id == account_id,
                        FinanceTrade.source == source,
                        FinanceTrade.external_id == external_id,
                        FinanceTrade.deleted_at.is_(None),
                    )
                )
            ).first()
        await self.get_or_create_currency(currency)  # trade.currency FK
        if existing is not None:
            existing.security_id = security_id
            existing.type = trade_type
            existing.subtype = subtype
            existing.quantity_e8 = quantity_e8
            existing.price = price
            existing.price_scale = price_scale
            existing.amount = amount
            existing.fees = fees
            existing.currency = currency
            existing.trade_date = trade_date
            existing.name = name
            existing.connection_id = connection_id
            existing.raw_payload = raw_payload
            existing.deleted_at = None
            self.db.add(existing)
            await self.db.flush()
            return existing
        trade = FinanceTrade(
            owner_user_id=trade_owner,
            account_id=account_id,
            security_id=security_id,
            connection_id=connection_id,
            source=source,
            external_id=external_id,
            external_id_source=external_id_source,
            type=trade_type,
            subtype=subtype,
            quantity_e8=quantity_e8,
            price=price,
            price_scale=price_scale,
            amount=amount,
            fees=fees,
            currency=currency,
            trade_date=trade_date,
            name=name,
            raw_payload=raw_payload,
        )
        self.db.add(trade)
        await self.db.flush()
        return trade

    async def list_trades(
        self,
        *,
        owner_user_id: int | None,
        account_id: int | None = None,
        account_ids: list[int] | None = None,
        limit: int = 100,
    ) -> list[FinanceTrade]:
        """Recent trades for an owner (optionally one account), newest first.

        ``account_ids`` is the register's account-picker scope - without
        it the All Accounts view showed every brokerage's trades no matter
        what the picker said.
        """
        trade_owner = 0 if owner_user_id is None else owner_user_id
        query = select(FinanceTrade).where(
            FinanceTrade.owner_user_id == trade_owner,
            FinanceTrade.deleted_at.is_(None),
            # Same live-account guard as list_transactions: a removed
            # account's trades stay stored but leave the feeds.
            FinanceTrade.account_id.in_(
                select(FinanceAccount.id).where(FinanceAccount.deleted_at.is_(None))
            ),
        )
        if account_id is not None:
            query = query.where(FinanceTrade.account_id == account_id)
        if account_ids is not None:
            query = query.where(FinanceTrade.account_id.in_(account_ids))
        query = query.order_by(
            FinanceTrade.trade_date.desc(), FinanceTrade.id.desc()
        ).limit(limit)
        return list((await self.db.exec(query)).all())

    async def _sync_account_balance_from_holdings(
        self, account_id: int, *, owner_user_id: int | None = None
    ) -> None:
        """Set an account's ``current_balance`` to its current holdings value.

        Keeps net worth (which sums ``current_balance``) in step with positions.
        """
        account = await self.get_account(account_id, owner_user_id=owner_user_id)
        if account is None:
            return
        account.current_balance = await self.get_portfolio_value(
            owner_user_id=owner_user_id, account_id=account_id
        )
        account.balance_as_of = _utcnow()
        account.updated_at = _utcnow()
        self.db.add(account)
        await self.db.flush()

    async def list_current_holdings(
        self, *, owner_user_id: int | None = None, account_id: int | None = None
    ) -> list[tuple[FinanceHolding, FinanceSecurity | None, int]]:
        """Current positions: the latest-dated holding per (account, security)
        with a non-zero quantity, each paired with its security and market
        value in cents (holding price, falling back to the security close).
        """
        # Exclude holdings whose account is soft-deleted (e.g. after
        # disconnecting a provider connection) so they don't leak into portfolio
        # totals — the account, not just the holding row, must be live.
        filters = [
            FinanceHolding.deleted_at.is_(None),
            FinanceAccount.deleted_at.is_(None),
        ]
        if owner_user_id is not None:
            filters.append(FinanceHolding.owner_user_id == owner_user_id)
        if account_id is not None:
            filters.append(FinanceHolding.account_id == account_id)
        rows = list(
            (
                await self.db.exec(
                    select(FinanceHolding)
                    .join(
                        FinanceAccount,
                        FinanceAccount.id == FinanceHolding.account_id,
                    )
                    .where(*filters)
                    .order_by(FinanceHolding.as_of_date)
                )
            ).all()
        )
        # Ascending date order -> the last write per (account, security) is the
        # current snapshot.
        latest: dict[tuple[int, int], FinanceHolding] = {}
        for holding in rows:
            latest[(holding.account_id, holding.security_id)] = holding
        current = [h for h in latest.values() if h.quantity_e8 != 0]
        if not current:
            return []
        security_ids = {h.security_id for h in current}
        securities = {
            s.id: s
            for s in (
                await self.db.exec(
                    select(FinanceSecurity).where(FinanceSecurity.id.in_(security_ids))
                )
            ).all()
        }
        result: list[tuple[FinanceHolding, FinanceSecurity | None, int]] = []
        for holding in current:
            security = securities.get(holding.security_id)
            price = holding.price
            if price is None and security is not None:
                price = security.close_price
            value = market_value_cents(holding.quantity_e8, price, holding.price_scale)
            result.append((holding, security, value))
        result.sort(key=lambda item: item[2], reverse=True)
        return result

    async def get_portfolio_value(
        self, *, owner_user_id: int | None = None, account_id: int | None = None
    ) -> int:
        """Total market value (cents) of the current holdings."""
        holdings = await self.list_current_holdings(
            owner_user_id=owner_user_id, account_id=account_id
        )
        return sum(value for _holding, _security, value in holdings)

    # -- Budget ----------------------------------------------------------

    async def get_or_create_budget(
        self, *, owner_user_id: int | None, period_month: int
    ) -> FinanceBudget:
        """The owner's one standing "Monthly" budget - created on first use,
        reused after (one SELECT, one INSERT only the first time ever).

        ``period_month`` only seeds ``start_date`` on that first creation;
        every later month reuses this same row. Each month's actual
        allocations live on ``FinanceBudgetCategory``, keyed by
        ``period_month`` - the budget definition itself doesn't repeat.
        """
        query = select(FinanceBudget).where(
            FinanceBudget.name == "Monthly",
            FinanceBudget.deleted_at.is_(None),
        )
        if owner_user_id is not None:
            query = query.where(FinanceBudget.owner_user_id == owner_user_id)
        existing = (await self.db.exec(query.order_by(FinanceBudget.id))).first()
        if existing is not None:
            return existing
        await self.get_or_create_currency(_DEFAULT_CURRENCY)
        start, _ = _month_bounds(period_month)
        budget = FinanceBudget(
            # NOT NULL column - standalone (no-auth) installs use the same
            # ``0`` owner sentinel ``create_recurring_stream`` already does.
            owner_user_id=0 if owner_user_id is None else owner_user_id,
            name="Monthly",
            period="monthly",
            start_date=start,
        )
        self.db.add(budget)
        await self.db.flush()
        return budget

    async def _spend_for_target(
        self,
        *,
        owner_user_id: int | None,
        period_month: int,
        category_id: int | None,
        payee_key: str | None,
    ) -> int:
        """Positive cents spent this period against one category or payee -
        a single scoped query, for the one-line response an upsert/delete
        needs right away. ``budget_summary`` does the all-lines-at-once
        version of this same fetch; this is deliberately the one-off
        sibling, not a call site of it, so setting a single line never
        pulls the whole period's transaction history."""
        start, end = _month_bounds(period_month)
        live_accounts = select(FinanceAccount.id).where(
            FinanceAccount.deleted_at.is_(None)
        )
        filters = [
            FinanceTransaction.deleted_at.is_(None),
            FinanceTransaction.dedup_status != "duplicate",
            FinanceTransaction.excluded_from_reports.is_(False),
            FinanceTransaction.account_id.in_(live_accounts),
            FinanceTransaction.amount < 0,
            FinanceTransaction.date_ >= start,
            FinanceTransaction.date_ < end,
        ]
        if owner_user_id is not None:
            filters.append(FinanceTransaction.owner_user_id == owner_user_id)
        if category_id is not None:
            filters.append(FinanceTransaction.category_id == category_id)
            total = (
                await self.db.exec(
                    select(func.sum(FinanceTransaction.amount)).where(*filters)
                )
            ).one()
            return int(-(total or 0))
        if payee_key is not None:
            rows = (
                await self.db.exec(
                    select(
                        FinanceTransaction.merchant_name,
                        FinanceTransaction.original_description,
                        FinanceTransaction.name,
                        FinanceTransaction.amount,
                    ).where(*filters)
                )
            ).all()
            return sum(
                -amount
                for merchant_name, original_description, name, amount in rows
                if transaction_payee_key(merchant_name, original_description, name)
                == payee_key
            )
        return 0

    # Auto-budget gates. Deliberately mirror the recurring-detection ones:
    # a mean with no dispersion check invents a pattern, which is how a
    # convenience store became a yearly subscription.
    _BUDGET_LOOKBACK_MONTHS = 6
    # Must actually show up most months - a one-off is not a budget.
    _BUDGET_MIN_MONTHS = 4
    # Steady means AT MOST ONE MONTH OUT OF LINE. A month counts as
    # unusual when it lands outside +/-50% of the median.
    #
    # Two measures were wrong before this. Biggest-over-smallest asks how
    # far apart the two most EXTREME months are, which one outlier
    # destroys: on a real ledger a $300 portfolio contribution identical
    # in five of six months scored 4.3x and was thrown out along with
    # every other steady line, leaving zero suggestions. Median absolute
    # deviation fixes that but overcorrects - it survives one outlier by
    # ignoring outliers, so auto repairs at $36, $40, $2301, $50, $45,
    # $1800 scored a placid 0.20 and would have been budgeted at $47.
    #
    # Counting them asks the question directly, and says out loud what a
    # user can check: how many months did not look like the others.
    _BUDGET_UNUSUAL_BAND = 0.5
    _BUDGET_MAX_UNUSUAL_MONTHS = 1
    # Below this, a line is noise nobody wants to manage.
    _BUDGET_MIN_AMOUNT = 2_000
    # Share of a category's monthly spend that bills must already account
    # for before a budget line on it would be double-counting.
    _BUDGET_BILLED_SHARE = 0.6

    async def suggest_budget_lines(
        self,
        *,
        owner_user_id: int | None = None,
        today: date | None = None,
    ) -> list[dict[str, Any]]:
        """Budget lines your own spending already implies.

        Category level only. A payee sits INSIDE a category (Starbucks
        inside Eating Out), so suggesting both would count the same coffee
        twice - here and again in the forecast.

        Excluded on purpose: transfers (money moving between your own
        accounts, and the three biggest rows by value), categories a
        recurring bill already covers (budgeting the mortgage as well as
        billing it charges the forecast twice), and anything you have
        already set a line for.
        """
        today = today or date.today()
        current = today.year * 12 + today.month - 1
        first = current - self._BUDGET_LOOKBACK_MONTHS

        query = select(FinanceTransaction).where(
            FinanceTransaction.deleted_at.is_(None),
            FinanceTransaction.is_transfer.is_(False),
            FinanceTransaction.amount < 0,
            FinanceTransaction.category_id.is_not(None),
        )
        if owner_user_id is not None:
            query = query.where(FinanceTransaction.owner_user_id == owner_user_id)
        rows = (await self.db.exec(query)).all()

        per_month: dict[int, dict[int, int]] = {}
        for txn in rows:
            index = txn.date_.year * 12 + txn.date_.month - 1
            # Complete months only - the current one is still filling up
            # and would drag every suggestion down.
            if not (first <= index < current):
                continue
            per_month.setdefault(txn.category_id, {}).setdefault(index, 0)
            per_month[txn.category_id][index] += -txn.amount

        # A category is "already billed" if any live stream carries it -
        # or if the category INFERRED from a stream's own transactions
        # matches. Most bills carry no stored category (the column is a
        # provider field the detector never fills), so checking the stored
        # one alone missed nearly every real overlap: a $460 productivity
        # subscription was suggested as a budget line while also being
        # billed, which would charge the forecast twice.
        live_streams = (
            await self.db.exec(
                select(FinanceRecurringStream).where(
                    FinanceRecurringStream.deleted_at.is_(None),
                )
            )
        ).all()
        # How much of each category the bills already account for, per
        # month. Presence is the wrong test: nearly every stream INFERS a
        # category from its transactions, so one detected rhythm holding a
        # single grocery charge would block the whole groceries budget
        # (19 suggestions collapsed to 2 when tried that way). Magnitude
        # is the right test - if bills already cover most of what a
        # category costs, budgeting it too charges the forecast twice; if
        # they cover a sliver, the budget is still the useful number.
        from app.services.finance.categorize.insights import (
            _MONTHLY_FACTOR,
            is_commitment,
            is_paused,
        )

        all_categories = (await self.db.exec(select(FinanceCategory))).all()
        by_name = {c.name: c.id for c in all_categories}
        # A budget line is about money SPENT. Categories carry their own
        # classification, and it is the reliable signal: the
        # transaction-level ``is_transfer`` guard above only catches rows
        # PAIRING flagged, and it misses plenty - with the steadiness gate
        # fixed, the single largest suggestion on a real ledger became
        # "Transfer" at $1,599/month, money moving between the user's own
        # accounts.
        spendable = {c.id for c in all_categories if c.classification == "expense"}
        inferred = await self.stream_category_names([s.id for s in live_streams])
        billed_per_month: dict[int, int] = {}
        # Categories a CONFIRMED bill claims. Presence, not magnitude: the
        # user already said this money is a bill, so no arithmetic gets to
        # re-suggest it - the magnitude test below stays for unconfirmed
        # detector rhythms only (where it is what keeps one grocery-store
        # rhythm from blocking the whole groceries budget).
        confirmed_categories: set[int] = set()
        for stream in live_streams:
            if stream.is_muted or is_paused(stream):
                continue
            confirmed = bool(stream.is_user_confirmed or stream.source == "user")
            category_id = stream.category_id or by_name.get(inferred.get(stream.id, ""))
            if category_id is None and confirmed:
                # A confirmed bill stripped of its members infers nothing
                # from them (FIN-34 made this real: the Mortgage bill sat
                # at 0 members and Mortgage got suggested). The stream's
                # own name through the alias table is the fallback signal.
                category_id = await self.resolve_category_alias(stream.name)
            if category_id is None:
                continue
            if confirmed:
                confirmed_categories.add(category_id)
                continue
            # Only what the FORECAST charges can double-count. Most
            # merchant rhythms fail the commitment gate and project
            # nothing - counting them here blocked groceries with 19
            # shopping streams that never touch the balance.
            if not is_commitment(stream):
                continue
            amount = stream.expected_amount or stream.average_amount or 0
            factor = _MONTHLY_FACTOR.get(stream.frequency, 0)
            billed_per_month[category_id] = billed_per_month.get(category_id, 0) + int(
                amount * factor
            )
        budget = await self.get_or_create_budget(
            owner_user_id=owner_user_id, period_month=_current_period_month()
        )
        already = {
            line.category_id
            for line in (
                await self.db.exec(
                    select(FinanceBudgetCategory).where(
                        FinanceBudgetCategory.budget_id == budget.id,
                        FinanceBudgetCategory.category_id.is_not(None),
                    )
                )
            ).all()
        }
        names = {
            c.id: c.name for c in (await self.db.exec(select(FinanceCategory))).all()
        }

        picks: list[dict[str, Any]] = []
        for category_id, months in per_month.items():
            # ``already`` also carries the DISMISSAL markers (period-less
            # budget-line rows, see dismiss_budget_suggestions) - a
            # declined suggestion is excluded by the same set as a set one.
            if category_id in already:
                continue
            if category_id in confirmed_categories:
                continue
            if category_id not in spendable:
                continue
            # Steady, and passes every numeric gate on real data - but
            # "budget your uncategorized spending" is not something anyone
            # can act on. The fix for that money is to categorize it.
            if (names.get(category_id) or "").strip().lower() in (
                UNCATEGORIZED_CATEGORY_NAMES
            ):
                continue
            spends = [v for v in months.values() if v > 0]
            if len(spends) < self._BUDGET_MIN_MONTHS:
                continue
            # Median, not mean: one repair bill should not set the year.
            amount = int(statistics.median(spends))
            if amount < self._BUDGET_MIN_AMOUNT:
                continue
            low = amount * (1 - self._BUDGET_UNUSUAL_BAND)
            high = amount * (1 + self._BUDGET_UNUSUAL_BAND)
            unusual = sum(1 for v in spends if v < low or v > high)
            if unusual > self._BUDGET_MAX_UNUSUAL_MONTHS:
                continue
            # Bills already cover most of this category - the forecast has
            # counted it once, and a budget line would count it again.
            covered = billed_per_month.get(category_id, 0)
            if covered >= amount * self._BUDGET_BILLED_SHARE:
                continue
            picks.append(
                {
                    "category_id": category_id,
                    "category_name": names.get(category_id),
                    "suggested_amount": amount,
                    "months_seen": len(spends),
                    "unusual_months": unusual,
                }
            )
        picks.sort(key=lambda p: -p["suggested_amount"])
        return picks

    # -- Suggestion dismissals ------------------------------------------------
    #
    # A declined suggestion is stored as a MARKER row on the standing
    # "Monthly" budget: a ``finance_budget_category`` row with the category
    # set and ``period_month`` NULL. Real budget lines always carry a
    # period, and every lines/summary read filters on one, so markers are
    # invisible everywhere except here - and ``suggest_budget_lines``'s
    # ``already`` set (which does NOT filter by period, on purpose) excludes
    # them with no extra query. Standing by construction: the budget row is
    # one per owner across all months, so a dismissal never re-nags on
    # month rollover. No new table, no new column.

    async def _dismissal_markers(
        self, *, owner_user_id: int | None
    ) -> list[FinanceBudgetCategory]:
        budget = await self.get_or_create_budget(
            owner_user_id=owner_user_id, period_month=_current_period_month()
        )
        return list(
            (
                await self.db.exec(
                    select(FinanceBudgetCategory).where(
                        FinanceBudgetCategory.budget_id == budget.id,
                        FinanceBudgetCategory.category_id.is_not(None),
                        FinanceBudgetCategory.period_month.is_(None),
                    )
                )
            ).all()
        )

    async def list_dismissed_suggestions(
        self, *, owner_user_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Declined suggestions, with display names, name-sorted."""
        markers = await self._dismissal_markers(owner_user_id=owner_user_id)
        if not markers:
            return []
        names = {
            c.id: c.name
            for c in (
                await self.db.exec(
                    select(FinanceCategory).where(
                        FinanceCategory.id.in_([m.category_id for m in markers])
                    )
                )
            ).all()
        }
        return sorted(
            (
                {
                    "category_id": m.category_id,
                    "category_name": names.get(m.category_id),
                }
                for m in markers
            ),
            key=lambda d: d["category_name"] or "",
        )

    async def dismiss_budget_suggestions(
        self, *, owner_user_id: int | None = None, category_ids: list[int]
    ) -> int:
        """Decline suggestions for these categories. Idempotent; returns
        how many new dismissals were recorded."""
        budget = await self.get_or_create_budget(
            owner_user_id=owner_user_id, period_month=_current_period_month()
        )
        existing = {
            m.category_id
            for m in await self._dismissal_markers(owner_user_id=owner_user_id)
        }
        added = 0
        for category_id in dict.fromkeys(category_ids):
            if category_id is None or category_id in existing:
                continue
            self.db.add(
                FinanceBudgetCategory(
                    owner_user_id=0 if owner_user_id is None else owner_user_id,
                    budget_id=budget.id,
                    category_id=category_id,
                    period_month=None,
                    allocated_amount=0,
                )
            )
            added += 1
        if added:
            await self.db.flush()
        return added

    async def restore_budget_suggestions(
        self, *, owner_user_id: int | None = None, category_ids: list[int]
    ) -> int:
        """Un-decline suggestions: delete the markers. Returns how many."""
        wanted = {c for c in category_ids if c is not None}
        removed = 0
        for marker in await self._dismissal_markers(owner_user_id=owner_user_id):
            if marker.category_id in wanted:
                await self.db.delete(marker)
                removed += 1
        if removed:
            await self.db.flush()
        return removed

    async def upsert_budget_line(
        self,
        *,
        owner_user_id: int | None,
        period_month: int | None,
        category_id: int | None,
        payee_key: str | None,
        payee_label: str | None,
        allocated_amount: int,
        rollover_enabled: bool = False,
    ) -> dict[str, Any]:
        """Set (create or replace) one budget line for the period. One
        lookup on the matching partial-unique key, one write, plus one
        scoped spend query so the response's status is correct immediately
        (a category with existing spend shouldn't show "good" at 0)."""
        month = period_month or _current_period_month()
        budget = await self.get_or_create_budget(
            owner_user_id=owner_user_id, period_month=month
        )
        filters = [
            FinanceBudgetCategory.budget_id == budget.id,
            FinanceBudgetCategory.period_month == month,
        ]
        if category_id is not None:
            filters.append(FinanceBudgetCategory.category_id == category_id)
        elif payee_key is not None:
            filters.append(FinanceBudgetCategory.payee_key == payee_key)
        else:
            filters.append(FinanceBudgetCategory.category_id.is_(None))
            filters.append(FinanceBudgetCategory.payee_key.is_(None))
        line = (
            await self.db.exec(select(FinanceBudgetCategory).where(*filters))
        ).first()
        if line is None:
            line = FinanceBudgetCategory(
                owner_user_id=0 if owner_user_id is None else owner_user_id,
                budget_id=budget.id,
                category_id=category_id,
                payee_key=payee_key,
                period_month=month,
            )
        line.payee_label = payee_label
        line.allocated_amount = allocated_amount
        line.rollover_enabled = rollover_enabled
        line.updated_at = _utcnow()
        self.db.add(line)
        await self.db.flush()

        category_name = None
        if line.category_id is not None:
            names = await self.category_names({line.category_id})
            category_name = names.get(line.category_id)
        spent = await self._spend_for_target(
            owner_user_id=owner_user_id,
            period_month=month,
            category_id=line.category_id,
            payee_key=line.payee_key,
        )
        return {
            "id": line.id,
            "category_id": line.category_id,
            "category_name": category_name,
            "payee_key": line.payee_key,
            "payee_label": line.payee_label,
            "allocated_amount": line.allocated_amount,
            "spent_amount": spent,
            "status": _budget_line_status(line.allocated_amount, spent),
        }

    async def delete_budget_line(
        self, line_id: int, *, owner_user_id: int | None = None
    ) -> bool:
        filters = [FinanceBudgetCategory.id == line_id]
        if owner_user_id is not None:
            filters.append(FinanceBudgetCategory.owner_user_id == owner_user_id)
        line = (
            await self.db.exec(select(FinanceBudgetCategory).where(*filters))
        ).first()
        if line is None:
            return False
        await self.db.delete(line)
        await self.db.flush()
        return True

    async def budget_summary(
        self,
        *,
        owner_user_id: int | None = None,
        period_month: int | None = None,
        account_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Flexible: explicit limits the owner chose to track (category or
        payee) - the only bucket with a real spend-vs-allocation status.
        Fixed/Non-monthly: recurring commitments shown for CONTEXT only
        (an earlier version gave every detected bill, including the
        mortgage, its own spend-vs-allocation status - wrong, a bill's own
        cost isn't a limit anyone set). These read a variance-vs-last-month
        signal instead and never go "critical".

        Query count does NOT grow with the number of budget lines or
        recurring streams: one fetch of this period's transactions and one
        of last period's (each tallied by category/payee-key/recurring-
        stream in a single Python pass) stand in for what would otherwise
        be a spend lookup per line. Do not "simplify" steps 4/5 below into
        per-line queries - that is exactly the N+1 this was built to avoid.
        """
        from app.services.finance.categorize import commitment_rollup

        month = period_month or _current_period_month()
        start, end = _month_bounds(month)
        prior_start, prior_end = _month_bounds(_prior_period_month(month))

        # 1-2. The budget + its explicit lines for this period.
        budget = await self.get_or_create_budget(
            owner_user_id=owner_user_id, period_month=month
        )
        lines = list(
            (
                await self.db.exec(
                    select(FinanceBudgetCategory).where(
                        FinanceBudgetCategory.budget_id == budget.id,
                        FinanceBudgetCategory.period_month == month,
                    )
                )
            ).all()
        )

        # 3. Category display names, batched.
        names = await self.category_names(
            {line.category_id for line in lines if line.category_id is not None}
        )

        live_accounts = select(FinanceAccount.id).where(
            FinanceAccount.deleted_at.is_(None)
        )

        def outflow_filters(window_start: date, window_end: date) -> list[Any]:
            filters: list[Any] = [
                FinanceTransaction.deleted_at.is_(None),
                FinanceTransaction.dedup_status != "duplicate",
                FinanceTransaction.excluded_from_reports.is_(False),
                FinanceTransaction.account_id.in_(live_accounts),
                FinanceTransaction.amount < 0,
                FinanceTransaction.date_ >= window_start,
                FinanceTransaction.date_ < window_end,
            ]
            if owner_user_id is not None:
                filters.append(FinanceTransaction.owner_user_id == owner_user_id)
            if account_ids is not None:
                filters.append(FinanceTransaction.account_id.in_(account_ids))
            return filters

        # 4. ONE fetch of THIS period's outflows, tallied by category,
        # payee-key, AND recurring-stream in a single Python pass - this
        # is the line that keeps the whole method O(1) queries regardless
        # of how many budget lines or streams exist.
        txn_rows = (
            await self.db.exec(
                select(
                    FinanceTransaction.category_id,
                    FinanceTransaction.merchant_name,
                    FinanceTransaction.original_description,
                    FinanceTransaction.name,
                    FinanceTransaction.amount,
                    FinanceTransaction.recurring_stream_id,
                ).where(*outflow_filters(start, end))
            )
        ).all()
        spent_by_category: dict[int, int] = defaultdict(int)
        spent_by_payee: dict[str, int] = defaultdict(int)
        spent_by_stream: dict[int, int] = defaultdict(int)
        for (
            cat_id,
            merchant_name,
            original_description,
            name,
            amount,
            stream_id,
        ) in txn_rows:
            spend = -amount
            if cat_id is not None:
                spent_by_category[cat_id] += spend
            key = transaction_payee_key(merchant_name, original_description, name)
            if key:
                spent_by_payee[key] += spend
            if stream_id is not None:
                spent_by_stream[stream_id] += spend

        # 5. ONE fetch of LAST period's per-stream spend - the "vs last
        # month" variance signal on Fixed/Non-monthly, a second FIXED
        # query, not one per stream.
        prior_rows = (
            await self.db.exec(
                select(
                    FinanceTransaction.recurring_stream_id, FinanceTransaction.amount
                ).where(*outflow_filters(prior_start, prior_end))
            )
        ).all()
        spent_by_stream_prior: dict[int, int] = defaultdict(int)
        for stream_id, amount in prior_rows:
            if stream_id is not None:
                spent_by_stream_prior[stream_id] += -amount

        # 6. Recurring commitments (existing detection, ~3 fixed queries),
        # reused rather than re-derived - same source /recurring reads.
        streams = await self.list_recurring(owner_user_id=owner_user_id)
        transfer_ids = await self.transfer_stream_ids([s.id for s in streams])
        streams = [s for s in streams if s.id not in transfer_ids]
        if account_ids is not None:
            streams = [s for s in streams if s.account_id in account_ids]
        rollup = commitment_rollup(streams)
        stream_category_names = await self.stream_category_names(
            {s.id for s in rollup["fixed"] + rollup["non_monthly"]}
        )

        def commitment_line(stream: FinanceRecurringStream) -> dict[str, Any]:
            typical = int(stream.average_amount or 0)
            actual = spent_by_stream.get(stream.id, 0)
            status, variance = _commitment_variance_status(
                actual, spent_by_stream_prior.get(stream.id)
            )
            return {
                "id": stream.id,
                "category_id": stream.category_id,
                "category_name": stream_category_names.get(stream.id),
                "payee_key": None,
                "payee_label": None,
                "allocated_amount": typical,
                "spent_amount": actual,
                "status": status,
                "variance_amount": variance,
            }

        def user_line(line: FinanceBudgetCategory) -> dict[str, Any]:
            spent = (
                spent_by_category.get(line.category_id, 0)
                if line.category_id is not None
                else spent_by_payee.get(line.payee_key or "", 0)
            )
            return {
                "id": line.id,
                "category_id": line.category_id,
                "category_name": names.get(line.category_id)
                if line.category_id is not None
                else None,
                "payee_key": line.payee_key,
                "payee_label": line.payee_label,
                "allocated_amount": line.allocated_amount,
                "spent_amount": spent,
                "status": _budget_line_status(line.allocated_amount, spent),
                "variance_amount": None,
            }

        def bucket(name: str, item_lines: list[dict[str, Any]]) -> dict[str, Any]:
            return {
                "name": name,
                "total_allocated": sum(row["allocated_amount"] for row in item_lines),
                "total_spent": sum(row["spent_amount"] for row in item_lines),
                "lines": item_lines,
            }

        fixed_lines = [commitment_line(s) for s in rollup["fixed"]]
        non_monthly_lines = [commitment_line(s) for s in rollup["non_monthly"]]
        flexible_lines = [user_line(line) for line in lines]

        # 7. Stats strip - derived entirely from data already in memory
        # above, no further queries.
        over_budget = [row for row in flexible_lines if row["status"] == "critical"]
        today = date.today()
        days_left = (end - today).days if start <= today < end else 0
        stats = {
            "flexible_spent": sum(row["spent_amount"] for row in flexible_lines),
            "flexible_allocated": sum(
                row["allocated_amount"] for row in flexible_lines
            ),
            "days_left_in_period": max(days_left, 0),
            "flexible_count": len(flexible_lines),
            "on_track_count": len(flexible_lines) - len(over_budget),
            "over_budget_count": len(over_budget),
            "over_budget_labels": [
                row["category_name"] or row["payee_label"] or "Overall"
                for row in over_budget
            ],
            # MONTHLY-EQUIVALENT, not the sum of face values: this is the
            # header's "Bills / month" figure AND the number ``month_net``
            # subtracts below, so the two must ride the same footing. A
            # quarterly $300 bill costs $100 a month; summing the face
            # values instead (the original) overstated the cell by the
            # whole non-monthly book, and the strip visibly failed its own
            # arithmetic - the three cells on display did not subtract to
            # the fourth.
            "fixed_total": rollup["monthly_total"],
            "fixed_count": len(fixed_lines) + len(non_monthly_lines),
        }

        # 8. The month's bottom line: confirmed income minus confirmed
        # bills minus budget allocations, all monthly-equivalent - the
        # same commitment gate and factors the forecast walks with, so
        # this verdict and the Projected tab cannot disagree. Budget
        # lines are the flexible ones only; a category a bill covers is
        # already excluded from budgets by the suggestion guards.

        income_total, income_count = _monthly_income(streams)
        stats["income_total"] = income_total
        stats["income_count"] = income_count
        # Goals ask their monthly need of the month, the same
        # commitment-gate discipline bills ride:
        # paused/reached goals ask nothing, by the pure-math contract.
        goal_accounts = await self.list_goals(owner_user_id=owner_user_id)
        figures = MonthlyFigures(
            income_total=stats["income_total"],
            committed=stats["fixed_total"] + stats["flexible_allocated"],
        )
        engine_rows = [
            (str(account.id), meta, account.current_balance or 0)
            for account in goal_accounts
            if (meta := goal_metadata(account.metadata_)) is not None
        ]
        asks = allocate_month(figures, engine_rows, today=today)
        goal_asks = [
            {
                "account_id": account.id,
                "label": account.name,
                "monthly_need": asks.get(str(account.id), 0),
            }
            for account in goal_accounts
            if goal_metadata(account.metadata_) is not None
        ]
        stats["goals_total"] = sum(g["monthly_need"] for g in goal_asks)
        stats["goals_count"] = sum(1 for g in goal_asks if g["monthly_need"] > 0)

        # Auto-credit envelopes are spoken-for money too: the allowance
        # leaves the spendable month whether or not anyone clicks. Manual
        # envelopes ask nothing - crediting them is a choice made live.
        envelope_credits = [
            int(meta.monthly_credit * CADENCES[meta.cadence].monthly_factor)
            for account in await self.list_envelopes(owner_user_id=owner_user_id)
            if (meta := envelope_metadata(account.metadata_)) is not None
            and meta.auto_credit
            and meta.monthly_credit
        ]
        stats["envelopes_total"] = sum(envelope_credits)
        stats["envelopes_count"] = len(envelope_credits)

        # The sixth term: observed spending no bill and no limit covers.
        stats["everything_else"] = await self.uncovered_spending_rate(
            owner_user_id=owner_user_id, today=today, account_ids=account_ids
        )

        # Subtracts the figures the header STRIP shows, not equivalents of
        # them recomputed here - the cells and this verdict are one
        # arithmetic statement, and a reader checking it by hand has to
        # get the same answer.
        stats["month_net"] = (
            stats["income_total"]
            - stats["fixed_total"]
            - stats["flexible_allocated"]
            - stats["goals_total"]
            - stats["envelopes_total"]
            - stats["everything_else"]
        )

        # 9. When the month lands negative, the summary carries its own
        # fix: pause-a-goal rows first, then deterministic per-line cuts
        # (see plan_budget_trims). One payload, so the tab offers the
        # adjustment beside the verdict and a later decision layer reads
        # the same structure.
        plan = plan_budget_trims(
            flexible_lines,
            deficit=max(0, -stats["month_net"]),
            goals=goal_asks,
        )
        stats["trim_residual"] = plan["residual"]

        return {
            "period_month": month,
            "buckets": [
                bucket("fixed", fixed_lines),
                bucket("non_monthly", non_monthly_lines),
                bucket("flexible", flexible_lines),
            ],
            "stats": stats,
            "trims": plan["cuts"],
        }

    async def uncovered_spending_rate(
        self,
        *,
        owner_user_id: int | None = None,
        today: date | None = None,
        account_ids: list[int] | None = None,
    ) -> int:
        """Cents/month of observed spending no bill and no budget limit
        covers - the trailing 3 full months' average of spend-space
        outflows that are neither linked to a recurring stream nor in a
        budgeted category. The sixth term of the month equation: without
        it, unplanned spending is invisible and every future month reads
        optimistic by exactly that amount (confirmed live: ~40% of real
        spending was in no bucket).
        """
        filters, _window = await self._uncovered_spend_filters(
            owner_user_id=owner_user_id, today=today, account_ids=account_ids
        )
        total = (
            await self.db.exec(
                select(func.coalesce(func.sum(FinanceTransaction.amount), 0)).where(
                    *filters
                )
            )
        ).one()
        return round(-int(total) / 3)

    async def _uncovered_spend_filters(
        self,
        *,
        owner_user_id: int | None,
        today: date | None,
        account_ids: list[int] | None,
    ) -> tuple[list[Any], tuple[date, date]]:
        """The uncovered-spend population, shared by the rate and its
        per-category breakdown so the popup's rows always sum to the
        cell's figure. Returns (filters, (window_start, window_end))."""
        today = today or date.today()
        window_end = date(today.year, today.month, 1)
        window_start = add_months(window_end, -3)

        budget = await self.get_or_create_budget(
            owner_user_id=owner_user_id, period_month=_current_period_month()
        )
        budgeted_category_ids = {
            line.category_id
            for line in (
                await self.db.exec(
                    select(FinanceBudgetCategory).where(
                        FinanceBudgetCategory.budget_id == budget.id,
                        FinanceBudgetCategory.period_month == _current_period_month(),
                    )
                )
            ).all()
            if line.category_id is not None
        }

        live_accounts = select(FinanceAccount.id).where(
            FinanceAccount.deleted_at.is_(None)
        )
        filters: list[Any] = [
            FinanceTransaction.deleted_at.is_(None),
            FinanceTransaction.dedup_status != "duplicate",
            FinanceTransaction.excluded_from_reports.is_(False),
            FinanceTransaction.is_transfer.is_(False),
            FinanceTransaction.account_id.in_(live_accounts),
            FinanceTransaction.amount < 0,
            FinanceTransaction.date_ >= window_start,
            FinanceTransaction.date_ < window_end,
            FinanceTransaction.recurring_stream_id.is_(None),
            # A reconciliation adjustment is bookkeeping, not spending.
            or_(
                FinanceTransaction.external_id_source.is_(None),
                FinanceTransaction.external_id_source != "reconcile",
            ),
        ]
        if owner_user_id is not None:
            filters.append(FinanceTransaction.owner_user_id == owner_user_id)
        if account_ids is not None:
            filters.append(FinanceTransaction.account_id.in_(account_ids))
        if budgeted_category_ids:
            filters.append(
                or_(
                    FinanceTransaction.category_id.is_(None),
                    FinanceTransaction.category_id.notin_(budgeted_category_ids),
                )
            )
        return filters, (window_start, window_end)

    async def budget_stat_details(
        self,
        *,
        owner_user_id: int | None = None,
        today: date | None = None,
        account_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Per-row backup for the header cells, for the click-a-cell popup.

        Income and Bills mirror the cells' own math row for row (same
        commitment gate, same monthly-equivalent factors as
        ``_monthly_income``/``commitment_rollup``), so the rows always sum
        to the cell. Everything-else is the uncovered-spend bucket grouped
        by category, over the SAME filters as the rate.
        """
        from app.services.finance.categorize.insights import (
            _MONTHLY_FACTOR,
            commitment_rollup,
            is_commitment,
            is_paused,
        )

        today = today or date.today()
        streams = await self.list_recurring(owner_user_id=owner_user_id)

        income_rows = [
            {
                "label": s.name,
                "value": int(
                    (s.expected_amount or s.average_amount or 0)
                    * _MONTHLY_FACTOR.get(s.frequency, 0.0)
                ),
                "caption": None
                if _MONTHLY_FACTOR.get(s.frequency, 0.0) >= 1.0
                else s.frequency,
            }
            for s in streams
            if s.direction == "inflow"
            and not s.is_muted
            and not is_paused(s, today)
            and is_commitment(s)
            and _MONTHLY_FACTOR.get(s.frequency, 0.0) > 0
        ]
        income_rows.sort(key=lambda r: -r["value"])

        rollup = commitment_rollup(streams, today=today)
        bills_rows = [
            {
                "label": s.name,
                "value": int(
                    (s.average_amount or 0) * _MONTHLY_FACTOR.get(s.frequency, 0.0)
                ),
                "caption": None
                if _MONTHLY_FACTOR.get(s.frequency, 0.0) >= 1.0
                else f"${(s.average_amount or 0) / 100:,.2f} {s.frequency}",
            }
            for s in rollup["fixed"] + rollup["non_monthly"]
        ]
        bills_rows.sort(key=lambda r: -r["value"])

        filters, (window_start, window_end) = await self._uncovered_spend_filters(
            owner_user_id=owner_user_id, today=today, account_ids=account_ids
        )
        grouped = (
            await self.db.exec(
                select(
                    FinanceTransaction.category_id,
                    func.count(),
                    func.sum(FinanceTransaction.amount),
                )
                .where(*filters)
                .group_by(FinanceTransaction.category_id)
            )
        ).all()
        names = await self.category_names(
            {category_id for category_id, _n, _total in grouped if category_id}
        )
        else_rows = [
            {
                "label": names.get(category_id) or "Uncategorized",
                "value": round(-int(total) / 3),
                "caption": f"{count} row{'s' if count != 1 else ''}",
            }
            for category_id, count, total in grouped
        ]
        else_rows.sort(key=lambda r: -r["value"])

        window_last = add_months(window_end, -1)
        window = (
            f"{window_start.strftime('%b')} - {window_last.strftime('%b %Y')} average"
        )
        return {
            "income": income_rows,
            "bills": bills_rows,
            "everything_else": else_rows,
            "window": window,
        }

    async def budget_month_outlook(
        self,
        *,
        owner_user_id: int | None = None,
        months: int = 6,
        today: date | None = None,
        account_ids: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        """The header equation computed per month, months ahead - bills at
        FACE VALUE on their real cadence, so the month the annual premium
        lands looks like that month and not like an average. "Fine this
        month" and "broke in October" become visible from one page.

        Same population rules as the header: confirmed commitments only,
        muted/paused out, transfers (card payments included) out of the
        bills figure - swipes are already counted in budgets. Budgets,
        goals, and envelopes ask their standing monthly amounts of every
        month (they are plans, not occurrences).
        """
        from app.services.finance.categorize import is_commitment, is_paused

        today = today or date.today()
        first = date(today.year, today.month, 1)
        horizon_end = add_months(first, months)

        streams = await self.list_recurring(owner_user_id=owner_user_id)
        # Same scoping rule as budget_summary, the header this pages.
        if account_ids is not None:
            streams = [s for s in streams if s.account_id in account_ids]
        transfer_ids = await self.transfer_stream_ids([s.id for s in streams])
        due_in: dict[tuple[int, int, str], int] = {}
        for stream in streams:
            if (
                stream.is_muted
                or is_paused(stream, today)
                or stream.id in transfer_ids
                or not is_commitment(stream)
                or stream.next_expected_date is None
            ):
                continue
            amount = stream.expected_amount or stream.average_amount or 0
            if amount <= 0:
                continue
            direction = "in" if stream.direction == "inflow" else "out"
            if stream.frequency == ONE_TIME_FREQUENCY:
                when = stream.next_expected_date
                if today <= when < horizon_end:
                    key = (when.year, when.month, direction)
                    due_in[key] = due_in.get(key, 0) + amount
                continue
            step = _FREQUENCY_STEPS.get(stream.frequency)
            if step is None:
                continue
            when = stream.next_expected_date
            guard = 0
            while when < today and guard < 400:
                when = step(when)
                guard += 1
            while when < horizon_end and guard < 400:
                key = (when.year, when.month, direction)
                due_in[key] = due_in.get(key, 0) + amount
                when = step(when)
                guard += 1

        # The standing monthly asks - plans, identical every month.
        budget = await self.get_or_create_budget(
            owner_user_id=owner_user_id, period_month=_current_period_month()
        )
        budgets_monthly = sum(
            line.allocated_amount
            for line in (
                await self.db.exec(
                    select(FinanceBudgetCategory).where(
                        FinanceBudgetCategory.budget_id == budget.id,
                        FinanceBudgetCategory.period_month == _current_period_month(),
                    )
                )
            ).all()
        )
        goals_monthly = sum(
            (
                await self.goal_allocations(owner_user_id=owner_user_id, today=today)
            ).values()
        )
        envelopes_monthly = sum(
            int(meta.monthly_credit * CADENCES[meta.cadence].monthly_factor)
            for account in await self.list_envelopes(owner_user_id=owner_user_id)
            if (meta := envelope_metadata(account.metadata_)) is not None
            and meta.auto_credit
            and meta.monthly_credit
        )
        everything_else = await self.uncovered_spending_rate(
            owner_user_id=owner_user_id, today=today, account_ids=account_ids
        )

        # The LEVEL under the rates: today's real cash for the selected
        # accounts, compounded through each month's net - a healthy rate
        # starting from an empty account still reads red where it should.
        accounts, _total = await self.list_accounts(
            owner_user_id=owner_user_id, page_size=500
        )
        if account_ids is not None:
            allowed = set(account_ids)
            accounts = [a for a in accounts if a.id in allowed]
        cash = [
            a
            for a in accounts
            if a.classification != "liability" and a.account_type in _CASH_ACCOUNT_TYPES
        ]
        totals = await self.account_transaction_totals(
            owner_user_id=owner_user_id, account_ids=[a.id for a in cash]
        )
        running = _display_cash_balance(cash, totals)

        outlook: list[dict[str, Any]] = []
        for offset in range(months):
            month_start = add_months(first, offset)
            income_due = due_in.get((month_start.year, month_start.month, "in"), 0)
            bills_due = due_in.get((month_start.year, month_start.month, "out"), 0)
            month_net = (
                income_due
                - bills_due
                - budgets_monthly
                - goals_monthly
                - envelopes_monthly
                - everything_else
            )
            outlook.append(
                {
                    "period_month": month_start.year * 100 + month_start.month,
                    "income_due": income_due,
                    "bills_due": bills_due,
                    "budgets": budgets_monthly,
                    "goals": goals_monthly,
                    "envelopes": envelopes_monthly,
                    "everything_else": everything_else,
                    "month_net": month_net,
                    "start_balance": running,
                    "end_balance": running + month_net,
                }
            )
            running += month_net
        return outlook

    async def parse_budget_goal(
        self, *, owner_user_id: int | None, text: str
    ) -> dict[str, Any]:
        """Deterministic (not LLM-backed) reading of a natural-language
        goal: "I wanna cut back on Starbucks" -> a payee match against the
        last 90 days of transactions, or a category match against the
        taxonomy, plus an explicit or default-50% cut fraction. Computes
        only - the frontend's Confirm step is what actually writes, via
        ``upsert_budget_line``.
        """
        from app.services.finance.categorize.insights import format_usd

        casefold_text = text.casefold()

        percent_match = re.search(r"(\d+)\s*%", text)
        fraction = int(percent_match.group(1)) / 100 if percent_match else 0.5

        cutoff = date.today() - timedelta(days=90)
        live_accounts = select(FinanceAccount.id).where(
            FinanceAccount.deleted_at.is_(None)
        )
        filters = [
            FinanceTransaction.deleted_at.is_(None),
            FinanceTransaction.dedup_status != "duplicate",
            FinanceTransaction.excluded_from_reports.is_(False),
            FinanceTransaction.account_id.in_(live_accounts),
            FinanceTransaction.amount < 0,
            FinanceTransaction.date_ >= cutoff,
        ]
        if owner_user_id is not None:
            filters.append(FinanceTransaction.owner_user_id == owner_user_id)
        txn_rows = (
            await self.db.exec(
                select(
                    FinanceTransaction.merchant_name,
                    FinanceTransaction.original_description,
                    FinanceTransaction.name,
                    FinanceTransaction.amount,
                ).where(*filters)
            )
        ).all()
        payee_spend: dict[str, int] = defaultdict(int)
        payee_label: dict[str, str] = {}
        for merchant_name, original_description, name, amount in txn_rows:
            key = transaction_payee_key(merchant_name, original_description, name)
            if not key:
                continue
            payee_spend[key] += -amount
            payee_label.setdefault(key, merchant_name or name or key.title())

        # Match on the key's FIRST token, not the full label - the goal
        # text is short ("...on Starbucks") while the label can be a noisy
        # full descriptor ("STARBUCKS STORE 1234 NEW YORK NY"), so testing
        # "label in text" would almost never hit. The merchant name is
        # reliably the key's first token (transaction_payee_key's own
        # invariant). If several store-number variants share that first
        # token, the highest-spend one wins - the most representative
        # baseline for a single deterministic guess.
        candidates = [
            key
            for key in payee_label
            if len(key.split()[0]) >= 3 and key.split()[0].casefold() in casefold_text
        ]
        matched_payee_key = (
            max(candidates, key=lambda k: payee_spend[k]) if candidates else None
        )

        if matched_payee_key is not None:
            baseline_monthly = int(payee_spend[matched_payee_key] / 3)
            suggested_limit = round(baseline_monthly * fraction)
            label = payee_label[matched_payee_key]
            return {
                "matched": True,
                "target_type": "payee",
                "category_id": None,
                "payee_key": matched_payee_key,
                "payee_label": label,
                "baseline_monthly": baseline_monthly,
                "suggested_limit": suggested_limit,
                "message": (
                    f"{label} has averaged {format_usd(baseline_monthly)}/mo "
                    f"over the last 90 days. Suggested limit: "
                    f"{format_usd(suggested_limit)}/mo "
                    f"({int(fraction * 100)}% of baseline)."
                ),
            }

        categories = await self.list_categories()
        matched_category = None
        for category in categories:
            leaf = category.name.rsplit(":", 1)[-1].strip()
            if len(leaf) >= 3 and leaf.casefold() in casefold_text:
                matched_category = category
                break

        if matched_category is not None:
            cat_filters = [
                *filters,
                FinanceTransaction.category_id == matched_category.id,
            ]
            cat_total = (
                await self.db.exec(
                    select(func.sum(FinanceTransaction.amount)).where(*cat_filters)
                )
            ).one()
            baseline_monthly = int(-(cat_total or 0) / 3)
            suggested_limit = round(baseline_monthly * fraction)
            return {
                "matched": True,
                "target_type": "category",
                "category_id": matched_category.id,
                "payee_key": None,
                "payee_label": None,
                "baseline_monthly": baseline_monthly,
                "suggested_limit": suggested_limit,
                "message": (
                    f"{matched_category.name} has averaged "
                    f"{format_usd(baseline_monthly)}/mo over the last 90 days. "
                    f"Suggested limit: {format_usd(suggested_limit)}/mo "
                    f"({int(fraction * 100)}% of baseline)."
                ),
            }

        return {
            "matched": False,
            "target_type": None,
            "category_id": None,
            "payee_key": None,
            "payee_label": None,
            "baseline_monthly": None,
            "suggested_limit": None,
            "message": (
                "Couldn't find a category or recent payee matching that - "
                "try naming one directly, or add a budget line manually."
            ),
        }
