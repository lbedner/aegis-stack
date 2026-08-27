"""The nightly pass: find the rhythms, upsert them, retire the dead ones.

Runs per owner after each sync/import. Idempotent - streams upsert on the
detected-stream unique key and members back-link via
``finance_transaction.recurring_stream_id`` - so a second pass over the
same ledger writes nothing new.

Confidence and maturity rather than a boolean, because an annual charge
is invisible for a year. The purge half is the other side of that
patience: a proposal nothing points at any more has to go, or the list
fills with guesses that were wrong in 2019.
"""

from __future__ import annotations

from datetime import date, timedelta
import statistics

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.log import logger
from app.services.finance.domains.detection import queries
from app.services.finance.domains.detection.recurring.cadence import (
    _SUBSCRIPTION_FREQUENCIES,
    AMOUNT_TOLERANCE,
    MIN_OCCURRENCES,
    MIN_RHYTHM_RATIO,
    MIN_STREAM_AMOUNT,
    _canonical_days,
    _frequency_for,
    _has_gone_quiet,
    _payee_key,
    _rhythm_ratio,
    split_interleaved,
)
from app.services.finance.domains.detection.recurring.resolve import (
    _dismissed_twin,
    _is_the_bill_again,
    _resolve_payee_key,
)
from app.services.finance.models import (
    FinanceAccount,
    FinanceInsight,
    FinanceRecurringStream,
    FinanceTransaction,
    FinanceTransfer,
)


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


class RecurringDetectionResult(BaseModel):
    """Counts from one detection pass."""

    detected: int = 0
    # Streams retired because nothing points at them any more - see
    pruned: int = 0


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


