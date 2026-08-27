"""SnapTrade payload -> our field names. Pure functions, no I/O.

Two symbol shapes arrive from the API and neither is the other's superset:
activities carry a nested UniversalSymbol, while ``/positions/all`` carries a
flat ``instrument`` discriminated by ``kind`` with its numbers serialized as
strings. Each gets its own flattener; both produce
``upsert_provider_security`` kwargs.
"""

from __future__ import annotations

from typing import Any

# SnapTrade activity ``type`` -> canonical finance_trade type. TRANSFER is
# resolved by cash direction below; anything unknown degrades to "other" so a
# new provider type never breaks a sync.
_SNAPTRADE_TRADE_TYPES: dict[str, str] = {
    "BUY": "buy",
    "SELL": "sell",
    "DIVIDEND": "dividend",
    "STOCK_DIVIDEND": "dividend",
    "REI": "reinvest",
    "INTEREST": "interest",
    "FEE": "fee",
    "TAX": "tax",
    "CONTRIBUTION": "deposit",
    "WITHDRAWAL": "withdrawal",
    "SPLIT": "split",
}


def map_trade_type(raw_type: str | None, amount: int | None) -> str:
    kind = (raw_type or "").upper()
    if kind == "TRANSFER":
        return "transfer_in" if (amount or 0) >= 0 else "transfer_out"
    return _SNAPTRADE_TRADE_TYPES.get(kind, "other")


def symbol_fields(symbol: dict[str, Any] | None) -> dict[str, Any] | None:
    """Flatten an activity's UniversalSymbol to upsert_provider_security
    kwargs."""
    if not symbol:
        return None
    provider_security_id = symbol.get("id")
    if not provider_security_id:
        return None
    security_type = symbol.get("type") or {}
    currency = symbol.get("currency") or {}
    return {
        "provider_security_id": str(provider_security_id),
        "ticker": symbol.get("raw_symbol") or symbol.get("symbol"),
        "name": symbol.get("description"),
        "security_type": security_type.get("code")
        if isinstance(security_type, dict)
        else security_type,
        "figi": symbol.get("figi_code"),
        "currency": (
            currency.get("code", "usd") if isinstance(currency, dict) else currency
        ).lower(),
    }


def instrument_fields(
    instrument: dict[str, Any] | None, currency: str | None
) -> dict[str, Any] | None:
    """Flatten a position's instrument to upsert_provider_security kwargs.
    ``currency`` is the position's own ISO code, which is what its ``price``
    and ``cost_basis`` are denominated in."""
    if not instrument or not instrument.get("id"):
        return None
    figi = instrument.get("figi_instrument")
    return {
        "provider_security_id": str(instrument["id"]),
        "ticker": instrument.get("raw_symbol") or instrument.get("symbol"),
        "name": instrument.get("description"),
        "security_type": instrument.get("kind"),
        "figi": figi.get("figi_code") if isinstance(figi, dict) else None,
        "currency": str(currency or instrument.get("currency") or "usd").lower(),
    }


def decimal_value(value: Any) -> float | None:
    """``/positions/all`` serializes quantities and money as strings."""
    if value is None or value == "":
        return None
    return float(value)
