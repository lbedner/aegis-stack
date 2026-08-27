"""The envelope contract: a virtual sub-account wearing envelope metadata.

An envelope is a running balance living inside real cash - an allowance
the kid draws down, a house-repairs pot. Same account-as-carrier design
as ``goals.py`` (hidden manual account, balance and dated history on
``FinanceValuation``), but balances move BOTH directions and there is no
target, progress, or finish line.

The two ``metadata_`` keys below are the whole schema; this module's
accessors are their only reader/writer.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.ledger import accounts, valuations
from app.services.finance.domains.ledger import queries as ledger_queries
from app.services.finance.domains.planning import queries
from app.services.finance.models import (
    FinanceAccount,
)
from app.services.finance.utils import (
    utcnow,
)

ENVELOPE_ACCOUNT_TYPE = "envelope"
ENVELOPE_CADENCES = ("weekly", "monthly")

_MARKER_KEY = "envelope"
_CREDIT_KEY = "envelope_monthly_credit"
_AUTO_KEY = "envelope_auto_credit"
_CADENCE_KEY = "envelope_credit_cadence"
_ENVELOPE_KEYS = (_MARKER_KEY, _CREDIT_KEY, _AUTO_KEY, _CADENCE_KEY)


class EnvelopeMeta(BaseModel):
    """An account's envelope facts, parsed and validated.

    Each field's alias IS its stored ``metadata_`` key, so the model both
    parses a stored blob and serializes back to one. The marker key is
    storage-only presence, not a fact about the envelope.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    # cents PER PERIOD, >= 0
    monthly_credit: int | None = Field(default=None, alias=_CREDIT_KEY)
    # the scheduler books the credit each period
    auto_credit: bool = Field(default=False, alias=_AUTO_KEY)
    # weekly | monthly - how often the credit lands
    cadence: str = Field(default="monthly", alias=_CADENCE_KEY)


def envelope_metadata(metadata: dict[str, Any] | None) -> EnvelopeMeta | None:
    """The account's ``EnvelopeMeta``, or ``None`` when it wears none
    (the marker key is the presence flag)."""
    if not metadata or not metadata.get(_MARKER_KEY):
        return None
    stored = {
        key: metadata[key]
        for key in (_CREDIT_KEY, _AUTO_KEY, _CADENCE_KEY)
        if metadata.get(key) is not None
    }
    return _validated(EnvelopeMeta.model_validate(stored))


def set_envelope_metadata(
    metadata: dict[str, Any] | None,
    *,
    monthly_credit: int | None = None,
    auto_credit: bool = False,
    cadence: str = "monthly",
) -> dict[str, Any]:
    """A new metadata dict with the envelope keys written (neighbours kept)."""
    meta = _validated(
        EnvelopeMeta(
            monthly_credit=monthly_credit, auto_credit=auto_credit, cadence=cadence
        )
    )
    return {
        **(metadata or {}),
        _MARKER_KEY: True,
        **meta.model_dump(mode="json", by_alias=True),
    }


def clear_envelope_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    return {k: v for k, v in (metadata or {}).items() if k not in _ENVELOPE_KEYS}


def _validated(meta: EnvelopeMeta) -> EnvelopeMeta:
    if meta.monthly_credit is not None and meta.monthly_credit < 0:
        raise ValueError(
            f"Monthly credit cannot be negative, got {meta.monthly_credit}."
        )
    if meta.cadence not in ENVELOPE_CADENCES:
        raise ValueError(
            f"Unknown credit cadence {meta.cadence!r}. "
            f"Known: {', '.join(ENVELOPE_CADENCES)}."
        )
    return meta


async def create_envelope(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    name: str,
    monthly_credit: int | None = None,
    cadence: str = "monthly",
    starting_balance: int = 0,
) -> FinanceAccount:
    account = await accounts.create_manual_account(
        db,
        owner_user_id=owner_user_id,
        name=name,
        account_type=ENVELOPE_ACCOUNT_TYPE,
        classification="asset",
    )
    account.is_hidden = True
    account.metadata_ = set_envelope_metadata(
        account.metadata_, monthly_credit=monthly_credit, cadence=cadence
    )
    db.add(account)
    await db.flush()
    if starting_balance > 0:
        return await credit_envelope(
            db,
            account.id,
            amount=starting_balance,
            owner_user_id=owner_user_id,
            note="Starting balance",
        )
    return account


