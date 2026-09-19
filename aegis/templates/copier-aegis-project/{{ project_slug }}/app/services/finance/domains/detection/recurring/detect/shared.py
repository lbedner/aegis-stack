"""What a candidate is, and what already counts as curated."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlmodel import or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.detection import queries
from app.services.finance.models import (
    FinanceAccount,
    FinanceTransaction,
    FinanceTransfer,
)
from app.services.shared.queries import owner_clause


class RecurringDetectionResult(BaseModel):
    """Counts from one detection pass."""

    detected: int = 0
    # Streams retired because nothing points at them any more - see
    pruned: int = 0


def candidate_filters(owner_user_id: int | None) -> list[Any]:
    """The rows a recurring stream can be made of: the owner's live, posted,
    non-duplicate rows, ordinary only. Transfer legs and excluded
    bookkeeping recur with steady descriptors, exactly the shape this
    hunts, and must not become "bills"; the one carve-out is the cash leg
    of a card/loan payment (``_payment_leg``), a transfer the cash forecast
    genuinely has to know about. Detection and declaration share this so a
    declared stream and a detected one are made of the same kind of rows.
    """
    return [
        owner_clause(FinanceTransaction.owner_user_id, owner_user_id),
        FinanceTransaction.deleted_at.is_(None),
        FinanceTransaction.dedup_status != "duplicate",
        or_(
            (FinanceTransaction.is_transfer.is_(False))
            & (FinanceTransaction.excluded_from_reports.is_(False)),
            _payment_leg(),
        ),
        FinanceTransaction.status == "posted",
    ]


def _payment_leg():
    """SQL predicate: this row is the CASH side of a confirmed transfer
    into a liability account - a credit-card or loan payment.

    A payment is a transfer, but it is a payment FIRST: it drains the
    checking account on a rhythm the cash forecast has to know about.
    Excluding all transfer legs from detection meant the largest single
    monthly outflow (the card autopay) could never form a stream -
    nothing to confirm, nothing to project, and a runway optimistic by
    the whole payment (confirmed live). Only the outflow leg qualifies;
    the card-side inflow, and asset-to-asset moves, stay out.
    """
    return (
        select(FinanceTransfer.id)
        .join(
            FinanceAccount,
            FinanceAccount.id
            == select(FinanceTransaction.account_id)
            .where(FinanceTransaction.id == FinanceTransfer.to_transaction_id)
            .scalar_subquery(),
        )
        .where(
            FinanceTransfer.from_transaction_id == FinanceTransaction.id,
            FinanceTransfer.status == "confirmed",
            FinanceAccount.classification == "liability",
        )
        .exists()
    )


async def _curated_members(db: AsyncSession, owner_user_id: int | None) -> set[int]:
    """Transactions belonging to a stream the user would call a real bill.

    Detection is a proposal engine, and anything the user SET - confirmed
    by hand, or typed in - is off limits, along with every transaction
    inside it. Re-scan is a button people press to pick up new payees; it
    must not be capable of renaming, re-keying, merging, re-amounting or
    pruning a bill they settled, and "it only ever improves things" is not
    a promise worth betting someone's forecast on.

    ``is_subscription`` deliberately does NOT count, even though the Bills
    tab shows those rows: that flag is the detector's own guess (every
    fixed monthly outflow earns it automatically), so honouring it here
    would freeze detection's output after a single pass and it could never
    correct itself. Which is also why Bills currently holds 56 rows nobody
    confirmed - see _is_curated in the Bills tab.

    The cost, stated plainly: a curated bill no longer absorbs next
    month's charge on its own. Growing it is now an explicit act (Make
    recurring from the register, or the bill's own edit dialog) rather
    than something a background pass does to a row you already settled.
    """
    ids = await queries.confirmed_stream_ids(db)
    return await queries.member_ids_of_streams(db, ids, owner_user_id)
