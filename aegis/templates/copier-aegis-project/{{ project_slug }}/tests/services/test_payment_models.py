"""
Tests for payment service database models.
"""

from datetime import datetime

import pytest
from app.services.payment.constants import (
    ProviderKeys,
    SubscriptionStatus,
    TransactionStatus,
    TransactionType,
)
from app.services.payment.models import (
    PaymentCustomer,
    PaymentProvider,
    PaymentSubscription,
    PaymentTransaction,
)
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_provider(session: AsyncSession) -> PaymentProvider:
    """Create a test payment provider."""
    provider = PaymentProvider(
        key=ProviderKeys.STRIPE,
        display_name="Stripe",
        enabled=True,
        is_test_mode=True,
    )
    session.add(provider)
    await session.flush()
    return provider


async def _seed_customer(
    session: AsyncSession, provider: PaymentProvider
) -> PaymentCustomer:
    """Create a test payment customer."""
    customer = PaymentCustomer(
        user_id=1,
        provider_id=provider.id,  # type: ignore[arg-type]
        provider_customer_id="cus_test_123",
        email="test@example.com",
    )
    session.add(customer)
    await session.flush()
    return customer


# ---------------------------------------------------------------------------
# Tests: PaymentProvider
# ---------------------------------------------------------------------------


class TestPaymentProvider:
    """Test PaymentProvider model."""

    @pytest.mark.asyncio
    async def test_create_provider(self, async_db_session: AsyncSession) -> None:
        """Can create a payment provider."""
        provider = await _seed_provider(async_db_session)
        assert provider.id is not None
        assert provider.key == ProviderKeys.STRIPE
        assert provider.enabled is True
        assert provider.is_test_mode is True

    @pytest.mark.asyncio
    async def test_provider_unique_key(self, async_db_session: AsyncSession) -> None:
        """Provider key must be unique."""
        await _seed_provider(async_db_session)
        await async_db_session.commit()

        duplicate = PaymentProvider(
            key=ProviderKeys.STRIPE,
            display_name="Stripe Duplicate",
        )
        async_db_session.add(duplicate)
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


# ---------------------------------------------------------------------------
# Tests: PaymentCustomer
# ---------------------------------------------------------------------------


class TestPaymentCustomer:
    """Test PaymentCustomer model."""

    @pytest.mark.asyncio
    async def test_create_customer(self, async_db_session: AsyncSession) -> None:
        """Can create a payment customer linked to a provider."""
        provider = await _seed_provider(async_db_session)
        customer = await _seed_customer(async_db_session, provider)

        assert customer.id is not None
        assert customer.user_id == 1
        assert customer.provider_customer_id == "cus_test_123"
        assert customer.email == "test@example.com"

    @pytest.mark.asyncio
    async def test_customer_provider_relationship(
        self, async_db_session: AsyncSession
    ) -> None:
        """Customer has a relationship back to provider."""
        provider = await _seed_provider(async_db_session)
        customer = await _seed_customer(async_db_session, provider)
        await async_db_session.commit()

        result = await async_db_session.exec(
            select(PaymentCustomer).where(PaymentCustomer.id == customer.id)
        )
        loaded = result.first()
        assert loaded is not None
        assert loaded.provider_id == provider.id


# ---------------------------------------------------------------------------
# Tests: PaymentTransaction
# ---------------------------------------------------------------------------


class TestPaymentTransaction:
    """Test PaymentTransaction model."""

    @pytest.mark.asyncio
    async def test_create_transaction(self, async_db_session: AsyncSession) -> None:
        """Can create a payment transaction."""
        provider = await _seed_provider(async_db_session)

        txn = PaymentTransaction(
            provider_id=provider.id,  # type: ignore[arg-type]
            provider_transaction_id="pi_test_123",
            type=TransactionType.CHARGE,
            status=TransactionStatus.SUCCEEDED,
            amount=2999,
            currency="usd",
        )
        async_db_session.add(txn)
        await async_db_session.flush()

        assert txn.id is not None
        assert txn.amount == 2999
        assert txn.currency == "usd"
        assert txn.status == TransactionStatus.SUCCEEDED

    @pytest.mark.asyncio
    async def test_transaction_unique_provider_id(
        self, async_db_session: AsyncSession
    ) -> None:
        """Provider transaction ID must be unique."""
        provider = await _seed_provider(async_db_session)

        txn1 = PaymentTransaction(
            provider_id=provider.id,  # type: ignore[arg-type]
            provider_transaction_id="pi_test_dup",
            type=TransactionType.CHARGE,
            status=TransactionStatus.SUCCEEDED,
            amount=1000,
        )
        async_db_session.add(txn1)
        await async_db_session.commit()

        txn2 = PaymentTransaction(
            provider_id=provider.id,  # type: ignore[arg-type]
            provider_transaction_id="pi_test_dup",
            type=TransactionType.CHARGE,
            status=TransactionStatus.SUCCEEDED,
            amount=2000,
        )
        async_db_session.add(txn2)
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


# ---------------------------------------------------------------------------
# Tests: PaymentSubscription
# ---------------------------------------------------------------------------


class TestPaymentSubscription:
    """Test PaymentSubscription model."""

    @pytest.mark.asyncio
    async def test_create_subscription(self, async_db_session: AsyncSession) -> None:
        """Can create a payment subscription."""
        provider = await _seed_provider(async_db_session)
        customer = await _seed_customer(async_db_session, provider)

        now = datetime.now()
        sub = PaymentSubscription(
            customer_id=customer.id,  # type: ignore[arg-type]
            provider_subscription_id="sub_test_123",
            plan_name="Pro Plan",
            status=SubscriptionStatus.ACTIVE,
            current_period_start=now,
            current_period_end=now,
        )
        async_db_session.add(sub)
        await async_db_session.flush()

        assert sub.id is not None
        assert sub.plan_name == "Pro Plan"
        assert sub.status == SubscriptionStatus.ACTIVE
        assert sub.cancel_at_period_end is False


# ---------------------------------------------------------------------------
# Tests: Constants
# ---------------------------------------------------------------------------


class TestPaymentConstants:
    """Test payment service constants."""

    def test_provider_keys(self) -> None:
        """Provider keys are defined."""
        assert ProviderKeys.STRIPE == "stripe"
        assert ProviderKeys.STRIPE in ProviderKeys.ALL

    def test_transaction_statuses(self) -> None:
        """Transaction statuses are defined."""
        assert TransactionStatus.PENDING == "pending"
        assert TransactionStatus.SUCCEEDED == "succeeded"
        assert TransactionStatus.FAILED == "failed"
        assert TransactionStatus.REFUNDED == "refunded"

    def test_transaction_types(self) -> None:
        """Transaction types are defined."""
        assert TransactionType.CHARGE == "charge"
        assert TransactionType.REFUND == "refund"
        assert TransactionType.SUBSCRIPTION == "subscription"

    def test_subscription_statuses(self) -> None:
        """Subscription statuses are defined."""
        assert SubscriptionStatus.ACTIVE == "active"
        assert SubscriptionStatus.CANCELED == "canceled"
        assert SubscriptionStatus.PAST_DUE == "past_due"


@pytest.mark.parametrize("hostile", ["//evil.example/x", "/\\evil.example/x"])
def test_a_checkout_redirect_cannot_leave_the_site(hostile: str) -> None:
    """A path that a browser resolves off-site is not a local one."""
    from pydantic import ValidationError

    from app.services.payment.schemas import CheckoutRequest

    with pytest.raises(ValidationError):
        CheckoutRequest(price_id="price_1", success_url=hostile)