async def list_envelopes(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> list[FinanceAccount]:
    return await queries.accounts_of_type(
        db, account_type=ENVELOPE_ACCOUNT_TYPE, owner_user_id=owner_user_id
    )


async def walk_envelope(
    db: AsyncSession,
    account_id: int,
    *,
    delta: int,
    owner_user_id: int | None,
    when: date | None,
    note: str | None,
    source: str = "manual",
) -> FinanceAccount:
    account = await accounts.get_account(db, account_id, owner_user_id=owner_user_id)
    if account is None or envelope_metadata(account.metadata_) is None:
        raise ValueError(f"No envelope {account_id}.")
    await valuations.upsert_valuation(
        db,
        account_id=account_id,
        as_of_date=when or utcnow().date(),
        value=(account.current_balance or 0) + delta,
        owner_user_id=owner_user_id,
        source=source,
        note=note,
    )
    refreshed = await accounts.get_account(db, account_id, owner_user_id=owner_user_id)
    assert refreshed is not None  # just written
    return refreshed


async def credit_envelope(
    db: AsyncSession,
    account_id: int,
    *,
    amount: int,
    owner_user_id: int | None,
    when: date | None = None,
    note: str | None = None,
) -> FinanceAccount:
    if amount <= 0:
        raise ValueError("Credit a positive amount.")
    return await walk_envelope(
        db,
        account_id,
        delta=amount,
        owner_user_id=owner_user_id,
        when=when,
        note=note or "Credit",
    )


async def spend_from_envelope(
    db: AsyncSession,
    account_id: int,
    *,
    amount: int,
    owner_user_id: int | None,
    when: date | None = None,
    note: str | None = None,
) -> FinanceAccount:
    if amount <= 0:
        raise ValueError("Spend a positive amount.")
    return await walk_envelope(
        db,
        account_id,
        delta=-amount,
        owner_user_id=owner_user_id,
        when=when,
        note=note or "Spent",
    )


async def set_envelope_auto_credit(
    db: AsyncSession, account_id: int, enabled: bool, *, owner_user_id: int | None
) -> FinanceAccount | None:
    account = await accounts.get_account(db, account_id, owner_user_id=owner_user_id)
    if account is None:
        return None
    meta = envelope_metadata(account.metadata_)
    if meta is None:
        raise ValueError(f"Account {account_id} is not an envelope.")
    account.metadata_ = set_envelope_metadata(
        account.metadata_,
        monthly_credit=meta.monthly_credit,
        auto_credit=enabled,
        cadence=meta.cadence,
    )
    db.add(account)
    await db.flush()
    return account


async def update_envelope(
    db: AsyncSession,
    account_id: int,
    *,
    owner_user_id: int | None,
    monthly_credit: int | None,
    auto_credit: bool,
    cadence: str = "monthly",
) -> FinanceAccount | None:
    account = await accounts.get_account(db, account_id, owner_user_id=owner_user_id)
    if account is None or envelope_metadata(account.metadata_) is None:
        return None
    account.metadata_ = set_envelope_metadata(
        account.metadata_,
        monthly_credit=monthly_credit,
        auto_credit=auto_credit,
        cadence=cadence,
    )
    db.add(account)
    await db.flush()
    return account


async def auto_credit_envelopes(
    db: AsyncSession, *, owner_user_id: int | None, today: date
) -> int:
    """The 1st-of-month booking: each auto-credit-on envelope's
    monthly credit as an ``envelope_auto`` valuation. Idempotent per
    month via the distinct source - catch-up safe."""
    booked = 0
    for account in await list_envelopes(db, owner_user_id=owner_user_id):
        meta = envelope_metadata(account.metadata_)
        if meta is None or not meta.auto_credit or not meta.monthly_credit:
            continue
        # The period's booking date IS the idempotency key: the 1st
        # for monthly, this week's Monday for weekly.
        if meta.cadence == "weekly":
            period_start = today - timedelta(days=today.weekday())
        else:
            period_start = date(today.year, today.month, 1)
        already = await ledger_queries.valuation_by_key(
            db,
            account_id=account.id,
            as_of_date=period_start,
            source="envelope_auto",
        )
        if already is not None:
            continue
        await valuations.upsert_valuation(
            db,
            account_id=account.id,
            as_of_date=period_start,
            value=(account.current_balance or 0) + meta.monthly_credit,
            owner_user_id=owner_user_id,
            source="envelope_auto",
            note="Weekly credit" if meta.cadence == "weekly" else "Monthly credit",
        )
        booked += 1
    return booked
