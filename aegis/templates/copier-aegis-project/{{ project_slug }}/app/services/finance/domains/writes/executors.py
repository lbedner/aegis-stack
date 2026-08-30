"""The registered change types. FW-05 ships one - categorize - to prove
the loop end to end; FW-06..09 add theirs HERE, one entry each."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.detection.insights.formatting import format_usd
from app.services.finance.domains.ledger import categories, transactions
from app.services.finance.domains.writes.registry import ChangeExecutor, register


class CategorizePayload(BaseModel):
    """The exact mutation: which transaction, which category. ``extra``
    is forbidden so a proposal cannot smuggle fields no executor reads
    but a card might display."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: int
    category_id: int


async def _categorize_execute(
    db: AsyncSession, payload: CategorizePayload, owner_user_id: int | None
) -> dict[str, Any]:
    txn = await categories.categorize_transaction(
        db,
        payload.transaction_id,
        payload.category_id,
        owner_user_id=owner_user_id,
        source="user",
    )
    if txn is None:
        raise ValueError(f"Transaction {payload.transaction_id} not found.")
    return {"transaction_id": txn.id, "category_id": payload.category_id}


async def _txn_subject(
    db: AsyncSession, transaction_id: int, owner_user_id: int | None
) -> tuple[Any, str]:
    """The row and its card-ready one-liner: the register's curated
    payee (never the raw bank descriptor), amount, date. Every
    describe renders the same subject the same way."""
    txn = await transactions.get_transaction(
        db, transaction_id, owner_user_id=owner_user_id
    )
    subject = (
        f"{txn.merchant_name or txn.name} "
        f"({format_usd(abs(txn.amount))} on {txn.date_})"
        if txn is not None
        else f"transaction {transaction_id} (missing)"
    )
    return txn, subject


async def _categorize_describe(
    db: AsyncSession, payload: CategorizePayload, owner_user_id: int | None
) -> list[dict[str, str]]:
    txn, subject = await _txn_subject(db, payload.transaction_id, owner_user_id)
    wanted = [payload.category_id]
    if txn is not None and txn.category_id is not None:
        wanted.append(txn.category_id)
    names = await categories.category_names(db, wanted)
    # A recategorization is a MOVE: show what it moves FROM, resolved
    # from the row at read time - if the category changed since the
    # proposal, the card shows the current truth.
    before = (
        names.get(txn.category_id, "Uncategorized")
        if txn is not None and txn.category_id is not None
        else "Uncategorized"
    )
    after = names.get(payload.category_id, f"category {payload.category_id}")
    return [
        {"label": "Transaction", "value": subject},
        {"label": "Category", "value": f"{before} \u2192 {after}"},
    ]


class MatchPayload(BaseModel):
    """Which payment paid which bill."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: int
    stream_id: int


async def _match_execute(
    db: AsyncSession, payload: MatchPayload, owner_user_id: int | None
) -> dict[str, Any]:
    from app.services.finance.domains.planning.recurring import streams

    stream = await streams.attach_transaction_to_stream(
        db,
        payload.transaction_id,
        payload.stream_id,
        owner_user_id=owner_user_id,
    )
    if stream is None:
        raise ValueError(
            f"Transaction {payload.transaction_id} or bill "
            f"{payload.stream_id} not found."
        )
    return {
        "transaction_id": payload.transaction_id,
        "stream_id": stream.id,
        "next_expected_date": (
            stream.next_expected_date.isoformat() if stream.next_expected_date else None
        ),
    }


async def _match_describe(
    db: AsyncSession, payload: MatchPayload, owner_user_id: int | None
) -> list[dict[str, str]]:
    from app.services.finance.domains.planning.recurring import streams

    txn, subject = await _txn_subject(db, payload.transaction_id, owner_user_id)
    stream = await streams.get_recurring(db, payload.stream_id, owner_user_id)
    # A match is a MOVE too: from whichever live bill holds the row now
    # (usually none) to the proposed one, read from the row so the card
    # shows the current truth.
    before = "Unmatched"
    if txn is not None and txn.recurring_stream_id is not None:
        holder = await streams.get_recurring(db, txn.recurring_stream_id, owner_user_id)
        if holder is not None:
            before = holder.name
    after = stream.name if stream is not None else f"bill {payload.stream_id} (missing)"
    return [
        {"label": "Payment", "value": subject},
        {"label": "Bill", "value": f"{before} \u2192 {after}"},
    ]


class TagPayload(BaseModel):
    """Which transaction, which label. The tag is a NAME - created on
    first use, resolved by normalized spelling after that - because the
    label vocabulary belongs to the user, not to an id table the model
    would have to pre-populate."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: int
    tag: str


