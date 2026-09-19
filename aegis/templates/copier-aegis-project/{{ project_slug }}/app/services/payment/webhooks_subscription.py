"""Subscription lifecycle, as Stripe reports it."""

import logging
from typing import TYPE_CHECKING

from sqlmodel import select

from app.core.time import utcnow

if TYPE_CHECKING:
    pass

from .constants import (
    SubscriptionStatus,
)
from .models import (
    PaymentCustomer,
    PaymentSubscription,
)
from .providers.base import WebhookEvent
from .service_base import (
    PaymentServiceBase,
    _ts_to_naive,
)
from .stripe_events import (
    StripeSubscription,
)

logger = logging.getLogger(__name__)


class SubscriptionWebhookMixin(PaymentServiceBase):
    """Created, updated, ended, and the trial-ending warning that

    precedes a first charge.
    """

    async def _handle_subscription_event(self, event: WebhookEvent) -> None:
        """Handle subscription created/updated."""
        sub = StripeSubscription.model_validate(event.data)

        result = await self.db.exec(
            select(PaymentSubscription).where(
                PaymentSubscription.provider_subscription_id == sub.id
            )
        )
        existing = result.first()

        # Subscription items carry a full ``price`` dict (nickname,
        # unit_amount, etc.) - unlike invoice lines, which carry only
        # id references on ``pricing.price_details``.
        plan_name = ""
        unit_amount: int | None = None
        currency: str | None = None
        item = sub.first_item
        price = item.price if item else None
        if price:
            plan_name = price.nickname or price.id or ""
            unit_amount = price.unit_amount
            currency = price.currency

        # Stripe moved ``current_period_start``/``_end`` from the top-
        # level subscription onto each item in the 2025-* API versions.
        # Read the per-item fields first; fall back to top-level so
        # older webhook payloads still parse.
        # ``None`` when both per-item and top-level period are absent.
        # That happens on some events (``trial_will_end`` mid-trial in
        # particular), and we'd rather leave existing values alone (or
        # skip the insert) than write a 1970-01-01 epoch placeholder
        # that propagates into emails and dashboards.
        period_start = _ts_to_naive(
            item.current_period_start if item else None
        ) or _ts_to_naive(sub.current_period_start)
        period_end = _ts_to_naive(
            item.current_period_end if item else None
        ) or _ts_to_naive(sub.current_period_end)

        # Track whether plan_name actually changed on an update -
        # drives whether we email. Pure status / period rolls don't
        # need a "your plan changed" notification.
        plan_name_changed = False
        is_new = existing is None

        if existing:
            plan_name_changed = bool(plan_name and plan_name != existing.plan_name)
            existing.status = sub.status or existing.status
            existing.plan_name = plan_name or existing.plan_name
            # Only overwrite period when the event actually carried one.
            # Partial events shouldn't blow away good data with epoch
            # placeholders.
            if period_start is not None:
                existing.current_period_start = period_start
            if period_end is not None:
                existing.current_period_end = period_end
            existing.cancel_at_period_end = sub.cancel_at_period_end
            existing.updated_at = utcnow()
            self.db.add(existing)
        else:
            customer_id: int | None = None
            if sub.customer:
                cust_result = await self.db.exec(
                    select(PaymentCustomer).where(
                        PaymentCustomer.provider_customer_id == sub.customer
                    )
                )
                customer = cust_result.first()
                if customer:
                    customer_id = customer.id

            # Symmetry with the invoice handlers: make the dropped
            # subscription observable instead of silent.
            if not customer_id:
                logger.warning(
                    "subscription_event: subscription %s for unknown "
                    "customer %s; dropping row insert",
                    sub.id,
                    sub.customer,
                )

            # Never insert a sub without a billing period -
            # ``current_period_*`` are NOT NULL on the schema, and a
            # 1970 placeholder is worse than skipping. Webhooks that
            # lack a period for new subs are malformed.
            elif period_start is None or period_end is None:
                logger.warning(
                    "subscription_event: subscription %s missing period "
                    "(start=%s end=%s); dropping row insert",
                    sub.id,
                    period_start,
                    period_end,
                )
            else:
                # Normalize once so the pre-check and the insert below
                # agree on the row's effective status. Webhooks rarely
                # ship an empty ``status``, but Stripe's schema allows
                # it - and without this, a falsy status would skip the
                # pre-check while the insert silently defaulted to
                # ACTIVE, tripping the partial unique index with no
                # try/except to catch it.
                effective_status = sub.status or SubscriptionStatus.ACTIVE

                # Pre-check against the partial unique index on
                # ``payment_subscription (customer_id) WHERE status IN
                # ('active', 'trialing')``. If another active sub
                # already exists for this customer (operator-side
                # mistake, direct API create, replay race), skip the
                # insert before flushing - SQLAlchemy treats a failed
                # ``session.flush()`` as a session-poisoning event
                # even inside ``begin_nested``, so we can't rely on a
                # SAVEPOINT to scope the rollback cleanly. The DB
                # index stays as the race-condition backstop: if a
                # concurrent webhook commits the duplicate between our
                # pre-check and our flush, the index will fire, the
                # webhook route catches it and returns 400. Stripe
                # does not retry 4xx, but that is acceptable here -
                # the competing insert already committed the row we
                # would have created.
                if effective_status in ("active", "trialing"):
                    existing_active = (
                        await self.db.exec(
                            select(PaymentSubscription).where(
                                PaymentSubscription.customer_id == customer_id,
                                PaymentSubscription.status.in_(  # type: ignore[attr-defined]
                                    ["active", "trialing"]
                                ),
                            )
                        )
                    ).first()
                    if existing_active is not None:
                        logger.warning(
                            "subscription_event: refused duplicate active "
                            "sub for customer=%s provider_sub=%s "
                            "(existing active row id=%s wins).",
                            sub.customer,
                            sub.id,
                            existing_active.id,
                        )
                        return

                new_sub = PaymentSubscription(
                    customer_id=customer_id,
                    provider_subscription_id=sub.id,
                    plan_name=plan_name,
                    status=effective_status,
                    current_period_start=period_start,
                    current_period_end=period_end,
                    cancel_at_period_end=sub.cancel_at_period_end,
                )
                self.db.add(new_sub)

        await self.db.flush()

        # Notification side-effect. We email on:
        #   - SUBSCRIPTION_CREATED: always, when the row was new
        #   - SUBSCRIPTION_UPDATED: only when plan_name actually changed
        # Pure status flips / period rolls don't email - too noisy.
        from .constants import WebhookEventType

        target_sub_result = await self.db.exec(
            select(PaymentSubscription).where(
                PaymentSubscription.provider_subscription_id == sub.id
            )
        )
        target_sub = target_sub_result.first()

        if event.event_type == WebhookEventType.SUBSCRIPTION_CREATED and is_new:
            from app.services.payment.email_helpers import send_subscription_started

            to = await self._email_for_stripe_customer(sub.customer)
            email_result = await send_subscription_started(
                to=to or "",
                plan_name=plan_name or "your subscription",
                period_start=period_start,
                period_end=period_end,
                amount_cents=unit_amount,
                currency=currency,
            )
            if target_sub is not None:
                await self._tag_with_email_result(target_sub, email_result)
        elif (
            event.event_type == WebhookEventType.SUBSCRIPTION_UPDATED
            and plan_name_changed
        ):
            from app.services.payment.email_helpers import send_subscription_updated

            to = await self._email_for_stripe_customer(sub.customer)
            email_result = await send_subscription_updated(
                to=to or "",
                plan_name=plan_name or "your subscription",
                period_start=period_start,
                period_end=period_end,
                amount_cents=unit_amount,
                currency=currency,
            )
            if target_sub is not None:
                await self._tag_with_email_result(target_sub, email_result)

    async def _handle_subscription_deleted(self, event: WebhookEvent) -> None:
        """Handle subscription deleted - mark as canceled."""
        sub_event = StripeSubscription.model_validate(event.data)

        result = await self.db.exec(
            select(PaymentSubscription).where(
                PaymentSubscription.provider_subscription_id == sub_event.id
            )
        )
        sub = result.first()
        if sub is None:
            return

        sub.status = SubscriptionStatus.CANCELED
        sub.updated_at = utcnow()
        self.db.add(sub)
        await self.db.flush()

        from app.services.payment.email_helpers import send_subscription_canceled

        to = await self._email_for_stripe_customer(sub_event.customer)
        email_result = await send_subscription_canceled(
            to=to or "",
            plan_name=sub.plan_name or "your subscription",
            period_end=sub.current_period_end,
        )
        await self._tag_with_email_result(sub, email_result)

    async def _handle_subscription_trial_will_end(self, event: WebhookEvent) -> None:
        """Handle ``customer.subscription.trial_will_end``.

        Stripe fires this once per trial, ~3 days before the first
        paid charge. We send a heads-up email with the trial-end
        date and first-charge amount so the customer can cancel /
        swap cards in time. No DB state change - the trial transition
        itself (``trialing`` -> ``active``) lands later via the
        ``invoice.paid`` event.
        """
        sub_event = StripeSubscription.model_validate(event.data)

        result = await self.db.exec(
            select(PaymentSubscription).where(
                PaymentSubscription.provider_subscription_id == sub_event.id
            )
        )
        sub = result.first()
        if sub is None:
            logger.warning(
                "trial_will_end: no local row for %s; skipping email",
                sub_event.id,
            )
            return

        # Pull the upcoming charge amount + currency from the first
        # subscription line item. ``trial_end`` is the unix timestamp
        # Stripe will actually charge on.
        item = sub_event.first_item
        price = item.price if item else None
        unit_amount = price.unit_amount if price else None
        currency = price.currency if price else None
        trial_end = _ts_to_naive(sub_event.trial_end) or sub.current_period_end

        from app.services.payment.email_helpers import send_trial_ending_soon

        to = await self._email_for_stripe_customer(sub_event.customer)
        email_result = await send_trial_ending_soon(
            to=to or "",
            plan_name=sub.plan_name or "your subscription",
            trial_end=trial_end,
            amount_cents=unit_amount,
            currency=currency,
        )
        await self._tag_with_email_result(sub, email_result)