async def detect_recurring(
    db: AsyncSession, *, owner_user_id: int | None, today: date | None = None
) -> RecurringDetectionResult:
    """Detect + upsert recurring streams for one owner. Idempotent.

    Streams/insights have a NOT-NULL owner, so a standalone (NULL-owner) install
    stores them under the ``0`` sentinel while scanning its NULL-owner rows.
    """
    result = RecurringDetectionResult()
    store_owner = 0 if owner_user_id is None else owner_user_id
    today = today or date.today()

    accounts = await queries.account_rows_where(
        db,
        [
            FinanceAccount.deleted_at.is_(None),
            queries.owner_clause(FinanceAccount.owner_user_id, owner_user_id),
        ],
    )
    acct_ids = [a.id for a in accounts]
    if not acct_ids:
        return result
    # Money ARRIVING on a credit card is a payment toward it, never
    # household income - it came from another account of yours. Knowable
    # structurally, which matters because the matching outflow is often
    # not imported at all (81 AMEX credits here with no counterpart).
    # Spending charged TO the card is untouched: that is an ordinary bill.
    liability_accounts = {a.id for a in accounts if a.classification == "liability"}

    txns = await queries.transaction_rows_where(
        db,
        [
            queries.owner_clause(FinanceTransaction.owner_user_id, owner_user_id),
            FinanceTransaction.deleted_at.is_(None),
            FinanceTransaction.dedup_status != "duplicate",
            # Ordinary rows only - transfer legs and excluded
            # bookkeeping recur with steady descriptors, exactly the
            # shape this hunts, and must not become "bills". The one
            # carve-out is the cash leg of a card/loan payment (see
            # _payment_leg): a payment is a transfer that the cash
            # forecast genuinely has to know about.
            or_(
                (FinanceTransaction.is_transfer.is_(False))
                & (FinanceTransaction.excluded_from_reports.is_(False)),
                _payment_leg(),
            ),
            FinanceTransaction.status == "posted",
            FinanceTransaction.account_id.in_(list(acct_ids)),
        ],
    )

    # Group by (account, direction, payee key) - see _payee_key: an
    # assigned merchant, else the normalized descriptor. Transactions the
    # user pinned by confirming their bill are skipped outright: they
    # already have an owner, and regrouping them is how an exclusion or a
    # split gets silently undone overnight.
    curated = await _curated_members(db, owner_user_id)
    # Confirmed bills by (account, direction), for the repropose guard:
    # a group that IS one of these must release, not duplicate. Streams
    # are STORED under ``store_owner`` (0 for a standalone install), so
    # the read matches that, not the raw argument - owner_clause's
    # IS NULL would find nothing a standalone install ever wrote.
    confirmed_by_slot: dict[tuple[int | None, str], list[FinanceRecurringStream]] = {}
    for bill in await queries.stream_rows_where(
        db,
        [
            FinanceRecurringStream.owner_user_id == store_owner,
            or_(
                FinanceRecurringStream.is_user_confirmed.is_(True),
                FinanceRecurringStream.source == "user",
            ),
        ],
    ):
        confirmed_by_slot.setdefault((bill.account_id, bill.direction), []).append(bill)
    groups: dict[tuple[int, str, str], list[FinanceTransaction]] = {}
    for txn in txns:
        # Already spoken for by a real bill - not detection's business.
        if txn.id in curated:
            continue
        key = _payee_key(txn)
        if not key:
            continue
        direction = "outflow" if txn.amount < 0 else "inflow"
        if direction == "inflow" and txn.account_id in liability_accounts:
            continue
        groups.setdefault((txn.account_id, direction, key), []).append(txn)

    # Display names for merchant-keyed groups, in one query - a stream
    # named "merchant:12" would be nonsense in Bills & Income.
    merchant_ids = {t.merchant_id for t in txns if t.merchant_id is not None}
    merchant_names = await queries.merchant_names_by_ids(db, merchant_ids)

    # Only discovered groups do any work. A curated stream - anything in
    # Bills or Income - and every transaction inside it were removed above
    # and are not represented here at all, so nothing below can rename,
    # re-key, merge, re-amount or prune one.
    work: list[tuple[int, str, str, list[FinanceTransaction]]] = [
        (account_id, direction, payee, members)
        for (account_id, direction, payee), members in groups.items()
    ]
    touched: set[int] = set()

    def _release(members: list[FinanceTransaction]) -> None:
        """A rejected group's members must not keep pointing at a row the
        purge below is about to hard-delete."""
        for member in members:
            if member.recurring_stream_id is not None:
                member.recurring_stream_id = None
                db.add(member)

    # One payee interleaving two subscriptions (Apple billing iCloud
    # and Music on one descriptor) either has no rhythm as a single
    # group or fakes a shorter cadence from the interleaved gaps -
    # see split_interleaved for the banding rule and its guardrails.
    work, unbanded = split_interleaved(work, today)
    _release(unbanded)

    for account_id, direction, payee, members in work:
        if len(members) < MIN_OCCURRENCES:
            _release(members)
            continue
        members.sort(key=lambda t: (t.date_, t.id or 0))
        gaps = [
            (members[i].date_ - members[i - 1].date_).days
            for i in range(1, len(members))
        ]
        gaps = [g for g in gaps if g > 0]
        if not gaps:
            _release(members)
            continue
        median_interval = statistics.median(gaps)
        matched = _frequency_for(median_interval)
        if matched is None:
            _release(members)
            continue  # no stable cadence -> not a recurring stream
        frequency = matched
        # A median can land on a cadence by coincidence. Require that the
        # gaps themselves mostly agree, or a handful of unrelated visits
        # to the same shop becomes a subscription.
        canonical = _canonical_days(frequency)
        rhythm = _rhythm_ratio(gaps, canonical) if canonical else 0.0
        if rhythm < MIN_RHYTHM_RATIO:
            _release(members)
            continue
        # Real cadence, but it stopped. Releasing lets the prune pass
        # retire it rather than leaving a dead bill in the rollup and the
        # forecast for years.
        if _has_gone_quiet(members[-1].date_, canonical, today):
            _release(members)
            continue

        amounts = [abs(t.amount) for t in members]
        median_amount = int(statistics.median(amounts))
        if median_amount < MIN_STREAM_AMOUNT:
            _release(members)
            continue
        if _is_the_bill_again(
            confirmed_by_slot.get((account_id, direction), []),
            payee,
            frequency,
            median_amount,
        ):
            _release(members)
            continue
        variable = any(
            abs(a - median_amount) > median_amount * AMOUNT_TOLERANCE for a in amounts
        )
        last = members[-1]
        is_subscription = (
            direction == "outflow"
            and frequency in _SUBSCRIPTION_FREQUENCIES
            and not variable
        )
        # Fit first, evidence second. The old formula was
        # 50 + 10*occurrences + 20 if fixed, so MORE random visits raised
        # confidence - Stewart's scored 90.
        confidence = int(
            round(
                40
                + 30 * rhythm
                + 10 * min(len(members) / 6, 1.0)
                + (0 if variable else 20)
            )
        )
        merchant_id = last.merchant_id
        # A confirmed bill already on this key owns its own membership, so
        # an unpinned group of the same payee is a DIFFERENT bill and gets
        # its own key rather than being merged into someone's decision.
        resolved_key, _target = await _resolve_payee_key(
            db,
            owner_user_id=store_owner,
            account_id=account_id,
            direction=direction,
            base=payee,
            member_ids={m.id for m in members if m.id is not None},
        )
        try:
            async with db.begin_nested():
                stream = await _upsert_stream(
                    db,
                    owner_user_id=store_owner,
                    account_id=account_id,
                    direction=direction,
                    payee=resolved_key,
                    merchant_id=merchant_id,
                    name=(
                        merchant_names.get(merchant_id)
                        if merchant_id is not None
                        else None
                    )
                    or last.merchant_name
                    or last.name
                    or payee,
                    frequency=frequency,
                    average_amount=median_amount,
                    last_amount=abs(last.amount),
                    first_date=members[0].date_,
                    last_date=last.date_,
                    next_expected_date=(
                        last.date_ + timedelta(days=int(median_interval))
                        if median_interval is not None
                        else None
                    ),
                    occurrence_count=len(members),
                    variable=variable,
                    is_subscription=is_subscription,
                    confidence=confidence,
                    currency=last.currency,
                )
                touched.add(stream.id)
                for member in members:
                    member.recurring_stream_id = stream.id
                    db.add(member)
                await db.flush()
        except IntegrityError:
            logger.debug("recurring upsert skipped (race)")
            continue
        result.detected += 1

    result.pruned = await _purge_stale_proposals(db, store_owner, touched)
    return result


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


