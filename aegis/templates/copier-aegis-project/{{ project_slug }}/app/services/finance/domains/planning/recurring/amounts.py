"""Re-read every bill's amount from the transactions that paid it.

``average_amount`` is what every surface shows for a bill (the whole app
reads ``stream.amount``, and most streams have no
``expected_amount``), but only two things ever wrote it: the nightly
detector, which permanently skips user-confirmed streams, and the attach
path, which until now did not. So a bill's amount froze on the day it was
confirmed - 49 of this ledger's 56 detected streams are confirmed, and
Netflix was quoting $21.61 against a $29.18 charge.

The attach fix keeps new ones honest. This is for the ones already
frozen, and like ``recompute_payee_aliases`` it is a recompute rather
than a one-off backfill: it answers to the member transactions, so
running it twice changes nothing, and it is the right verb again after a
restore, after a bulk re-match, or after the window rule is retuned.
"""

from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.detection.recurring.cadence import amount_profile
from app.services.finance.domains.planning.recurring import queries
from app.services.finance.domains.planning.recurring.membership import claimable_strays
from app.services.finance.utils import current_date


async def recompute_stream_amounts(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> dict[str, int]:
    """Rewrite ``average_amount``/``amount_is_variable`` from members.

    Membership first, because the amount is read off it. The backfill
    that runs on attach used to claim the whole payee, so the streams
    this has to repair are holding rows that were never payments - Citi
    with three interest lines a statement, CVS with 273 shopping trips.
    Those are RELEASED (``recurring_stream_id`` cleared), not deleted:
    they go back to unclaimed and can be matched again. A row the user
    attached by hand is indistinguishable from one the old backfill
    swept in, so a hand-made match that breaks the one-per-period rule
    is released too - which is why this is a command and not something
    that runs on its own.

    Returns counts of streams seen, members released and amounts
    changed.
    """
    today = current_date()
    streams = [
        s
        for s in await queries.all_live_streams(db)
        if owner_user_id is None or s.owner_user_id == owner_user_id
    ]
    members = await queries.members_of_streams(
        db, [s.id for s in streams if s.id is not None]
    )
    changed = 0
    released = 0
    for stream in streams:
        rows = [t for t in members.get(stream.id or 0, []) if t.deleted_at is None]
        if not rows:
            # No evidence is not the same as "it costs nothing": a bill
            # nothing points at yet keeps whatever it was told.
            continue
        keep = claimable_strays(stream, rows, [], band=False)
        kept = {t.id for t in keep}
        for row in rows:
            if row.id not in kept:
                row.recurring_stream_id = None
                db.add(row)
                released += 1
        rows = keep or rows
        amount, variable = amount_profile(rows, today=today)
        if amount == stream.average_amount and variable == stream.amount_is_variable:
            continue
        stream.average_amount = amount
        stream.amount_is_variable = variable
        db.add(stream)
        changed += 1
    await db.flush()
    return {"streams": len(streams), "released": released, "changed": changed}
