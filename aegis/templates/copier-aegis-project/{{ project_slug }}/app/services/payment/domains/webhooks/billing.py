"""Checkout and charges, as Stripe reports them (invoices: ``invoices``)."""

from sqlmodel import select

from app.core.time import utcnow
from app.services.payment.adapters.providers.base import WebhookEvent
from app.services.payment.constants import (
    TransactionStatus,
    TransactionType,
)
from app.services.payment.domains.base import (
    PaymentServiceBase,
    _ts_to_naive,
)
from app.services.payment.domains.webhooks.events import (
    StripeCharge,
    StripeCheckoutSession,
)
from app.services.payment.models import (
    PaymentCustomer,
    PaymentTransaction,
)


class BillingWebhookMixin(PaymentServiceBase):
    """Everything the provider sends about a checkout or a charge actually
    happening (or failing to). Each handler is idempotent on the event id.
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
            from app.services.payment.domains.notifications.emails import (
                send_refund_processed,
            )

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
