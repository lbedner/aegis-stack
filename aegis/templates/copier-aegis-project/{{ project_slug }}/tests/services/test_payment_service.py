"""
Tests for the PaymentService business logic layer.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from app.services.payment.constants import (
    DisputeStatus,
    ProviderKeys,
    SubscriptionStatus,
    TransactionStatus,
    TransactionType,
)
from app.services.payment.models import (
    PaymentCustomer,
    PaymentDispute,
    PaymentProvider,
    PaymentSubscription,
    PaymentTransaction,
)
from app.services.payment.service import PaymentService
from app.services.payment.providers.base import (
    CheckoutResult,
    CustomerResult,
    ProviderHealth,
    RefundResult,
    WebhookEvent,
)
from sqlmodel.ext.asyncio.session import AsyncSession

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_provider(session: AsyncSession) -> PaymentProvider:
    """Create a test provider row."""
    provider = PaymentProvider(
        key=ProviderKeys.STRIPE,
        display_name="Stripe",
        enabled=True,
        is_test_mode=True,
    )
    session.add(provider)
    await session.flush()
    return provider


async def _seed_transaction(
    session: AsyncSession,
    provider: PaymentProvider,
    status: str = TransactionStatus.SUCCEEDED,
    amount: int = 2999,
) -> PaymentTransaction:
    """Create a test transaction."""
    txn = PaymentTransaction(
        provider_id=provider.id,  # type: ignore[arg-type]
        provider_transaction_id=f"pi_test_{id(provider)}_{amount}",
        type=TransactionType.CHARGE,
        status=status,
        amount=amount,
        currency="usd",
    )
    session.add(txn)
    await session.flush()
    return txn


# ---------------------------------------------------------------------------
# Tests: get_or_create_provider
# ---------------------------------------------------------------------------


class TestCheckoutRequestValidation:
    """``CheckoutRequest.quantity`` must be 1 when mode is 'subscription'.

    Stripe supports quantity > 1 on subs for per-seat pricing, but that's
    a deliberate product design — the default Aegis project treats it as
    a footgun and blocks it at the schema layer so API callers (not just
    the UI) can't sneak past.
    """

    def test_payment_mode_accepts_quantity_greater_than_one(self) -> None:
        from app.services.payment.schemas import CheckoutRequest

        req = CheckoutRequest(price_id="price_x", quantity=10, mode="payment")
        assert req.quantity == 10

    def test_subscription_mode_rejects_quantity_greater_than_one(self) -> None:
        from app.services.payment.schemas import CheckoutRequest

        with pytest.raises(ValueError, match="quantity=1"):
            CheckoutRequest(price_id="price_x", quantity=5, mode="subscription")

    def test_subscription_mode_allows_quantity_one(self) -> None:
        from app.services.payment.schemas import CheckoutRequest

        req = CheckoutRequest(price_id="price_x", quantity=1, mode="subscription")
        assert req.quantity == 1


class TestGetOrCreateProvider:
    """Test PaymentService.get_or_create_provider."""

    @pytest.mark.asyncio
    async def test_creates_provider_when_missing(
        self, async_db_session: AsyncSession
    ) -> None:
        """Creates a provider row if none exists."""
        service = PaymentService(async_db_session)
        provider = await service.get_or_create_provider()
        assert provider.id is not None
        assert provider.key == ProviderKeys.STRIPE

    @pytest.mark.asyncio
    async def test_returns_existing_provider(
        self, async_db_session: AsyncSession
    ) -> None:
        """Returns existing provider instead of creating duplicate."""
        existing = await _seed_provider(async_db_session)
        await async_db_session.commit()

        service = PaymentService(async_db_session)
        provider = await service.get_or_create_provider()
        assert provider.id == existing.id


# ---------------------------------------------------------------------------
# Tests: get_transactions
# ---------------------------------------------------------------------------


class TestGetTransactions:
    """Test PaymentService.get_transactions."""

    @pytest.mark.asyncio
    async def test_empty_transactions(self, async_db_session: AsyncSession) -> None:
        """Returns empty list when no transactions exist."""
        service = PaymentService(async_db_session)
        txns, total = await service.get_transactions()
        assert txns == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_returns_transactions(self, async_db_session: AsyncSession) -> None:
        """Returns transactions with correct count."""
        provider = await _seed_provider(async_db_session)
        await _seed_transaction(async_db_session, provider, amount=1000)
        await _seed_transaction(async_db_session, provider, amount=2000)
        await async_db_session.commit()

        service = PaymentService(async_db_session)
        txns, total = await service.get_transactions()
        assert total == 2
        assert len(txns) == 2

    @pytest.mark.asyncio
    async def test_filter_by_status(self, async_db_session: AsyncSession) -> None:
        """Can filter transactions by status."""
        provider = await _seed_provider(async_db_session)
        await _seed_transaction(
            async_db_session, provider, status=TransactionStatus.SUCCEEDED
        )
        await _seed_transaction(
            async_db_session, provider, status=TransactionStatus.FAILED, amount=500
        )
        await async_db_session.commit()

        service = PaymentService(async_db_session)
        txns, total = await service.get_transactions(status=TransactionStatus.SUCCEEDED)
        assert total == 1
        assert txns[0].status == TransactionStatus.SUCCEEDED

    @pytest.mark.asyncio
    async def test_pagination(self, async_db_session: AsyncSession) -> None:
        """Pagination works correctly."""
        provider = await _seed_provider(async_db_session)
        for i in range(5):
            await _seed_transaction(async_db_session, provider, amount=100 * (i + 1))
        await async_db_session.commit()

        service = PaymentService(async_db_session)
        txns, total = await service.get_transactions(page=1, page_size=2)
        assert total == 5
        assert len(txns) == 2


# ---------------------------------------------------------------------------
# Tests: get_subscriptions
# ---------------------------------------------------------------------------


class TestGetSubscriptions:
    """Test PaymentService.get_subscriptions."""

    @pytest.mark.asyncio
    async def test_empty_subscriptions(self, async_db_session: AsyncSession) -> None:
        """Returns empty list when no subscriptions exist."""
        service = PaymentService(async_db_session)
        subs = await service.get_subscriptions()
        assert subs == []

    @pytest.mark.asyncio
    async def test_returns_subscriptions(self, async_db_session: AsyncSession) -> None:
        """Returns subscriptions."""
        provider = await _seed_provider(async_db_session)
        customer = PaymentCustomer(
            user_id=1,
            provider_id=provider.id,  # type: ignore[arg-type]
            provider_customer_id="cus_test",
        )
        async_db_session.add(customer)
        await async_db_session.flush()

        now = datetime.now(UTC).replace(tzinfo=None)
        sub = PaymentSubscription(
            customer_id=customer.id,  # type: ignore[arg-type]
            provider_subscription_id="sub_test",
            plan_name="Pro",
            status=SubscriptionStatus.ACTIVE,
            current_period_start=now,
            current_period_end=now,
        )
        async_db_session.add(sub)
        await async_db_session.commit()

        service = PaymentService(async_db_session)
        subs = await service.get_subscriptions()
        assert len(subs) == 1
        assert subs[0].plan_name == "Pro"


# ---------------------------------------------------------------------------
# Tests: get_status_summary
# ---------------------------------------------------------------------------


class TestGetStatusSummary:
    """Test PaymentService.get_status_summary."""

    @pytest.mark.asyncio
    async def test_returns_summary(self, async_db_session: AsyncSession) -> None:
        """Returns a complete status summary dict."""
        service = PaymentService(async_db_session)

        # Mock the provider health check since we don't have real Stripe keys
        mock_health = ProviderHealth(
            provider_key="stripe",
            healthy=True,
            is_test_mode=True,
            message="Connected (test mode)",
        )
        service.provider.health_check = AsyncMock(return_value=mock_health)

        summary = await service.get_status_summary()

        assert summary.provider_key == ProviderKeys.STRIPE
        assert summary.healthy is True
        assert summary.is_test_mode is True
        assert summary.total_transactions == 0
        assert summary.total_revenue_cents == 0
        assert summary.active_subscriptions == 0
        assert summary.open_disputes == 0
        assert summary.recent_transactions == []
        assert summary.recent_subscriptions == []
        assert summary.recent_disputes == []


# ---------------------------------------------------------------------------
# Tests: Provider base classes
# ---------------------------------------------------------------------------


class TestProviderBaseClasses:
    """Test payment provider base Pydantic models."""

    def test_checkout_result(self) -> None:
        """CheckoutResult has required fields."""
        result = CheckoutResult(
            session_id="cs_test_123",
            checkout_url="https://checkout.stripe.com/...",
            provider_key="stripe",
        )
        assert result.session_id == "cs_test_123"
        assert result.provider_key == "stripe"

    def test_refund_result(self) -> None:
        """RefundResult has required fields."""
        result = RefundResult(
            provider_refund_id="re_test_123",
            status="succeeded",
            amount=2999,
            currency="usd",
        )
        assert result.amount == 2999

    def test_webhook_event(self) -> None:
        """WebhookEvent has required fields."""
        event = WebhookEvent(
            event_type="checkout.session.completed",
            provider_key="stripe",
            data={"id": "cs_test_123"},
        )
        assert event.event_type == "checkout.session.completed"

    def test_provider_health(self) -> None:
        """ProviderHealth has required fields."""
        health = ProviderHealth(
            provider_key="stripe",
            healthy=True,
            is_test_mode=True,
            message="Connected",
        )
        assert health.healthy is True


# ---------------------------------------------------------------------------
# Tests: create_checkout customer caching
# ---------------------------------------------------------------------------


class TestCreateCheckoutCustomerCaching:
    """PaymentService.create_checkout looks up an existing PaymentCustomer
    for the given user_id and forwards provider_customer_id to the provider."""

    @pytest.mark.asyncio
    async def test_no_user_id_passes_none(self, async_db_session: AsyncSession) -> None:
        """When user_id is not provided, provider is called with customer_id=None."""
        await _seed_provider(async_db_session)
        service = PaymentService(async_db_session)
        service.provider.create_checkout = AsyncMock(
            return_value=CheckoutResult(
                session_id="cs_stub",
                checkout_url="https://stub",
                provider_key=ProviderKeys.STRIPE,
            )
        )

        await service.create_checkout(
            price_id="price_x",
            quantity=1,
            mode="payment",
            success_url="https://success",
            cancel_url="https://cancel",
            user_id=None,
        )

        call_kwargs = service.provider.create_checkout.call_args.kwargs
        assert call_kwargs["customer_id"] is None

    @pytest.mark.asyncio
    async def test_existing_customer_forwards_provider_id(
        self, async_db_session: AsyncSession
    ) -> None:
        """user_id with a PaymentCustomer row forwards the provider_customer_id."""
        provider = await _seed_provider(async_db_session)
        customer = PaymentCustomer(
            provider_id=provider.id,  # type: ignore[arg-type]
            user_id=42,
            provider_customer_id="cus_stripe_abc",
            email="user@example.com",
        )
        async_db_session.add(customer)
        await async_db_session.flush()

        service = PaymentService(async_db_session)
        service.provider.create_checkout = AsyncMock(
            return_value=CheckoutResult(
                session_id="cs_stub",
                checkout_url="https://stub",
                provider_key=ProviderKeys.STRIPE,
            )
        )

        await service.create_checkout(
            price_id="price_x",
            quantity=1,
            mode="payment",
            success_url="https://success",
            cancel_url="https://cancel",
            user_id=42,
        )

        call_kwargs = service.provider.create_checkout.call_args.kwargs
        assert call_kwargs["customer_id"] == "cus_stripe_abc"

    @pytest.mark.asyncio
    async def test_user_id_without_customer_row_passes_none(
        self, async_db_session: AsyncSession
    ) -> None:
        """user_id with no matching PaymentCustomer row still calls provider."""
        await _seed_provider(async_db_session)
        service = PaymentService(async_db_session)
        service.provider.create_checkout = AsyncMock(
            return_value=CheckoutResult(
                session_id="cs_stub",
                checkout_url="https://stub",
                provider_key=ProviderKeys.STRIPE,
            )
        )

        await service.create_checkout(
            price_id="price_x",
            quantity=1,
            mode="payment",
            success_url="https://success",
            cancel_url="https://cancel",
            user_id=999,
        )

        call_kwargs = service.provider.create_checkout.call_args.kwargs
        assert call_kwargs["customer_id"] is None


# ---------------------------------------------------------------------------
# Tests: refund_transaction linking + status transitions
# ---------------------------------------------------------------------------


class TestRefundTransactionLinking:
    """Full vs partial refunds set the original txn status correctly and
    create a linked refund row with type=REFUND."""

    @pytest.mark.asyncio
    async def test_full_refund_marks_original_refunded(
        self, async_db_session: AsyncSession
    ) -> None:
        provider = await _seed_provider(async_db_session)
        original = await _seed_transaction(async_db_session, provider, amount=5000)
        service = PaymentService(async_db_session)
        service.provider.refund = AsyncMock(
            return_value=RefundResult(
                provider_refund_id="re_test_full",
                status="succeeded",
                amount=5000,
                currency="usd",
            )
        )

        refund = await service.refund_transaction(
            transaction_id=original.id,  # type: ignore[arg-type]
            amount=None,
        )

        assert refund is not None
        assert refund.type == TransactionType.REFUND
        assert refund.amount == 5000
        assert refund.provider_transaction_id == "re_test_full"
        assert refund.metadata_ == {"original_transaction_id": original.id}
        assert original.status == TransactionStatus.REFUNDED

    @pytest.mark.asyncio
    async def test_partial_refund_marks_original_partially_refunded(
        self, async_db_session: AsyncSession
    ) -> None:
        provider = await _seed_provider(async_db_session)
        original = await _seed_transaction(async_db_session, provider, amount=5000)
        service = PaymentService(async_db_session)
        service.provider.refund = AsyncMock(
            return_value=RefundResult(
                provider_refund_id="re_test_partial",
                status="succeeded",
                amount=2000,
                currency="usd",
            )
        )

        refund = await service.refund_transaction(
            transaction_id=original.id,  # type: ignore[arg-type]
            amount=2000,
        )

        assert refund is not None
        assert refund.amount == 2000
        assert original.status == TransactionStatus.PARTIALLY_REFUNDED

    @pytest.mark.asyncio
    async def test_refund_missing_transaction_returns_none(
        self, async_db_session: AsyncSession
    ) -> None:
        service = PaymentService(async_db_session)
        result = await service.refund_transaction(transaction_id=999_999)
        assert result is None

    @pytest.mark.asyncio
    async def test_refund_refuses_already_refunded_transaction(
        self, async_db_session: AsyncSession
    ) -> None:
        """Refunding a fully-refunded txn raises and writes no new row.

        Guards against IntegrityError from colliding synthetic refund IDs
        and masks less actionable provider errors for real charges.
        """
        from sqlmodel import select as sm_select

        provider = await _seed_provider(async_db_session)
        original = await _seed_transaction(
            async_db_session,
            provider,
            status=TransactionStatus.REFUNDED,
            amount=5000,
        )
        service = PaymentService(async_db_session)
        service.provider.refund = AsyncMock()  # should never be invoked

        with pytest.raises(RuntimeError, match="already fully refunded"):
            await service.refund_transaction(
                transaction_id=original.id,  # type: ignore[arg-type]
            )

        service.provider.refund.assert_not_called()

        # No refund row was inserted.
        result = await async_db_session.exec(
            sm_select(PaymentTransaction).where(
                PaymentTransaction.type == TransactionType.REFUND
            )
        )
        assert result.all() == []

    @pytest.mark.asyncio
    async def test_refund_synthetic_ids_are_unique_across_partials(
        self, async_db_session: AsyncSession
    ) -> None:
        """Two partial refunds on a fake-prefixed txn get distinct IDs.

        Regression: seed rows previously generated a deterministic
        ``re_fake_<suffix>_refund`` id, so a second partial refund on the
        same row collided on ``provider_transaction_id``.
        """
        provider = await _seed_provider(async_db_session)
        txn = PaymentTransaction(
            provider_id=provider.id,  # type: ignore[arg-type]
            provider_transaction_id="pi_fake_alice_sub",
            type=TransactionType.CHARGE,
            status=TransactionStatus.SUCCEEDED,
            amount=5000,
            currency="usd",
        )
        async_db_session.add(txn)
        await async_db_session.flush()

        service = PaymentService(async_db_session)

        first = await service.refund_transaction(
            transaction_id=txn.id,  # type: ignore[arg-type]
            amount=1000,
        )
        second = await service.refund_transaction(
            transaction_id=txn.id,  # type: ignore[arg-type]
            amount=1000,
        )

        assert first is not None and second is not None
        assert first.provider_transaction_id != second.provider_transaction_id
        assert first.provider_transaction_id.startswith("re_fake_alice_sub_refund_")
        assert second.provider_transaction_id.startswith("re_fake_alice_sub_refund_")
        # Both refunds were partial; original remains PARTIALLY_REFUNDED.
        assert txn.status == TransactionStatus.PARTIALLY_REFUNDED


# ---------------------------------------------------------------------------
# Tests: handle_webhook event dispatch
# ---------------------------------------------------------------------------


class TestHandleWebhookDispatch:
    """Each Stripe event type routes to the right handler and produces the
    expected DB side-effects."""

    @pytest.mark.asyncio
    async def test_checkout_completed_creates_transaction(
        self, async_db_session: AsyncSession
    ) -> None:
        service = PaymentService(async_db_session)
        service.provider.verify_webhook = AsyncMock(
            return_value=WebhookEvent(
                event_type="checkout.session.completed",
                provider_key=ProviderKeys.STRIPE,
                data={
                    "id": "cs_test_wh_1",
                    "payment_intent": "pi_test_wh_1",
                    "amount_total": 7500,
                    "currency": "usd",
                    "mode": "payment",
                },
            )
        )

        result = await service.handle_webhook(b"{}", "sig")

        assert result["event_type"] == "checkout.session.completed"
        from sqlmodel import select

        txns = (
            await async_db_session.exec(
                select(PaymentTransaction).where(
                    PaymentTransaction.provider_transaction_id == "pi_test_wh_1"
                )
            )
        ).all()
        assert len(txns) == 1
        assert txns[0].status == TransactionStatus.SUCCEEDED
        assert txns[0].amount == 7500
        assert txns[0].type == TransactionType.CHARGE

    @pytest.mark.asyncio
    async def test_checkout_completed_subscription_mode_marks_type(
        self, async_db_session: AsyncSession
    ) -> None:
        service = PaymentService(async_db_session)
        service.provider.verify_webhook = AsyncMock(
            return_value=WebhookEvent(
                event_type="checkout.session.completed",
                provider_key=ProviderKeys.STRIPE,
                data={
                    "id": "cs_test_wh_sub",
                    "payment_intent": "pi_test_wh_sub",
                    "amount_total": 9900,
                    "currency": "usd",
                    "mode": "subscription",
                },
            )
        )

        await service.handle_webhook(b"{}", "sig")

        from sqlmodel import select

        txn = (
            await async_db_session.exec(
                select(PaymentTransaction).where(
                    PaymentTransaction.provider_transaction_id == "pi_test_wh_sub"
                )
            )
        ).first()
        assert txn is not None
        assert txn.type == TransactionType.SUBSCRIPTION

    @pytest.mark.asyncio
    async def test_checkout_completed_subscription_null_payment_intent(
        self, async_db_session: AsyncSession
    ) -> None:
        """Subscription checkouts ship ``payment_intent: null`` — must fall
        back to the session id rather than INSERT NULL (NOT NULL column →
        IntegrityError → 400 response, as seen in production).
        """
        service = PaymentService(async_db_session)
        service.provider.verify_webhook = AsyncMock(
            return_value=WebhookEvent(
                event_type="checkout.session.completed",
                provider_key=ProviderKeys.STRIPE,
                data={
                    "id": "cs_test_null_pi",
                    "payment_intent": None,  # explicit null, not missing
                    "amount_total": 9990,
                    "currency": "usd",
                    "mode": "subscription",
                },
            )
        )

        # Must not raise; must create a row keyed off the session id.
        await service.handle_webhook(b"{}", "sig")

        from sqlmodel import select

        txn = (
            await async_db_session.exec(
                select(PaymentTransaction).where(
                    PaymentTransaction.provider_transaction_id == "cs_test_null_pi"
                )
            )
        ).first()
        assert txn is not None
        assert txn.type == TransactionType.SUBSCRIPTION
        assert txn.amount == 9990

    @pytest.mark.asyncio
    async def test_checkout_completed_is_idempotent(
        self, async_db_session: AsyncSession
    ) -> None:
        """Re-delivery of the same event is a no-op, not a 400.

        Stripe retries webhooks on 5xx, and our forwarder may double-
        deliver during reconnects; the second attempt used to collide
        on the UNIQUE constraint on ``provider_transaction_id``. The
        handler now looks up by id and returns early when a row exists.
        """
        service = PaymentService(async_db_session)
        event = WebhookEvent(
            event_type="checkout.session.completed",
            provider_key=ProviderKeys.STRIPE,
            data={
                "id": "cs_test_idem",
                "payment_intent": "pi_test_idem",
                "amount_total": 2500,
                "currency": "usd",
                "mode": "payment",
            },
        )
        service.provider.verify_webhook = AsyncMock(return_value=event)

        await service.handle_webhook(b"{}", "sig")
        await service.handle_webhook(b"{}", "sig")  # replay

        from sqlmodel import select

        rows = (
            await async_db_session.exec(
                select(PaymentTransaction).where(
                    PaymentTransaction.provider_transaction_id == "pi_test_idem"
                )
            )
        ).all()
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_charge_refunded_updates_original_status(
        self, async_db_session: AsyncSession
    ) -> None:
        provider = await _seed_provider(async_db_session)
        txn = PaymentTransaction(
            provider_id=provider.id,  # type: ignore[arg-type]
            provider_transaction_id="pi_test_wh_refund",
            type=TransactionType.CHARGE,
            status=TransactionStatus.SUCCEEDED,
            amount=3000,
            currency="usd",
        )
        async_db_session.add(txn)
        await async_db_session.flush()

        service = PaymentService(async_db_session)
        service.provider.verify_webhook = AsyncMock(
            return_value=WebhookEvent(
                event_type="charge.refunded",
                provider_key=ProviderKeys.STRIPE,
                data={
                    "id": "ch_test_wh_refund",
                    "payment_intent": "pi_test_wh_refund",
                    "amount": 3000,
                    "amount_refunded": 3000,
                },
            )
        )

        await service.handle_webhook(b"{}", "sig")

        await async_db_session.refresh(txn)
        assert txn.status == TransactionStatus.REFUNDED

    @pytest.mark.asyncio
    async def test_charge_refunded_partial(
        self, async_db_session: AsyncSession
    ) -> None:
        provider = await _seed_provider(async_db_session)
        txn = PaymentTransaction(
            provider_id=provider.id,  # type: ignore[arg-type]
            provider_transaction_id="pi_test_wh_partial",
            type=TransactionType.CHARGE,
            status=TransactionStatus.SUCCEEDED,
            amount=3000,
            currency="usd",
        )
        async_db_session.add(txn)
        await async_db_session.flush()

        service = PaymentService(async_db_session)
        service.provider.verify_webhook = AsyncMock(
            return_value=WebhookEvent(
                event_type="charge.refunded",
                provider_key=ProviderKeys.STRIPE,
                data={
                    "id": "ch_test_wh_partial",
                    "payment_intent": "pi_test_wh_partial",
                    "amount": 3000,
                    "amount_refunded": 1000,
                },
            )
        )

        await service.handle_webhook(b"{}", "sig")

        await async_db_session.refresh(txn)
        assert txn.status == TransactionStatus.PARTIALLY_REFUNDED

    @pytest.mark.asyncio
    async def test_unknown_event_type_is_no_op(
        self, async_db_session: AsyncSession
    ) -> None:
        """Unrecognized event types are acknowledged, not crashed on."""
        service = PaymentService(async_db_session)
        service.provider.verify_webhook = AsyncMock(
            return_value=WebhookEvent(
                event_type="some.event.we.dont.handle",
                provider_key=ProviderKeys.STRIPE,
                data={},
            )
        )

        result = await service.handle_webhook(b"{}", "sig")
        assert result["event_type"] == "some.event.we.dont.handle"


class TestSubscriptionCreatedDuplicateActive:
    """``customer.subscription.created`` must refuse a second active row.

    The handler pre-checks the partial unique index on
    ``payment_subscription (customer_id) WHERE status IN
    ('active', 'trialing')``. The status used by the pre-check has to
    match the status the insert would use — otherwise a webhook with
    falsy ``status`` would skip the check and then default to ACTIVE on
    insert, tripping the index with no try/except to catch it.
    """

    @staticmethod
    async def _seed_customer_with_active_sub(
        session: AsyncSession,
    ) -> PaymentCustomer:
        provider = await _seed_provider(session)
        customer = PaymentCustomer(
            user_id=1,
            provider_id=provider.id,  # type: ignore[arg-type]
            provider_customer_id="cus_dup_active",
        )
        session.add(customer)
        await session.flush()
        now = datetime.now(UTC).replace(tzinfo=None)
        session.add(
            PaymentSubscription(
                customer_id=customer.id,  # type: ignore[arg-type]
                provider_subscription_id="sub_existing",
                plan_name="Pro",
                status=SubscriptionStatus.ACTIVE,
                current_period_start=now,
                current_period_end=now + timedelta(days=30),
            )
        )
        await session.commit()
        return customer

    @pytest.mark.asyncio
    @pytest.mark.parametrize("incoming_status", ["", None])
    async def test_falsy_status_does_not_create_duplicate(
        self,
        async_db_session: AsyncSession,
        incoming_status: str | None,
    ) -> None:
        """Empty or null status defaults to ACTIVE on insert; the pre-check
        must use that same effective status, not the raw value."""
        from sqlmodel import select

        await self._seed_customer_with_active_sub(async_db_session)

        service = PaymentService(async_db_session)
        period_start = int(datetime.now(UTC).timestamp())
        period_end = period_start + 30 * 24 * 3600
        service.provider.verify_webhook = AsyncMock(
            return_value=WebhookEvent(
                event_type="customer.subscription.created",
                provider_key=ProviderKeys.STRIPE,
                data={
                    "id": "sub_new_falsy_status",
                    "customer": "cus_dup_active",
                    "status": incoming_status,
                    "cancel_at_period_end": False,
                    "items": {
                        "data": [
                            {
                                "current_period_start": period_start,
                                "current_period_end": period_end,
                                "price": {
                                    "id": "price_test",
                                    "nickname": "Pro",
                                    "unit_amount": 2999,
                                    "currency": "usd",
                                },
                            }
                        ]
                    },
                },
            )
        )

        await service.handle_webhook(b"{}", "sig")

        rows = (
            await async_db_session.exec(
                select(PaymentSubscription).where(
                    PaymentSubscription.provider_subscription_id.in_(  # type: ignore[attr-defined]
                        ["sub_existing", "sub_new_falsy_status"]
                    )
                )
            )
        ).all()
        assert len(rows) == 1, (
            f"Expected pre-check to refuse duplicate active sub for falsy "
            f"status={incoming_status!r}; got {len(rows)} rows instead."
        )
        assert rows[0].provider_subscription_id == "sub_existing"


# ---------------------------------------------------------------------------
# Tests: fraud and dispute webhook handling
# ---------------------------------------------------------------------------


async def _seed_charge(
    session: AsyncSession, provider_transaction_id: str = "ch_test_abc"
) -> PaymentTransaction:
    """Seed a charge row so disputes can reference it."""
    provider = await _seed_provider(session)
    txn = PaymentTransaction(
        provider_id=provider.id,  # type: ignore[arg-type]
        provider_transaction_id=provider_transaction_id,
        type=TransactionType.CHARGE,
        status=TransactionStatus.SUCCEEDED,
        amount=5000,
        currency="usd",
    )
    session.add(txn)
    await session.flush()
    return txn


class TestEarlyFraudWarning:
    """radar.early_fraud_warning.created creates a dispute row with
    status=warning_issued and links it to the charged transaction."""

    @pytest.mark.asyncio
    async def test_efw_creates_warning_row(
        self, async_db_session: AsyncSession
    ) -> None:
        from sqlmodel import select

        txn = await _seed_charge(async_db_session, "ch_efw_1")
        service = PaymentService(async_db_session)
        service.provider.verify_webhook = AsyncMock(
            return_value=WebhookEvent(
                event_type="radar.early_fraud_warning.created",
                provider_key=ProviderKeys.STRIPE,
                data={
                    "id": "issfr_test_1",
                    "charge": "ch_efw_1",
                    "fraud_type": "fraudulent",
                    "actionable": True,
                },
            )
        )

        await service.handle_webhook(b"{}", "sig")

        disputes = (
            await async_db_session.exec(
                select(PaymentDispute).where(
                    PaymentDispute.provider_dispute_id == "issfr_test_1"
                )
            )
        ).all()
        assert len(disputes) == 1
        d = disputes[0]
        assert d.status == DisputeStatus.WARNING_ISSUED
        assert d.transaction_id == txn.id
        assert d.amount == txn.amount
        assert d.event_type == "radar.early_fraud_warning.created"
        assert d.reason == "fraudulent"

    @pytest.mark.asyncio
    async def test_efw_is_idempotent(self, async_db_session: AsyncSession) -> None:
        """Duplicate webhook deliveries don't create duplicate rows."""
        from sqlmodel import select

        await _seed_charge(async_db_session, "ch_efw_idem")
        service = PaymentService(async_db_session)
        event = WebhookEvent(
            event_type="radar.early_fraud_warning.created",
            provider_key=ProviderKeys.STRIPE,
            data={
                "id": "issfr_test_idem",
                "charge": "ch_efw_idem",
                "fraud_type": "fraudulent",
            },
        )
        service.provider.verify_webhook = AsyncMock(return_value=event)

        await service.handle_webhook(b"{}", "sig")
        await service.handle_webhook(b"{}", "sig")

        disputes = (
            await async_db_session.exec(
                select(PaymentDispute).where(
                    PaymentDispute.provider_dispute_id == "issfr_test_idem"
                )
            )
        ).all()
        assert len(disputes) == 1

    @pytest.mark.asyncio
    async def test_efw_for_unknown_charge_is_logged(
        self, async_db_session: AsyncSession
    ) -> None:
        """An EFW for a charge we don't have doesn't crash or create a row."""
        from sqlmodel import select

        service = PaymentService(async_db_session)
        service.provider.verify_webhook = AsyncMock(
            return_value=WebhookEvent(
                event_type="radar.early_fraud_warning.created",
                provider_key=ProviderKeys.STRIPE,
                data={
                    "id": "issfr_ghost",
                    "charge": "ch_unknown",
                    "fraud_type": "fraudulent",
                },
            )
        )

        result = await service.handle_webhook(b"{}", "sig")
        assert result["event_type"] == "radar.early_fraud_warning.created"

        disputes = (
            await async_db_session.exec(
                select(PaymentDispute).where(
                    PaymentDispute.provider_dispute_id == "issfr_ghost"
                )
            )
        ).all()
        assert len(disputes) == 0


