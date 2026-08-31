"""The registered change types. FW-05 ships one - categorize - to prove
the loop end to end; FW-06..09 add theirs HERE, one entry each."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.formatting import format_date
from app.services.finance.domains.detection.insights.formatting import format_usd
from app.services.finance.domains.ledger import categories, splits, transactions
from app.services.finance.domains.writes.registry import ChangeExecutor, register
from app.services.finance.schemas import ChangeDisplayRow, SplitPart


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
        f"({format_usd(abs(txn.amount))} on {format_date(txn.date_)})"
        if txn is not None
        else f"transaction {transaction_id} (missing)"
    )
    return txn, subject


async def _categorize_describe(
    db: AsyncSession, payload: CategorizePayload, owner_user_id: int | None
) -> list[ChangeDisplayRow]:
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
        ChangeDisplayRow(label="Transaction", value=subject),
        ChangeDisplayRow(label="Category", value=f"{before} \u2192 {after}"),
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
) -> list[ChangeDisplayRow]:
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
        ChangeDisplayRow(label="Payment", value=subject),
        ChangeDisplayRow(label="Bill", value=f"{before} \u2192 {after}"),
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
) -> list[ChangeDisplayRow]:
    return [
        ChangeDisplayRow(label="Transaction", value=subject),
        ChangeDisplayRow(
            label="Tags",
            value=f"{', '.join(before) or 'none'} \u2192 "
            f"{', '.join(after) or 'none'}",
        ),
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
) -> list[ChangeDisplayRow]:
    from app.services.finance.utils import normalize_payee

    _txn, subject = await _txn_subject(db, payload.transaction_id, owner_user_id)
    before = await _tag_names(db, payload.transaction_id)
    # Predict with the executor's own rule: attach dedupes by normalized
    # name, so "business" against an existing "Business" changes nothing
    # - the card must not promise a duplicate that will never exist.
    wanted = normalize_payee(payload.tag)
    if any(normalize_payee(name) == wanted for name in before):
        after = before
    else:
        after = sorted([*before, payload.tag.strip()])
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
) -> list[ChangeDisplayRow]:
    from app.services.finance.utils import normalize_payee

    _txn, subject = await _txn_subject(db, payload.transaction_id, owner_user_id)
    before = await _tag_names(db, payload.transaction_id)
    # Same normalization the executor resolves the tag with.
    wanted = normalize_payee(payload.tag)
    after = [n for n in before if normalize_payee(n) != wanted]
    return _tag_rows(subject, before, after)


class SplitChangePayload(BaseModel):
    """Which transaction, which lines. Parts follow the ``SplitPart``
    contract - positive magnitudes in cents; the service signs them and
    fills the difference as a remainder line under the parent's own
    category, so a proposal only states what the agent knows."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: int
    parts: list[SplitPart]

    @field_validator("parts")
    @classmethod
    def _parts_are_positive_magnitudes(
        cls, parts: list[SplitPart]
    ) -> list[SplitPart]:
        """Propose-time, not approve-time: a card that can never execute
        must never exist, and the error loops back to the proposer."""
        if not parts:
            raise ValueError("a split needs at least one part")
        if any(part.amount <= 0 for part in parts):
            raise ValueError(
                "part amounts are positive magnitudes in cents; the "
                "transaction's own sign is applied automatically"
            )
        return parts


async def _split_execute(
    db: AsyncSession, payload: SplitChangePayload, owner_user_id: int | None
) -> dict[str, Any]:
    lines = await splits.split_transaction(
        db, payload.transaction_id, payload.parts, owner_user_id=owner_user_id
    )
    return {
        "transaction_id": payload.transaction_id,
        "line_count": len(lines),
        "amounts": [line.amount for line in lines],
    }


async def _split_describe(
    db: AsyncSession, payload: SplitChangePayload, owner_user_id: int | None
) -> list[ChangeDisplayRow]:
    txn, subject = await _txn_subject(db, payload.transaction_id, owner_user_id)
    wanted = [p.category_id for p in payload.parts if p.category_id is not None]
    if txn is not None and txn.category_id is not None:
        wanted.append(txn.category_id)
    names = await categories.category_names(db, wanted)
    # One card row PER LINE - the user reviews the itemization the way
    # it will land: category, amount, and what the amount covers.
    rows = [ChangeDisplayRow(label="Transaction", value=subject)]
    for part in payload.parts:
        value = format_usd(part.amount)
        if part.memo:
            value += f" · {part.memo}"
        rows.append(
            ChangeDisplayRow(
                label=names.get(part.category_id, "Uncategorized"), value=value
            )
        )
    # Show the remainder line the approval will actually create - the
    # card must promise exactly what the executor does.
    if txn is not None:
        remainder = abs(txn.amount) - sum(p.amount for p in payload.parts)
        if remainder > 0:
            parent_name = (
                names.get(txn.category_id, "Uncategorized")
                if txn.category_id is not None
                else "Uncategorized"
            )
            rows.append(
                ChangeDisplayRow(
                    label=parent_name,
                    value=f"{format_usd(remainder)} · the rest",
                )
            )
    return rows


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
register(
    ChangeExecutor(
        change_type="transaction.split",
        title="Split a transaction",
        payload_model=SplitChangePayload,
        execute=_split_execute,
        describe=_split_describe,
    )
)
