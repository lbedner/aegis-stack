"""Budget lines your own spending already implies, and declining them.

The gates below are the whole of it: a proposal has to be steady, big
enough to bother with, not already billed, and not already declined.
Everything a user does with a proposal other than accepting it (accepting
writes a line, which is ``lines``) lands here as a dismissal marker.
"""

from __future__ import annotations

from datetime import date
import statistics

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.constants import UNCATEGORIZED_CATEGORY_NAMES
from app.services.finance.domains.detection.insights.commitments import (
    MONTHLY_FACTOR,
    is_commitment,
    is_paused,
)
from app.services.finance.domains.ledger import categories
from app.services.finance.domains.ledger import queries as ledger_queries
from app.services.finance.domains.planning import recurring
from app.services.finance.domains.planning.budgets import queries
from app.services.finance.domains.planning.budgets.lines import get_or_create_budget
from app.services.finance.models import FinanceBudgetCategory
from app.services.finance.schemas import BudgetSuggestion, DismissedBudgetSuggestion
from app.services.finance.utils import current_period_month

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
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    today: date | None = None,
) -> list[BudgetSuggestion]:
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
    first = current - _BUDGET_LOOKBACK_MONTHS

    rows = await queries.categorized_outflow_history(db, owner_user_id=owner_user_id)

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
    live_streams = await recurring.queries.all_live_streams(db)
    # How much of each category the bills already account for, per
    # month. Presence is the wrong test: nearly every stream INFERS a
    # category from its transactions, so one detected rhythm holding a
    # single grocery charge would block the whole groceries budget
    # (19 suggestions collapsed to 2 when tried that way). Magnitude
    # is the right test - if bills already cover most of what a
    # category costs, budgeting it too charges the forecast twice; if
    # they cover a sliver, the budget is still the useful number.
    all_categories = await ledger_queries.all_categories(db)
    by_name = {c.name: c.id for c in all_categories}
    # A budget line is about money SPENT. Categories carry their own
    # classification, and it is the reliable signal: the
    # transaction-level ``is_transfer`` guard above only catches rows
    # PAIRING flagged, and it misses plenty - with the steadiness gate
    # fixed, the single largest suggestion on a real ledger became
    # "Transfer" at $1,599/month, money moving between the user's own
    # accounts.
    spendable = {c.id for c in all_categories if c.classification == "expense"}
    inferred = await recurring.stream_category_names(db, [s.id for s in live_streams])
    billed_per_month: dict[int, int] = {}
    # Categories a CONFIRMED bill claims. Presence, not magnitude: the
    # user already said this money is a bill, so no arithmetic gets to
    # re-suggest it - the magnitude test below stays for unconfirmed
    # detector rhythms only (where it is what keeps one grocery-store
    # rhythm from blocking the whole groceries budget).
    # A confirmed bill stripped of its members infers nothing from them
    # (the Mortgage bill sat at 0 members and Mortgage got suggested).
    # The stream's own name through the alias table is the fallback
    # signal - resolved for every such stream in one query up front.
    fallback_names = {
        stream.name
        for stream in live_streams
        if not (stream.is_muted or is_paused(stream))
        and bool(stream.is_user_confirmed or stream.source == "user")
        and (stream.category_id or by_name.get(inferred.get(stream.id, ""))) is None
    }
    alias_fallback = await ledger_queries.category_alias_ids(db, fallback_names)

    confirmed_categories: set[int] = set()
    for stream in live_streams:
        if stream.is_muted or is_paused(stream):
            continue
        confirmed = bool(stream.is_user_confirmed or stream.source == "user")
        category_id = stream.category_id or by_name.get(inferred.get(stream.id, ""))
        if category_id is None and confirmed:
            category_id = alias_fallback.get(stream.name)
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
        factor = MONTHLY_FACTOR.get(stream.frequency, 0)
        billed_per_month[category_id] = billed_per_month.get(category_id, 0) + int(
            amount * factor
        )
    budget = await get_or_create_budget(
        db, owner_user_id=owner_user_id, period_month=current_period_month()
    )
    already = {
        line.category_id
        for line in await queries.budget_lines_with_category(db, budget.id)
    }
    names = {c.id: c.name for c in await ledger_queries.all_categories(db)}

    picks: list[BudgetSuggestion] = []
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
        if len(spends) < _BUDGET_MIN_MONTHS:
            continue
        # Median, not mean: one repair bill should not set the year.
        amount = int(statistics.median(spends))
        if amount < _BUDGET_MIN_AMOUNT:
            continue
        low = amount * (1 - _BUDGET_UNUSUAL_BAND)
        high = amount * (1 + _BUDGET_UNUSUAL_BAND)
        unusual = sum(1 for v in spends if v < low or v > high)
        if unusual > _BUDGET_MAX_UNUSUAL_MONTHS:
            continue
        # Bills already cover most of this category - the forecast has
        # counted it once, and a budget line would count it again.
        covered = billed_per_month.get(category_id, 0)
        if covered >= amount * _BUDGET_BILLED_SHARE:
            continue
        picks.append(
            BudgetSuggestion(
                category_id=category_id,
                category_name=names.get(category_id),
                suggested_amount=amount,
                months_seen=len(spends),
                unusual_months=unusual,
            )
        )
    picks.sort(key=lambda p: -p.suggested_amount)
    return picks


async def dismissal_markers(
    db: AsyncSession, *, owner_user_id: int | None
) -> list[FinanceBudgetCategory]:
    budget = await get_or_create_budget(
        db, owner_user_id=owner_user_id, period_month=current_period_month()
    )
    return await queries.dismissal_marker_lines(db, budget.id)


async def list_dismissed_suggestions(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> list[DismissedBudgetSuggestion]:
    """Declined suggestions, with display names, name-sorted."""
    markers = await dismissal_markers(db, owner_user_id=owner_user_id)
    if not markers:
        return []
    names = await categories.category_names(db, [m.category_id for m in markers])
    return sorted(
        (
            DismissedBudgetSuggestion(
                category_id=m.category_id,
                category_name=names.get(m.category_id),
            )
            for m in markers
        ),
        key=lambda d: d.category_name or "",
    )


async def dismiss_budget_suggestions(
    db: AsyncSession, *, owner_user_id: int | None = None, category_ids: list[int]
) -> int:
    """Decline suggestions for these categories. Idempotent; returns
    how many new dismissals were recorded."""
    budget = await get_or_create_budget(
        db, owner_user_id=owner_user_id, period_month=current_period_month()
    )
    existing = {
        m.category_id for m in await dismissal_markers(db, owner_user_id=owner_user_id)
    }
    added = 0
    for category_id in dict.fromkeys(category_ids):
        if category_id is None or category_id in existing:
            continue
        db.add(
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
        await db.flush()
    return added


async def restore_budget_suggestions(
    db: AsyncSession, *, owner_user_id: int | None = None, category_ids: list[int]
) -> int:
    """Un-decline suggestions: delete the markers. Returns how many."""
    wanted = {c for c in category_ids if c is not None}
    removed = 0
    for marker in await dismissal_markers(db, owner_user_id=owner_user_id):
        if marker.category_id in wanted:
            await db.delete(marker)
            removed += 1
    if removed:
        await db.flush()
    return removed
