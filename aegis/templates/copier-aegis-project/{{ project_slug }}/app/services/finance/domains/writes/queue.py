"""The queue itself: propose, approve, reject, and the reads over them.

Approval is the ONLY execution path. ``approve`` re-validates the
payload and runs the registered executor in the caller's transaction, so
the status flip and the mutation land or fail together; a failing
execution leaves the row PENDING with the error in ``result`` - the user
rejects it with full information, nothing half-lands.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import ValidationError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.writes.registry import executor_for
from app.services.finance.models import FinancePendingChange
from app.services.finance.schemas import ChangeDisplayRow
from app.services.finance.utils import utcnow


def _freeze(display: list[ChangeDisplayRow]) -> list[dict[str, str]]:
    """Typed rows -> the plain dicts the JSON audit column stores."""
    return [line.model_dump() for line in display]


async def propose(
    db: AsyncSession,
    change_type: str,
    payload: dict[str, Any],
    *,
    owner_user_id: int | None = None,
    proposed_by_agent: str | None = None,
    conversation_id: str | None = None,
) -> FinancePendingChange:
    """Record a proposed mutation. Nothing in the ledger moves here.

    The payload is validated against the change type's contract NOW: a
    malformed proposal dies at the door instead of becoming a card the
    user cannot safely approve.
    """
    executor = executor_for(change_type)
    try:
        model = executor.payload_model(**payload)
    except ValidationError as e:
        raise ValueError(f"invalid {change_type} payload: {e}") from None
    row = FinancePendingChange(
        owner_user_id=owner_user_id,
        change_type=change_type,
        payload=model.model_dump(mode="json"),
        proposed_by_agent=proposed_by_agent,
        conversation_id=conversation_id,
    )
    db.add(row)
    await db.flush()
    return row


MAX_BATCH_SIZE = 100


async def propose_many(
    db: AsyncSession,
    change_type: str,
    payloads: list[dict[str, Any]],
    *,
    owner_user_id: int | None = None,
    proposed_by_agent: str | None = None,
    conversation_id: str | None = None,
) -> list[FinancePendingChange]:
    """One decision over many rows: N ordinary proposals sharing a
    batch id. Every row still resolves individually and keeps its own
    audit trail - a batch is a grouping, not a different kind of thing.

    All payloads validate BEFORE any row is written: a batch with one
    malformed member dies whole at the door rather than filing a card
    the user can only partially trust.
    """
    if not payloads:
        raise ValueError("a batch needs at least one change")
    if len(payloads) > MAX_BATCH_SIZE:
        raise ValueError(
            f"batch of {len(payloads)} exceeds the {MAX_BATCH_SIZE}-change cap"
        )
    executor = executor_for(change_type)
    models = []
    for index, payload in enumerate(payloads):
        try:
            models.append(executor.payload_model(**payload))
        except ValidationError as e:
            raise ValueError(
                f"invalid {change_type} payload at index {index}: {e}"
            ) from None
    batch_id = str(uuid4())
    rows = [
        FinancePendingChange(
            owner_user_id=owner_user_id,
            change_type=change_type,
            payload=model.model_dump(mode="json"),
            proposed_by_agent=proposed_by_agent,
            conversation_id=conversation_id,
            batch_id=batch_id,
        )
        for model in models
    ]
    for row in rows:
        db.add(row)
    await db.flush()
    return rows


async def batch_rows(
    db: AsyncSession, batch_id: str, *, owner_user_id: int | None = None
) -> list[FinancePendingChange]:
    query = select(FinancePendingChange).where(
        FinancePendingChange.batch_id == batch_id
    )
    if owner_user_id is not None:
        query = query.where(FinancePendingChange.owner_user_id == owner_user_id)
    return list((await db.exec(query.order_by(FinancePendingChange.id))).all())  # type: ignore[arg-type]


async def approve_batch(
    db: AsyncSession,
    batch_id: str,
    *,
    owner_user_id: int | None = None,
    exclude_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Approve every pending row in the batch except the vetoed ones
    (which are rejected - a veto is a decision, not a deferral). One
    failing row stays pending with its error; the rest land.
    """
    excluded = set(exclude_ids or [])
    approved = rejected = failed = 0
    for row in await batch_rows(db, batch_id, owner_user_id=owner_user_id):
        if row.status != "pending" or row.id is None:
            continue
        if row.id in excluded:
            await reject(db, row.id, owner_user_id=owner_user_id, note="vetoed")
            rejected += 1
            continue
        try:
            await approve(db, row.id, owner_user_id=owner_user_id)
            approved += 1
        except Exception:
            failed += 1
    return {"approved": approved, "rejected": rejected, "failed": failed}


async def reject_batch(
    db: AsyncSession,
    batch_id: str,
    *,
    owner_user_id: int | None = None,
) -> dict[str, Any]:
    rejected = 0
    for row in await batch_rows(db, batch_id, owner_user_id=owner_user_id):
        if row.status != "pending" or row.id is None:
            continue
        await reject(db, row.id, owner_user_id=owner_user_id)
        rejected += 1
    return {"approved": 0, "rejected": rejected, "failed": 0}


