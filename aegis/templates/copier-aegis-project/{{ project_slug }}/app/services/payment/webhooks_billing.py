"""Checkout, charges and invoices, as Stripe reports them."""

import logging
from typing import TYPE_CHECKING, Any

from sqlmodel import select

from app.core.time import utcnow

if TYPE_CHECKING:
    pass

from .constants import (
    TransactionStatus,
    TransactionType,
)
from .models import (
    PaymentCustomer,
    PaymentSubscription,
    PaymentTransaction,
)
from .providers.base import WebhookEvent
from .service_base import (
    PaymentServiceBase,
    _ts_to_naive,
)
from .stripe_events import (
    StripeCharge,
    StripeCheckoutSession,
    StripeInvoice,
)

logger = logging.getLogger(__name__)


class BillingWebhookMixin(PaymentServiceBase):
    """Everything the provider sends about a payment actually happening

    (or failing to). Each handler is idempotent on the event id.
    """

    async def _handle_checkout_completed(self, event: WebhookEvent) -> None:
        """Handle checkout.session.completed - record the transaction."""
        session = StripeCheckoutSession.model_validate(event.data)
        provider = await self.get_or_create_provider()

        customer_id: int | None = None
        if session.customer:
            result = await self.db.exec(
                select(PaymentCustomer).where(
                    PaymentCustomer.provider_customer_id == session.customer
                )
            )
            customer = result.first()
            if customer:
                customer_id = customer.id

        # Subscription checkouts have ``payment_intent: null`` (the
        # invoice creates the PI separately) - fall back to the session
        # id so the row always has a non-null provider identifier.
        provider_txn_id = session.payment_intent or session.id

        # Idempotency: Stripe may re-deliver the same event (retries,
        # replay-from-CLI), and the local stripe-listen forwarder
        # occasionally doubles up during reconnects.
        existing = await self.db.exec(
            select(PaymentTransaction).where(
                PaymentTransaction.provider_transaction_id == provider_txn_id
            )
        )
        if existing.first():
            return

        txn_type = (
            TransactionType.SUBSCRIPTION
            if session.mode == "subscription"
            else TransactionType.CHARGE
        )
        txn = PaymentTransaction(
            provider_id=provider.id,  # type: ignore[arg-type]
            customer_id=customer_id,
            provider_transaction_id=provider_txn_id,
            type=txn_type,
            status=TransactionStatus.SUCCEEDED,
            amount=session.amount_total or 0,
            currency=session.currency or "usd",
            metadata_={"checkout_session_id": session.id},
        )
        self.db.add(txn)
        await self.db.flush()

    async def _handle_charge_refunded(self, event: WebhookEvent) -> None:
        """Handle charge.refunded - update transaction status.

        Lookup is a two-step dance because Stripe's ``charge.refunded``
        event payload contains only ``payment_intent`` (no ``invoice``
        field), but rows from ``_handle_invoice_payment`` are keyed off
        the invoice id, not the PI.

        1. Try ``provider_transaction_id == payment_intent`` -
           catches one-shot ``checkout.session.completed`` charges.
        2. Fall back to ``metadata_->>'payment_intent' == payment_intent`` -
           catches subscription-invoice charges, where we stashed the
           PI at invoice-payment time as a bridge.
        """
        charge = StripeCharge.model_validate(event.data)
        if not charge.payment_intent:
            return

        result = await self.db.exec(
            select(PaymentTransaction).where(
                PaymentTransaction.provider_transaction_id == charge.payment_intent
            )
        )
        txn = result.first()
        if not txn:
            # Subscription-invoice path: row is keyed by invoice id with
            # the PI stashed in metadata at invoice-payment time. JSON
            # extract works across both Postgres (``->>``) and SQLite
            # (``json_extract``); SQLAlchemy's index operator translates
            # automatically for the JSON column type.
            result = await self.db.exec(
                select(PaymentTransaction).where(
                    PaymentTransaction.metadata_["payment_intent"].as_string()  # type: ignore[index,attr-defined]
                    == charge.payment_intent
                )
            )
            txn = result.first()
        if not txn:
            return

        # Track whether status actually transitioned this call - Stripe
        # re-sends charge.refunded events for partial refunds in some
        # flows, and we don't want to email twice for the same state.
        refunded = charge.amount_refunded or 0
        total = charge.amount or txn.amount
        new_status = (
            TransactionStatus.REFUNDED
            if refunded >= total
            else TransactionStatus.PARTIALLY_REFUNDED
        )
        status_changed = txn.status != new_status
        txn.status = new_status
        txn.updated_at = utcnow()
        self.db.add(txn)
        await self.db.flush()

        if status_changed:
            from app.services.payment.email_helpers import send_refund_processed

            to = await self._email_for_stripe_customer(charge.customer)
            refunded_at = _ts_to_naive(charge.created) or utcnow()
            email_result = await send_refund_processed(
                to=to or "",
                amount_cents=refunded,
                currency=txn.currency,
                refunded_at=refunded_at,
                original_charge_at=txn.created_at,
                invoice_number=(txn.metadata_ or {}).get("invoice_number")
                or txn.provider_transaction_id
                or "",
            )
            await self._tag_with_email_result(txn, email_result)

    async def _handle_invoice_payment(self, event: WebhookEvent) -> None:
        """Handle ``invoice.paid`` and ``invoice.payment_succeeded``.

        Subscription charges (initial + renewals) ride on Stripe invoices,
        not the ``checkout.session.completed`` event. We only see the real
        money here. Stripe sends both event types for the same payment for
        backward compat - the idempotency check on the invoice id makes
        the duplicate harmless.
        """
        invoice = StripeInvoice.model_validate(event.data)

        # Idempotency across redelivery and the duplicate ``invoice.paid``/
        # ``invoice.payment_succeeded`` event pair.
        existing = await self.db.exec(
            select(PaymentTransaction).where(
                PaymentTransaction.provider_transaction_id == invoice.id
            )
        )
        if existing.first():
            return

        provider = await self.get_or_create_provider()

        customer_id: int | None = None
        if invoice.customer:
            cust = await self.db.exec(
                select(PaymentCustomer).where(
                    PaymentCustomer.provider_customer_id == invoice.customer
                )
            )
            customer = cust.first()
            if customer:
                customer_id = customer.id
            else:
                logger.warning(
                    "invoice payment for unknown customer %s; recording with "
                    "customer_id=NULL",
                    invoice.customer,
                )

        amount = invoice.amount_paid or invoice.total or 0
        currency = invoice.currency or "usd"
        number = invoice.number or invoice.id

        metadata: dict[str, Any] = {}
        if invoice.subscription:
            metadata["subscription_id"] = invoice.subscription
        if invoice.hosted_invoice_url:
            metadata["hosted_invoice_url"] = invoice.hosted_invoice_url
        # Stash the invoice's payment_intent so ``_handle_charge_refunded``
        # AND the outbound ``refund_transaction`` flow can find this row
        # by PI later. Two places need it:
        #
        #   1. ``charge.refunded`` event carries ``payment_intent`` but
        #      NOT ``invoice``, so the inbound handler looks up the
        #      row via metadata.payment_intent.
        #   2. ``stripe.Refund.create`` needs a PI; we pass the stashed
        #      value as ``provider_transaction_id`` to bridge the
        #      ``in_xxx`` -> ``pi_xxx`` gap.
        #
        # Modern Stripe API versions (2025-* and later) removed
        # ``invoice.payment_intent`` and ``invoice.charge`` as top-level
        # fields, so we can't read it directly from the webhook payload.
        # Fetch the related charge via ``stripe.Charge.list(invoice=...)``;
        # one extra API call per invoice is cheap and runs only on the
        # ingest path.
        pi_from_invoice = invoice.payment_intent
        if not pi_from_invoice:
            try:
                import stripe as _stripe

                charges = await _stripe.Charge.list_async(invoice=invoice.id, limit=1)
                # Stripe SDK returns ``ListObject`` (StripeObject), not
                # a dict - attribute access only.
                data = list(getattr(charges, "data", []) or [])
                if data:
                    first = data[0]
                    pi_from_invoice = (
                        getattr(first, "payment_intent", None)
                        if not isinstance(first, dict)
                        else first.get("payment_intent")
                    )
            except Exception:
                logger.warning(
                    "invoice_payment: failed to resolve payment_intent for "
                    "%s; refund bridge will be unavailable for this row",
                    invoice.id,
                    exc_info=True,
                )
        if pi_from_invoice:
            metadata["payment_intent"] = pi_from_invoice

        txn = PaymentTransaction(
            provider_id=provider.id,  # type: ignore[arg-type]
            customer_id=customer_id,
            provider_transaction_id=invoice.id,
            type=TransactionType.CHARGE,
            status=TransactionStatus.SUCCEEDED,
            amount=amount,
            currency=currency,
            description=f"Invoice {number}",
            metadata_=metadata,
        )
        self.db.add(txn)
        await self.db.flush()

        # Receipt. If Stripe's automated receipts are disabled
        # (Settings -> Emails -> Successful payments OFF), this email
        # is the only payment confirmation the customer gets.
        from app.services.payment.email_helpers import send_invoice_paid

        to = await self._email_for_stripe_customer(invoice.customer)

        plan_name = await self._resolve_invoice_plan_name(invoice)

        # Period: line.period first (current API), fall back to top-level.
        line = invoice.first_line
        line_period = line.period if line else None
        period_start = _ts_to_naive(
            line_period.start if line_period else None
        ) or _ts_to_naive(invoice.period_start)
        period_end = _ts_to_naive(
            line_period.end if line_period else None
        ) or _ts_to_naive(invoice.period_end)

        paid_at_unix = (
            invoice.status_transitions.paid_at if invoice.status_transitions else None
        )
        charged_at = (
            _ts_to_naive(invoice.created) or _ts_to_naive(paid_at_unix) or utcnow()
        )

        email_result = await send_invoice_paid(
            to=to or "",
            plan_name=plan_name,
            invoice_number=number,
            amount_cents=amount,
            currency=currency,
            charged_at=charged_at,
            period_start=period_start,
            period_end=period_end,
            hosted_invoice_url=invoice.hosted_invoice_url,
        )
        await self._tag_with_email_result(txn, email_result)

    async def _handle_invoice_payment_failed(self, event: WebhookEvent) -> None:
        """Handle ``invoice.payment_failed`` - record a FAILED CHARGE row.

        Idempotent on the invoice id. If you want each dunning attempt
        as its own row instead, key off ``invoice_id + ":" + attempt_count``.
        """
        invoice = StripeInvoice.model_validate(event.data)

        existing = await self.db.exec(
            select(PaymentTransaction).where(
                PaymentTransaction.provider_transaction_id == invoice.id
            )
        )
        if existing.first():
            return

        provider = await self.get_or_create_provider()

        customer_id: int | None = None
        if invoice.customer:
            cust = await self.db.exec(
                select(PaymentCustomer).where(
                    PaymentCustomer.provider_customer_id == invoice.customer
                )
            )
            customer = cust.first()
            if customer:
                customer_id = customer.id

        amount = invoice.amount_due or invoice.total or 0
        currency = invoice.currency or "usd"
        number = invoice.number or invoice.id

        txn = PaymentTransaction(
            provider_id=provider.id,  # type: ignore[arg-type]
            customer_id=customer_id,
            provider_transaction_id=invoice.id,
            type=TransactionType.CHARGE,
            status=TransactionStatus.FAILED,
            amount=amount,
            currency=currency,
            description=f"Invoice {number} (payment failed)",
            metadata_=(
                {"subscription_id": invoice.subscription}
                if invoice.subscription
                else {}
            ),
        )
        self.db.add(txn)
        await self.db.flush()

        # Dunning email - Stripe retries the card on its own, but the
        # customer needs to know NOW so they can update payment before
        # service drops.
        from app.services.payment.email_helpers import send_payment_failed

        to = await self._email_for_stripe_customer(invoice.customer)
        plan_name = await self._resolve_invoice_plan_name(invoice)

        attempted_at = _ts_to_naive(invoice.created) or utcnow()
        email_result = await send_payment_failed(
            to=to or "",
            plan_name=plan_name,
            amount_cents=amount,
            currency=currency,
            attempted_at=attempted_at,
            update_payment_url=invoice.hosted_invoice_url,
        )
        await self._tag_with_email_result(txn, email_result)

    async def _resolve_invoice_plan_name(self, invoice: object) -> str:
        """Resolve the human-readable plan name for an invoice email.

        Order of preference:
        1. Local ``PaymentSubscription.plan_name`` (the friendly nickname
           captured by ``_handle_subscription_event``). This is the
           common case for renewals + dunning where the sub row already
           exists - using the invoice line's bare ``product`` id here
           would regress receipts to read "Charged for prod_ABC123".
        2. Invoice line ``pricing.price_details.product`` id. The first-
           checkout race - Stripe can deliver ``invoice.paid`` before
           ``customer.subscription.created`` - means the sub row may
           not exist yet. Subclasses can override to call
           ``stripe.Product.retrieve(...)`` for a friendlier name.
        3. Bare price id, then a placeholder string, as last resorts.
        """
        sub_id = getattr(invoice, "subscription", None)
        if sub_id:
            result = await self.db.exec(
                select(PaymentSubscription).where(
                    PaymentSubscription.provider_subscription_id == sub_id
                )
            )
            sub = result.first()
            if sub and sub.plan_name:
                return sub.plan_name

        line = getattr(invoice, "first_line", None)
        pricing = getattr(line, "pricing", None) if line else None
        details = getattr(pricing, "price_details", None) if pricing else None
        if details:
            product_id = getattr(details, "product", None)
            if product_id:
                return product_id
            price_id = getattr(details, "price", None)
            if price_id:
                return price_id
        return "your subscription"
