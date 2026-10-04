"""Structural change types: what a row IS. A split carves one purchase
into category lines; a match records which payment paid which bill.
The hub module ``executors`` registers these."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.change_queue.schemas import ChangeDisplayRow
from app.services.finance.domains.detection.insights.formatting import format_usd
from app.services.finance.domains.ledger import categories, splits
from app.services.finance.domains.writes.display import live_transactions, txn_subject
from app.services.finance.models import FinanceTransaction
from app.services.finance.schemas import SplitPart


class MatchPayload(BaseModel):
    """Which payment paid which bill."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: int
    stream_id: int


async def match_execute(
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


async def match_describe(
    db: AsyncSession, payloads: list[MatchPayload], owner_user_id: int | None
) -> list[list[ChangeDisplayRow]]:
    from app.services.finance.domains.planning.recurring import queries

    txns = await live_transactions(
        db, [p.transaction_id for p in payloads], owner_user_id
    )
    bills = await queries.streams_by_ids(
        db,
        list(
            {p.stream_id for p in payloads}
            | {
                t.recurring_stream_id
                for t in txns.values()
                if t.recurring_stream_id is not None
            }
        ),
        owner_user_id=owner_user_id,
    )
    cards = []
    for payload in payloads:
        txn = txns.get(payload.transaction_id)
        # A match is a MOVE too: from whichever live bill holds the row now
        # (usually none) to the proposed one, read from the row so the card
        # shows the current truth.
        holder = bills.get(txn.recurring_stream_id) if txn and txn.recurring_stream_id else None
        before = holder.name if holder is not None else "Unmatched"
        stream = bills.get(payload.stream_id)
        after = stream.name if stream is not None else f"bill {payload.stream_id} (missing)"
        cards.append(
            [
                ChangeDisplayRow(
                    label="Payment", value=txn_subject(txn, payload.transaction_id)
                ),
                ChangeDisplayRow(label="Bill", value=f"{before} \u2192 {after}"),
            ]
        )
    return cards


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
    def _parts_are_positive_magnitudes(cls, parts: list[SplitPart]) -> list[SplitPart]:
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


async def split_execute(
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


async def split_describe(
    db: AsyncSession, payloads: list[SplitChangePayload], owner_user_id: int | None
) -> list[list[ChangeDisplayRow]]:
    txns = await live_transactions(
        db, [p.transaction_id for p in payloads], owner_user_id
    )
    names = await categories.category_names(
        db,
        {
            part.category_id
            for p in payloads
            for part in p.parts
            if part.category_id is not None
        }
        | {t.category_id for t in txns.values() if t.category_id is not None},
    )
    return [
        _split_card(p, txns.get(p.transaction_id), names) for p in payloads
    ]


def _split_card(
    payload: SplitChangePayload,
    txn: FinanceTransaction | None,
    names: dict[int, str],
) -> list[ChangeDisplayRow]:
    subject = txn_subject(txn, payload.transaction_id)
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
