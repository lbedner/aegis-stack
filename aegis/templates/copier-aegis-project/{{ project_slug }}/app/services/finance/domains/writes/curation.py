"""Label-axis change types: what a row is filed under and who it was
with. Categorize, payee assignment, tag, untag - curation in FW-06's
sense. The hub module ``executors`` registers these."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.ledger import categories, merchants, transactions
from app.services.finance.domains.writes.display import txn_subject
from app.services.finance.schemas import ChangeDisplayRow


class CategorizePayload(BaseModel):
    """The exact mutation: which transaction, which category. ``extra``
    is forbidden so a proposal cannot smuggle fields no executor reads
    but a card might display."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: int
    category_id: int


async def categorize_execute(
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


async def categorize_describe(
    db: AsyncSession, payload: CategorizePayload, owner_user_id: int | None
) -> list[ChangeDisplayRow]:
    txn, subject = await txn_subject(db, payload.transaction_id, owner_user_id)
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


class AssignPayeePayload(BaseModel):
    """Which transaction, which payee - by NAME, because the payee may
    not exist yet; approval find-or-creates it by normalized name (the
    register picker's own rule), so two spellings cannot mint two rows."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: int
    payee: str

    @field_validator("payee")
    @classmethod
    def _payee_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("payee must not be blank")
        return value.strip()


async def assign_payee_execute(
    db: AsyncSession, payload: AssignPayeePayload, owner_user_id: int | None
) -> dict[str, Any]:
    merchant = await merchants.create_merchant(
        db, payload.payee, owner_user_id=owner_user_id
    )
    updated = await merchants.assign_merchant(
        db, [payload.transaction_id], merchant.id, owner_user_id=owner_user_id
    )
    if updated == 0:
        raise ValueError(f"Transaction {payload.transaction_id} not found.")
    return {
        "transaction_id": payload.transaction_id,
        "merchant_id": merchant.id,
        "merchant": merchant.name,
    }


async def assign_payee_describe(
    db: AsyncSession, payload: AssignPayeePayload, owner_user_id: int | None
) -> list[ChangeDisplayRow]:
    txn, subject = await txn_subject(db, payload.transaction_id, owner_user_id)
    # An assignment is a MOVE like the rest: from the payee holding the
    # row now (usually none), read at render time so the card shows the
    # current truth.
    before = "Unassigned"
    if txn is not None and txn.merchant_id is not None:
        names = await merchants.merchant_names(db, {txn.merchant_id})
        before = names.get(txn.merchant_id, before)
    return [
        ChangeDisplayRow(label="Transaction", value=subject),
        ChangeDisplayRow(label="Payee", value=f"{before} \u2192 {payload.payee}"),
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
            value=f"{', '.join(before) or 'none'} \u2192 {', '.join(after) or 'none'}",
        ),
    ]


async def tag_execute(
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


async def tag_describe(
    db: AsyncSession, payload: TagPayload, owner_user_id: int | None
) -> list[ChangeDisplayRow]:
    from app.services.finance.utils import normalize_payee

    _txn, subject = await txn_subject(db, payload.transaction_id, owner_user_id)
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


async def untag_execute(
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


async def untag_describe(
    db: AsyncSession, payload: TagPayload, owner_user_id: int | None
) -> list[ChangeDisplayRow]:
    from app.services.finance.utils import normalize_payee

    _txn, subject = await txn_subject(db, payload.transaction_id, owner_user_id)
    before = await _tag_names(db, payload.transaction_id)
    # Same normalization the executor resolves the tag with.
    wanted = normalize_payee(payload.tag)
    after = [n for n in before if normalize_payee(n) != wanted]
    return _tag_rows(subject, before, after)
