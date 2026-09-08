"""
Fake data for the payment service — dev/UX testing only.

Populates the payment_* tables with a rich set of rows so every state
visible in the dashboard tabs can be inspected without running live
Stripe flows. Not for production — pure fixtures, no provider calls.

IDs are Stripe-shaped: opaque alphanumeric strings with the correct
prefix (``cus_`` / ``pi_`` / ``sub_`` / ``dp_`` / ``issfr_`` / ``re_``).
They're generated deterministically from a stable seed so re-seeding
and regeneration testing stay reproducible, but the strings themselves
carry no human-readable hints — mirroring what real Stripe data looks
like in the dashboard.

Run via the generated project's CLI:
``<your-app> payment seed`` (or ``--reset`` to wipe first).
"""

from __future__ import annotations

import hashlib
import logging
import string
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow

from .constants import (
    DisputeStatus,
    SubscriptionStatus,
    TransactionStatus,
    TransactionType,
)
from .models import (
    PaymentCustomer,
    PaymentDispute,
    PaymentProvider,
    PaymentSubscription,
    PaymentTransaction,
)

logger = logging.getLogger(__name__)

# Marker stored on every fake customer's ``metadata_`` so the sentinel
# check doesn't depend on any specific opaque ID.
_FAKE_MARKER_KEY = "_aegis_fake"



def _ago(days: int = 0, hours: int = 0, minutes: int = 0) -> datetime:
    """Return a naive UTC datetime offset from now."""
    return utcnow() - timedelta(days=days, hours=hours, minutes=minutes)


def _ahead(days: int = 0, hours: int = 0) -> datetime:
    """Return a naive UTC datetime in the future."""
    return utcnow() + timedelta(days=days, hours=hours)


_ALPHABET = string.ascii_letters + string.digits


def _stripe_id(prefix: str, seed: str, length: int = 24) -> str:
    """Generate a deterministic Stripe-shaped fake id.

    ``prefix`` is the object prefix ("cus", "pi", "sub", etc.) without
    the trailing underscore. ``seed`` stabilizes the output so
    re-seeding after ``--reset`` regenerates the same IDs.
    """
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    # Spread the digest bytes over our 62-char alphabet. Using modulo on
    # a 256-byte range slightly biases the distribution but is fine for
    # visual realism and remains deterministic.
    chars = [_ALPHABET[b % len(_ALPHABET)] for b in digest]
    # Stripe IDs almost always start with a digit after the prefix (e.g.
    # ``cus_Q4...``). Don't enforce it — looks convincingly random either
    # way, and forcing would reduce the keyspace.
    return f"{prefix}_{''.join(chars)[:length]}"


async def clear_fake_data(session: AsyncSession) -> None:
    """Delete all payment rows EXCEPT the provider (which the seed installs).

    Order matters: disputes → subscriptions → transactions → customers.
    """
    await session.exec(delete(PaymentDispute))  # type: ignore[call-overload]
    await session.exec(delete(PaymentSubscription))  # type: ignore[call-overload]
    await session.exec(delete(PaymentTransaction))  # type: ignore[call-overload]
    await session.exec(delete(PaymentCustomer))  # type: ignore[call-overload]
    await session.commit()
    logger.info("Cleared fake payment data")


async def fake_data_exists(session: AsyncSession) -> bool:
    """Return True if this DB has already been seeded with fake data.

    Matches on the ``_aegis_fake`` marker set in each fake customer's
    metadata — keeps the check independent of the opaque IDs so we're
    free to change the seed's ID format without breaking idempotency.
    """
    result = await session.exec(
        select(PaymentCustomer).where(
            PaymentCustomer.metadata_[_FAKE_MARKER_KEY].is_not(None)  # type: ignore[attr-defined]
        )
    )
    return result.first() is not None


