"""Categories: aliases, PFC mapping, spending rollups.

Read statements live in ``ledger/queries.py``; this module owns writes and
orchestration and delegates every fetch.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.ledger import queries, transactions
from app.services.finance.models import (
    FinanceCategory,
    FinanceCategoryAlias,
    FinanceTransaction,
)
from app.services.finance.schemas import (
    CategorySuggestion,
    CategorySuggestionListResponse,
    CategoryUsageResponse,
)
from app.services.finance.utils import (
    transaction_payee_key,
    utcnow,
)


async def resolve_category_alias(
    db: AsyncSession, category_hint: str | None
) -> int | None:
    """Map a free-text category string to a category id via
    finance_category_alias (normalized lookup). None if unmatched.

    Prefers a user alias over a global (owner NULL) seed when both match.
    """
    if not category_hint:
        return None
    resolved = await queries.category_alias_ids(db, [category_hint])
    return resolved.get(category_hint)


async def get_or_create_category_from_hint(
    db: AsyncSession, hint: str | None
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
    from app.services.finance.utils import normalize_payee

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

    category = await queries.category_by_slug_global(db, slug)
    if category is None:
        category = FinanceCategory(name=name, slug=slug, classification=classification)
        db.add(category)
        await db.flush()

    normalized = normalize_payee(text)
    existing_alias = await queries.alias_by_normalized_global(db, normalized)
    if existing_alias is None:
        db.add(
            FinanceCategoryAlias(
                category_id=category.id,
                alias_text=text,
                normalized_alias=normalized,
                source="import",
            )
        )
        await db.flush()
    return category


async def get_or_create_pfc_category(
    db: AsyncSession, pfc_primary: str
) -> FinanceCategory:
    """Fetch (or create) the system category for a Plaid personal-finance
    category primary (e.g. ``FOOD_AND_DRINK``). Categories are global/system
    seeds (owner NULL), shared across users and created on first sight."""
    slug = pfc_primary.strip().lower()
    existing = await queries.category_by_slug_global(db, slug)
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
    db.add(category)
    await db.flush()
    return category


async def category_names(db: AsyncSession, ids: set[int] | list[int]) -> dict[int, str]:
    """Category names by id, in one query.

    Rows carry ``category_id``; a table that wants to SHOW the category
    would otherwise fetch one name per row.
    """
    return await queries.category_names_by_id(db, ids)


async def list_categories(db: AsyncSession) -> list[FinanceCategory]:
    """The full taxonomy, name-sorted, nothing joined.

    For pickers that only need id + name (the uncategorized-transactions
    dropdown). ``category_usage`` also lists every category but LEFT
    JOINs + GROUPs BY over the *entire* transaction history to compute
    usage stats a picker never shows - measurably slow once there's a
    real amount of transaction data. This is a plain, single-table
    select instead.
    """
    return await queries.all_categories(db)


async def category_usage(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    days: int | None = None,
) -> list[CategoryUsageResponse]:
    """Every category with how it is actually used.

    Unlike ``spending_by_category`` this keeps INFLOWS and transfers,
    reports a signed total, and lists categories that saw no activity
    in the window - the point is the taxonomy itself, not a spend
    ranking. ``days=None`` covers all time.
    """
    rows = await queries.category_usage_rows(db, owner_user_id=owner_user_id, days=days)
    return [
        CategoryUsageResponse(
            id=category_id,
            name=name,
            classification=classification,
            is_system=is_system,
            transaction_count=int(count or 0),
            total=int(total or 0),
            last_used=last_used,
        )
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
    db: AsyncSession,
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
    miscellaneous spend, it was several mid-size siblings each too
    small on its own to crack the top N, that together are a top
    category once combined. Confirmed against live data: 30.7% "Other"
    leaf-grouped vs 16.3% parent-rolled-up, same window, same ledger.

    The GROUP BY itself stays on the leaf name (portable SQL); the
    rollup happens in Python after, over a few dozen rows at most.

    ``account_ids`` narrows the breakdown to those accounts (still
    intersected with live accounts and the owner scope, so a stray id can
    never widen the view)."""
    cutoff = date.today() - timedelta(days=days)
    rows = await queries.category_spend_totals(
        db, owner_user_id=owner_user_id, start=cutoff, account_ids=account_ids
    )
    totals: dict[str, int] = {}
    for name, total in rows:
        parent = name.split(":", 1)[0]
        totals[parent] = totals.get(parent, 0) - total
    return sorted(totals.items(), key=lambda pair: pair[1], reverse=True)


