"""Reads for the category taxonomy and what falls under it.

Lookups by id, slug and alias, plus the spend roll-ups that answer "how
much went to this category" - the shape budget suggestions and the
analyst snapshot both consume.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

from sqlalchemy import and_, func
from sqlmodel import or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.ledger.queries.filters import (
    live_account_ids,
    split_aware_category_clause,
    uncategorized_catchall_ids,
)
from app.services.finance.models import (
    FinanceCategory,
    FinanceCategoryAlias,
    FinanceTransaction,
    FinanceTransactionSplit,
)


async def category_alias_ids(
    db: AsyncSession, hints: Iterable[str | None]
) -> dict[str, int]:
    """hint -> category id via the alias table, one query for all hints.

    Same semantics as the single-hint ``resolve_category_alias``:
    normalized match, alias-owner precedence via the same ordering.
    Unmatched hints are absent from the result.
    """
    from app.services.finance.utils import normalize_payee

    normalized_by_hint = {hint: normalize_payee(hint) for hint in hints if hint}
    wanted = {normalized for normalized in normalized_by_hint.values() if normalized}
    if not wanted:
        return {}
    rows = (
        await db.exec(
            select(
                FinanceCategoryAlias.normalized_alias,
                FinanceCategoryAlias.category_id,
            )
            .where(FinanceCategoryAlias.normalized_alias.in_(wanted))
            .order_by(FinanceCategoryAlias.owner_user_id.desc())
        )
    ).all()
    by_normalized: dict[str, int] = {}
    for normalized, category_id in rows:
        by_normalized.setdefault(normalized, category_id)
    return {
        hint: by_normalized[normalized]
        for hint, normalized in normalized_by_hint.items()
        if normalized in by_normalized
    }


async def category_by_id(db: AsyncSession, category_id: int) -> FinanceCategory | None:
    return await db.get(FinanceCategory, category_id)


async def category_by_slug_global(
    db: AsyncSession, slug: str
) -> FinanceCategory | None:
    """The global (owner NULL) category with this slug, or None."""
    return (
        await db.exec(
            select(FinanceCategory).where(
                FinanceCategory.slug == slug,
                FinanceCategory.owner_user_id.is_(None),
            )
        )
    ).first()


async def alias_by_normalized_global(
    db: AsyncSession, normalized: str
) -> FinanceCategoryAlias | None:
    return (
        await db.exec(
            select(FinanceCategoryAlias).where(
                FinanceCategoryAlias.normalized_alias == normalized,
                FinanceCategoryAlias.owner_user_id.is_(None),
            )
        )
    ).first()


async def category_names_by_id(
    db: AsyncSession, ids: set[int] | list[int]
) -> dict[int, str]:
    wanted = [i for i in set(ids) if i is not None]
    if not wanted:
        return {}
    rows = (
        await db.exec(select(FinanceCategory).where(FinanceCategory.id.in_(wanted)))
    ).all()
    return {row.id: row.name for row in rows}


async def all_categories(db: AsyncSession) -> list[FinanceCategory]:
    """The full taxonomy, name-sorted, single-table."""
    rows = (await db.exec(select(FinanceCategory).order_by(FinanceCategory.name))).all()
    return list(rows)


async def category_usage_rows(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    days: int | None = None,
) -> list[tuple[int, str, str, bool, int, int, date | None]]:
    """Every category LEFT-joined to its live activity: (id, name,
    classification, is_system, count, total, last_used).

    Split-aware: a split parent contributes its LINES to their categories
    (second query, merged in Python) and nothing to its own."""
    filters = [
        FinanceTransaction.deleted_at.is_(None),
        FinanceTransaction.dedup_status != "duplicate",
        FinanceTransaction.excluded_from_reports.is_(False),
    ]
    if owner_user_id is not None:
        filters.append(FinanceTransaction.owner_user_id == owner_user_id)
    if days is not None:
        filters.append(FinanceTransaction.date_ >= date.today() - timedelta(days=days))
    rows = (
        await db.exec(
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
                    FinanceTransaction.is_split.is_(False),
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
    split_rows = (
        await db.exec(
            select(
                FinanceTransactionSplit.category_id,
                func.count(FinanceTransactionSplit.id),
                func.coalesce(func.sum(FinanceTransactionSplit.amount), 0),
                func.max(FinanceTransaction.date_),
            )
            .join(
                FinanceTransaction,
                FinanceTransaction.id
                == FinanceTransactionSplit.parent_transaction_id,
            )
            .where(
                *filters,
                FinanceTransaction.is_split.is_(True),
                FinanceTransactionSplit.category_id.is_not(None),
            )
            .group_by(FinanceTransactionSplit.category_id)
        )
    ).all()
    if not split_rows:
        return list(rows)
    extra = {cid: (count, total, last) for cid, count, total, last in split_rows}
    merged = []
    for cat_id, name, classification, is_system, count, total, last_used in rows:
        line_count, line_total, line_last = extra.get(cat_id, (0, 0, None))
        if line_count:
            count = int(count) + int(line_count)
            total = int(total) + int(line_total)
            last_used = max(d for d in (last_used, line_last) if d is not None)
        merged.append(
            (cat_id, name, classification, is_system, count, total, last_used)
        )
    return merged


def _category_outflow_filters(
    owner_user_id: int | None,
    start: date,
    end: date | None,
    account_ids: list[int] | None,
) -> list[object]:
    """Report-included outflows on live accounts - the shared predicate
    behind every category-spend rollup. Callers add their own "which
    category column is non-NULL" clause: the parent's for unsplit rows,
    the line's when reading through ``finance_transaction_split``."""
    filters: list[object] = [
        FinanceTransaction.deleted_at.is_(None),
        FinanceTransaction.dedup_status != "duplicate",
        FinanceTransaction.excluded_from_reports.is_(False),
        FinanceTransaction.account_id.in_(live_account_ids()),
        FinanceTransaction.amount < 0,
        FinanceTransaction.date_ >= start,
    ]
    if end is not None:
        filters.append(FinanceTransaction.date_ < end)
    if account_ids is not None:
        filters.append(FinanceTransaction.account_id.in_(account_ids))
    if owner_user_id is not None:
        filters.append(FinanceTransaction.owner_user_id == owner_user_id)
    return filters


