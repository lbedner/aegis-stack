"""Property facts stored on an account's ``metadata`` blob.

Real estate is the largest asset on most balance sheets, and the ledger
represents it the way goals and envelopes are represented: an ordinary
account (``account_type='property'``, classification asset) wearing a
namespaced metadata contract. No new table.

``PropertyMeta`` is that contract, and it is the validation boundary. Each
field's alias IS its stored key, so one model both parses a stored blob and
serializes back to one - the shape ``GoalMeta`` uses. Figures that reach
JSON unchecked are figures every later reader has to re-guess: a house
valued at "$711,200 (user estimate, Aug 2026)" answers a question an
unlabelled 71120000 cannot.
"""

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlmodel import Field, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.models import FinanceAccount, FinanceLiabilityDetail

PROPERTY_ACCOUNT_TYPE = "property"

# How a current value was arrived at. The distinction is the point: an
# automated estimate and an appraisal carry different weight in a lending
# conversation, and the model must never present one as the other.
VALUATION_SOURCES = ("user", "automated", "broker", "appraisal")
PROPERTY_KINDS = ("primary", "rental", "vacation", "land", "other")

FULL_OWNERSHIP_BPS = 10_000

_KIND_KEY = "property_kind"
_PURCHASE_PRICE_KEY = "property_purchase_price"
_PURCHASE_DATE_KEY = "property_purchase_date"
_DOWN_PAYMENT_KEY = "property_down_payment"
_OWNERSHIP_KEY = "property_ownership_share_bps"
_SOURCE_KEY = "property_valuation_source"
_VALUED_KEY = "property_valuation_as_of"
_NET_WORTH_KEY = "property_include_in_net_worth"
_LABEL_KEY = "property_address_label"
_PREFERRED_SOURCE_KEY = "property_preferred_valuation_source"
_PROPERTY_KEYS = (
    _KIND_KEY,
    _PURCHASE_PRICE_KEY,
    _PURCHASE_DATE_KEY,
    _DOWN_PAYMENT_KEY,
    _OWNERSHIP_KEY,
    _SOURCE_KEY,
    _VALUED_KEY,
    _NET_WORTH_KEY,
    _LABEL_KEY,
    _PREFERRED_SOURCE_KEY,
)


