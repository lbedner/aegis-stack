"""The normalized shape every investment-ledger profile parses into, and the
replay check that verifies a parsed ledger before it's loaded.

House sign rule (matches ``importers/base.py``): negative means an outflow.
Here that's per-security: a row that adds shares/value to a position is
positive, one that removes shares/value is negative.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class InvestmentActivity(BaseModel):
    """One normalized trade-ledger row, source-agnostic."""

    model_config = ConfigDict(frozen=True)

    trade_date: date
    security_name: str
    trade_type: (
        str  # FinanceTrade.type vocabulary: buy, sell, reinvest, fee, transfer_in, ...
    )
    units: Decimal  # signed: + adds to the position, - removes from it
    price: Decimal
    amount_cents: int  # signed cents, same direction as units
    raw_type: str  # the source's own label, for traceability
    subtype: str | None = None
    ticker: str | None = None


def replay_positions(activities: list[InvestmentActivity]) -> dict[str, Decimal]:
    """Sum signed ``units`` per security name.

    The verify step: replay a parsed ledger and compare the result to the
    source's own stated current holdings before writing anything.
    """
    positions: dict[str, Decimal] = defaultdict(Decimal)
    for activity in activities:
        positions[activity.security_name] += activity.units
    return dict(positions)
