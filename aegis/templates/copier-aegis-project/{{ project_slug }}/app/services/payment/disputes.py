"""Chargebacks and fraud warnings."""

import logging
from typing import TYPE_CHECKING

from sqlmodel import select

from app.core.time import utcnow

if TYPE_CHECKING:
    pass

from .constants import (
    DisputeStatus,
)
from .models import (
    PaymentDispute,
    PaymentTransaction,
)
from .providers.base import WebhookEvent
from .service_base import (
    PaymentServiceBase,
    _stripe_dispute_status_to_local,
    _ts_to_naive,
)
from .stripe_events import (
    StripeDispute,
    StripeEarlyFraudWarning,
)

logger = logging.getLogger(__name__)


class DisputesMixin(PaymentServiceBase):
    """The provider raises these against a charge, so every one of them

    starts by finding the transaction that charge belongs to.
    """

    async def _find_transaction_by_charge_id(
        self, charge_id: str
    ) -> PaymentTransaction | None:
        """Locate a transaction row from a Stripe charge id.

        Charges and payment_intents share the same `ch_xxx` / `pi_xxx` identity
        space on our side — we store whatever the provider sent at
        checkout-completed time. Look up both.
        """
        if not charge_id:
            return None
        result = await self.db.exec(
            select(PaymentTransaction).where(
                PaymentTransaction.provider_transaction_id == charge_id
            )
        )
        return result.first()

    async def _handle_early_fraud_warning(self, event: WebhookEvent) -> None:
        """Handle radar.early_fraud_warning.created.

        The card network told Stripe the cardholder is claiming fraud.
        A chargeback is usually 1-30 days away. Record it so the app
        can surface it to ops and optionally auto-refund.
        """
        efw = StripeEarlyFraudWarning.model_validate(event.data)
        if not efw.charge:
            logger.warning("EFW missing charge id; skipping")
            return
        txn = await self._find_transaction_by_charge_id(efw.charge)
        if not txn:
            logger.warning("EFW received for unknown charge: %s", efw.charge)
            return

        result = await self.db.exec(
            select(PaymentDispute).where(PaymentDispute.provider_dispute_id == efw.id)
        )
        if result.first():
            return  # Idempotent: duplicate webhook deliveries are a thing.

        # ``reason`` is the human-readable column an ops dashboard
        # renders next to the row - only populate it with an actual
        # fraud taxonomy value from Stripe. ``actionable`` is a bool
        # flag (Stripe's signal of "you should refund this proactively"),
        # not a reason; stash it on metadata so ops can filter on it
        # without polluting the reason column with a flag-as-string.
        dispute = PaymentDispute(
            transaction_id=txn.id,  # type: ignore[arg-type]
            provider_dispute_id=efw.id,
            status=DisputeStatus.WARNING_ISSUED,
            reason=efw.fraud_type or None,
            amount=txn.amount,
            currency=txn.currency,
            event_type=event.event_type,
            metadata_={
                "raw": event.data,
                "actionable": bool(efw.actionable),
            },
        )
        self.db.add(dispute)
        await self.db.flush()

    async def _handle_dispute_event(self, event: WebhookEvent) -> None:
        """Handle charge.dispute.created / updated / closed.

        Upserts a PaymentDispute row keyed on the provider's dispute id.
        Maps Stripe's dispute.status to our DisputeStatus lifecycle.
        """
        dispute_event = StripeDispute.model_validate(event.data)
        status = _stripe_dispute_status_to_local(dispute_event.status or "")
        evidence_due_by = _ts_to_naive(
            dispute_event.evidence_details.due_by
            if dispute_event.evidence_details
            else None
        )

        result = await self.db.exec(
            select(PaymentDispute).where(
                PaymentDispute.provider_dispute_id == dispute_event.id
            )
        )
        existing = result.first()

        if existing:
            existing.status = status
            existing.reason = dispute_event.reason or existing.reason
            existing.evidence_due_by = evidence_due_by or existing.evidence_due_by
            existing.event_type = event.event_type
            existing.updated_at = utcnow()
            self.db.add(existing)
            await self.db.flush()
            return

        # No existing row: create one linked to the charge.
        if not dispute_event.charge:
            logger.warning("Dispute %s missing charge id; skipping", dispute_event.id)
            return
        txn = await self._find_transaction_by_charge_id(dispute_event.charge)
        if not txn:
            logger.warning(
                "Dispute event for unknown charge: %s (dispute=%s)",
                dispute_event.charge,
                dispute_event.id,
            )
            return

        dispute = PaymentDispute(
            transaction_id=txn.id,  # type: ignore[arg-type]
            provider_dispute_id=dispute_event.id,
            status=status,
            reason=dispute_event.reason,
            amount=dispute_event.amount or txn.amount,
            currency=dispute_event.currency or txn.currency,
            evidence_due_by=evidence_due_by,
            event_type=event.event_type,
            metadata_={"raw": event.data},
        )
        self.db.add(dispute)
        await self.db.flush()

    async def get_disputes(
        self, status: str | None = None, user_id: int | None = None
    ) -> list[PaymentDispute]:
        """List disputes, optionally filtered by status (or 'open') and user.

        When ``user_id`` is supplied, disputes are scoped to transactions
        belonging to that user's ``PaymentCustomer`` rows. PaymentDispute
        links to PaymentTransaction, which links to PaymentCustomer.
        """
        query = select(PaymentDispute).order_by(PaymentDispute.created_at.desc())
        if status == "open":
            query = query.where(PaymentDispute.status.in_(DisputeStatus.OPEN))  # type: ignore[attr-defined]
        elif status:
            query = query.where(PaymentDispute.status == status)
        if user_id is not None:
            customer_ids = await self._customer_ids_for_user(user_id)
            txn_ids = await self._transaction_ids_for_customers(customer_ids)
            query = query.where(PaymentDispute.transaction_id.in_(txn_ids))  # type: ignore[attr-defined]
        result = await self.db.exec(query)
        return list(result.all())

    async def get_dispute_by_id(
        self, dispute_id: int, user_id: int | None = None
    ) -> PaymentDispute | None:
        """Get a single dispute by primary key.

        When ``user_id`` is supplied, returns None if the dispute does not
        belong to one of that user's transactions.
        """
        query = select(PaymentDispute).where(PaymentDispute.id == dispute_id)
        if user_id is not None:
            customer_ids = await self._customer_ids_for_user(user_id)
            txn_ids = await self._transaction_ids_for_customers(customer_ids)
            query = query.where(PaymentDispute.transaction_id.in_(txn_ids))  # type: ignore[attr-defined]
        result = await self.db.exec(query)
        return result.first()

    async def _transaction_ids_for_customers(
        self, customer_ids: list[int]
    ) -> list[int]:
        """Return PaymentTransaction ids for the given customer ids.

        Returns [-1] if no matches so WHERE-IN queries match nothing.
        """
        result = await self.db.exec(
            select(PaymentTransaction.id).where(
                PaymentTransaction.customer_id.in_(customer_ids)  # type: ignore[attr-defined]
            )
        )
        ids = [tid for tid in result.all() if tid is not None]
        return ids or [-1]
