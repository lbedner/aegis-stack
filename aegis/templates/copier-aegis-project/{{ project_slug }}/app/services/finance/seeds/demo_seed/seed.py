"""One deterministic pass: clear, write, curate, count.

Everything goes through the real service layer rather than direct
inserts, so the demo dataset is one a user could have produced.
"""

from __future__ import annotations

from datetime import timedelta

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.detection import (
    detect_recurring,
    detect_transfers,
    generate_insights,
)
from app.services.finance.domains.ledger import networth
from app.services.finance.models import (
    FinanceRecurringStream,
)
from app.services.finance.seeds.demo_household import (
    _COMMITMENT_PAYEES,
)
from app.services.finance.seeds.demo_plan import (  # noqa: F401
    _DEFAULT_MONTHS,
    _SEED,
    PlannedSplit,
    PlannedTransaction,
    _day_in_month,
    _jitter,
    _month_starts,
    build_demo_ledger,
)
from app.services.finance.seeds.demo_seed.clear import _delete_demo_rows
from app.services.finance.seeds.demo_seed.curate import (
    _count_derived,
    _file_proposals,
    _name_payees,
)
from app.services.finance.seeds.demo_seed.shared import (
    _IMPORT_WINDOW_DAYS,
    DemoSeedResult,
    _demo_accounts,
)
from app.services.finance.seeds.demo_seed.write import (
    _create_accounts,
    _write_investments,
    _write_transactions,
    _write_valuations,
)
from app.services.finance.service import FinanceService
from app.services.finance.utils import current_date


async def seed_demo(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    reset: bool = False,
    months: int = _DEFAULT_MONTHS,
) -> DemoSeedResult:
    """Populate a believable finance dataset. Writes; the caller commits.

    Idempotent: a second run without ``reset`` is a no-op and reports
    ``skipped``. With ``reset``, previously seeded rows are deleted first and
    the dataset is rebuilt.
    """
    existing = await _demo_accounts(db, owner_user_id)
    if existing and not reset:
        return DemoSeedResult(skipped=True)
    if reset:
        await _delete_demo_rows(db, owner_user_id)

    service = FinanceService(db)
    anchor = current_date()
    window_start = _month_starts(anchor, months)[0]
    ledger = build_demo_ledger(anchor=anchor, months=months)

    accounts = await _create_accounts(service, owner_user_id)
    direct, imported, splits = await _write_transactions(
        service,
        accounts,
        ledger,
        owner_user_id=owner_user_id,
        import_cutoff=anchor - timedelta(days=_IMPORT_WINDOW_DAYS),
    )
    trades, market_value = await _write_investments(
        service, accounts, owner_user_id=owner_user_id, anchor=anchor, months=months
    )
    valuations = await _write_valuations(
        service,
        accounts,
        ledger,
        owner_user_id=owner_user_id,
        anchor=anchor,
        months=months,
        brokerage_value=market_value,
    )

    # Return values deliberately ignored: ``ingest_transactions`` runs these
    # same detectors at the end of the import above, so by now most pairs are
    # already made and a detector's own counter reports only what THIS pass
    # added. Both are idempotent, and running them here is what covers the
    # entries that never went through the import lane. The counts below come
    # from the rows themselves.
    # Full history on purpose: the seed writes months of activity and the
    # demo should show transfers detected across all of it.
    await detect_transfers(db, owner_user_id=owner_user_id, lookback_days=0)
    await _name_payees(
        db, owner_user_id=owner_user_id, account_ids=[a.id for a in accounts.values()]
    )
    await detect_recurring(db, owner_user_id=owner_user_id)
    # One more insight pass now that every leg is paired: the per-batch
    # passes above ran before some transfer partners existed, and the rules
    # retract their own now-provably-wrong alerts (e.g. a "transfer hasn't
    # been paid" raised when only one leg had landed).
    # The demo household has confirmed its detected bills - under the
    # record/proposal split an unconfirmed stream counts for nothing, and
    # a showcase with an empty forecast and no missed-bill insights would
    # demo a product nobody configured.
    demo_streams = (
        await db.exec(
            select(FinanceRecurringStream).where(
                FinanceRecurringStream.owner_user_id
                == (0 if owner_user_id is None else owner_user_id),
                FinanceRecurringStream.deleted_at.is_(None),
            )
        )
    ).all()
    for stream in demo_streams:
        # Confirm what the household would: its income, its bills, its
        # subscriptions. Not every rhythm the detector found - a grocery
        # habit confirmed as a bill reads as delinquent the moment one gap
        # outruns the grace window - and not by the fixed-amount flag,
        # which skips the one subscription whose price changed: the
        # stream a price-hike finding is about.
        if stream.direction != "inflow" and stream.name not in _COMMITMENT_PAYEES:
            continue
        stream.is_user_confirmed = True
        db.add(stream)
    await db.flush()
    await _file_proposals(
        db,
        service,
        owner_user_id=owner_user_id,
        account_ids=[a.id for a in accounts.values()],
    )
    await generate_insights(db, owner_user_id=owner_user_id)
    net_worth_days = await networth.recompute_snapshots(
        db, owner_user_id=owner_user_id, start_date=window_start
    )

    account_ids = [a.id for a in accounts.values()]
    transfers, recurring = await _count_derived(db, account_ids)
    return DemoSeedResult(
        accounts=len(accounts),
        transactions=direct + imported,
        imported_rows=imported,
        splits=splits,
        transfers=transfers,
        recurring=recurring,
        valuations=valuations,
        trades=trades,
        net_worth_days=net_worth_days,
        reset=reset,
    )
