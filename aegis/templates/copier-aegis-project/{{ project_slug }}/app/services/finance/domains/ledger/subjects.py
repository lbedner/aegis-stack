"""Whose money a row describes.

A subject is a person, trust, or estate whose money this household
tracks but does not own: a parent in care, a child's savings, an estate
being settled. Rows without one are the household's own, which is why
every existing ledger reads unchanged.
"""

from __future__ import annotations

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.models import FinanceAccount, FinanceSubject
from app.services.finance.utils import utcnow

# What a subject can be. The table constrains these too; validating here
# turns a flush-time IntegrityError into an answer the caller can read.
SUBJECT_KINDS = ("person", "trust", "estate", "entity")


async def create_subject(
    db: AsyncSession,
    *,
    name: str,
    kind: str = "person",
    note: str | None = None,
    owner_user_id: int | None = None,
) -> FinanceSubject:
    """Record someone whose money this household tracks."""
    display = (name or "").strip()
    if not display:
        raise ValueError("A subject needs a name.")
    if kind not in SUBJECT_KINDS:
        raise ValueError(
            f"Unknown subject kind {kind!r}; expected one of "
            f"{', '.join(SUBJECT_KINDS)}."
        )
    subject = FinanceSubject(
        owner_user_id=owner_user_id, name=display, kind=kind, note=note
    )
    db.add(subject)
    await db.flush()
    return subject


async def list_subjects(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> list[FinanceSubject]:
    query = select(FinanceSubject).where(FinanceSubject.deleted_at.is_(None))
    if owner_user_id is not None:
        query = query.where(FinanceSubject.owner_user_id == owner_user_id)
    return list((await db.exec(query.order_by(FinanceSubject.name))).all())


async def get_subject(
    db: AsyncSession, subject_id: int, *, owner_user_id: int | None = None
) -> FinanceSubject | None:
    query = select(FinanceSubject).where(
        FinanceSubject.id == subject_id, FinanceSubject.deleted_at.is_(None)
    )
    if owner_user_id is not None:
        query = query.where(FinanceSubject.owner_user_id == owner_user_id)
    return (await db.exec(query)).first()


async def assign_subject(
    db: AsyncSession,
    account_id: int,
    subject_id: int | None,
    *,
    owner_user_id: int | None = None,
) -> FinanceAccount | None:
    """Point an account at whose money it holds; None releases it back
    to the household."""
    query = select(FinanceAccount).where(
        FinanceAccount.id == account_id, FinanceAccount.deleted_at.is_(None)
    )
    if owner_user_id is not None:
        query = query.where(FinanceAccount.owner_user_id == owner_user_id)
    account = (await db.exec(query)).first()
    if account is None:
        return None
    if subject_id is not None:
        subject = await get_subject(db, subject_id, owner_user_id=owner_user_id)
        if subject is None:
            raise ValueError(f"Subject {subject_id} not found.")
    account.subject_id = subject_id
    account.updated_at = utcnow()
    db.add(account)
    await db.flush()
    return account
