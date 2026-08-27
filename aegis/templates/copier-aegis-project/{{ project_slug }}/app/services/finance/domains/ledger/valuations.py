"""Valuations: dated marks on an account, and which one drives its balance.

A manual asset (a house, a car) has no statement to reconcile against, so
its worth is a series of dated marks, each stamped with where it came
from. The row key is ``(account_id, as_of_date, source)``, so several
sources can hold an opinion about the same day - which makes "the current
value" a question the balance rule has to answer deliberately.

Bulk ingest: a dated series from one source, in one pass.

A property's history arrives as a block - a decade of monthly estimates
pasted out of a listing site - not as one write at a time. Each row is
upserted on ``(account_id, as_of_date, source)``, so re-pasting a longer
window updates what overlaps instead of doubling the history.

The source label is the caller's honest answer to "where did this come
from": ``zillow`` for a Zestimate, ``appraisal`` for an appraisal,
``manual`` only when a human typed the figure. The model quotes whatever
it finds, so a wrong label here becomes a wrong claim later.
"""

from dataclasses import dataclass
from datetime import date

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.ledger.accounts import get_account
from app.services.finance.domains.ledger.queries import accounts as queries
from app.services.finance.models import FinanceAccount, FinanceValuation
from app.services.finance.utils import utcnow


@dataclass
class IngestResult:
    """What one ingest did, per row: new dates vs dates already held."""

    added: int = 0
    updated: int = 0

    @property
    def total(self) -> int:
        return self.added + self.updated


async def ingest_valuations(
    db: AsyncSession,
    account_id: int,
    *,
    rows: list[tuple[date, int]],
    source: str = "manual",
    is_estimate: bool = False,
    note: str | None = None,
    owner_user_id: int | None = None,
) -> IngestResult:
    """Upsert a whole series. Returns how much was new.

    Rows are applied oldest-first so the balance the writer derives on the
    way through lands on the newest date, not on whichever row happened to
    be last in the pasted block.
    """
    result = IngestResult()
    existing_dates = {
        valuation.as_of_date
        for valuation in await queries.valuations_for_account(db, account_id)
        if valuation.source == source
    }
    for as_of_date, value in sorted(rows):
        await upsert_valuation(
            db,
            account_id=account_id,
            as_of_date=as_of_date,
            value=value,
            source=source,
            note=note,
            owner_user_id=owner_user_id,
            is_estimate=is_estimate,
        )
        if as_of_date in existing_dates:
            result.updated += 1
        else:
            result.added += 1
    return result


def parse_series(text: str) -> list[tuple[date, int]]:
    """Parse a pasted ``date<sep>value`` block into rows of (date, cents).

    Accepts what a listing site's table actually pastes as - ``Aug 2026``
    or ``2026-08-01``, ``$711.2K`` or ``711200`` or ``711,200.00`` - and
    raises on a line it cannot read rather than skipping it silently: a
    dropped row in a valuation series is an invisible dent in net worth.
    """
    from app.services.finance.domains.ledger.series_parsing import parse_series_lines

    return parse_series_lines(text)


async def add_valuation(
    db: AsyncSession,
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
    db.add(valuation)
    await db.flush()
    return valuation


async def preferred_valuation_row(
    db: AsyncSession, account: FinanceAccount | None
) -> FinanceValuation | None:
    """The valuation row that drives this account's balance, if any."""
    from app.services.finance.domains.ledger.properties import property_metadata

    if account is None or account.id is None:
        return None
    meta = property_metadata(account.metadata_)
    preferred = meta.preferred_valuation_source if meta is not None else None
    if preferred is not None:
        row = await queries.latest_valuation_row(db, account.id, source=preferred)
        if row is not None:
            return row
    return await queries.latest_valuation_row(db, account.id)


async def preferred_valuation_value(
    db: AsyncSession, account: FinanceAccount | None
) -> int | None:
    """The value that should drive this account's balance.

    A property may name the source it believes (``PropertyMeta``); that
    source's newest row wins even when another source posted later. When
    the preferred source has nothing yet - a fresh appraisal preference
    on a Zillow-only history - the newest row of any source stands in,
    rather than the balance going blank.
    """
    row = await preferred_valuation_row(db, account)
    return int(row.value) if row is not None else None


async def upsert_valuation(
    db: AsyncSession,
    *,
    account_id: int,
    as_of_date: date,
    value: int,
    owner_user_id: int | None = None,
    source: str = "manual",
    source_ref: str | None = None,
    note: str | None = None,
    is_estimate: bool = False,
) -> FinanceValuation:
    """Insert or update the (account, date, source) valuation, then set the
    account's ``current_balance`` to the latest-dated valuation.

    Idempotent on ``uq_finance_valuation (account_id, as_of_date, source)``:
    a repeat write updates in place rather than duplicating.
    """
    existing = await queries.valuation_by_key(
        db, account_id=account_id, as_of_date=as_of_date, source=source
    )
    if existing is not None:
        existing.value = value
        existing.source_ref = source_ref
        existing.note = note
        existing.is_estimate = is_estimate
        existing.updated_at = utcnow()
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
            is_estimate=is_estimate,
        )
    db.add(valuation)
    await db.flush()

    # current_balance for a manual asset = its latest-dated valuation,
    # from the source the property prefers when it names one. Without
    # that rule a second provider's first ingest reprices the asset by
    # write order alone.
    account = await get_account(db, account_id, owner_user_id=owner_user_id)
    latest_value = await preferred_valuation_value(db, account)
    if account is not None and latest_value is not None:
        account.current_balance = int(latest_value)
        account.balance_as_of = utcnow()
        db.add(account)
        await db.flush()
    return valuation


async def list_valuations(
    db: AsyncSession, account_id: int, *, owner_user_id: int | None = None
) -> list[FinanceValuation]:
    """Valuation series for an account, oldest first. Empty if not owned."""
    account = await get_account(db, account_id, owner_user_id=owner_user_id)
    if account is None:
        return []
    return await queries.valuations_for_account(db, account_id)
