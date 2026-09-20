"""Refunding a transaction."""

import logging
from typing import TYPE_CHECKING

from app.core.time import utcnow

if TYPE_CHECKING:
    pass

from .constants import (
    TransactionStatus,
    TransactionType,
)
from .models import (
    PaymentCustomer,
    PaymentTransaction,
)
from .service_base import PaymentServiceBase

logger = logging.getLogger(__name__)


class RefundsMixin(PaymentServiceBase):
    """One verb, but it moves money, so it checks the local row, asks the

    provider, and records what the receipt email did.
    """

    async def refund_transaction(
        self,
        transaction_id: int,
        amount: int | None = None,
        reason: str | None = None,
        user_id: int | None = None,
    ) -> PaymentTransaction | None:
        """Refund a transaction (full or partial).

        When ``user_id`` is supplied, returns None if the transaction isn't
        owned by that user. Prevents cross-user refunds.
        """
        txn = await self.get_transaction_by_id(transaction_id, user_id=user_id)
        if not txn:
            return None

        # Guard: fully refunded transactions can't be refunded again. Without
        # this check, the subsequent INSERT can collide on
        # provider_transaction_id (seed data) or get rejected by Stripe
        # with a less actionable error for real charges.
        if txn.status == TransactionStatus.REFUNDED:
            raise RuntimeError(
                "Transaction is already fully refunded and cannot be refunded again."
            )

        # Dev-only short-circuit: seed data uses synthetic `pi_fake_*` /
        # `ch_fake_*` / `re_fake_*` identifiers that don't exist in Stripe.
        # Skip the provider round-trip and build a synthetic RefundResult
        # so the dashboard Refund button works against seeded rows without
        # hitting the Stripe API (and failing with "No such payment_intent").
        if txn.provider_transaction_id.startswith(("pi_fake_", "ch_fake_", "re_fake_")):
            from uuid import uuid4

            from .providers.base import RefundResult

            refund_amount = amount if amount is not None else txn.amount
            fake_suffix = txn.provider_transaction_id.split("_", 2)[-1]
            # Include a short uuid so two partial refunds on the same row
            # don't collide on provider_transaction_id.
            unique = uuid4().hex[:8]
            refund_result = RefundResult(
                provider_refund_id=f"re_fake_{fake_suffix}_refund_{unique}",
                status=TransactionStatus.SUCCEEDED,
                amount=refund_amount,
                currency=txn.currency,
            )
        else:
            # Stripe's ``Refund.create`` requires a PaymentIntent id
            # (``pi_xxx``), not an Invoice id (``in_xxx``). For
            # subscription-invoice charges, ``provider_transaction_id``
            # is the invoice id - we stash the underlying PI at
            # invoice-payment time in ``metadata.payment_intent``
            # specifically to bridge this gap (same bridge the inbound
            # ``charge.refunded`` handler uses). Prefer the stashed PI;
            # fall back to the column for one-shot ``pi_xxx`` charges
            # that bypass the invoice layer.
            stashed_pi = (txn.metadata_ or {}).get("payment_intent")
            refund_target = (
                stashed_pi
                if isinstance(stashed_pi, str) and stashed_pi
                else txn.provider_transaction_id
            )
            refund_result = await self.provider.refund(
                provider_transaction_id=refund_target,
                amount=amount,
                reason=reason,
            )

        # Record the refund as a new transaction
        provider = await self.get_or_create_provider()
        refund_txn = PaymentTransaction(
            provider_id=provider.id,  # type: ignore[arg-type]
            customer_id=txn.customer_id,
            provider_transaction_id=refund_result.provider_refund_id,
            type=TransactionType.REFUND,
            status=refund_result.status,
            amount=refund_result.amount,
            currency=refund_result.currency,
            description=reason,
            metadata_={"original_transaction_id": txn.id},
        )
        self.db.add(refund_txn)

        # Update original transaction status
        if amount and amount < txn.amount:
            txn.status = TransactionStatus.PARTIALLY_REFUNDED
        else:
            txn.status = TransactionStatus.REFUNDED
        txn.updated_at = utcnow()
        self.db.add(txn)

        await self.db.flush()

        # Send the refund email here rather than relying on the inbound
        # ``charge.refunded`` webhook. We just flipped ``txn.status``
        # synchronously; by the time the webhook fires, its
        # ``status_changed`` check sees no transition and silently
        # skips the send. Without this branch, dashboard-initiated
        # refunds never email the customer.
        from app.services.payment.email_helpers import send_refund_processed

        customer_email: str | None = None
        if txn.customer_id is not None:
            cust = await self.db.get(PaymentCustomer, txn.customer_id)
            if cust is not None:
                customer_email = cust.email
                if not customer_email and cust.user_id:
                    from app.models.user import User as _User

                    user = await self.db.get(_User, cust.user_id)
                    if user is not None:
                        customer_email = user.email
        email_result = await send_refund_processed(
            to=customer_email or "",
            amount_cents=refund_result.amount,
            currency=refund_result.currency,
            refunded_at=utcnow(),
            original_charge_at=txn.created_at,
            invoice_number=(txn.metadata_ or {}).get("invoice_number")
            or txn.provider_transaction_id
            or "",
        )
        await self._tag_with_email_result(txn, email_result)
        return refund_txn
