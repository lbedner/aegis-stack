"""Listing, re-planning and cancelling a subscription."""

import logging
from typing import TYPE_CHECKING

from sqlmodel import select

from app.core.time import utcnow

if TYPE_CHECKING:
    pass

from .models import (
    PaymentSubscription,
)
from .service_base import PaymentServiceBase

logger = logging.getLogger(__name__)


class SubscriptionsMixin(PaymentServiceBase):
    """The user-facing half; what the provider tells us afterwards is

    handled by the subscription webhooks.
    """

    async def get_subscriptions(
        self, status: str | None = None, user_id: int | None = None
    ) -> list[PaymentSubscription]:
        """Get subscriptions, optionally filtered by status and/or user_id."""
        query = select(PaymentSubscription).order_by(
            PaymentSubscription.created_at.desc()
        )
        if status:
            query = query.where(PaymentSubscription.status == status)
        if user_id is not None:
            customer_ids = await self._customer_ids_for_user(user_id)
            query = query.where(PaymentSubscription.customer_id.in_(customer_ids))  # type: ignore[attr-defined]
        result = await self.db.exec(query)
        return list(result.all())

    async def change_subscription_plan(
        self,
        subscription_id: int,
        new_price_id: str,
        *,
        user_id: int | None = None,
        proration_behavior: str = "create_prorations",
    ) -> PaymentSubscription | None:
        """Change the price on an existing subscription in place.

        The provider (Stripe) handles the actual swap + proration. We
        don't touch the local row here - the inbound
        ``customer.subscription.updated`` webhook arrives moments later
        and ``_handle_subscription_event`` writes the new plan_name /
        period to the same row. That keeps the webhook handler as the
        single writer for subscription state and avoids us racing it.

        When ``user_id`` is supplied, returns None if the subscription
        isn't owned by that user (prevents cross-user plan changes).
        """
        # Validate at the service boundary so non-API callers (CLI,
        # admin tooling) get the same protection as the route's
        # Pydantic schema. Routes raise 400 from the resulting
        # ``ValueError``; CLI callers see a clear failure instead of
        # a wrapped Stripe error.
        _valid_proration = {"create_prorations", "always_invoice", "none"}
        if proration_behavior not in _valid_proration:
            raise ValueError(
                f"Invalid proration_behavior {proration_behavior!r}. "
                f"Must be one of: {', '.join(sorted(_valid_proration))}"
            )

        query = select(PaymentSubscription).where(
            PaymentSubscription.id == subscription_id
        )
        if user_id is not None:
            customer_ids = await self._customer_ids_for_user(user_id)
            query = query.where(
                PaymentSubscription.customer_id.in_(customer_ids)  # type: ignore[attr-defined]
            )
        result = await self.db.exec(query)
        sub = result.first()
        if not sub:
            return None

        await self.provider.change_subscription_plan(
            sub.provider_subscription_id,
            new_price_id,
            proration_behavior=proration_behavior,
        )
        return sub

    async def cancel_subscription(
        self, subscription_id: int, user_id: int | None = None
    ) -> PaymentSubscription | None:
        """Cancel a subscription (at period end).

        When ``user_id`` is supplied, returns None if the subscription isn't
        owned by that user. Prevents cross-user cancellation.
        """
        query = select(PaymentSubscription).where(
            PaymentSubscription.id == subscription_id
        )
        if user_id is not None:
            customer_ids = await self._customer_ids_for_user(user_id)
            query = query.where(
                PaymentSubscription.customer_id.in_(customer_ids)  # type: ignore[attr-defined]
            )
        result = await self.db.exec(query)
        sub = result.first()
        if not sub:
            return None

        sub.cancel_at_period_end = True
        sub.updated_at = utcnow()
        self.db.add(sub)
        await self.db.flush()
        return sub