async def _delete_insights_for(db: AsyncSession, stream_ids: list[int]) -> None:
    """Delete the insights that hang off proposals being purged.

    Same regime rule, one level down: an insight about a proposal is
    derived opinion about derived opinion. A ``missed_recurring`` whose
    stream is gone can never refresh (its dedup_key embeds the dead
    stream id) and its account FK would strand it as debris that blocks
    account deletion - detaching instead of deleting left exactly that.
    Insights on the RECORD are safe by construction: curated streams are
    never purged.
    """
    if not stream_ids:
        return
    rows = await queries.insight_rows_where(
        db, [FinanceInsight.related_stream_id.in_(stream_ids)]
    )
    for row in rows:
        await db.delete(row)


async def _purge_orphaned_proposals(db: AsyncSession, owner_user_id: int) -> int:
    """Hard-delete proposals with no live members.

    The narrow sibling of ``_purge_stale_proposals``, for callers that are
    NOT a full detection pass: "Make recurring" moves one payee's members
    onto a confirmed stream, which empties the descriptor-keyed proposals
    they came from - those are the "folded in" duplicates it reports. A
    full purge here would wrongly delete every other healthy proposal the
    declare never looked at.
    """
    linked = await queries.linked_stream_ids(db)
    stale = await queries.stream_rows_where(
        db,
        [
            FinanceRecurringStream.owner_user_id == owner_user_id,
            FinanceRecurringStream.source == "derived",
            FinanceRecurringStream.is_user_confirmed.is_(False),
            FinanceRecurringStream.provider_stream_id.is_(None),
        ],
    )
    doomed = [row for row in stale if row.id not in linked]
    await _delete_insights_for(db, [row.id for row in doomed])
    for row in doomed:
        await db.delete(row)
    if doomed:
        await db.flush()
    return len(doomed)


async def _purge_stale_proposals(
    db: AsyncSession, owner_user_id: int, touched: set[int]
) -> int:
    """Hard-delete every proposal this pass did not regenerate.

    THE structural rule: a proposal row is never load-bearing. Detection
    owns every derived, unconfirmed row outright and rebuilds them from
    evidence each pass - so anything it did not just produce is stale by
    definition and is REMOVED, not soft-deleted. The old regime
    (soft-delete + watermark + revival gate + release + orphan-prune) let
    a row die only through a four-link chain and revive through three
    doors; broken links made rows immortal (a 2023 Home Depot survived
    every pass, twinned on a duplicate key with a ghost).

    Never touched: the record (``source='user'`` or confirmed) and
    provider-supplied rows. Dismissals (muted/deleted proposals) survive
    exactly as long as their pattern keeps being regenerated - a dismissal
    of something no longer proposed is debris and goes with the rest.
    """
    stale = await queries.stream_rows_where(
        db,
        [
            FinanceRecurringStream.owner_user_id == owner_user_id,
            FinanceRecurringStream.source == "derived",
            FinanceRecurringStream.is_user_confirmed.is_(False),
            FinanceRecurringStream.provider_stream_id.is_(None),
            FinanceRecurringStream.id.not_in(touched) if touched else True,  # noqa: E712
        ],
    )
    if not stale:
        return 0
    stale_ids = [row.id for row in stale]
    await _delete_insights_for(db, stale_ids)
    members = await queries.transaction_rows_where(
        db, [FinanceTransaction.recurring_stream_id.in_(stale_ids)]
    )
    for member in members:
        member.recurring_stream_id = None
        db.add(member)
    for row in stale:
        await db.delete(row)
    await db.flush()
    return len(stale_ids)


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