async def get_change(
    db: AsyncSession, change_id: int, *, owner_user_id: int | None = None
) -> FinancePendingChange | None:
    row = (
        await db.exec(
            select(FinancePendingChange).where(FinancePendingChange.id == change_id)
        )
    ).first()
    if row is None:
        return None
    if owner_user_id is not None and row.owner_user_id != owner_user_id:
        return None
    return row


async def list_changes(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    status: str | None = "pending",
) -> list[FinancePendingChange]:
    """Newest first. ``status=None`` returns the full audit trail."""
    query = select(FinancePendingChange).order_by(
        FinancePendingChange.id.desc()  # type: ignore[attr-defined]
    )
    if status is not None:
        query = query.where(FinancePendingChange.status == status)
    if owner_user_id is not None:
        query = query.where(FinancePendingChange.owner_user_id == owner_user_id)
    return list((await db.exec(query)).all())


def _require_pending(row: FinancePendingChange | None) -> FinancePendingChange:
    if row is None:
        raise ValueError("pending change not found")
    if row.status != "pending":
        raise ValueError(f"change already {row.status}")
    return row


async def _describe_row(
    db: AsyncSession, row: FinancePendingChange
) -> list[ChangeDisplayRow]:
    """The card body for a stored row, tolerant of tightened rules.

    Validation guards the DOOR (propose); a stored payload that no
    longer validates is exactly what reject/withdraw exist to clean up,
    so it renders as its raw payload instead of raising."""
    executor = executor_for(row.change_type)
    try:
        model = executor.payload_model(**row.payload)
    except ValidationError:
        return [
            ChangeDisplayRow(label="Change", value=executor.title),
            ChangeDisplayRow(
                label="Payload (no longer valid)", value=str(row.payload)
            ),
        ]
    return await executor.describe(db, model, row.owner_user_id)


async def approve(
    db: AsyncSession, change_id: int, *, owner_user_id: int | None = None
) -> FinancePendingChange:
    """Execute the stored mutation. The one door into the ledger."""
    row = _require_pending(await get_change(db, change_id, owner_user_id=owner_user_id))
    executor = executor_for(row.change_type)
    model = executor.payload_model(**row.payload)
    # Snapshot the display BEFORE executing: after the mutation the
    # world reflects it, and re-resolving read "Groceries -> Groceries".
    # Resolution freezes the record; only pending cards track the world.
    display = _freeze(await executor.describe(db, model, row.owner_user_id))
    try:
        result = await executor.execute(db, model, row.owner_user_id)
    except Exception as e:
        # The row stays PENDING: the error is audit, the decision is
        # still the user's (reject it, or fix the world and re-approve).
        row.result = {"error": str(e)}
        row.updated_at = utcnow()
        db.add(row)
        await db.flush()
        raise
    row.status = "approved"
    row.result = {**result, "display": display}
    row.resolved_at = utcnow()
    row.updated_at = row.resolved_at
    db.add(row)
    await db.flush()
    return row


async def reject(
    db: AsyncSession,
    change_id: int,
    *,
    owner_user_id: int | None = None,
    note: str | None = None,
) -> FinancePendingChange:
    row = _require_pending(await get_change(db, change_id, owner_user_id=owner_user_id))
    display = _freeze(await _describe_row(db, row))
    row.status = "rejected"
    row.result = {"display": display, **({"note": note} if note else {})}
    row.resolved_at = utcnow()
    row.updated_at = row.resolved_at
    db.add(row)
    await db.flush()
    return row


async def withdraw(
    db: AsyncSession,
    change_id: int,
    *,
    agent_slug: str | None,
    owner_user_id: int | None = None,
) -> FinancePendingChange:
    """An agent retracting ITS OWN pending proposal - propose's cleanup
    half. Guarded to the proposer, so one agent (or a slug-less caller)
    can never sweep another's cards, and it lands as a rejection with a
    note: the audit trail keeps the mistake visible, the user just
    never has to clean it up by hand."""
    row = _require_pending(await get_change(db, change_id, owner_user_id=owner_user_id))
    if not agent_slug or row.proposed_by_agent != agent_slug:
        raise ValueError("only the proposing agent can withdraw a change")
    return await reject(
        db,
        change_id,
        owner_user_id=owner_user_id,
        note=f"Withdrawn by {agent_slug}.",
    )


async def describe_change(
    db: AsyncSession, row: FinancePendingChange
) -> list[ChangeDisplayRow]:
    """The card's body lines: system truth, never model copy.

    Pending rows resolve from the database at read time (the world may
    have moved since the proposal); resolved rows read the snapshot
    frozen at resolution - history does not re-resolve.
    """
    frozen = (row.result or {}).get("display")
    if row.status != "pending" and isinstance(frozen, list):
        return [ChangeDisplayRow(**line) for line in frozen]
    return await _describe_row(db, row)
