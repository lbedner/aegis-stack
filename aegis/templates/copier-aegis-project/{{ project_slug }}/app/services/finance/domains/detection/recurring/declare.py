""" "Make recurring": turning hand-picked rows into a bill.

The other door into the same tables. Detection infers a stream from a
rhythm it found; this takes rows a person selected and states one, which
means the cadence may be thin, the amounts may not match, and the answer
still has to be a real stream rather than a guess.

``plan_recurring`` computes what would happen and writes nothing - the
frontend's confirm step is what calls ``declare_recurring``. Both reuse
the detection pass's own upsert and purge helpers, so a declared bill and
a detected one are the same kind of row.
"""

from __future__ import annotations

from datetime import timedelta
import statistics

from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import IntegrityError
from sqlmodel import or_
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.log import logger
from app.services.finance.domains.detection import queries
from app.services.finance.domains.detection.recurring.cadence import (
    _SUBSCRIPTION_FREQUENCIES,
    AMOUNT_TOLERANCE,
    _declared_cadence,
    _payee_key,
)
from app.services.finance.domains.detection.recurring.detect import (
    _inherited_curation,
    _payment_leg,
    _purge_orphaned_proposals,
    _resolve_payee_key,
    _upsert_stream,
)
from app.services.finance.domains.detection.recurring.resolve import (
    _sibling_streams,
)
from app.services.finance.models import (
    FinanceTransaction,
)


class RecurringPlanGroup(BaseModel):
    """One bill the selection would produce, fully costed before anything
    is written - so the confirm step can SHOW the roll-up instead of
    describing it, and the user can rename it before it exists."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

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


class DeclareRecurringResult(BaseModel):
    """Counts from one user-declared recurring pass."""

    streams: int = 0
    # Transactions now pointing at those streams. Larger than the
    # selection whenever the sweep picked up siblings.
    transactions: int = 0
    # Streams that retired: left with no members once the roll-up moved.
    reconciled: int = 0


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

    selected = await queries.transaction_rows_where(
        db,
        [
            FinanceTransaction.id.in_(list(ids)),
            FinanceTransaction.deleted_at.is_(None),
            queries.owner_clause(FinanceTransaction.owner_user_id, owner_user_id),
        ],
    )
    if not selected:
        return []
    selected_ids = {t.id for t in selected}

    wanted: set[tuple[int, str, str]] = set()
    for txn in selected:
        key = _payee_key(txn)
        if key and txn.account_id is not None:
            wanted.add((txn.account_id, "outflow" if txn.amount < 0 else "inflow", key))
    if not wanted:
        return []

    # The sweep. Same filters detection uses, so a declared stream and a
    # detected one are made of the same kind of rows.
    candidates = await queries.transaction_rows_where(
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
        ],
    )
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
    merchant_names = await queries.merchant_names_by_ids(db, merchant_ids)

    # Names of every stream the members currently sit in, for "folds in".
    current_ids = {
        sid
        for g in groups.values()
        for t in g
        if (sid := t.recurring_stream_id) is not None
    }
    stream_names = {s.id: s.name for s in await queries.streams_by_ids(db, current_ids)}

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
    frequencies: dict[str, str] | None = None,
) -> DeclareRecurringResult:
    """Turn selected transactions into confirmed recurring streams, and
    reconcile whatever else was already describing the same bill.

    ``names`` renames a planned group, keyed by ``RecurringPlanGroup.key``
    - the caller previews with ``plan_recurring``, the user edits the name
    it proposed, and the edit comes back here. Anything unnamed keeps the
    proposal.

    ``frequencies`` states the cadence the same way, and matters more than
    it looks. Detection knows six canonical gaps; a semiannual premium is
    not one of them, so it measures as ``irregular``, and the forecast
    cannot STEP an irregular stream - the bill silently never appears in
    it. Stating the cadence is what puts it there. A label the forecast
    cannot step is ignored rather than stored, since accepting one would
    leave the bill exactly as invisible while looking deliberate.

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
    # Local import: the ``service`` facade imports this module, so the step
    # table cannot be reached at module scope.
    from app.services.finance.utils import FREQUENCY_STEPS

    chosen_frequencies = {
        key: value
        for key, value in (frequencies or {}).items()
        if value in FREQUENCY_STEPS
    }

    for group in plan:
        members = group.members
        inherited = await _inherited_curation(
            db, {m.recurring_stream_id for m in members if m.recurring_stream_id}
        )
        name = (chosen.get(group.key) or "").strip() or group.name
        category_id = chosen_categories.get(group.key)
        stated_amount = chosen_amounts.get(group.key)
        frequency = chosen_frequencies.get(group.key) or group.frequency
        # The next date has to follow the cadence just stated. Leaving it
        # where the measured median put it would contradict the
        # instruction on the very next line.
        next_expected = group.next_expected_date
        if frequency != group.frequency:
            next_expected = FREQUENCY_STEPS[frequency](group.last_date)
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
                    frequency=frequency,
                    average_amount=group.average_amount,
                    last_amount=group.last_amount,
                    first_date=group.first_date,
                    last_date=group.last_date,
                    next_expected_date=next_expected,
                    occurrence_count=group.occurrence_count,
                    variable=group.variable,
                    is_subscription=(
                        group.is_subscription or inherited.is_subscription
                    ),
                    # The whole difference from detection: the user SAID
                    # so, so it lands confirmed rather than waiting in
                    # Detected for the confirmation it already has.
                    is_user_confirmed=True,
                    is_muted=inherited.is_muted,
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
