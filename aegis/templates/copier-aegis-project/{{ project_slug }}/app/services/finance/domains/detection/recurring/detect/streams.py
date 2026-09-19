"""Writing a detected stream, carrying curation forward.

A re-detected stream must keep what a user already decided about
it, which is what ``_inherited_curation`` reads back.
"""

from __future__ import annotations

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.detection import queries
from app.services.finance.domains.detection.recurring.cadence import (
    MIN_OCCURRENCES,
)
from app.services.finance.domains.detection.recurring.resolve import (
    _dismissed_twin,
)
from app.services.finance.models import (
    FinanceRecurringStream,
)


class _InheritedCuration(BaseModel):
    is_user_confirmed: bool = False
    is_subscription: bool = False
    is_muted: bool = False


async def _inherited_curation(
    db: AsyncSession, stream_ids: set[int]
) -> _InheritedCuration:
    """Curation carried by the streams these transactions are leaving.

    Any predecessor being confirmed (or a recognized subscription) makes
    the successor so: the user's decision was about the MERCHANT, and a
    descriptor changing is not them changing their mind. Muted is
    inherited the same way and for the same reason - a silenced bill that
    un-silences itself because its bank restated a descriptor is worse
    than one that stays quiet.
    """
    ids = {i for i in stream_ids if i is not None}
    if not ids:
        return _InheritedCuration()
    rows = await queries.streams_by_ids(db, ids)
    return _InheritedCuration(
        is_user_confirmed=any(r.is_user_confirmed for r in rows),
        is_subscription=any(r.is_subscription for r in rows),
        is_muted=any(r.is_muted for r in rows),
    )


async def _upsert_stream(
    db: AsyncSession,
    *,
    owner_user_id: int,
    account_id: int,
    direction: str,
    payee: str,
    merchant_id: int | None,
    name: str,
    frequency: str,
    average_amount: int,
    last_amount: int,
    first_date,
    last_date,
    next_expected_date,
    occurrence_count: int,
    variable: bool,
    is_subscription: bool,
    confidence: int,
    is_user_confirmed: bool = False,
    is_muted: bool = False,
    currency: str,
    revive_retired: bool = False,
) -> FinanceRecurringStream | None:
    """Insert or update the detected stream (keyed by the detected unique).

    Returns ``None`` when the key belongs to a stream that was retired and
    has seen nothing new since - the caller skips the group rather than
    resurrecting it. ``revive_retired`` overrides that for the user's own
    "Make recurring": declaring a bill IS the new evidence.
    """
    existing = await queries.local_stream_by_key(
        db,
        owner_user_id=owner_user_id,
        account_id=account_id,
        direction=direction,
        normalized_payee=payee,
    )
    if existing is None:
        # A dismissal must survive a key respelling (a normalization
        # change, descriptor drift): re-key the tombstone and refresh
        # its facts below - muted and hidden it stays - rather than
        # letting the purge eat it and this pass repropose it loud.
        existing = await _dismissed_twin(
            db,
            owner_user_id=owner_user_id,
            account_id=account_id,
            direction=direction,
            payee=payee,
            frequency=frequency,
            average_amount=average_amount,
        )
        if existing is not None:
            existing.normalized_payee = payee
    status = "mature" if occurrence_count >= MIN_OCCURRENCES else "early_detection"
    if existing is not None:
        existing.name = name
        existing.merchant_id = merchant_id
        # Only ever ADD curation here - detection must not un-confirm or
        # un-mute something the user decided about.
        existing.is_user_confirmed = existing.is_user_confirmed or is_user_confirmed
        existing.is_muted = existing.is_muted or is_muted
        existing.frequency = frequency
        existing.average_amount = average_amount
        existing.last_amount = last_amount
        existing.first_date = first_date
        existing.last_date = last_date
        existing.next_expected_date = next_expected_date
        existing.occurrence_count = occurrence_count
        existing.amount_is_variable = variable
        existing.is_subscription = is_subscription
        existing.confidence = confidence
        existing.status = status
        # Dismissals persist: a muted or deleted proposal stays silent and
        # hidden while its facts refresh. Only the user's own "Make
        # recurring" (revive_retired) brings a row back to life.
        if revive_retired:
            existing.deleted_at = None
        db.add(existing)
        await db.flush()
        return existing
    stream = FinanceRecurringStream(
        owner_user_id=owner_user_id,
        account_id=account_id,
        direction=direction,
        # For a merchant-keyed group this is the synthetic "merchant:{id}"
        # key, not a descriptor - the column is purely the detected-stream
        # unique key (uq_finance_recurring_detected), never displayed
        # anywhere (Bills & Income shows ``name``), so it can carry either
        # without a migration to widen the index.
        normalized_payee=payee,
        merchant_id=merchant_id,
        name=name,
        frequency=frequency,
        average_amount=average_amount,
        last_amount=last_amount,
        currency=currency,
        first_date=first_date,
        last_date=last_date,
        next_expected_date=next_expected_date,
        occurrence_count=occurrence_count,
        amount_is_variable=variable,
        is_subscription=is_subscription,
        is_user_confirmed=is_user_confirmed,
        is_muted=is_muted,
        confidence=confidence,
        status=status,
        source="derived",
    )
    db.add(stream)
    await db.flush()
    return stream
