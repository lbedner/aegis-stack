"""Whose money a row describes.

A subject is a person, trust, or estate whose money this household
tracks but does not own: a parent in care, a child's savings, an estate
being settled. Rows without one are the household's own, which is why
every existing ledger reads unchanged.
"""

from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.services.finance.domains.ledger import queries
from app.services.finance.models import FinanceAccount, FinanceSubject

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
    return await queries.subjects_for_owner(db, owner_user_id=owner_user_id)


async def get_subject(
    db: AsyncSession, subject_id: int, *, owner_user_id: int | None = None
) -> FinanceSubject | None:
    return await queries.subject_by_id(db, subject_id, owner_user_id=owner_user_id)


async def assign_subject(
    db: AsyncSession,
    account_id: int,
    subject_id: int | None,
    *,
    owner_user_id: int | None = None,
) -> FinanceAccount | None:
    """Point an account at whose money it holds; None releases it back
    to the household."""
    account = await queries.account_by_id(db, account_id, owner_user_id=owner_user_id)
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
