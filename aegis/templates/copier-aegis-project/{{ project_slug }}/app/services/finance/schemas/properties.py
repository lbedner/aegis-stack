"""Property request and response shapes.

Split from ``schemas.py`` the way the goal contract was: the stored blob is
namespaced keys and the API is field names, and the translation between the
two deserves its own screen. A topic module of the ``schemas`` package; re-exported from its root so
``from app.services.finance.schemas import PropertySummary`` keeps working.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel


class PropertySummary(BaseModel):
    """A property account's facts, as the API renders them.

    Mirrors ``PropertyMeta`` without the stored-key aliases: clients read
    field names, the column keeps its namespaced keys.
    """

    kind: str
    purchase_price: int | None = None
    purchase_date: date | None = None
    down_payment: int | None = None
    ownership_share_bps: int
    valuation_source: str
    valuation_as_of: date | None = None
    include_in_net_worth: bool
    address_label: str | None = None

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any] | None) -> PropertySummary | None:
        from app.services.finance.domains.ledger.properties import property_metadata

        meta = property_metadata(metadata)
        if meta is None:
            return None
        return cls(
            kind=meta.property_kind,
            purchase_price=meta.purchase_price,
            purchase_date=meta.purchase_date,
            down_payment=meta.down_payment,
            ownership_share_bps=meta.ownership_share_bps,
            valuation_source=meta.valuation_source,
            valuation_as_of=meta.valuation_as_of,
            include_in_net_worth=meta.include_in_net_worth,
            address_label=meta.address_label,
        )


class PropertyDetailsUpdate(BaseModel):
    """PATCH /accounts/{id}/property - only provided fields change.

    Every field is optional so a surface can send the subset it shows: the
    account dialog displays six of these, and defaults for the rest would
    quietly reset an address label or an ownership share set elsewhere.
    """

    property_kind: str | None = None
    purchase_price: int | None = None
    purchase_date: date | None = None
    down_payment: int | None = None
    ownership_share_bps: int | None = None
    valuation_source: str | None = None
    valuation_as_of: date | None = None
    include_in_net_worth: bool | None = None
    address_label: str | None = None


class ValuationBulkRequest(BaseModel):
    """POST /accounts/{id}/valuations/bulk - a pasted series, one source.

    ``text`` is what the user copied: a listing site's history table, or a
    CSV column pair. Parsing lives in the service so the same block works
    from the CLI or a future importer.
    """

    text: str
    source: str = "manual"
    is_estimate: bool = False
    note: str | None = None


class ValuationBulkResponse(BaseModel):
    """How much of the paste was new."""

    added: int
    updated: int
    total: int
