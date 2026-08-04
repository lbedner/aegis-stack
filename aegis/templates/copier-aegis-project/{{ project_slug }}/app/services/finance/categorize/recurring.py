"""Recurring-stream detection (FIN-27).

Finds subscriptions, bills, and paychecks so the product can answer "what am I
paying every month?" and flag price hikes. Runs nightly (and after each
sync/import) per owner.

Heuristic: group a user's posted, non-transfer transactions by
``(account, direction, normalized payee)``; a group with >= ``MIN_OCCURRENCES``
whose median gap matches a known cadence (within ``INTERVAL_TOLERANCE``) is a
stream. Amounts within ``AMOUNT_TOLERANCE`` of the median are "fixed"; otherwise
the stream is variable (a utility bill). Confidence/maturity rather than a
boolean, because an annual charge is invisible for a year. Idempotent: streams
upsert on the detected-stream unique key and members back-link via
``finance_transaction.recurring_stream_id``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import statistics

from sqlalchemy.exc import IntegrityError
from sqlmodel import or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.log import logger
from app.services.finance.importers.base import normalize_payee
from app.services.finance.models import (
    FinanceAccount,
    FinanceInsight,
    FinanceMerchant,
    FinanceRecurringStream,
    FinanceTransaction,
)

MIN_OCCURRENCES = 3
INTERVAL_TOLERANCE = 0.20  # +/- 20% of a canonical cadence
# ...but never more than this in absolute days. 20% of a year is a 73-day
# window, so anything from 292 to 438 days read as "yearly" - which is how
# a convenience store with four visits (gaps of 2044, 430 and 17 days)
# became an annual subscription. The cap only binds on long cadences; 20%
# of a week is a day and a half, and stays.
MAX_INTERVAL_SLACK_DAYS = 21
# How many of a group's gaps must actually sit near the cadence before it
# counts as a rhythm. A median alone cannot tell [30, 31, 29] from
# [2044, 430, 17]. Two thirds leaves room for a bill that skipped a month
# without letting noise through.
MIN_RHYTHM_RATIO = 0.6
# Below this a stream is a rounding error with a heartbeat: a savings
# account paid $0.31 for 54 months running - flawless cadence, fixed
# amount, and meaningless. Set under a real cheap subscription ($5.41 CVS
# ExtraCare) so those still count.
MIN_STREAM_AMOUNT = 200


# How long a stream may go quiet before it stops being a live bill. Shape
# alone cannot catch these: CAPITAL ONE AUTO CARPAY really was monthly,
# and so were Wix, AES, TJX and Synchrony - they simply ended in 2019.
# Scaled by cadence, because 11 months of silence is normal for an annual
# bill and terminal for a monthly one.
MAX_SILENCE_DAYS = 365
SILENCE_CADENCE_MULTIPLE = 2
AMOUNT_TOLERANCE = 0.20  # within 20% of median => fixed amount
# Canonical cadence (median-gap days) -> frequency label.
_CADENCES: tuple[tuple[int, str], ...] = (
    (7, "weekly"),
    (14, "biweekly"),
    (15, "semi_monthly"),
    (30, "monthly"),
    (90, "quarterly"),
    (365, "annually"),
)
_SUBSCRIPTION_FREQUENCIES = {"monthly", "annually"}


@dataclass
class RecurringDetectionResult:
    """Counts from one detection pass."""

    detected: int = 0
    # Streams retired because nothing points at them any more - see
    pruned: int = 0


def _cadence_slack(days: int) -> float:
    """Allowed drift around a canonical cadence, in days."""
    return min(days * INTERVAL_TOLERANCE, MAX_INTERVAL_SLACK_DAYS)


def _frequency_for(median_interval: float) -> str | None:
    """Map a median day-gap to a cadence label, or None if it matches none."""
    for days, label in _CADENCES:
        if abs(median_interval - days) <= _cadence_slack(days):
            return label
    return None


def _canonical_days(frequency: str) -> int | None:
    for days, label in _CADENCES:
        if label == frequency:
            return days
    return None


def _rhythm_ratio(gaps: list[int], canonical: int) -> float:
    """Fraction of gaps that actually sit near ``canonical``.

    The median says where the middle is; this says whether there IS a
    middle. ``[30, 31, 29]`` scores 1.0 and ``[2044, 430, 17]`` scores
    0.33 even though both have a median inside their cadence band.
    """
    if not gaps:
        return 0.0
    slack = _cadence_slack(canonical)
    return sum(1 for g in gaps if abs(g - canonical) <= slack) / len(gaps)


def _payee_key(txn: FinanceTransaction) -> str:
    """Stable grouping key for one transaction.

    An assigned payee (``FinanceMerchant``, "the prerequisite for
    recurring/subscription detection" per its own model docstring) wins
    outright: a bank descriptor is not a stable identity, and treating it
    as one splits a single bill every time the format drifts. Confirmed
    live on real data - one YouTube Premium subscription appeared as
    "YOUTUBEPREMIG.CO/HELPPAY# CA XXXX--X3007" then "YOUTUBEPREMI
    G.CO/HELPPAY# CA XXXX3007" (a space moved, the card ref changed) =
    two streams, and after it moved to another account as "YouTubePremi
    g.co/helppay# CA 07/19" the embedded statement date made EVERY month
    a unique string, so it never reached MIN_OCCURRENCES and was never
    detected at all.

    The normalized-descriptor fallback is what still auto-detects
    everything nobody has named a payee for - so assigning payees is an
    improvement you opt into per merchant, not a prerequisite for the
    feature working at all.
    """
    if txn.merchant_id is not None:
        return f"merchant:{txn.merchant_id}"
    return normalize_payee(
        txn.merchant_name or txn.original_description or txn.name or ""
    )


def _owner_clause(column, owner_user_id: int | None):
    """Scan the owner's rows; a NULL owner (standalone, no auth) uses IS NULL."""
    return column.is_(None) if owner_user_id is None else column == owner_user_id


# Separator for the second, third, ... bill a single payee runs on one
# account. ``normalized_payee`` is purely the detected-stream unique key
# and is never displayed (Bills & Income shows ``name``), so widening it
# this way needs no migration - the unique index still does its job, it
# just stops forcing one payee to mean one bill.
_SPLIT_MARK = "#"


async def _sibling_streams(
    db: AsyncSession, *, owner_user_id: int, account_id: int, direction: str, base: str
) -> list[FinanceRecurringStream]:
    """Every live stream on this payee+account+direction, base key or a
    split of it."""
    rows = (
        await db.exec(
            select(FinanceRecurringStream).where(
                FinanceRecurringStream.owner_user_id == owner_user_id,
                FinanceRecurringStream.account_id == account_id,
                FinanceRecurringStream.direction == direction,
                FinanceRecurringStream.provider_stream_id.is_(None),
                FinanceRecurringStream.deleted_at.is_(None),
            )
        )
    ).all()
    return [
        s
        for s in rows
        if s.normalized_payee == base
        or (s.normalized_payee or "").startswith(base + _SPLIT_MARK)
    ]


async def _resolve_payee_key(
    db: AsyncSession,
    *,
    owner_user_id: int,
    account_id: int,
    direction: str,
    base: str,
    member_ids: set[int],
) -> tuple[str, FinanceRecurringStream | None]:
    """The key this group of members should land on, and the stream already
    holding it (if any).

    One payee on one account used to mean exactly one bill, because the key
    WAS the payee. That is wrong for a payee that really does sell you two
    things - Anthropic billing a Claude subscription and API usage, Amazon
    billing Prime and AWS - and it is what would quietly undo an exclusion:
    drop a charge from a bill, and the next pass regroups it under the same
    payee key, finds the bill, and puts it straight back.

    So a CONFIRMED bill owns its membership. If one exists on the base key
    and these members are not its members, they are something else, and
    they get their own key (``merchant:12#2``) rather than being merged in.
    """
    siblings = await _sibling_streams(
        db,
        owner_user_id=owner_user_id,
        account_id=account_id,
        direction=direction,
        base=base,
    )
    # A stream these members already sit in is the one they belong to -
    # this is the ordinary re-run, and it must absorb rather than fork.
    for stream in siblings:
        if stream.id is not None and member_ids:
            linked = (
                await db.exec(
                    select(FinanceTransaction.id).where(
                        FinanceTransaction.recurring_stream_id == stream.id,
                        FinanceTransaction.id.in_(list(member_ids)),
                    )
                )
            ).first()
            if linked is not None:
                return str(stream.normalized_payee or base), stream
    on_base = next((s for s in siblings if s.normalized_payee == base), None)
    if on_base is not None and on_base.is_user_confirmed:
        taken = {s.normalized_payee for s in siblings}
        index = 2
        while f"{base}{_SPLIT_MARK}{index}" in taken:
            index += 1
        return f"{base}{_SPLIT_MARK}{index}", None
    return base, on_base


async def _curated_members(
    db: AsyncSession, owner_user_id: int | None
) -> set[int]:
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
    confirmed = (
        await db.exec(
            select(FinanceRecurringStream.id).where(
                or_(
                    FinanceRecurringStream.is_user_confirmed.is_(True),
                    FinanceRecurringStream.source == "user",
                ),
                FinanceRecurringStream.deleted_at.is_(None),
            )
        )
    ).all()
    ids = [s for s in confirmed if s is not None]
    if not ids:
        return set()
    rows = (
        await db.exec(
            select(FinanceTransaction.id).where(
                FinanceTransaction.recurring_stream_id.in_(ids),
                FinanceTransaction.deleted_at.is_(None),
                _owner_clause(FinanceTransaction.owner_user_id, owner_user_id),
            )
        )
    ).all()
    return {t for t in rows if t is not None}


def _has_gone_quiet(last_date: date, canonical: int | None, today: date) -> bool:
    """Has this stream been silent long enough to be over?

    ``max`` of a flat year and twice the cadence: the flat floor kills a
    monthly bill that stopped, the multiple keeps an annual one alive
    through its normal 11-month gap.
    """
    window = max(MAX_SILENCE_DAYS, SILENCE_CADENCE_MULTIPLE * (canonical or 0))
    return (today - last_date).days > window


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

    accounts = (
        await db.exec(
            select(FinanceAccount).where(
                FinanceAccount.deleted_at.is_(None),
                _owner_clause(FinanceAccount.owner_user_id, owner_user_id),
            )
        )
    ).all()
    acct_ids = [a.id for a in accounts]
    if not acct_ids:
        return result
    # Money ARRIVING on a credit card is a payment toward it, never
    # household income - it came from another account of yours. Knowable
    # structurally, which matters because the matching outflow is often
    # not imported at all (81 AMEX credits here with no counterpart).
    # Spending charged TO the card is untouched: that is an ordinary bill.
    liability_accounts = {
        a.id for a in accounts if a.classification == "liability"
    }

    txns = (
        await db.exec(
            select(FinanceTransaction).where(
                _owner_clause(FinanceTransaction.owner_user_id, owner_user_id),
                FinanceTransaction.deleted_at.is_(None),
                FinanceTransaction.dedup_status != "duplicate",
                FinanceTransaction.is_transfer.is_(False),
                FinanceTransaction.status == "posted",
                FinanceTransaction.account_id.in_(list(acct_ids)),
            )
        )
    ).all()

    # Group by (account, direction, payee key) - see _payee_key: an
    # assigned merchant, else the normalized descriptor. Transactions the
    # user pinned by confirming their bill are skipped outright: they
    # already have an owner, and regrouping them is how an exclusion or a
    # split gets silently undone overnight.
    curated = await _curated_members(db, owner_user_id)
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
    merchant_names: dict[int, str] = {}
    if merchant_ids:
        merchant_names = {
            m.id: m.name
            for m in (
                await db.exec(
                    select(FinanceMerchant).where(FinanceMerchant.id.in_(merchant_ids))
                )
            ).all()
        }

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


async def _inherited_curation(
    db: AsyncSession, stream_ids: set[int]
) -> dict[str, bool]:
    """Curation carried by the streams these transactions are leaving.

    Any predecessor being confirmed (or a recognized subscription) makes
    the successor so: the user's decision was about the MERCHANT, and a
    descriptor changing is not them changing their mind. Muted is
    inherited the same way and for the same reason - a silenced bill that
    un-silences itself because its bank restated a descriptor is worse
    than one that stays quiet.
    """
    blank = {"is_user_confirmed": False, "is_subscription": False, "is_muted": False}
    ids = {i for i in stream_ids if i is not None}
    if not ids:
        return blank
    rows = (
        await db.exec(
            select(FinanceRecurringStream).where(FinanceRecurringStream.id.in_(ids))
        )
    ).all()
    return {
        "is_user_confirmed": any(r.is_user_confirmed for r in rows),
        "is_subscription": any(r.is_subscription for r in rows),
        "is_muted": any(r.is_muted for r in rows),
    }


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
    rows = (
        await db.exec(
            select(FinanceInsight).where(
                FinanceInsight.related_stream_id.in_(stream_ids)
            )
        )
    ).all()
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
    linked = {
        sid
        for sid in (
            await db.exec(
                select(FinanceTransaction.recurring_stream_id).where(
                    FinanceTransaction.recurring_stream_id.is_not(None),
                    FinanceTransaction.deleted_at.is_(None),
                )
            )
        ).all()
        if sid is not None
    }
    stale = (
        await db.exec(
            select(FinanceRecurringStream).where(
                FinanceRecurringStream.owner_user_id == owner_user_id,
                FinanceRecurringStream.source == "derived",
                FinanceRecurringStream.is_user_confirmed.is_(False),
                FinanceRecurringStream.provider_stream_id.is_(None),
            )
        )
    ).all()
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
    stale = (
        await db.exec(
            select(FinanceRecurringStream).where(
                FinanceRecurringStream.owner_user_id == owner_user_id,
                FinanceRecurringStream.source == "derived",
                FinanceRecurringStream.is_user_confirmed.is_(False),
                FinanceRecurringStream.provider_stream_id.is_(None),
                FinanceRecurringStream.id.not_in(touched) if touched else True,  # noqa: E712
            )
        )
    ).all()
    if not stale:
        return 0
    stale_ids = [row.id for row in stale]
    await _delete_insights_for(db, stale_ids)
    members = (
        await db.exec(
            select(FinanceTransaction).where(
                FinanceTransaction.recurring_stream_id.in_(stale_ids)
            )
        )
    ).all()
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
    existing = (
        await db.exec(
            select(FinanceRecurringStream).where(
                FinanceRecurringStream.owner_user_id == owner_user_id,
                FinanceRecurringStream.account_id == account_id,
                FinanceRecurringStream.direction == direction,
                FinanceRecurringStream.normalized_payee == payee,
                FinanceRecurringStream.provider_stream_id.is_(None),
            )
        )
    ).first()
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


@dataclass
class RecurringPlanGroup:
    """One bill the selection would produce, fully costed before anything
    is written - so the confirm step can SHOW the roll-up instead of
    describing it, and the user can rename it before it exists."""

    # Stable handle the caller echoes back to rename this group. Not the
    # database key: the stream may not exist yet.
    key: str
    account_id: int
    direction: str
    payee: str
    name: str
    frequency: str
    median_interval: float | None
    average_amount: int
    last_amount: int
    first_date: object | None
    last_date: object | None
    next_expected_date: object | None
    # Everything that would join, vs how much of it the user actually
    # ticked. The gap between these two is the whole reason to preview.
    occurrence_count: int
    selected_count: int
    # The median of the rows the user ACTUALLY ticked, before the sweep
    # widened the group. On a descriptor that covers $500 and $16,320
    # alike, this is the only figure anyone can vouch for - the sweep's
    # own median is an average of strangers.
    selected_amount: int
    variable: bool
    is_subscription: bool
    members: list[FinanceTransaction]
    # Names of streams already describing this bill that would fold in.
    absorbs: list[str]
    # True when a CONFIRMED bill already holds this payee on this account
    # and these rows are not its members - so this becomes a second bill
    # beside it rather than being merged into it.
    creates_new_bill: bool = False
    # That existing bill's name, so the dialog can say which one.
    existing_bill_name: str | None = None


@dataclass
class DeclareRecurringResult:
    """Counts from one user-declared recurring pass."""

    streams: int = 0
    # Transactions now pointing at those streams. Larger than the
    # selection whenever the sweep picked up siblings.
    transactions: int = 0
    # Streams that retired: left with no members once the roll-up moved.
    reconciled: int = 0


def _declared_cadence(members: list[FinanceTransaction]) -> tuple[str, float | None]:
    """``(frequency, median gap)`` for a group the USER says is recurring.

    Detection may decline - fewer than ``MIN_OCCURRENCES``, or a median gap
    matching no canonical cadence - and returning "not recurring" is right
    for a guess. It is wrong for an instruction: the user selected these
    rows and said this is a bill, so the only open question is which label
    fits, not whether to make one.

    So the ladder never bottoms out at a refusal. A cadence that matches a
    canonical gap gets that name; one that does not is "irregular" and
    still carries its real median forward, so the next date is projected
    from what actually happened; a single transaction has no gap to
    measure at all and stays "unknown" until a second one arrives.
    """
    gaps = [
        (members[i].date_ - members[i - 1].date_).days for i in range(1, len(members))
    ]
    gaps = [g for g in gaps if g > 0]
    if not gaps:
        return "unknown", None
    median_interval = statistics.median(gaps)
    return _frequency_for(median_interval) or "irregular", median_interval



def _plan_key(account_id: int, direction: str, payee: str) -> str:
    return f"{account_id}|{direction}|{payee}"


async def plan_recurring(
    db: AsyncSession,
    transaction_ids: list[int],
    *,
    owner_user_id: int | None,
    exclude_transaction_ids: list[int] | None = None,
) -> list[RecurringPlanGroup]:
    """What ``declare_recurring`` WOULD do, without doing it.

    Shares the grouping and the cadence maths with the apply path rather
    than re-deriving them, because a preview that can disagree with the
    write it previews is worse than no preview.
    """
    ids = {int(i) for i in transaction_ids if i is not None}
    if not ids:
        return []

    selected = (
        await db.exec(
            select(FinanceTransaction).where(
                FinanceTransaction.id.in_(list(ids)),
                FinanceTransaction.deleted_at.is_(None),
                _owner_clause(FinanceTransaction.owner_user_id, owner_user_id),
            )
        )
    ).all()
    if not selected:
        return []
    selected_ids = {t.id for t in selected}

    wanted: set[tuple[int, str, str]] = set()
    for txn in selected:
        key = _payee_key(txn)
        if key and txn.account_id is not None:
            wanted.add(
                (txn.account_id, "outflow" if txn.amount < 0 else "inflow", key)
            )
    if not wanted:
        return []

    # The sweep. Same filters detection uses, so a declared stream and a
    # detected one are made of the same kind of rows.
    candidates = (
        await db.exec(
            select(FinanceTransaction).where(
                _owner_clause(FinanceTransaction.owner_user_id, owner_user_id),
                FinanceTransaction.deleted_at.is_(None),
                FinanceTransaction.dedup_status != "duplicate",
                FinanceTransaction.is_transfer.is_(False),
                FinanceTransaction.status == "posted",
            )
        )
    ).all()
    # Rows the user unticked in the preview. Dropped AFTER the sweep, so
    # excluding one charge never drops its siblings with it - and because
    # a confirmed bill owns its membership (_pinned_transaction_ids), the
    # exclusion survives the next detection pass instead of being undone.
    excluded = {int(i) for i in (exclude_transaction_ids or []) if i is not None}
    groups: dict[tuple[int, str, str], list[FinanceTransaction]] = {}
    for txn in candidates:
        key = _payee_key(txn)
        if not key or txn.account_id is None or txn.id in excluded:
            continue
        signature = (txn.account_id, "outflow" if txn.amount < 0 else "inflow", key)
        if signature in wanted:
            groups.setdefault(signature, []).append(txn)

    merchant_ids = {t.merchant_id for g in groups.values() for t in g}
    merchant_ids.discard(None)
    merchant_names: dict[int, str] = {}
    if merchant_ids:
        merchant_names = {
            m.id: m.name
            for m in (
                await db.exec(
                    select(FinanceMerchant).where(
                        FinanceMerchant.id.in_(list(merchant_ids))
                    )
                )
            ).all()
        }

    # Names of every stream the members currently sit in, for "folds in".
    current_ids = {
        sid
        for g in groups.values()
        for t in g
        if (sid := t.recurring_stream_id) is not None
    }
    stream_names: dict[int, str] = {}
    if current_ids:
        stream_names = {
            s.id: s.name
            for s in (
                await db.exec(
                    select(FinanceRecurringStream).where(
                        FinanceRecurringStream.id.in_(list(current_ids))
                    )
                )
            ).all()
        }

    plan: list[RecurringPlanGroup] = []
    for (account_id, direction, payee), members in sorted(
        groups.items(), key=lambda kv: -len(kv[1])
    ):
        members.sort(key=lambda t: (t.date_, t.id or 0))
        frequency, median_interval = _declared_cadence(members)
        amounts = [abs(t.amount) for t in members]
        median_amount = int(statistics.median(amounts))
        variable = any(
            abs(a - median_amount) > median_amount * AMOUNT_TOLERANCE for a in amounts
        )
        picked_amounts = [abs(t.amount) for t in members if t.id in selected_ids]
        selected_amount = int(
            statistics.median(picked_amounts) if picked_amounts else median_amount
        )
        last = members[-1]
        # The stream this group would land on. The resolver is shared with
        # the write, so the preview cannot claim "adds to Claude Code"
        # where the write would in fact fork a second bill.
        resolved_key, target = await _resolve_payee_key(
            db,
            owner_user_id=(0 if owner_user_id is None else owner_user_id),
            account_id=account_id,
            direction=direction,
            base=payee,
            member_ids={m.id for m in members if m.id is not None},
        )
        held = None
        if target is None and resolved_key != payee:
            held = next(
                (
                    s
                    for s in await _sibling_streams(
                        db,
                        owner_user_id=(0 if owner_user_id is None else owner_user_id),
                        account_id=account_id,
                        direction=direction,
                        base=payee,
                    )
                    if s.normalized_payee == payee
                ),
                None,
            )
        absorbs = sorted(
            {
                stream_names[sid]
                for m in members
                if (sid := m.recurring_stream_id) is not None
                and sid in stream_names
                and (target is None or sid != target.id)
            }
        )
        plan.append(
            RecurringPlanGroup(
                key=_plan_key(account_id, direction, resolved_key),
                account_id=account_id,
                direction=direction,
                payee=resolved_key,
                name=(
                    (target.name if target is not None else None)
                    or (
                        merchant_names.get(last.merchant_id)
                        if last.merchant_id is not None
                        else None
                    )
                    or last.merchant_name
                    or last.name
                    or payee
                ),
                frequency=frequency,
                median_interval=median_interval,
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
                selected_count=sum(1 for m in members if m.id in selected_ids),
                selected_amount=selected_amount,
                variable=variable,
                is_subscription=(
                    direction == "outflow"
                    and frequency in _SUBSCRIPTION_FREQUENCIES
                    and not variable
                ),
                members=members,
                absorbs=absorbs,
                creates_new_bill=held is not None,
                existing_bill_name=held.name if held is not None else None,
            )
        )
    return plan


async def declare_recurring(
    db: AsyncSession,
    transaction_ids: list[int],
    *,
    owner_user_id: int | None,
    names: dict[str, str] | None = None,
    exclude_transaction_ids: list[int] | None = None,
    categories: dict[str, int] | None = None,
    amounts: dict[str, int] | None = None,
) -> DeclareRecurringResult:
    """Turn selected transactions into confirmed recurring streams, and
    reconcile whatever else was already describing the same bill.

    ``names`` renames a planned group, keyed by ``RecurringPlanGroup.key``
    - the caller previews with ``plan_recurring``, the user edits the name
    it proposed, and the edit comes back here. Anything unnamed keeps the
    proposal.

    Reconciliation is the point, not a side effect. The same bill routinely
    exists two or three times over - a descriptor drifted, so detection
    keyed it twice; a payee was assigned later, so it keyed a third way -
    and declaring a stream without cleaning that up just adds a fourth.
    Three things make it converge, all of them detection's own machinery
    rather than a parallel implementation:

    - The selection is EXPANDED to every sibling sharing its
      ``(account, direction, payee key)``. Declaring from three of a
      payee's thirteen rows would otherwise leave ten pointing at the old
      stream, which then keeps its members, never orphans, and survives as
      the duplicate this was meant to remove.
    - ``_upsert_stream`` is keyed on that same tuple, so an existing
      stream for the bill is UPDATED in place and confirmed, not shadowed
      by a second row.
    - Whatever the members leave behind hands over its curation
      (``_inherited_curation``) and is then hard-deleted once orphaned.
    """
    result = DeclareRecurringResult()
    plan = await plan_recurring(
        db,
        transaction_ids,
        owner_user_id=owner_user_id,
        exclude_transaction_ids=exclude_transaction_ids,
    )
    if not plan:
        return result
    store_owner = 0 if owner_user_id is None else owner_user_id
    chosen = names or {}
    chosen_categories = categories or {}
    chosen_amounts = amounts or {}

    for group in plan:
        members = group.members
        inherited = await _inherited_curation(
            db, {m.recurring_stream_id for m in members if m.recurring_stream_id}
        )
        name = (chosen.get(group.key) or "").strip() or group.name
        category_id = chosen_categories.get(group.key)
        stated_amount = chosen_amounts.get(group.key)
        try:
            async with db.begin_nested():
                stream = await _upsert_stream(
                    db,
                    owner_user_id=store_owner,
                    account_id=group.account_id,
                    direction=group.direction,
                    payee=group.payee,
                    merchant_id=members[-1].merchant_id,
                    name=name,
                    frequency=group.frequency,
                    average_amount=group.average_amount,
                    last_amount=group.last_amount,
                    first_date=group.first_date,
                    last_date=group.last_date,
                    next_expected_date=group.next_expected_date,
                    occurrence_count=group.occurrence_count,
                    variable=group.variable,
                    is_subscription=(
                        group.is_subscription or inherited["is_subscription"]
                    ),
                    # The whole difference from detection: the user SAID
                    # so, so it lands confirmed rather than waiting in
                    # Detected for the confirmation it already has.
                    is_user_confirmed=True,
                    is_muted=inherited["is_muted"],
                    confidence=100,
                    currency=members[-1].currency,
                    revive_retired=True,
                )
                # On the stream only: the members keep the categories
                # they already have, which may have been corrected by hand.
                if category_id is not None:
                    stream.category_id = category_id
                    db.add(stream)
                if stated_amount is not None:
                    # Same rule update_recurring follows: stating what the
                    # bill IS beats the detector's average, so it stops
                    # reading "varies" off a spread it never chose.
                    stream.expected_amount = stated_amount
                    stream.amount_is_variable = False
                    db.add(stream)
                for member in members:
                    member.recurring_stream_id = stream.id
                    db.add(member)
                await db.flush()
        except IntegrityError:
            logger.debug("declared recurring upsert skipped (race)")
            continue
        result.streams += 1
        result.transactions += len(members)

    # Only what actually retired. A stream the upsert absorbed IN PLACE is
    # reconciled too, but it is the same row still standing, so counting it
    # here as well would report two bills cleaned up where one row changed
    # and one disappeared.
    result.reconciled = await _purge_orphaned_proposals(db, store_owner)
    return result
