"""A stream's lifecycle: declare it, edit it, pause it, retire it.

Everything here is about the row itself and what the user states about
it. Deciding WHICH transaction paid a bill is ``matching``; walking the
bills forward through a balance is ``forecast``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.constants import CADENCE_KEYS, ONE_TIME_FREQUENCY
from app.services.finance.domains.ledger import accounts
from app.services.finance.domains.ledger import queries as ledger_queries
from app.services.finance.domains.planning.recurring import queries
from app.services.finance.models import (
    FinanceRecurringStream,
    FinanceTransaction,
)
from app.services.finance.utils import (
    DEFAULT_CURRENCY,
    FREQUENCY_STEPS,
    utcnow,
)

_STREAM_DIRECTIONS = frozenset({"inflow", "outflow"})


# DERIVED, never re-listed. This was a hand-written copy of the same
# six cadences and it drifted: the menus and the forecast grew
# bimonthly and semiannual, this did not, so the edit dialog offered
# cadences that raised on save. A stream may be stored with exactly
# the cadences the forecast can step - anything else is a bill that
# cannot appear in it.
_STREAM_FREQUENCIES = frozenset(CADENCE_KEYS) | {ONE_TIME_FREQUENCY}


async def list_recurring(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> list[FinanceRecurringStream]:
    """Active recurring streams, soonest-due first."""
    return await queries.active_streams(db, owner_user_id=owner_user_id)


async def create_recurring_stream(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    name: str,
    direction: str,
    frequency: str,
    expected_amount: int,
    next_expected_date: date,
    account_id: int | None = None,
    is_subscription: bool = False,
) -> FinanceRecurringStream:
    """Create a user-declared bill (outflow) or income (inflow) stream.

    Hand-entered rows are commitments by definition: ``source="user"``,
    confirmed, mature, fixed-amount - the missed-payment rule chases
    them at any cadence. Streams use the ``0`` owner sentinel in
    standalone (NULL-owner) installs, like insights.
    """
    if direction not in _STREAM_DIRECTIONS:
        raise ValueError(f"direction must be one of {sorted(_STREAM_DIRECTIONS)}")
    if frequency not in _STREAM_FREQUENCIES:
        raise ValueError(f"frequency must be one of {sorted(_STREAM_FREQUENCIES)}")
    await accounts.get_or_create_currency(db, DEFAULT_CURRENCY)
    stream = FinanceRecurringStream(
        owner_user_id=0 if owner_user_id is None else owner_user_id,
        account_id=account_id,
        name=name,
        normalized_payee=name.strip().upper(),
        direction=direction,
        frequency=frequency,
        average_amount=expected_amount,
        expected_amount=expected_amount,
        amount_is_variable=False,
        currency=DEFAULT_CURRENCY,
        next_expected_date=next_expected_date,
        status="mature",
        source="user",
        confidence=100,
        is_subscription=is_subscription,
        is_user_confirmed=True,
    )
    db.add(stream)
    await db.flush()
    return stream


async def transfer_stream_ids(db: AsyncSession, stream_ids: Sequence[int]) -> set[int]:
    """Streams with any transfer-flagged member transaction.

    Detection can build a stream out of a recurring INTERNAL transfer
    (a monthly card autopay) before pairing flags the legs. Such a
    stream is money moved, not a bill: the Bills & Income surface and
    its monthly rollup exclude it, the same way the missed-payment
    rule skips it.
    """
    return await queries.transfer_flagged_stream_ids(db, stream_ids)


async def payment_stream_ids(db: AsyncSession, stream_ids: Sequence[int]) -> set[int]:
    """The subset of streams that are card/loan PAYMENTS: their
    members are the cash side of confirmed transfers into a liability
    account.

    A payment is a transfer, but it is a payment first. The split
    matters because the two halves of the app disagree about it: the
    cash forecast must charge it (it genuinely drains checking every
    month), while the Bills total and spending math must not (the
    card swipes already counted - adding the payment double-counts
    every dollar on the card).
    """
    return await queries.payment_flagged_stream_ids(db, stream_ids)


async def get_recurring(
    db: AsyncSession, stream_id: int, owner_user_id: int | None
) -> FinanceRecurringStream | None:
    return await queries.stream_by_id(db, stream_id, owner_user_id=owner_user_id)


async def mute_recurring(
    db: AsyncSession, stream_id: int, *, owner_user_id: int | None = None
) -> FinanceRecurringStream | None:
    """Mute a stream so it stops raising price-hike insights."""
    stream = await get_recurring(db, stream_id, owner_user_id)
    if stream is None:
        return None
    stream.is_muted = True
    db.add(stream)
    await db.flush()
    return stream


async def unmute_recurring(
    db: AsyncSession, stream_id: int, *, owner_user_id: int | None = None
) -> FinanceRecurringStream | None:
    """Reverse a mute."""
    stream = await get_recurring(db, stream_id, owner_user_id)
    if stream is None:
        return None
    stream.is_muted = False
    db.add(stream)
    await db.flush()
    return stream


async def attach_transaction_to_stream(
    db: AsyncSession,
    transaction_id: int,
    stream_id: int,
    *,
    owner_user_id: int | None = None,
) -> FinanceRecurringStream | None:
    """Reconcile a stray transaction with the bill it paid.

    The automatic matcher unites the two when the payee key lines up;
    this is the manual verb for when it cannot (a changed descriptor,
    a hand-entered bill no bank string resembles). It does BOTH
    halves of the job: consumes the occurrence (membership, due date
    stepped from the payment's date - the same rule the matcher
    follows - occurrence counted), and TEACHES the payee key by
    aligning merchant between the two, so future months match on
    their own instead of putting the user on a mark-as-paid
    treadmill. The due date never moves backward: attaching June's
    charge for the record must not re-arm July's nag.
    """
    stream = await get_recurring(db, stream_id, owner_user_id)
    if stream is None:
        return None
    txn = await ledger_queries.transaction_by_id(
        db, transaction_id, owner_user_id=owner_user_id
    )
    if txn is None:
        return None

    txn.recurring_stream_id = stream.id
    # Teach whichever side knows less.
    if txn.merchant_id is not None and stream.merchant_id is None:
        stream.merchant_id = txn.merchant_id
    elif stream.merchant_id is not None and txn.merchant_id is None:
        txn.merchant_id = stream.merchant_id

    # Backfill: claim the payee's OTHER unclaimed rows too. Teaching
    # the key only helps future months - without this, last
    # quarter's payments still read as unplanned spending and the
    # "Everything else" figure double-counts the bill (confirmed
    # live: a nursing-home bill counted once in BILLS and again in
    # the observed run rate). Strays only: rows a live stream
    # already claims are not re-litigated.
    if txn.merchant_id is not None:
        strays = await queries.stray_payee_rows(
            db,
            exclude_transaction_id=txn.id,
            merchant_id=txn.merchant_id,
            inflow=stream.direction == "inflow",
            owner_clause=queries.owner_clause_txn(
                FinanceTransaction.owner_user_id, owner_user_id
            ),
        )
        for stray in strays:
            stray.recurring_stream_id = stream.id
            db.add(stray)

    stream.occurrence_count += 1
    stream.last_amount = abs(txn.amount)
    if stream.last_date is None or txn.date_ > stream.last_date:
        stream.last_date = txn.date_
    if stream.frequency == ONE_TIME_FREQUENCY:
        # "Pay someone back" has no next occurrence - the payment
        # arriving is the end of it, not a reschedule.
        stream.next_expected_date = None
    else:
        step = FREQUENCY_STEPS.get(stream.frequency)
        if step is not None:
            advanced = step(txn.date_)
            current = stream.next_expected_date
            if current is None or advanced > current:
                stream.next_expected_date = advanced

    db.add(txn)
    db.add(stream)
    await db.flush()
    return stream


async def pause_recurring(
    db: AsyncSession,
    stream_id: int,
    *,
    until: date,
    note: str | None = None,
    owner_user_id: int | None = None,
) -> FinanceRecurringStream | None:
    """Pause a stream until a date: out of the forecast, the Bills
    total, the month verdict and every nag until then - and back in
    all of them the day the date passes, by pure comparison (see
    ``is_paused``). ``note`` is the why, for the future reader who
    forgot ("waiting until the pool is paid off"); it rides in
    ``metadata_`` rather than a column because it is prose for one
    surface, not a fact anything computes on.
    """
    stream = await get_recurring(db, stream_id, owner_user_id)
    if stream is None:
        return None
    stream.paused_until = until
    if note and note.strip():
        stream.metadata_ = {**(stream.metadata_ or {}), "pause_note": note.strip()}
    db.add(stream)
    await db.flush()
    return stream


async def resume_recurring(
    db: AsyncSession, stream_id: int, *, owner_user_id: int | None = None
) -> FinanceRecurringStream | None:
    """End a pause early. Clears the note too - a stale reason
    explaining a pause that is no longer happening is worse than no
    note at all."""
    stream = await get_recurring(db, stream_id, owner_user_id)
    if stream is None:
        return None
    stream.paused_until = None
    if stream.metadata_ and "pause_note" in stream.metadata_:
        stream.metadata_ = {
            k: v for k, v in stream.metadata_.items() if k != "pause_note"
        }
    db.add(stream)
    await db.flush()
    return stream


async def confirm_recurring(
    db: AsyncSession, stream_id: int, *, owner_user_id: int | None = None
) -> FinanceRecurringStream | None:
    """Mark a detected stream as a real commitment (bill or income).

    Confirmation is what promotes a guess into something the missed-
    payment rule will chase regardless of amount variability.
    """
    stream = await get_recurring(db, stream_id, owner_user_id)
    if stream is None:
        return None
    stream.is_user_confirmed = True
    db.add(stream)
    await db.flush()
    return stream


async def update_recurring(
    db: AsyncSession,
    stream_id: int,
    *,
    owner_user_id: int | None = None,
    name: str | None = None,
    frequency: str | None = None,
    expected_amount: int | None = None,
    next_expected_date: date | None = None,
    category_id: int | None = None,
    account_id: int | None = None,
) -> FinanceRecurringStream | None:
    """Edit a stream's declared facts; ``None`` fields are left alone.

    ``category_id`` is stated ABOUT THE BILL and stops there: the
    member transactions keep whatever they already had. A bill's
    category is otherwise inferred from them (see
    ``stream_category_names``), and cascading would overwrite
    per-transaction corrections made by hand to fix an inference.

    Setting an expected amount pins the stream fixed-amount
    (``amount_is_variable`` off): the user is stating what the bill IS,
    which beats the detector's average. Renaming only re-keys
    ``normalized_payee`` on hand-entered streams - a detected stream's
    payee key is how the detector re-finds it, and changing it would
    make the next detection pass spawn a duplicate.
    """
    if frequency is not None and frequency not in _STREAM_FREQUENCIES:
        raise ValueError(f"frequency must be one of {sorted(_STREAM_FREQUENCIES)}")
    stream = await get_recurring(db, stream_id, owner_user_id)
    if stream is None:
        return None
    if name is not None and name.strip():
        stream.name = name.strip()
        if stream.source == "user":
            stream.normalized_payee = name.strip().upper()
    if frequency is not None:
        stream.frequency = frequency
    if expected_amount is not None:
        stream.expected_amount = expected_amount
        stream.amount_is_variable = False
    if next_expected_date is not None:
        stream.next_expected_date = next_expected_date
    elif frequency in FREQUENCY_STEPS and stream.next_expected_date is None:
        # A cadence with no date to apply it to still projects
        # nothing, so stating one has to complete the repair. This is
        # the shape a bill takes when it has been seen ONCE: no gap to
        # measure, so no cadence and no next date - it sits in Bills
        # reading "Active" and contributes zero to the forecast.
        # Stepped from the last occurrence when there is one; the
        # forecast rolls a past date forward on its own.
        step = FREQUENCY_STEPS[frequency]
        stream.next_expected_date = step(stream.last_date or date.today())
    if category_id is not None:
        stream.category_id = category_id
    if account_id is not None and account_id != stream.account_id:
        # (owner, account, direction, normalized_payee) is unique - it
        # is the key detection re-finds a stream by. Moving accounts
        # can land on a bill already there, so check first and refuse
        # with something the API can turn into a 409 rather than
        # letting the index raise as a 500.
        # NOT filtered on deleted_at: the unique index has no such
        # predicate (only provider_stream_id IS NULL), so a retired
        # row still occupies the slot. Filtering it out here let the
        # UPDATE hit the index and surface as a 500.
        clash = await queries.stream_slot_clash(
            db,
            owner_user_id=stream.owner_user_id,
            account_id=account_id,
            direction=stream.direction,
            normalized_payee=stream.normalized_payee,
            exclude_stream_id=stream.id,
        )
        if clash is not None and clash.deleted_at is None:
            raise ValueError(f'"{clash.name}" already exists on that account.')
        if clash is not None:
            # Retired, so refusing would block the move on a row the
            # user cannot see. Free the key instead of deleting the
            # history: the ghost stays for the record, it just stops
            # holding a slot it no longer uses.
            clash.normalized_payee = f"{clash.normalized_payee}#retired{clash.id}"
            db.add(clash)
            await db.flush()
        stream.account_id = account_id
    db.add(stream)
    await db.flush()
    return stream


async def stream_category_names(
    db: AsyncSession, stream_ids: Sequence[int] | set[int]
) -> dict[int, str]:
    """Each stream's category, derived from its member transactions.

    ``finance_recurring_stream.category_id`` is a provider field the
    local detector never fills, so the stream table itself has no
    category to show. The transactions DO carry one (import maps the
    Quicken category path), and a stream is one merchant's rhythm -
    so the most common category across its members is the stream's
    category. Ties break on the higher count, then category id.
    """
    ids = list(stream_ids)
    if not ids:
        return {}
    rows = await queries.stream_member_category_votes(db, ids)
    best: dict[int, tuple[int, str]] = {}
    for stream_id, name, hits in rows:
        current = best.get(stream_id)
        if current is None or hits > current[0]:
            best[stream_id] = (hits, name)
    resolved = {stream_id: name for stream_id, (_, name) in best.items()}

    # A category set ON THE BILL outranks the inference. Without this
    # the edit saves to a column nothing reads, and Bills & Income
    # keeps showing whatever its transactions vote for - the change
    # looks accepted and does nothing.
    stored = await queries.stream_stored_category_names(db, ids)
    resolved.update({stream_id: name for stream_id, name in stored if name})
    return resolved


async def delete_recurring(
    db: AsyncSession, stream_id: int, *, owner_user_id: int | None = None
) -> bool:
    """Soft-delete a stream (the row survives; it drops from listings).

    A derived stream is also muted: the detector resurrects its row
    when the rhythm keeps firing on import, and mute survives that
    resurrection - a deleted guess can come back silent, never loud.
    """
    stream = await get_recurring(db, stream_id, owner_user_id)
    if stream is None:
        return False
    stream.deleted_at = utcnow()
    if stream.source != "user":
        stream.is_muted = True
    # Free the members. Leaving them claimed by the corpse made them
    # invisible to Match (claimed) AND to re-detection (pinned), so a
    # confirmed twin of a deleted duplicate starved forever - 366
    # transactions sat zombie-claimed by 20 dead streams before this
    # released on delete (the purge path always did; this path
    # never had).
    members = await queries.stream_members(db, stream.id)
    for member in members:
        member.recurring_stream_id = None
        db.add(member)
    db.add(stream)
    await db.flush()
    return True


async def card_payment_stream_ids(
    db: AsyncSession, stream_ids: Sequence[int]
) -> set[int]:
    """The card-only subset of ``payment_stream_ids`` - see the query."""
    return await queries.card_payment_stream_ids(db, stream_ids)