async def category_spend_totals(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    start: date,
    end: date | None = None,
    account_ids: list[int] | None = None,
) -> list[tuple[str, int]]:
    """Signed spend total per LEAF category name over the window, two
    grouped queries (unsplit parents + split lines). Callers roll up /
    sign-flip as their surface needs."""
    filters = _category_outflow_filters(owner_user_id, start, end, account_ids)
    rows = (
        await db.exec(
            select(FinanceCategory.name, func.sum(FinanceTransaction.amount))
            .join(
                FinanceCategory,
                FinanceTransaction.category_id == FinanceCategory.id,
            )
            .where(*filters, FinanceTransaction.is_split.is_(False))
            .group_by(FinanceCategory.name)
        )
    ).all()
    split_rows = (
        await db.exec(
            select(FinanceCategory.name, func.sum(FinanceTransactionSplit.amount))
            .join(
                FinanceTransaction,
                FinanceTransaction.id
                == FinanceTransactionSplit.parent_transaction_id,
            )
            .join(
                FinanceCategory,
                FinanceTransactionSplit.category_id == FinanceCategory.id,
            )
            .where(*filters, FinanceTransaction.is_split.is_(True))
            .group_by(FinanceCategory.name)
        )
    ).all()
    totals: dict[str, int] = {}
    for name, total in [*rows, *split_rows]:
        totals[name] = totals.get(name, 0) + int(total)
    return list(totals.items())


async def spending_rows(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    start: date,
    account_ids: list[int] | None = None,
    categories: list[str] | None = None,
) -> list[FinanceTransaction]:
    """The rows behind a spend slice - same predicate as
    ``category_spend_totals``, minus the GROUP BY. ``categories`` matches
    exactly or as a "name:" prefix (parent rollup drill-down). A split
    parent surfaces when one of its LINES matches - the row shown is
    still the parent, badge and lines rendered by the register."""
    filters = _category_outflow_filters(owner_user_id, start, None, account_ids)
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
        own_category = FinanceTransaction.category_id.in_(matching_ids)
        line_category = FinanceTransactionSplit.category_id.in_(matching_ids)
    else:
        own_category = FinanceTransaction.category_id.is_not(None)
        line_category = FinanceTransactionSplit.category_id.is_not(None)
    filters.append(split_aware_category_clause(own_category, line_category))
    rows = (
        await db.exec(
            select(FinanceTransaction)
            .where(*filters)
            .order_by(FinanceTransaction.date_.desc())
        )
    ).all()
    return list(rows)


async def categorized_history(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> list[FinanceTransaction]:
    """Every live categorized row (catch-all buckets excluded) - the
    precedent corpus for payee-based suggestions, one query."""
    filters = [
        FinanceTransaction.deleted_at.is_(None),
        FinanceTransaction.dedup_status != "duplicate",
        FinanceTransaction.category_id.is_not(None),
        FinanceTransaction.category_id.not_in(uncategorized_catchall_ids()),
    ]
    if owner_user_id is not None:
        filters.append(FinanceTransaction.owner_user_id == owner_user_id)
    return list((await db.exec(select(FinanceTransaction).where(*filters))).all())
