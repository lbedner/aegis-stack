"""Positions and activities.

Activities are date-windowed rather than cursored, so each sync
re-pulls a trailing window and dedups. Securities merge across
providers by FIGI/CUSIP/ISIN through the shared upsert, so the same
holding arriving from Plaid and SnapTrade is one row.
"""

from datetime import date
import logging
from typing import Any

from app.core.time import utcnow
from app.services.finance.adapters.providers.connections import snaptrade_mapping
from app.services.finance.constants import Provider
from app.services.finance.models import FinanceConnection
from app.services.finance.service import FinanceService

logger = logging.getLogger(__name__)


async def _apply_snaptrade_positions(
    service: FinanceService,
    positions: list[dict[str, Any]],
    *,
    account_id: int,
    owner_user_id: int | None,
) -> int:
    """Positions -> securities (via the FIGI-first shared upsert) + dated
    holdings. The account balance stays SnapTrade's ``balance.total``
    (``sync_account_balance=False``), mirroring the Plaid path."""
    count = 0
    for position in positions:
        fields = snaptrade_mapping.instrument_fields(
            position.get("instrument"), position.get("currency")
        )
        if fields is None:
            continue
        units = snaptrade_mapping.decimal_value(position.get("units"))
        if units is None:
            continue
        price = snaptrade_mapping.decimal_value(position.get("price"))
        price_cents = round(price * 100) if price is not None else None
        security = await service.upsert_provider_security(
            provider=Provider.SNAPTRADE,
            close_price=price_cents,
            **fields,
        )
        average_cost = snaptrade_mapping.decimal_value(position.get("cost_basis"))
        await service.upsert_holding(
            owner_user_id=owner_user_id,
            account_id=account_id,
            security_id=security.id,
            as_of_date=utcnow().date(),
            quantity_e8=round(units * 10**8),
            price=price_cents,
            cost_basis=(
                round(average_cost * units * 100)
                if average_cost is not None and units
                else None
            ),
            currency=fields["currency"],
            source=Provider.SNAPTRADE,
            sync_account_balance=False,
        )
        count += 1
    return count


async def _apply_snaptrade_activities(
    service: FinanceService,
    activities: list[dict[str, Any]],
    *,
    account_id: int,
    connection: FinanceConnection,
) -> int:
    """Activities -> finance_trade rows, deduped on the activity id.

    SnapTrade signs ``amount`` positive for cash INTO the account (docs:
    "sell, deposits, dividends ... positive; buy, withdrawals, fees ...
    negative") — already this project's convention, so no negation here.
    """
    count = 0
    for activity in activities:
        external_id = activity.get("id")
        if not external_id:
            continue
        raw_date = activity.get("trade_date") or activity.get("settlement_date")
        if not raw_date:
            continue
        trade_date = date.fromisoformat(str(raw_date)[:10])
        amount = activity.get("amount")
        amount_cents = round(amount * 100) if amount is not None else 0
        fields = snaptrade_mapping.symbol_fields(activity.get("symbol"))
        security_id = None
        if fields is not None:
            security = await service.upsert_provider_security(
                provider=Provider.SNAPTRADE, **fields
            )
            security_id = security.id
        units = activity.get("units")
        price = activity.get("price")
        fee = activity.get("fee")
        currency = activity.get("currency") or {}
        await service.upsert_trade(
            owner_user_id=connection.owner_user_id,
            account_id=account_id,
            trade_type=snaptrade_mapping.map_trade_type(
                activity.get("type"), amount_cents
            ),
            subtype=activity.get("option_type") or activity.get("type"),
            trade_date=trade_date,
            amount=amount_cents,
            security_id=security_id,
            quantity_e8=round(units * 10**8) if units is not None else None,
            price=round(price * 100) if price is not None else None,
            fees=round(fee * 100) if fee is not None else None,
            currency=(
                currency.get("code", "usd")
                if isinstance(currency, dict)
                else (currency or "usd")
            ).lower(),
            source=Provider.SNAPTRADE,
            external_id=str(external_id),
            external_id_source=Provider.SNAPTRADE,
            name=activity.get("description"),
            connection_id=connection.id,
            raw_payload=activity,
        )
        count += 1
    return count
