"""Parses Optum Financial / ConnectYourCare HSA "Settled Transactions" ledgers
(the investment-sleeve activity report — copy/pasted or exported as
tab-separated text from the account's Investment Transactions tab).

The report has no native row IDs, so the loader dedups on a content hash of
each row's natural key instead (date + security + type + units + price).
"""

from __future__ import annotations

import csv
from datetime import datetime
from decimal import Decimal
import io

from app.services.finance.importers.base import to_cents
from app.services.finance.investments.activity import InvestmentActivity

# raw Optum "Type" label -> (canonical trade type, subtype, share-sign)
# Sign follows the per-security house rule: + adds to the position (value
# entering), - removes from it (value leaving).
_ACTIVITY_MAP: dict[str, tuple[str, str | None, int]] = {
    "BUY INVESTMENTS": ("buy", None, 1),
    "REINVESTED DIVIDEND": ("reinvest", None, 1),
    "CONVERSION BALANCE": ("transfer_in", None, 1),
    "SALE OF RECORDKEEPING FEE": ("fee", "recordkeeping_fee", -1),
    "PURCHASE DUE TO FUND EXCHANGE": ("buy", "fund_exchange", 1),
    "SALE DUE TO FUND EXCHANGE": ("sell", "fund_exchange", -1),
}


class UnknownActivityTypeError(ValueError):
    """Raised when a ledger row's ``Type`` isn't in ``_ACTIVITY_MAP``.

    Silently guessing a sign for an unrecognized activity type would corrupt
    a financial ledger, so an unmapped type is a hard stop rather than an
    ``"other"`` fallback.
    """

    def __init__(self, raw_type: str, row: list[str]) -> None:
        self.raw_type = raw_type
        self.row = row
        super().__init__(
            f"Unrecognized Optum activity type {raw_type!r} in row {row}. "
            f"Known types: {sorted(_ACTIVITY_MAP)}."
        )


def _to_decimal(text: str) -> Decimal:
    return Decimal(text.replace("$", "").replace(",", "").strip())


def parse_optum_settled_transactions(text: str) -> list[InvestmentActivity]:
    """Parse the tab-separated "Settled Transactions" export/paste.

    Skips the title line, reads the header, then one activity per data row.
    """
    rows = list(csv.reader(io.StringIO(text), delimiter="\t"))
    header_idx = next(
        i for i, row in enumerate(rows) if row and row[0].strip() == "Transaction Date"
    )
    activities: list[InvestmentActivity] = []
    for row in rows[header_idx + 1 :]:
        if not row or not row[0].strip():
            continue
        raw_date, security_name, raw_type, raw_units, raw_price, raw_amount = row[:6]
        raw_type = raw_type.strip()
        mapping = _ACTIVITY_MAP.get(raw_type)
        if mapping is None:
            raise UnknownActivityTypeError(raw_type, row)
        trade_type, subtype, sign = mapping
        units = _to_decimal(raw_units) * sign
        price = _to_decimal(raw_price)
        amount_cents = to_cents(_to_decimal(raw_amount)) * sign
        activities.append(
            InvestmentActivity(
                trade_date=datetime.strptime(raw_date.strip(), "%m/%d/%Y").date(),
                security_name=security_name.strip(),
                trade_type=trade_type,
                units=units,
                price=price,
                amount_cents=amount_cents,
                raw_type=raw_type,
                subtype=subtype,
            )
        )
    return activities