async def _tag_names(db: AsyncSession, transaction_id: int) -> list[str]:
    current = await transactions.transaction_tags(db, [transaction_id])
    return sorted(t.name for t in current.get(transaction_id, []))


def _tag_rows(
    subject: str, before: list[str], after: list[str]
) -> list[dict[str, str]]:
    return [
        {"label": "Transaction", "value": subject},
        {
            "label": "Tags",
            "value": f"{', '.join(before) or 'none'} \u2192 "
            f"{', '.join(after) or 'none'}",
        },
    ]


async def _tag_execute(
    db: AsyncSession, payload: TagPayload, owner_user_id: int | None
) -> dict[str, Any]:
    txn = await transactions.get_transaction(
        db, payload.transaction_id, owner_user_id=owner_user_id
    )
    if txn is None:
        raise ValueError(f"Transaction {payload.transaction_id} not found.")
    tag = await transactions.tag_transactions(
        db, [payload.transaction_id], payload.tag, owner_user_id=owner_user_id
    )
    return {"transaction_id": payload.transaction_id, "tag_id": tag.id}


async def _tag_describe(
    db: AsyncSession, payload: TagPayload, owner_user_id: int | None
) -> list[dict[str, str]]:
    _txn, subject = await _txn_subject(db, payload.transaction_id, owner_user_id)
    before = await _tag_names(db, payload.transaction_id)
    after = sorted(set(before) | {payload.tag.strip()})
    return _tag_rows(subject, before, after)


async def _untag_execute(
    db: AsyncSession, payload: TagPayload, owner_user_id: int | None
) -> dict[str, Any]:
    from app.services.finance.domains.ledger.queries import transactions as queries
    from app.services.finance.utils import normalize_payee

    store_owner = 0 if owner_user_id is None else owner_user_id
    tag = await queries.tag_by_normalized_name(
        db, store_owner=store_owner, normalized=normalize_payee(payload.tag)
    )
    if tag is None or tag.id is None:
        raise ValueError(f'No tag named "{payload.tag}" exists.')
    removed = await transactions.untag_transactions(
        db, [payload.transaction_id], tag.id, owner_user_id=owner_user_id
    )
    return {
        "transaction_id": payload.transaction_id,
        "tag_id": tag.id,
        "removed": removed,
    }


async def _untag_describe(
    db: AsyncSession, payload: TagPayload, owner_user_id: int | None
) -> list[dict[str, str]]:
    _txn, subject = await _txn_subject(db, payload.transaction_id, owner_user_id)
    before = await _tag_names(db, payload.transaction_id)
    wanted = payload.tag.strip().casefold()
    after = [n for n in before if n.casefold() != wanted]
    return _tag_rows(subject, before, after)


register(
    ChangeExecutor(
        change_type="transaction.categorize",
        title="Categorize a transaction",
        payload_model=CategorizePayload,
        execute=_categorize_execute,
        describe=_categorize_describe,
    )
)
register(
    ChangeExecutor(
        change_type="recurring.match",
        title="Match a payment to a bill",
        payload_model=MatchPayload,
        execute=_match_execute,
        describe=_match_describe,
    )
)
register(
    ChangeExecutor(
        change_type="transaction.tag",
        title="Tag a transaction",
        payload_model=TagPayload,
        execute=_tag_execute,
        describe=_tag_describe,
    )
)
register(
    ChangeExecutor(
        change_type="transaction.untag",
        title="Remove a tag from a transaction",
        payload_model=TagPayload,
        execute=_untag_execute,
        describe=_untag_describe,
    )
)
