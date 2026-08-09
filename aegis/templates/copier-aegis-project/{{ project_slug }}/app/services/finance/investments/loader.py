"""Writes a parsed, verified investment ledger to the database.

Reuses ``FinanceService``'s existing idempotent primitives
(``get_or_create_security``, ``upsert_trade``, ``upsert_holding``,
``upsert_security_price``) rather than writing raw SQL, so this loader is
just the mapping from ``InvestmentActivity`` to those calls plus a
synthesized dedup key (the source ledger carries no row IDs).
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.finance_service import FinanceService
from app.services.finance.investments.activity import (
    InvestmentActivity,
    replay_positions,
)
from app.services.finance.models import FinanceSecurity, FinanceTrade

_SOURCE = "csv"
# finance_security_price's source CHECK has no 'csv' option (it enumerates
# market-data feeds); a ledger-derived price point is accurately "manual".
_PRICE_SOURCE = "manual"


@dataclass
class InvestmentImportResult:
    trades_inserted: int = 0
    trades_updated: int = 0
    securities_created: int = 0
    securities_matched: int = 0


def _fallback_ticker(security_name: str) -> str:
    """A placeholder ticker for a fund the caller didn't supply a real
    symbol for, so ``get_or_create_security`` (which requires one) never
    fails on an unrecognized fund name. Not a real market symbol — a later
    ``upsert_provider_security`` call with the true ticker will not merge
    onto this row automatically, so real symbols should be supplied via
    ``security_tickers`` whenever known."""
    slug = "".join(ch for ch in security_name.upper() if ch.isalnum())
    return f"MANUAL:{slug[:24]}"


def _row_hash(activity: InvestmentActivity) -> str:
    key = "|".join(
        (
            activity.trade_date.isoformat(),
            activity.security_name,
            activity.raw_type,
            str(activity.units),
            str(activity.price),
            str(activity.amount_cents),
        )
    )
    return hashlib.sha256(key.encode()).hexdigest()


async def import_investment_activities(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    account_id: int,
    activities: list[InvestmentActivity],
    security_tickers: dict[str, str] | None = None,
) -> InvestmentImportResult:
    """Load a parsed ledger: resolve securities, upsert trades (idempotent on
    a content hash of each row), then replay ending positions into
    ``FinanceHolding`` + a fresh ``FinanceSecurityPrice`` per security."""
    tickers = security_tickers or {}
    result = InvestmentImportResult()
    service = FinanceService(db)

    security_ids: dict[str, int] = {}
    for name in dict.fromkeys(a.security_name for a in activities):
        # Explicit override always wins. Otherwise, an EARLIER import of
        # this same fund (with or without a real ticker) already created a
        # security under this exact name - reuse ITS ticker rather than
        # re-deriving a fallback, which is deterministic per name but not
        # per ticker: a fund first imported with a real symbol (the CLI's
        # ``--ticker``) would never match its own placeholder guess on a
        # later re-import (the endpoint's, which supplies none), minting a
        # second security and repointing every trade at it. Confirmed
        # live: exactly this doubled a real account's balance.
        explicit = tickers.get(name)
        if explicit:
            ticker = explicit
        else:
            by_name = (
                await db.exec(
                    select(FinanceSecurity.ticker)
                    .where(FinanceSecurity.name == name)
                    # Deterministic: an unordered ``.first()`` over more
                    # than one match (a stale duplicate from before this
                    # fallback existed, say) picks whichever row the
                    # planner happens to return - confirmed live, it chose
                    # the newer placeholder-ticker row for 4 of 5 funds.
                    # Oldest row wins, always.
                    .order_by(FinanceSecurity.id)
                )
            ).first()
            ticker = by_name or _fallback_ticker(name)
        existing = (
            await db.exec(
                select(FinanceSecurity.id).where(
                    FinanceSecurity.ticker == ticker.upper()
                )
            )
        ).first()
        security = await service.get_or_create_security(ticker=ticker, name=name)
        assert security.id is not None
        security_ids[name] = security.id
        if existing is None:
            result.securities_created += 1
        else:
            result.securities_matched += 1

    latest_price: dict[str, InvestmentActivity] = {}
    for activity in activities:
        external_id = _row_hash(activity)
        already_exists = (
            await db.exec(
                select(FinanceTrade.id).where(
                    FinanceTrade.account_id == account_id,
                    FinanceTrade.source == _SOURCE,
                    FinanceTrade.external_id == external_id,
                    FinanceTrade.deleted_at.is_(None),
                )
            )
        ).first() is not None
        await service.upsert_trade(
            owner_user_id=owner_user_id,
            account_id=account_id,
            security_id=security_ids[activity.security_name],
            trade_type=activity.trade_type,
            subtype=activity.subtype,
            trade_date=activity.trade_date,
            amount=activity.amount_cents,
            quantity_e8=round(float(activity.units) * 10**8),
            price=round(float(activity.price) * 100),
            price_scale=2,
            currency="usd",
            source=_SOURCE,
            external_id=external_id,
            external_id_source=_SOURCE,
            name=activity.raw_type,
        )
        if already_exists:
            result.trades_updated += 1
        else:
            result.trades_inserted += 1
        prior = latest_price.get(activity.security_name)
        if prior is None or activity.trade_date >= prior.trade_date:
            latest_price[activity.security_name] = activity

    as_of = max(a.trade_date for a in activities)
    for name, quantity in replay_positions(activities).items():
        price_activity = latest_price[name]
        price_cents = round(float(price_activity.price) * 100)
        await service.upsert_security_price(
            security_id=security_ids[name],
            price_date=price_activity.trade_date,
            close_price=price_cents,
            price_scale=2,
            currency="usd",
            source=_PRICE_SOURCE,
        )
        await service.upsert_holding(
            owner_user_id=owner_user_id,
            account_id=account_id,
            security_id=security_ids[name],
            as_of_date=as_of,
            quantity_e8=round(float(quantity) * 10**8),
            price=price_cents,
            price_scale=2,
            currency="usd",
            source=_SOURCE,
        )

    return result
