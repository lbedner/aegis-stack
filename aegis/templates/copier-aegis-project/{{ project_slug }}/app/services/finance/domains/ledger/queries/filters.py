"""Predicate fragments the ledger's reads share.

Not reads themselves - subqueries and filter clauses several sections
build their WHERE out of. They live apart because "live accounts only"
and "which categories are catch-alls" have to mean one thing whether a
transaction, a category total, or a payee roll-up is asking.
"""

from __future__ import annotations

from sqlalchemy import func
from sqlmodel import or_, select

from app.services.finance.constants import (
    UNCATEGORIZED_CATEGORY_NAMES,
)
from app.services.finance.models import (
    FinanceAccount,
    FinanceCategory,
    FinanceMerchant,
    FinanceTransaction,
)


def live_account_ids():
    """Subquery: ids of accounts that are not soft-deleted.

    NOT the same function as ``detection.insights.rules.live_account_ids``,
    which takes an ``owner_user_id`` and scopes to it. This one is
    owner-blind on purpose - every caller here has already scoped the outer
    query by owner, and re-applying it would be a redundant join. Check
    which one you have imported before assuming a result set is scoped.
    """
    return select(FinanceAccount.id).where(FinanceAccount.deleted_at.is_(None))


def uncategorized_catchall_ids():
    """Subquery: category ids whose name is a source app's own catch-all
    bucket (see ``UNCATEGORIZED_CATEGORY_NAMES``)."""
    return select(FinanceCategory.id).where(
        func.lower(FinanceCategory.name).in_(list(UNCATEGORIZED_CATEGORY_NAMES))
    )


def transaction_search_filter(query: str):
    """One OR across every column the register actually shows.

    Searching only ``FinanceTransaction.name`` meant a query matching what
    was ON SCREEN could still return nothing: the Payee column shows the
    assigned merchant (not the descriptor), and the Category and Account
    columns are joins. An empty result then reads as "no such data"
    rather than "that column is not searched".

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