async def spending_transactions(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    days: int = 30,
    account_ids: list[int] | None = None,
    categories: list[str] | None = None,
) -> list[FinanceTransaction]:
    """The actual rows behind a ``spending_by_category`` slice - the
    SAME filters, verbatim, minus the ``GROUP BY``/``SUM``, so drilling
    into a slice shows exactly the transactions that summed to its
    dollar total.

    ``categories`` matches each name exactly OR as a "name:" prefix -
    spending_by_category already rolls a leaf category up to its
    PARENT before a caller ever sees it, so passing a parent name like
    "Food & Dining" pulls every "Food & Dining:*" leaf transaction
    too. Pass the full list of names folded into "Other" to drill into
    THAT slice the same way.
    """
    cutoff = date.today() - timedelta(days=days)
    return await queries.spending_rows(
        db,
        owner_user_id=owner_user_id,
        start=cutoff,
        account_ids=account_ids,
        categories=categories,
    )


async def spending_summary(
    db: AsyncSession, *, owner_user_id: int | None = None, month: str | None = None
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
    rows = await queries.category_spend_totals(
        db, owner_user_id=owner_user_id, start=start, end=end
    )
    result = [(name, -total) for name, total in rows]
    result.sort(key=lambda pair: pair[1], reverse=True)
    return result


async def categorize_transaction(
    db: AsyncSession,
    transaction_id: int,
    category_id: int,
    *,
    owner_user_id: int | None = None,
    source: str = "user",
) -> FinanceTransaction | None:
    """Set a transaction's category. ``source`` is ``"user"`` for a
    manual pick, ``"rule"`` for the payee-precedent auto-categorize
    sweep. Returns None if the transaction isn't found/owned."""
    txn = await transactions.get_transaction(
        db, transaction_id, owner_user_id=owner_user_id
    )
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
    category = await queries.category_by_id(db, category_id)
    to_transfer = category is not None and category.classification == "transfer"
    if to_transfer and not txn.is_transfer:
        txn.is_transfer = True
        txn.excluded_from_reports = True
    elif not to_transfer and txn.is_transfer and txn.transfer_group_id is None:
        txn.is_transfer = False
        txn.excluded_from_reports = False
    txn.updated_at = utcnow()
    db.add(txn)
    await db.flush()
    return txn


async def suggest_categories(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    transaction_ids: list[int] | set[int] | None = None,
) -> CategorySuggestionListResponse:
    """Preview a category by payee precedent - computes, does not write.

    If this owner has categorized other transactions from the same
    payee before, and one category clearly dominates (no tie), that
    transaction gets a suggestion. No ML, no new tables - just the
    owner's own past corrections, the same normalize_payee-based
    grouping recurring-stream detection already uses. A caller applies
    an accepted suggestion through the ordinary
    ``categorize_transaction`` (``source="rule"``) - this method only
    computes candidates, on purpose: an earlier version applied matches
    directly, which meant nothing was left to review before it hit the
    ledger.

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

    # One batched fetch of the owner's already-categorized history,
    # tallied in Python by payee key -> {category_id: count}.
    categorized_rows = await queries.categorized_history(
        db, owner_user_id=owner_user_id
    )
    tally: dict[str, Counter[int]] = defaultdict(Counter)
    for row in categorized_rows:
        key = payee_key(row)
        if key:
            tally[key][row.category_id] += 1

    candidates, _total = await transactions.uncategorized_transactions(
        db, owner_user_id=owner_user_id, limit=None
    )
    if transaction_ids is not None:
        wanted = set(transaction_ids)
        candidates = [t for t in candidates if t.id in wanted]

    suggestions: list[tuple[int, int]] = []  # (transaction_id, category_id)
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
        suggestions.append((txn.id, best_category))

    names = await category_names(db, {category_id for _, category_id in suggestions})
    return CategorySuggestionListResponse(
        items=[
            CategorySuggestion(
                transaction_id=transaction_id,
                category_id=category_id,
                category_name=names.get(category_id, ""),
            )
            for transaction_id, category_id in suggestions
        ],
        skipped=skipped,
    )