class PropertyMeta(BaseModel):
    """An account's property facts, parsed and validated.

    Every field is optional except the kind: a property inherited or
    gifted has no purchase price, and refusing to record it at all would
    be worse than recording what is known.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    property_kind: str = Field(default="primary", alias=_KIND_KEY)
    purchase_price: int | None = Field(default=None, alias=_PURCHASE_PRICE_KEY)
    purchase_date: date | None = Field(default=None, alias=_PURCHASE_DATE_KEY)
    down_payment: int | None = Field(default=None, alias=_DOWN_PAYMENT_KEY)
    # Basis points of the property this book owns. A jointly held house
    # recorded at 100% overstates net worth by exactly the other half.
    ownership_share_bps: int = Field(default=FULL_OWNERSHIP_BPS, alias=_OWNERSHIP_KEY)
    valuation_source: str = Field(default="user", alias=_SOURCE_KEY)
    valuation_as_of: date | None = Field(default=None, alias=_VALUED_KEY)
    include_in_net_worth: bool = Field(default=True, alias=_NET_WORTH_KEY)
    address_label: str | None = Field(default=None, alias=_LABEL_KEY)
    # Which source's series drives ``current_balance`` when several have an
    # opinion about the same property. None means "whatever is newest",
    # which is only unambiguous while there is exactly one source.
    preferred_valuation_source: str | None = Field(
        default=None, alias=_PREFERRED_SOURCE_KEY
    )


def _validated(meta: PropertyMeta) -> PropertyMeta:
    if meta.property_kind not in PROPERTY_KINDS:
        raise ValueError(
            f"Unknown property kind {meta.property_kind!r}. "
            f"Known: {', '.join(PROPERTY_KINDS)}."
        )
    if meta.valuation_source not in VALUATION_SOURCES:
        raise ValueError(
            f"Unknown valuation source {meta.valuation_source!r}. "
            f"Known: {', '.join(VALUATION_SOURCES)}."
        )
    if meta.purchase_price is not None and meta.purchase_price < 0:
        raise ValueError(
            f"Purchase price cannot be negative, got {meta.purchase_price}."
        )
    if meta.down_payment is not None and meta.down_payment < 0:
        raise ValueError(f"Down payment cannot be negative, got {meta.down_payment}.")
    if (
        meta.purchase_price is not None
        and meta.down_payment is not None
        and meta.down_payment > meta.purchase_price
    ):
        raise ValueError(
            f"Down payment {meta.down_payment} exceeds the purchase price "
            f"{meta.purchase_price}."
        )
    if not 0 < meta.ownership_share_bps <= FULL_OWNERSHIP_BPS:
        raise ValueError(
            f"Ownership share must be between 1 and {FULL_OWNERSHIP_BPS} bps, "
            f"got {meta.ownership_share_bps}."
        )
    return meta


def property_metadata(metadata: dict[str, Any] | None) -> PropertyMeta | None:
    """The account's ``PropertyMeta``, or ``None`` when it wears none.

    ``property_kind`` is the presence marker rather than the purchase
    price, which a gifted or inherited property legitimately lacks.

    Raises ``ValueError`` on corrupt stored values: a property whose
    source reads "vibes" must fail loudly, not silently present itself as
    an appraisal.
    """
    if not metadata or _KIND_KEY not in metadata:
        return None
    stored = {key: metadata[key] for key in _PROPERTY_KEYS if key in metadata}
    return _validated(PropertyMeta.model_validate(stored))


def set_property_metadata(
    metadata: dict[str, Any] | None,
    *,
    property_kind: str = "primary",
    purchase_price: int | None = None,
    purchase_date: date | None = None,
    down_payment: int | None = None,
    ownership_share_bps: int = FULL_OWNERSHIP_BPS,
    valuation_source: str = "user",
    valuation_as_of: date | None = None,
    include_in_net_worth: bool = True,
    address_label: str | None = None,
    preferred_valuation_source: str | None = None,
) -> dict[str, Any]:
    """A new metadata dict with the property keys written (neighbours kept)."""
    meta = _validated(
        PropertyMeta(
            property_kind=property_kind,
            purchase_price=purchase_price,
            purchase_date=purchase_date,
            down_payment=down_payment,
            ownership_share_bps=ownership_share_bps,
            valuation_source=valuation_source,
            valuation_as_of=valuation_as_of,
            include_in_net_worth=include_in_net_worth,
            address_label=address_label,
            preferred_valuation_source=preferred_valuation_source,
        )
    )
    return {**(metadata or {}), **meta.model_dump(mode="json", by_alias=True)}


def clear_property_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """A new metadata dict with the property keys stripped."""
    return {k: v for k, v in (metadata or {}).items() if k not in _PROPERTY_KEYS}


def equity(*, value: int | None, loan_balance: int) -> int | None:
    """Value minus what is secured against it, in cents.

    ``loan_balance`` arrives as the liability's magnitude (positive cents).
    Returns ``None`` when the property has no value to work from, rather
    than reporting the negative of the mortgage as equity.
    """
    if value is None:
        return None
    return value - abs(loan_balance)


async def set_property_details(
    db: AsyncSession,
    account_id: int,
    *,
    owner_user_id: int | None = None,
    **fields: Any,
) -> FinanceAccount | None:
    """Write one property account's facts. None when not found or not owned.

    Refuses a non-property account: the metadata column takes anything, so
    the only place this can be caught is on the way in - and property keys
    on a checking account would reach every net-worth reader downstream.

    ``None`` means "not provided" and leaves the stored value alone;
    ``False`` is a value and is written.
    """
    from app.services.finance.domains.ledger.accounts import get_account
    from app.services.finance.utils import utcnow

    account = await get_account(db, account_id, owner_user_id=owner_user_id)
    if account is None:
        return None
    if account.account_type != PROPERTY_ACCOUNT_TYPE:
        raise ValueError(
            f"Account {account_id} is a {account.account_type!r} account, "
            f"not a property."
        )
    # Partial by construction: callers send the fields their surface shows,
    # and anything absent keeps what is stored. A full write would let the
    # six-field dialog reset the three fields it does not display.
    current = property_metadata(account.metadata_)
    merged: dict[str, Any] = current.model_dump() if current is not None else {}
    merged.update({key: value for key, value in fields.items() if value is not None})
    account.metadata_ = set_property_metadata(account.metadata_, **merged)
    account.updated_at = utcnow()
    db.add(account)
    await db.flush()
    return account


class SecuredPosition(BaseModel):
    """Equity and LTV for one property, derived from its lien links.

    Computed at read time, never stored: the inputs (valuation, loan
    balances) each move on their own schedule, and a stored copy would
    just be one more number that can disagree. ``ltv_bps`` is basis
    points (26.29% = 2629), ``None`` when the property has no value to
    ratio against.
    """

    model_config = ConfigDict(frozen=True)

    equity: int
    ltv_bps: int | None


def secured_position(
    property_value: int, secured_balances: list[int]
) -> SecuredPosition | None:
    """The property's position against the liens it secures, or ``None``
    when nothing is linked - an unlinked property must show NO figures,
    not a noisy 100%-equity claim."""
    if not secured_balances:
        return None
    owed = sum(secured_balances)
    ltv = round(owed * 10_000 / property_value) if property_value > 0 else None
    return SecuredPosition(equity=property_value - owed, ltv_bps=ltv)


async def set_secured_debt(
    db: AsyncSession,
    account_id: int,
    *,
    owner_user_id: int | None = None,
    secured_by_account_id: int | None,
    lien_position: int | None = None,
) -> FinanceLiabilityDetail | None:
    """Record which property secures a liability - what the user CONFIRMS,
    never inferred (the assistant explicitly refused to guess lien
    priority, and that refusal was correct; this is where the confirmed
    answer lives). ``secured_by_account_id=None`` unlinks and clears the
    lien position with it. Equity and LTV derive from the link at read
    time and are never stored.
    """
    from app.services.finance.domains.ledger.accounts import get_account
    from app.services.finance.utils import utcnow

    liability = await get_account(db, account_id, owner_user_id=owner_user_id)
    if liability is None:
        return None
    if liability.classification != "liability":
        raise ValueError(
            f"Account {account_id} is an asset; only a liability can be "
            "secured by a property."
        )
    if secured_by_account_id is not None:
        target = await get_account(
            db, secured_by_account_id, owner_user_id=owner_user_id
        )
        if target is None or target.account_type != PROPERTY_ACCOUNT_TYPE:
            raise ValueError(
                f"Account {secured_by_account_id} is not a property; a lien "
                "can only attach to one."
            )
        if lien_position is not None and lien_position < 1:
            raise ValueError("lien_position counts from 1 (first mortgage).")

    detail = (
        await db.exec(
            select(FinanceLiabilityDetail).where(
                FinanceLiabilityDetail.account_id == account_id
            )
        )
    ).first()
    if detail is None:
        detail = FinanceLiabilityDetail(
            owner_user_id=owner_user_id, account_id=account_id
        )
    if secured_by_account_id is None:
        detail.secured_by_account_id = None
        detail.lien_position = None
    else:
        detail.secured_by_account_id = secured_by_account_id
        detail.lien_position = lien_position or 1
    detail.updated_at = utcnow()
    db.add(detail)
    await db.flush()
    return detail