async def seed_fake_data(
    session: AsyncSession, provider: PaymentProvider
) -> dict[str, int]:
    """Create a comprehensive set of fake rows covering every UI state.

    Returns a dict summarising what was created, e.g.::

        {"customers": 4, "transactions": 12, "subscriptions": 5, "disputes": 7}

    Raises ``RuntimeError`` if fake data is already present — caller
    should either use ``clear_fake_data`` first (via ``--reset``) or treat
    this as a no-op.
    """
    if await fake_data_exists(session):
        raise RuntimeError(
            "Fake payment data already present. Use `--reset` to wipe and reseed."
        )

    def _customer_meta(name: str) -> dict[str, object]:
        return {_FAKE_MARKER_KEY: True, "name": name}

    # -- Customers (anonymous — user_id left NULL) ---------------------------
    alice = PaymentCustomer(
        provider_id=provider.id,  # type: ignore[arg-type]
        provider_customer_id=_stripe_id("cus", "alice", length=14),
        email="alice@example.com",
        metadata_=_customer_meta("Alice Chen"),
    )
    bob = PaymentCustomer(
        provider_id=provider.id,  # type: ignore[arg-type]
        provider_customer_id=_stripe_id("cus", "bob", length=14),
        email="bob@example.com",
        metadata_=_customer_meta("Bob Martinez"),
    )
    carol = PaymentCustomer(
        provider_id=provider.id,  # type: ignore[arg-type]
        provider_customer_id=_stripe_id("cus", "carol", length=14),
        email="carol@example.com",
        metadata_=_customer_meta("Carol Nguyen"),
    )
    diana = PaymentCustomer(
        provider_id=provider.id,  # type: ignore[arg-type]
        provider_customer_id=_stripe_id("cus", "diana", length=14),
        email="diana@example.com",
        metadata_=_customer_meta("Diana Patel"),
    )
    for c in (alice, bob, carol, diana):
        session.add(c)
    await session.flush()

    # -- Transactions --------------------------------------------------------
    txns: list[PaymentTransaction] = []

    def add_txn(seed: str, **kwargs: object) -> PaymentTransaction:
        t = PaymentTransaction(
            provider_id=provider.id,  # type: ignore[arg-type]
            provider_transaction_id=_stripe_id("pi", seed),
            currency="usd",
            **kwargs,  # type: ignore[arg-type]
        )
        session.add(t)
        txns.append(t)
        return t

    def add_refund(seed: str, **kwargs: object) -> PaymentTransaction:
        t = PaymentTransaction(
            provider_id=provider.id,  # type: ignore[arg-type]
            provider_transaction_id=_stripe_id("re", seed),
            currency="usd",
            type=TransactionType.REFUND,
            **kwargs,  # type: ignore[arg-type]
        )
        session.add(t)
        txns.append(t)
        return t

    # Alice: repeat customer, three successful charges
    alice_charge_1 = add_txn(
        "alice_1",
        customer_id=alice.id,
        type=TransactionType.CHARGE,
        status=TransactionStatus.SUCCEEDED,
        amount=2999,
        description="Starter plan",
        created_at=_ago(days=45),
    )
    add_txn(
        "alice_2",
        customer_id=alice.id,
        type=TransactionType.CHARGE,
        status=TransactionStatus.SUCCEEDED,
        amount=4999,
        description="Add-on pack",
        created_at=_ago(days=15),
    )
    add_txn(
        "alice_sub",
        customer_id=alice.id,
        type=TransactionType.SUBSCRIPTION,
        status=TransactionStatus.SUCCEEDED,
        amount=9900,
        description="Pro plan — monthly",
        created_at=_ago(hours=6),
    )

    # Bob: partially refunded
    bob_charge = add_txn(
        "bob_1",
        customer_id=bob.id,
        type=TransactionType.CHARGE,
        status=TransactionStatus.PARTIALLY_REFUNDED,
        amount=19900,
        description="Annual pass",
        created_at=_ago(days=10),
    )
    add_refund(
        "bob_1_refund",
        customer_id=bob.id,
        status=TransactionStatus.REFUNDED,
        amount=5000,
        description="Partial refund — duplicate charge",
        metadata_={"original_transaction_id": bob_charge.id},
        created_at=_ago(days=10, hours=-2),
    )

    # Carol: failed + canceled
    add_txn(
        "carol_failed",
        customer_id=carol.id,
        type=TransactionType.CHARGE,
        status=TransactionStatus.FAILED,
        amount=1000,
        description="Retry — failed (insufficient funds)",
        created_at=_ago(hours=2),
    )
    add_txn(
        "carol_canceled",
        customer_id=carol.id,
        type=TransactionType.CHARGE,
        status=TransactionStatus.CANCELED,
        amount=1500,
        description="Canceled before capture",
        created_at=_ago(days=1),
    )
    carol_charge = add_txn(
        "carol_sub",
        customer_id=carol.id,
        type=TransactionType.SUBSCRIPTION,
        status=TransactionStatus.SUCCEEDED,
        amount=2900,
        description="Basic plan — monthly",
        created_at=_ago(days=40),
    )

    # Diana: disputed charge
    diana_charge = add_txn(
        "diana_disputed",
        customer_id=diana.id,
        type=TransactionType.CHARGE,
        status=TransactionStatus.SUCCEEDED,
        amount=25000,
        description="Premium Suite",
        created_at=_ago(days=21),
    )

    # Anonymous (no customer) — pending and fully refunded
    add_txn(
        "anon_pending",
        customer_id=None,
        type=TransactionType.CHARGE,
        status=TransactionStatus.PENDING,
        amount=500,
        description="Anonymous — awaiting capture",
        created_at=_ago(minutes=10),
    )
    anon_refunded = add_txn(
        "anon_refunded",
        customer_id=None,
        type=TransactionType.CHARGE,
        status=TransactionStatus.REFUNDED,
        amount=3500,
        description="Anonymous — fully refunded",
        created_at=_ago(days=3),
    )
    add_refund(
        "anon_refund",
        customer_id=None,
        status=TransactionStatus.REFUNDED,
        amount=3500,
        description="Full refund — customer request",
        metadata_={"original_transaction_id": anon_refunded.id},
        created_at=_ago(days=3, hours=-1),
    )

    await session.flush()

    # -- Subscriptions -------------------------------------------------------

    def add_sub(seed: str, **kwargs: object) -> PaymentSubscription:
        s = PaymentSubscription(
            provider_subscription_id=_stripe_id("sub", seed),
            **kwargs,  # type: ignore[arg-type]
        )
        session.add(s)
        return s

    add_sub(
        "alice_pro",
        customer_id=alice.id,
        plan_name="Pro",
        status=SubscriptionStatus.ACTIVE,
        current_period_start=_ago(days=20),
        current_period_end=_ahead(days=10),
    )
    add_sub(
        "alice_enterprise_trial",
        customer_id=alice.id,
        plan_name="Enterprise",
        status=SubscriptionStatus.TRIALING,
        current_period_start=_ago(days=3),
        current_period_end=_ahead(days=11),
    )
    add_sub(
        "bob_growth_cancelling",
        customer_id=bob.id,
        plan_name="Growth",
        status=SubscriptionStatus.ACTIVE,
        cancel_at_period_end=True,
        current_period_start=_ago(days=28),
        current_period_end=_ahead(days=2),
    )
    add_sub(
        "carol_past_due",
        customer_id=carol.id,
        plan_name="Basic",
        status=SubscriptionStatus.PAST_DUE,
        current_period_start=_ago(days=35),
        current_period_end=_ago(days=5),
    )
    add_sub(
        "carol_legacy_canceled",
        customer_id=carol.id,
        plan_name="Legacy Starter",
        status=SubscriptionStatus.CANCELED,
        current_period_start=_ago(days=90),
        current_period_end=_ago(days=60),
    )

    # -- Disputes ------------------------------------------------------------
    # Cover every DisputeStatus value on real txn rows.
    disputes: list[PaymentDispute] = []

    def add_dispute(seed: str, prefix: str = "dp", **kwargs: object) -> PaymentDispute:
        d = PaymentDispute(
            provider_dispute_id=_stripe_id(prefix, seed),
            currency="usd",
            **kwargs,  # type: ignore[arg-type]
        )
        session.add(d)
        disputes.append(d)
        return d

    add_dispute(
        "diana_needs_response",
        transaction_id=diana_charge.id,
        status=DisputeStatus.NEEDS_RESPONSE,
        reason="fraudulent",
        amount=diana_charge.amount,
        evidence_due_by=_ahead(days=5),
        event_type="charge.dispute.created",
        created_at=_ago(days=2),
    )
    add_dispute(
        "bob_warning",
        prefix="issfr",
        transaction_id=bob_charge.id,
        status=DisputeStatus.WARNING_ISSUED,
        reason="fraudulent",
        amount=bob_charge.amount,
        event_type="radar.early_fraud_warning.created",
        created_at=_ago(days=1),
    )
    add_dispute(
        "alice_cleared",
        prefix="issfr",
        transaction_id=alice_charge_1.id,
        status=DisputeStatus.WARNING_CLOSED,
        reason="fraudulent",
        amount=alice_charge_1.amount,
        event_type="radar.early_fraud_warning.created",
        created_at=_ago(days=40),
        updated_at=_ago(days=35),
    )
    add_dispute(
        "carol_under_review",
        transaction_id=carol_charge.id,
        status=DisputeStatus.UNDER_REVIEW,
        reason="product_not_received",
        amount=carol_charge.amount,
        evidence_due_by=_ahead(days=1),
        event_type="charge.dispute.updated",
        created_at=_ago(days=6),
        updated_at=_ago(days=3),
    )

    # Won, lost, charge_refunded — attach to synthetic historical charges.
    won_txn = add_txn(
        "alice_won_dispute",
        customer_id=alice.id,
        type=TransactionType.CHARGE,
        status=TransactionStatus.SUCCEEDED,
        amount=7500,
        description="Dispute outcome: won",
        created_at=_ago(days=60),
    )
    lost_txn = add_txn(
        "bob_lost_dispute",
        customer_id=bob.id,
        type=TransactionType.CHARGE,
        status=TransactionStatus.SUCCEEDED,
        amount=12000,
        description="Dispute outcome: lost",
        created_at=_ago(days=75),
    )
    refunded_dispute_txn = add_txn(
        "carol_refunded_dispute",
        customer_id=carol.id,
        type=TransactionType.CHARGE,
        status=TransactionStatus.REFUNDED,
        amount=5600,
        description="Dispute outcome: refunded preemptively",
        created_at=_ago(days=30),
    )
    await session.flush()

    add_dispute(
        "alice_won",
        transaction_id=won_txn.id,
        status=DisputeStatus.WON,
        reason="unrecognized",
        amount=won_txn.amount,
        event_type="charge.dispute.closed",
        created_at=_ago(days=55),
        updated_at=_ago(days=50),
    )
    add_dispute(
        "bob_lost",
        transaction_id=lost_txn.id,
        status=DisputeStatus.LOST,
        reason="duplicate",
        amount=lost_txn.amount,
        event_type="charge.dispute.closed",
        created_at=_ago(days=70),
        updated_at=_ago(days=55),
    )
    add_dispute(
        "carol_refunded",
        transaction_id=refunded_dispute_txn.id,
        status=DisputeStatus.CHARGE_REFUNDED,
        reason="fraudulent",
        amount=refunded_dispute_txn.amount,
        event_type="charge.dispute.closed",
        created_at=_ago(days=28),
        updated_at=_ago(days=27),
    )

    await session.commit()

    return {
        "customers": 4,
        "transactions": len(txns),
        "subscriptions": 5,
        "disputes": len(disputes),
    }
