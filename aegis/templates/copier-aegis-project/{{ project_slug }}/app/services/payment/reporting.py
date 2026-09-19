"""Revenue over time, and where the account stands right now."""

from datetime import UTC, datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import func
from sqlmodel import select

if TYPE_CHECKING:
    pass

from .constants import (
    DisputeStatus,
    SubscriptionStatus,
    TransactionStatus,
    TransactionType,
)
from .models import (
    PaymentCustomer,
    PaymentDispute,
    PaymentStatusSummary,
    PaymentSubscription,
    PaymentTransaction,
)
from .providers.base import ProviderHealth
from .service_base import PaymentServiceBase

logger = logging.getLogger(__name__)


class ReportingMixin(PaymentServiceBase):
    """Reads only: both aggregate what the other modules wrote."""

    async def get_revenue_timeseries(self, days: int = 30) -> list[dict[str, Any]]:
        """Return daily succeeded-charge revenue for the last ``days`` days.

        Emits a dense series — days with no successful charges are filled
        with zero so the chart doesn't collapse across gaps. Refunds and
        failed charges are excluded; the series mirrors the "Revenue" KPI
        on the Overview tab.

        Result shape::

            [{"date": "2026-03-23", "amount_cents": 29900}, ...]
        """
        if days < 1:
            days = 1

        today = datetime.now(UTC).date()
        start_date = today - timedelta(days=days - 1)
        start_dt = datetime.combine(start_date, datetime.min.time())

        result = await self.db.exec(
            select(
                func.date(PaymentTransaction.created_at).label("day"),
                func.coalesce(func.sum(PaymentTransaction.amount), 0).label("amount"),
            )
            .where(
                PaymentTransaction.status == TransactionStatus.SUCCEEDED,
                PaymentTransaction.type == TransactionType.CHARGE,
                PaymentTransaction.created_at >= start_dt,
            )
            .group_by(func.date(PaymentTransaction.created_at))
        )
        # ``func.date`` returns a ``date`` on PostgreSQL and a ``str`` on
        # SQLite — normalize to ISO-date strings for a stable API shape.
        totals: dict[str, int] = {}
        for row in result.all():
            day_val, amount = row
            if isinstance(day_val, str):
                key = day_val
            else:
                key = day_val.isoformat()
            totals[key] = int(amount or 0)

        series: list[dict[str, Any]] = []
        for offset in range(days):
            day = start_date + timedelta(days=offset)
            key = day.isoformat()
            series.append({"date": key, "amount_cents": totals.get(key, 0)})
        return series

    async def get_status_summary(
        self, provider_health: ProviderHealth | None = None
    ) -> PaymentStatusSummary:
        """Get payment service status.

        Returns a typed summary holding actual SQLModel instances. Serialization
        (if any) is the caller's responsibility — the API router shapes it into
        ``PaymentStatusResponse``, the health check dumps to JSON for the
        dashboard, the CLI reads attributes directly.

        Includes recent lists (10 each) so dashboard tabs render without
        extra round-trips. If these grow too large, the dashboard should
        switch to per-tab API fetches instead.

        ``provider_health`` lets callers inject a cached provider health
        result to avoid hammering the upstream API on every dashboard poll;
        when ``None`` a fresh check is performed.
        """
        provider = await self.get_or_create_provider()
        health = (
            provider_health
            if provider_health is not None
            else await self.provider.health_check()
        )

        # Transaction counts
        total_result = await self.db.exec(
            select(func.count()).select_from(PaymentTransaction)
        )
        total_transactions = total_result.one()

        # Revenue (succeeded charges only)
        revenue_result = await self.db.exec(
            select(func.coalesce(func.sum(PaymentTransaction.amount), 0)).where(
                PaymentTransaction.status == TransactionStatus.SUCCEEDED,
                PaymentTransaction.type == TransactionType.CHARGE,
            )
        )
        total_revenue = revenue_result.one()

        # Active subscriptions
        sub_result = await self.db.exec(
            select(func.count())
            .select_from(PaymentSubscription)
            .where(PaymentSubscription.status == SubscriptionStatus.ACTIVE)
        )
        active_subs = sub_result.one()

        # Open disputes count
        open_disputes_result = await self.db.exec(
            select(func.count())
            .select_from(PaymentDispute)
            .where(PaymentDispute.status.in_(DisputeStatus.OPEN))  # type: ignore[attr-defined]
        )
        open_disputes = open_disputes_result.one()

        # Recent lists for the dashboard tabs
        recent_transactions, _ = await self.get_transactions(page=1, page_size=10)
        recent_subscriptions_raw = await self.get_subscriptions()
        recent_disputes = await self.get_disputes()

        # Enrich each subscription row with its customer's display name /
        # email so the Subscriptions tab can render a "Customer" column
        # without a per-row round-trip. Batch-fetch the customers once.
        customer_ids = {
            s.customer_id for s in recent_subscriptions_raw if s.customer_id is not None
        }
        customers_by_id: dict[int, PaymentCustomer] = {}
        if customer_ids:
            cust_result = await self.db.exec(
                select(PaymentCustomer).where(
                    PaymentCustomer.id.in_(customer_ids)  # type: ignore[attr-defined]
                )
            )
            customers_by_id = {c.id: c for c in cust_result.all() if c.id is not None}

        recent_subscriptions: list[dict[str, Any]] = []
        for s in recent_subscriptions_raw[:10]:
            cust = customers_by_id.get(s.customer_id) if s.customer_id else None
            recent_subscriptions.append(
                {
                    "id": s.id,
                    "customer_id": s.customer_id,
                    "customer_name": (cust.metadata_ or {}).get("name")
                    if cust
                    else None,
                    "customer_email": cust.email if cust else None,
                    "provider_subscription_id": s.provider_subscription_id,
                    "plan_name": s.plan_name,
                    "status": s.status,
                    "current_period_start": s.current_period_start.isoformat(),
                    "current_period_end": s.current_period_end.isoformat(),
                    "cancel_at_period_end": s.cancel_at_period_end,
                    "created_at": s.created_at.isoformat(),
                    "updated_at": s.updated_at.isoformat(),
                }
            )

        return PaymentStatusSummary(
            provider_key=provider.key,
            provider_display_name=provider.display_name,
            enabled=provider.enabled,
            is_test_mode=health.is_test_mode,
            healthy=health.healthy,
            health_message=health.message,
            api_version=health.api_version,
            total_transactions=total_transactions,
            total_revenue_cents=total_revenue,
            active_subscriptions=active_subs,
            open_disputes=open_disputes,
            recent_transactions=list(recent_transactions),
            recent_subscriptions=list(recent_subscriptions[:10]),
            recent_disputes=list(recent_disputes[:10]),
        )