class TestDisputeLifecycle:
    """charge.dispute.created/updated/closed upsert a dispute row with
    the Stripe status mapped to our DisputeStatus lifecycle."""

    @pytest.mark.asyncio
    async def test_dispute_created_sets_needs_response(
        self, async_db_session: AsyncSession
    ) -> None:
        from sqlmodel import select

        txn = await _seed_charge(async_db_session, "ch_dp_1")
        service = PaymentService(async_db_session)
        service.provider.verify_webhook = AsyncMock(
            return_value=WebhookEvent(
                event_type="charge.dispute.created",
                provider_key=ProviderKeys.STRIPE,
                data={
                    "id": "dp_test_1",
                    "charge": "ch_dp_1",
                    "status": "needs_response",
                    "reason": "fraudulent",
                    "amount": 5000,
                    "currency": "usd",
                    "evidence_details": {
                        "due_by": 1714608000,  # 2024-05-02 UTC
                    },
                },
            )
        )

        await service.handle_webhook(b"{}", "sig")

        d = (
            await async_db_session.exec(
                select(PaymentDispute).where(
                    PaymentDispute.provider_dispute_id == "dp_test_1"
                )
            )
        ).first()
        assert d is not None
        assert d.status == DisputeStatus.NEEDS_RESPONSE
        assert d.transaction_id == txn.id
        assert d.reason == "fraudulent"
        assert d.evidence_due_by is not None

    @pytest.mark.asyncio
    async def test_dispute_updated_upserts_existing_row(
        self, async_db_session: AsyncSession
    ) -> None:
        """An update event on an existing dispute mutates that row in place."""
        from sqlmodel import select

        await _seed_charge(async_db_session, "ch_dp_upsert")
        service = PaymentService(async_db_session)

        # Create
        service.provider.verify_webhook = AsyncMock(
            return_value=WebhookEvent(
                event_type="charge.dispute.created",
                provider_key=ProviderKeys.STRIPE,
                data={
                    "id": "dp_upsert",
                    "charge": "ch_dp_upsert",
                    "status": "needs_response",
                    "reason": "fraudulent",
                    "amount": 5000,
                    "currency": "usd",
                },
            )
        )
        await service.handle_webhook(b"{}", "sig")

        # Update
        service.provider.verify_webhook = AsyncMock(
            return_value=WebhookEvent(
                event_type="charge.dispute.updated",
                provider_key=ProviderKeys.STRIPE,
                data={
                    "id": "dp_upsert",
                    "charge": "ch_dp_upsert",
                    "status": "under_review",
                    "reason": "fraudulent",
                    "amount": 5000,
                    "currency": "usd",
                },
            )
        )
        await service.handle_webhook(b"{}", "sig")

        rows = (
            await async_db_session.exec(
                select(PaymentDispute).where(
                    PaymentDispute.provider_dispute_id == "dp_upsert"
                )
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].status == DisputeStatus.UNDER_REVIEW
        assert rows[0].event_type == "charge.dispute.updated"

    @pytest.mark.asyncio
    async def test_dispute_closed_won_and_lost_map_correctly(
        self, async_db_session: AsyncSession
    ) -> None:
        """Stripe 'won' / 'lost' map to our DisputeStatus values."""
        from sqlmodel import select

        # Seed provider once; each iteration creates a charge on it.
        provider = await _seed_provider(async_db_session)

        for stripe_status, expected in [
            ("won", DisputeStatus.WON),
            ("lost", DisputeStatus.LOST),
            ("charge_refunded", DisputeStatus.CHARGE_REFUNDED),
            ("warning_closed", DisputeStatus.WARNING_CLOSED),
        ]:
            charge_id = f"ch_dp_{stripe_status}"
            txn = PaymentTransaction(
                provider_id=provider.id,  # type: ignore[arg-type]
                provider_transaction_id=charge_id,
                type=TransactionType.CHARGE,
                status=TransactionStatus.SUCCEEDED,
                amount=5000,
                currency="usd",
            )
            async_db_session.add(txn)
            await async_db_session.flush()
            service = PaymentService(async_db_session)
            service.provider.verify_webhook = AsyncMock(
                return_value=WebhookEvent(
                    event_type="charge.dispute.closed",
                    provider_key=ProviderKeys.STRIPE,
                    data={
                        "id": f"dp_{stripe_status}",
                        "charge": charge_id,
                        "status": stripe_status,
                        "reason": "fraudulent",
                        "amount": 5000,
                        "currency": "usd",
                    },
                )
            )
            await service.handle_webhook(b"{}", "sig")

            d = (
                await async_db_session.exec(
                    select(PaymentDispute).where(
                        PaymentDispute.provider_dispute_id == f"dp_{stripe_status}"
                    )
                )
            ).first()
            assert d is not None, f"no dispute row for {stripe_status}"
            assert d.status == expected


class TestDisputeQueries:
    """PaymentService.get_disputes and get_dispute_by_id."""

    @pytest.mark.asyncio
    async def test_get_disputes_filter_open(
        self, async_db_session: AsyncSession
    ) -> None:
        """status='open' returns only warning_issued, needs_response, under_review."""
        txn = await _seed_charge(async_db_session, "ch_queries")
        for i, status in enumerate(
            [
                DisputeStatus.WARNING_ISSUED,
                DisputeStatus.NEEDS_RESPONSE,
                DisputeStatus.UNDER_REVIEW,
                DisputeStatus.WON,
                DisputeStatus.LOST,
            ]
        ):
            async_db_session.add(
                PaymentDispute(
                    transaction_id=txn.id,  # type: ignore[arg-type]
                    provider_dispute_id=f"dp_q_{i}",
                    status=status,
                    amount=1000,
                    currency="usd",
                )
            )
        await async_db_session.flush()

        service = PaymentService(async_db_session)
        open_disputes = await service.get_disputes(status="open")
        statuses = {d.status for d in open_disputes}
        assert statuses == {
            DisputeStatus.WARNING_ISSUED,
            DisputeStatus.NEEDS_RESPONSE,
            DisputeStatus.UNDER_REVIEW,
        }

    @pytest.mark.asyncio
    async def test_get_dispute_by_id(self, async_db_session: AsyncSession) -> None:
        txn = await _seed_charge(async_db_session, "ch_byid")
        dispute = PaymentDispute(
            transaction_id=txn.id,  # type: ignore[arg-type]
            provider_dispute_id="dp_byid",
            status=DisputeStatus.NEEDS_RESPONSE,
            amount=1000,
            currency="usd",
        )
        async_db_session.add(dispute)
        await async_db_session.flush()

        service = PaymentService(async_db_session)
        found = await service.get_dispute_by_id(dispute.id)  # type: ignore[arg-type]
        assert found is not None
        assert found.provider_dispute_id == "dp_byid"

    @pytest.mark.asyncio
    async def test_get_dispute_by_id_missing(
        self, async_db_session: AsyncSession
    ) -> None:
        service = PaymentService(async_db_session)
        assert await service.get_dispute_by_id(999_999) is None


# ---------------------------------------------------------------------------
# Tests: PaymentCustomer upsert on authenticated checkout
# ---------------------------------------------------------------------------


async def _seed_customer(
    session: AsyncSession,
    provider: PaymentProvider,
    user_id: int,
    provider_customer_id: str = "cus_seed",
    email: str = "user@example.com",
) -> PaymentCustomer:
    """Seed a PaymentCustomer row."""
    c = PaymentCustomer(
        user_id=user_id,
        provider_id=provider.id,  # type: ignore[arg-type]
        provider_customer_id=provider_customer_id,
        email=email,
    )
    session.add(c)
    await session.flush()
    return c


class TestCustomerUpsertOnCheckout:
    """create_checkout upserts a PaymentCustomer when user_id is provided."""

    @pytest.mark.asyncio
    async def test_creates_customer_on_first_authenticated_checkout(
        self, async_db_session: AsyncSession
    ) -> None:
        """First checkout for a user creates Stripe customer + DB row."""
        from sqlmodel import select

        service = PaymentService(async_db_session)
        service.provider.create_customer = AsyncMock(
            return_value=CustomerResult(
                provider_customer_id="cus_new_123",
                email="alice@example.com",
            )
        )
        service.provider.create_checkout = AsyncMock(
            return_value=CheckoutResult(
                session_id="cs_new",
                checkout_url="https://stub",
                provider_key=ProviderKeys.STRIPE,
            )
        )

        await service.create_checkout(
            price_id="price_x",
            quantity=1,
            mode="payment",
            success_url="https://s",
            cancel_url="https://c",
            user_id=42,
            user_email="alice@example.com",
        )

        # Stripe customer creation happened exactly once
        service.provider.create_customer.assert_awaited_once_with(
            email="alice@example.com"
        )
        # Checkout received the new provider_customer_id
        assert (
            service.provider.create_checkout.call_args.kwargs["customer_id"]
            == "cus_new_123"
        )
        # A PaymentCustomer row exists for this user
        rows = (
            await async_db_session.exec(
                select(PaymentCustomer).where(PaymentCustomer.user_id == 42)
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].provider_customer_id == "cus_new_123"
        assert rows[0].email == "alice@example.com"

    @pytest.mark.asyncio
    async def test_reuses_existing_customer(
        self, async_db_session: AsyncSession
    ) -> None:
        """Second checkout for same user reuses the existing customer row."""
        provider = await _seed_provider(async_db_session)
        await _seed_customer(
            async_db_session,
            provider,
            user_id=7,
            provider_customer_id="cus_existing",
            email="bob@example.com",
        )

        service = PaymentService(async_db_session)
        service.provider.create_customer = AsyncMock()
        service.provider.create_checkout = AsyncMock(
            return_value=CheckoutResult(
                session_id="cs_existing",
                checkout_url="https://stub",
                provider_key=ProviderKeys.STRIPE,
            )
        )

        await service.create_checkout(
            price_id="price_x",
            quantity=1,
            mode="payment",
            success_url="https://s",
            cancel_url="https://c",
            user_id=7,
            user_email="bob@example.com",
        )

        # Did NOT call create_customer — reused
        service.provider.create_customer.assert_not_awaited()
        assert (
            service.provider.create_checkout.call_args.kwargs["customer_id"]
            == "cus_existing"
        )

    @pytest.mark.asyncio
    async def test_anonymous_checkout_skips_customer_creation(
        self, async_db_session: AsyncSession
    ) -> None:
        """No user_id -> no customer creation, None forwarded to provider."""
        await _seed_provider(async_db_session)
        service = PaymentService(async_db_session)
        service.provider.create_customer = AsyncMock()
        service.provider.create_checkout = AsyncMock(
            return_value=CheckoutResult(
                session_id="cs_anon",
                checkout_url="https://stub",
                provider_key=ProviderKeys.STRIPE,
            )
        )

        await service.create_checkout(
            price_id="price_x",
            quantity=1,
            mode="payment",
            success_url="https://s",
            cancel_url="https://c",
            user_id=None,
        )

        service.provider.create_customer.assert_not_awaited()
        assert service.provider.create_checkout.call_args.kwargs["customer_id"] is None

    @pytest.mark.asyncio
    async def test_user_id_without_email_skips_provider_create(
        self, async_db_session: AsyncSession
    ) -> None:
        """user_id alone (no email) doesn't call provider.create_customer.

        Without an email we can't create a provider-side customer; Stripe
        will make one at checkout from whatever the user types.
        """
        await _seed_provider(async_db_session)
        service = PaymentService(async_db_session)
        service.provider.create_customer = AsyncMock()
        service.provider.create_checkout = AsyncMock(
            return_value=CheckoutResult(
                session_id="cs_nocust",
                checkout_url="https://stub",
                provider_key=ProviderKeys.STRIPE,
            )
        )

        await service.create_checkout(
            price_id="price_x",
            quantity=1,
            mode="payment",
            success_url="https://s",
            cancel_url="https://c",
            user_id=99,
            user_email=None,
        )

        service.provider.create_customer.assert_not_awaited()
        assert service.provider.create_checkout.call_args.kwargs["customer_id"] is None


# ---------------------------------------------------------------------------
# Tests: user_id scoping on queries
# ---------------------------------------------------------------------------


async def _make_txn_for(
    session: AsyncSession,
    provider: PaymentProvider,
    customer: PaymentCustomer | None,
    pid: str,
    amount: int = 1000,
) -> PaymentTransaction:
    """Seed a transaction with an optional customer."""
    txn = PaymentTransaction(
        provider_id=provider.id,  # type: ignore[arg-type]
        customer_id=customer.id if customer else None,  # type: ignore[arg-type]
        provider_transaction_id=pid,
        type=TransactionType.CHARGE,
        status=TransactionStatus.SUCCEEDED,
        amount=amount,
        currency="usd",
    )
    session.add(txn)
    await session.flush()
    return txn


class TestTransactionScoping:
    """get_transactions / get_transaction_by_id with user_id filter."""

    @pytest.mark.asyncio
    async def test_get_transactions_scopes_to_user(
        self, async_db_session: AsyncSession
    ) -> None:
        provider = await _seed_provider(async_db_session)
        alice = await _seed_customer(
            async_db_session, provider, user_id=1, provider_customer_id="cus_a"
        )
        bob = await _seed_customer(
            async_db_session, provider, user_id=2, provider_customer_id="cus_b"
        )
        await _make_txn_for(async_db_session, provider, alice, "pi_a1")
        await _make_txn_for(async_db_session, provider, alice, "pi_a2")
        await _make_txn_for(async_db_session, provider, bob, "pi_b1")
        await _make_txn_for(async_db_session, provider, None, "pi_anon")

        service = PaymentService(async_db_session)

        alice_txns, alice_total = await service.get_transactions(user_id=1)
        assert alice_total == 2
        pids = {t.provider_transaction_id for t in alice_txns}
        assert pids == {"pi_a1", "pi_a2"}

        bob_txns, bob_total = await service.get_transactions(user_id=2)
        assert bob_total == 1

        # Unscoped returns all four
        all_txns, all_total = await service.get_transactions()
        assert all_total == 4

    @pytest.mark.asyncio
    async def test_get_transactions_user_with_no_customer(
        self, async_db_session: AsyncSession
    ) -> None:
        """User with no PaymentCustomer gets an empty list, not everyone's txns."""
        provider = await _seed_provider(async_db_session)
        await _make_txn_for(async_db_session, provider, None, "pi_anon")
        service = PaymentService(async_db_session)

        txns, total = await service.get_transactions(user_id=42)
        assert total == 0
        assert txns == []

    @pytest.mark.asyncio
    async def test_get_transaction_by_id_scopes_to_user(
        self, async_db_session: AsyncSession
    ) -> None:
        provider = await _seed_provider(async_db_session)
        alice = await _seed_customer(
            async_db_session, provider, user_id=1, provider_customer_id="cus_a"
        )
        bob = await _seed_customer(
            async_db_session, provider, user_id=2, provider_customer_id="cus_b"
        )
        alice_txn = await _make_txn_for(async_db_session, provider, alice, "pi_a")
        bob_txn = await _make_txn_for(async_db_session, provider, bob, "pi_b")

        service = PaymentService(async_db_session)

        # Alice can see her own
        assert (
            await service.get_transaction_by_id(alice_txn.id, user_id=1)  # type: ignore[arg-type]
            is not None
        )
        # Alice cannot see Bob's
        assert (
            await service.get_transaction_by_id(bob_txn.id, user_id=1)  # type: ignore[arg-type]
            is None
        )
        # Unscoped call sees both
        assert (
            await service.get_transaction_by_id(bob_txn.id)  # type: ignore[arg-type]
            is not None
        )


class TestSubscriptionScoping:
    """get_subscriptions with user_id filter."""

    @pytest.mark.asyncio
    async def test_scopes_to_user(self, async_db_session: AsyncSession) -> None:
        provider = await _seed_provider(async_db_session)
        alice = await _seed_customer(
            async_db_session, provider, user_id=1, provider_customer_id="cus_a"
        )
        bob = await _seed_customer(
            async_db_session, provider, user_id=2, provider_customer_id="cus_b"
        )
        now = datetime.now(UTC).replace(tzinfo=None)

        # Alice has one active + one canceled sub - the partial unique
        # index on (customer_id) WHERE status IN ('active','trialing')
        # rejects two active rows per customer.
        for cust, pid, status in (
            (alice, "sub_a1", SubscriptionStatus.ACTIVE),
            (alice, "sub_a2", SubscriptionStatus.CANCELED),
            (bob, "sub_b1", SubscriptionStatus.ACTIVE),
        ):
            async_db_session.add(
                PaymentSubscription(
                    customer_id=cust.id,  # type: ignore[arg-type]
                    provider_subscription_id=pid,
                    plan_name="Pro",
                    status=status,
                    current_period_start=now,
                    current_period_end=now,
                )
            )
        await async_db_session.flush()

        service = PaymentService(async_db_session)
        alice_subs = await service.get_subscriptions(user_id=1)
        assert len(alice_subs) == 2
        bob_subs = await service.get_subscriptions(user_id=2)
        assert len(bob_subs) == 1
        assert len(await service.get_subscriptions()) == 3


class TestDisputeScoping:
    """get_disputes / get_dispute_by_id with user_id filter."""

    @pytest.mark.asyncio
    async def test_scopes_through_transaction_ownership(
        self, async_db_session: AsyncSession
    ) -> None:
        provider = await _seed_provider(async_db_session)
        alice = await _seed_customer(
            async_db_session, provider, user_id=1, provider_customer_id="cus_a"
        )
        bob = await _seed_customer(
            async_db_session, provider, user_id=2, provider_customer_id="cus_b"
        )
        alice_txn = await _make_txn_for(async_db_session, provider, alice, "pi_a")
        bob_txn = await _make_txn_for(async_db_session, provider, bob, "pi_b")

        for txn, dp_id in (
            (alice_txn, "dp_a1"),
            (alice_txn, "dp_a2"),
            (bob_txn, "dp_b1"),
        ):
            async_db_session.add(
                PaymentDispute(
                    transaction_id=txn.id,  # type: ignore[arg-type]
                    provider_dispute_id=dp_id,
                    status=DisputeStatus.NEEDS_RESPONSE,
                    amount=1000,
                    currency="usd",
                )
            )
        await async_db_session.flush()

        service = PaymentService(async_db_session)
        alice_disputes = await service.get_disputes(user_id=1)
        assert len(alice_disputes) == 2
        bob_disputes = await service.get_disputes(user_id=2)
        assert len(bob_disputes) == 1
        assert len(await service.get_disputes()) == 3

    @pytest.mark.asyncio
    async def test_get_dispute_by_id_scopes(
        self, async_db_session: AsyncSession
    ) -> None:
        provider = await _seed_provider(async_db_session)
        alice = await _seed_customer(
            async_db_session, provider, user_id=1, provider_customer_id="cus_a"
        )
        bob = await _seed_customer(
            async_db_session, provider, user_id=2, provider_customer_id="cus_b"
        )
        alice_txn = await _make_txn_for(async_db_session, provider, alice, "pi_a")
        bob_txn = await _make_txn_for(async_db_session, provider, bob, "pi_b")

        alice_dp = PaymentDispute(
            transaction_id=alice_txn.id,  # type: ignore[arg-type]
            provider_dispute_id="dp_alice",
            status=DisputeStatus.NEEDS_RESPONSE,
            amount=1000,
            currency="usd",
        )
        bob_dp = PaymentDispute(
            transaction_id=bob_txn.id,  # type: ignore[arg-type]
            provider_dispute_id="dp_bob",
            status=DisputeStatus.NEEDS_RESPONSE,
            amount=1000,
            currency="usd",
        )
        async_db_session.add(alice_dp)
        async_db_session.add(bob_dp)
        await async_db_session.flush()

        service = PaymentService(async_db_session)
        assert (
            await service.get_dispute_by_id(alice_dp.id, user_id=1)  # type: ignore[arg-type]
            is not None
        )
        assert (
            await service.get_dispute_by_id(bob_dp.id, user_id=1)  # type: ignore[arg-type]
            is None
        )
        # Unscoped sees both
        assert await service.get_dispute_by_id(bob_dp.id) is not None  # type: ignore[arg-type]


class TestRefundAndCancelScoping:
    """refund_transaction and cancel_subscription enforce user_id ownership."""

    @pytest.mark.asyncio
    async def test_refund_refuses_other_users_transaction(
        self, async_db_session: AsyncSession
    ) -> None:
        provider = await _seed_provider(async_db_session)
        alice = await _seed_customer(
            async_db_session, provider, user_id=1, provider_customer_id="cus_a"
        )
        bob_txn = PaymentTransaction(
            provider_id=provider.id,  # type: ignore[arg-type]
            customer_id=None,  # bob has no customer row yet
            provider_transaction_id="pi_bob",
            type=TransactionType.CHARGE,
            status=TransactionStatus.SUCCEEDED,
            amount=5000,
            currency="usd",
        )
        async_db_session.add(bob_txn)
        await async_db_session.flush()

        service = PaymentService(async_db_session)
        service.provider.refund = AsyncMock()

        # Alice tries to refund bob's transaction → None, no provider call
        result = await service.refund_transaction(
            transaction_id=bob_txn.id,  # type: ignore[arg-type]
            user_id=alice.user_id,
        )
        assert result is None
        service.provider.refund.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_refund_allows_own_transaction(
        self, async_db_session: AsyncSession
    ) -> None:
        provider = await _seed_provider(async_db_session)
        alice = await _seed_customer(
            async_db_session, provider, user_id=1, provider_customer_id="cus_a"
        )
        alice_txn = await _make_txn_for(
            async_db_session, provider, alice, "pi_alice", amount=5000
        )

        service = PaymentService(async_db_session)
        service.provider.refund = AsyncMock(
            return_value=RefundResult(
                provider_refund_id="re_alice",
                status="succeeded",
                amount=5000,
                currency="usd",
            )
        )

        result = await service.refund_transaction(
            transaction_id=alice_txn.id,  # type: ignore[arg-type]
            user_id=alice.user_id,
        )
        assert result is not None
        assert result.type == TransactionType.REFUND

    @pytest.mark.asyncio
    async def test_cancel_subscription_refuses_other_user(
        self, async_db_session: AsyncSession
    ) -> None:
        provider = await _seed_provider(async_db_session)
        alice = await _seed_customer(
            async_db_session, provider, user_id=1, provider_customer_id="cus_a"
        )
        bob = await _seed_customer(
            async_db_session, provider, user_id=2, provider_customer_id="cus_b"
        )
        now = datetime.now(UTC).replace(tzinfo=None)
        bob_sub = PaymentSubscription(
            customer_id=bob.id,  # type: ignore[arg-type]
            provider_subscription_id="sub_bob",
            plan_name="Pro",
            status=SubscriptionStatus.ACTIVE,
            current_period_start=now,
            current_period_end=now,
        )
        async_db_session.add(bob_sub)
        await async_db_session.flush()

        service = PaymentService(async_db_session)
        # Alice tries to cancel bob's subscription
        result = await service.cancel_subscription(
            bob_sub.id,  # type: ignore[arg-type]
            user_id=alice.user_id,
        )
        assert result is None
        # Bob's sub is untouched
        await async_db_session.refresh(bob_sub)
        assert bob_sub.cancel_at_period_end is False


# ---------------------------------------------------------------------------
# Tests: get_revenue_timeseries
# ---------------------------------------------------------------------------


class TestGetRevenueTimeseries:
    """Daily revenue series is dense, zero-filled, succeeded-charges only."""

    @pytest.mark.asyncio
    async def test_empty_db_returns_zero_filled_series(
        self, async_db_session: AsyncSession
    ) -> None:
        service = PaymentService(async_db_session)
        series = await service.get_revenue_timeseries(days=7)

        assert len(series) == 7
        assert all(p["amount_cents"] == 0 for p in series)
        # Dates are consecutive and end on today (UTC).
        dates = [p["date"] for p in series]
        assert dates == sorted(dates)
        today = datetime.now(UTC).date().isoformat()
        assert series[-1]["date"] == today

    @pytest.mark.asyncio
    async def test_excludes_refunds_failures_and_older_rows(
        self, async_db_session: AsyncSession
    ) -> None:
        provider = await _seed_provider(async_db_session)
        today_dt = datetime.now(UTC).replace(tzinfo=None)

        # Succeeded charge today — counts.
        today_charge = PaymentTransaction(
            provider_id=provider.id,  # type: ignore[arg-type]
            provider_transaction_id="pi_today_ok",
            type=TransactionType.CHARGE,
            status=TransactionStatus.SUCCEEDED,
            amount=5000,
            currency="usd",
            created_at=today_dt,
        )
        # Refund today — excluded.
        refund_today = PaymentTransaction(
            provider_id=provider.id,  # type: ignore[arg-type]
            provider_transaction_id="re_today",
            type=TransactionType.REFUND,
            status=TransactionStatus.REFUNDED,
            amount=1000,
            currency="usd",
            created_at=today_dt,
        )
        # Failed charge today — excluded.
        failed_today = PaymentTransaction(
            provider_id=provider.id,  # type: ignore[arg-type]
            provider_transaction_id="pi_today_fail",
            type=TransactionType.CHARGE,
            status=TransactionStatus.FAILED,
            amount=2000,
            currency="usd",
            created_at=today_dt,
        )
        # Succeeded charge 60 days ago — outside 7-day window.
        old_charge = PaymentTransaction(
            provider_id=provider.id,  # type: ignore[arg-type]
            provider_transaction_id="pi_old_ok",
            type=TransactionType.CHARGE,
            status=TransactionStatus.SUCCEEDED,
            amount=9999,
            currency="usd",
            created_at=today_dt - timedelta(days=60),
        )
        for t in (today_charge, refund_today, failed_today, old_charge):
            async_db_session.add(t)
        await async_db_session.flush()

        service = PaymentService(async_db_session)
        series = await service.get_revenue_timeseries(days=7)

        total = sum(p["amount_cents"] for p in series)
        assert total == 5000  # only today_charge contributes
        # The ``today`` slot specifically carries the full amount.
        today_key = datetime.now(UTC).date().isoformat()
        today_row = next(p for p in series if p["date"] == today_key)
        assert today_row["amount_cents"] == 5000

    @pytest.mark.asyncio
    async def test_days_lower_bound_clamped_to_one(
        self, async_db_session: AsyncSession
    ) -> None:
        service = PaymentService(async_db_session)
        series = await service.get_revenue_timeseries(days=0)
        assert len(series) == 1
