"""The rows behind one summary stat, when a user opens it."""

from __future__ import annotations

from datetime import date

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.detection.insights.commitments import (
    MONTHLY_FACTOR,
    commitment_rollup,
    is_commitment,
    is_paused,
    monthly_share,
    monthly_share_of,
    shown_cadence,
)
from app.services.finance.domains.ledger import categories
from app.services.finance.domains.planning import recurring
from app.services.finance.domains.planning.budgets.uncovered import (
    uncovered_spend,
    uncovered_spend_filters,
)
from app.services.finance.schemas import (
    BudgetStatDetailsResponse,
    StatDetailRow,
)
from app.services.finance.utils import (
    current_date,
)


async def budget_stat_details(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    today: date | None = None,
    account_ids: list[int] | None = None,
) -> BudgetStatDetailsResponse:
    """Per-row backup for the header cells, for the click-a-cell popup.

    Income and Bills mirror the cells' own math row for row (same
    commitment gate, same monthly-equivalent factors as
    ``monthly_income``/``commitment_rollup``), so the rows always sum
    to the cell. Everything-else is the uncovered-spend bucket grouped
    by category, over the SAME filters as the rate.
    """
    today = today or current_date()
    # The same stream set the cells are computed from, filtered the same
    # way: a popup that explains a number has to be about that number.
    # Without this, narrowing to one account left the cell filtered and
    # its detail listing every account the owner has.
    streams = await recurring.list_recurring(db, owner_user_id=owner_user_id)
    transfer_ids = await recurring.transfer_stream_ids(db, [s.id for s in streams])
    streams = [s for s in streams if s.id not in transfer_ids]
    streams = [s for s in streams if recurring.in_account_scope(s, account_ids)]

    income_rows = [
        StatDetailRow(
            label=s.name,
            value=monthly_share_of(s.amount, s.frequency),
            frequency=shown_cadence(s.frequency),
        )
        for s in streams
        if s.direction == "inflow"
        and not s.is_muted
        and not is_paused(s, today)
        and is_commitment(s)
        and MONTHLY_FACTOR.get(s.frequency, 0.0) > 0
    ]
    income_rows.sort(key=lambda r: -r.value)

    rollup = commitment_rollup(streams, today=today)
    bills_rows = [
        StatDetailRow(
            label=s.name,
            value=monthly_share(s),
            frequency=shown_cadence(s.frequency),
            per_period_amount=None
            if shown_cadence(s.frequency) is None
            else int(s.average_amount or 0),
        )
        for s in rollup["fixed"] + rollup["non_monthly"]
    ]
    bills_rows.sort(key=lambda r: -r.value)

    _filters, (window_start, window_end) = await uncovered_spend_filters(
        db, owner_user_id=owner_user_id, today=today, account_ids=account_ids
    )
    uncovered = await uncovered_spend(
        db, owner_user_id=owner_user_id, today=today, account_ids=account_ids
    )
    names = await categories.category_names(
        db, {cid for cid in uncovered.counts if cid}
    )

    def _rows(by_category: dict[int | None, int]) -> list[StatDetailRow]:
        rows = [
            StatDetailRow(
                label=names.get(category_id) or "Uncategorized",
                value=value,
                transaction_count=uncovered.counts.get(category_id, 0),
            )
            for category_id, value in by_category.items()
        ]
        rows.sort(key=lambda r: -r.value)
        return rows

    # Two lists, because they are two different units: a monthly rate and
    # a window total. Each sums to the figure it explains.
    else_rows = _rows(uncovered.rate_by_category)
    one_off_rows = _rows(uncovered.one_off_by_category)

    return BudgetStatDetailsResponse(
        income=income_rows,
        bills=bills_rows,
        everything_else=else_rows,
        one_offs=one_off_rows,
        window_start=window_start,
        window_end=window_end,
    )
