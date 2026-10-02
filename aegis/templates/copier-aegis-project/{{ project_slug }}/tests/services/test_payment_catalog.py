"""
Tests for the payment catalog cache, CatalogEntry validation, and
StripeProvider.list_catalog mapping.

Mirrors the shape of ``test_payment_service.py`` — no live Stripe calls;
we mock ``stripe.Price.list`` at the SDK boundary.
"""

from __future__ import annotations

from collections.abc import Generator
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.payment import catalog as catalog_module
from app.services.payment.catalog import (
    _CACHE_TTL_SECONDS,
    get_catalog,
    invalidate_catalog_cache,
)
from app.services.payment.constants import PriceInterval, PriceType
from app.services.payment.providers.base import CatalogEntry

# ---------------------------------------------------------------------------
# CatalogEntry edge validation
# ---------------------------------------------------------------------------


class TestCatalogEntryValidation:
    """CatalogEntry enforces the Stripe interval/type enums at the boundary."""

    def test_accepts_known_interval(self) -> None:
        entry = CatalogEntry(
            price_id="price_1",
            product_name="Pro",
            amount=1000,
            currency="usd",
            interval=PriceInterval.MONTH,
            price_type=PriceType.RECURRING,
        )
        assert entry.interval == "month"

    def test_rejects_unknown_interval(self) -> None:
        with pytest.raises(ValueError, match="Invalid interval"):
            CatalogEntry(
                price_id="price_1",
                product_name="Pro",
                amount=1000,
                currency="usd",
                interval="fortnight",  # not a Stripe value
            )

    def test_allows_null_interval_for_one_time(self) -> None:
        entry = CatalogEntry(
            price_id="price_1",
            product_name="Lifetime",
            amount=50000,
            currency="usd",
            interval=None,
            price_type=PriceType.ONE_TIME,
        )
        assert entry.interval is None
        assert entry.price_type == "one_time"

    def test_rejects_unknown_price_type(self) -> None:
        with pytest.raises(ValueError, match="Invalid price_type"):
            CatalogEntry(
                price_id="price_1",
                product_name="Pro",
                amount=1000,
                currency="usd",
                price_type="installment",
            )


# ---------------------------------------------------------------------------
# Catalog cache behaviour
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_cache() -> Generator[None]:
    """Ensure every test starts with an empty cache."""
    invalidate_catalog_cache()
    yield
    invalidate_catalog_cache()


class TestCatalogCache:
    """get_catalog respects its TTL and exposes an invalidation hook."""

    @pytest.mark.asyncio
    async def test_first_call_hits_provider_and_caches(self) -> None:
        sample = [
            CatalogEntry(
                price_id="price_1",
                product_name="Pro",
                amount=1000,
                currency="usd",
                interval="month",
                price_type="recurring",
            )
        ]
        service = SimpleNamespace(
            provider=SimpleNamespace(list_catalog=AsyncMock(return_value=sample))
        )

        first = await get_catalog(service)  # type: ignore[arg-type]
        second = await get_catalog(service)  # type: ignore[arg-type]

        assert first == sample
        assert second == sample
        service.provider.list_catalog.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invalidate_forces_refetch(self) -> None:
        sample_a = [
            CatalogEntry(
                price_id="price_a",
                product_name="Pro",
                amount=1000,
                currency="usd",
                interval="month",
                price_type="recurring",
            )
        ]
        sample_b = [
            CatalogEntry(
                price_id="price_b",
                product_name="Enterprise",
                amount=5000,
                currency="usd",
                interval="year",
                price_type="recurring",
            )
        ]
        service = SimpleNamespace(
            provider=SimpleNamespace(
                list_catalog=AsyncMock(side_effect=[sample_a, sample_b])
            )
        )

        assert await get_catalog(service) == sample_a  # type: ignore[arg-type]
        invalidate_catalog_cache()
        assert await get_catalog(service) == sample_b  # type: ignore[arg-type]
        assert service.provider.list_catalog.await_count == 2

    @pytest.mark.asyncio
    async def test_cache_expires_after_ttl(self) -> None:
        sample_a = [
            CatalogEntry(
                price_id="price_a",
                product_name="Pro",
                amount=1000,
                currency="usd",
            )
        ]
        sample_b = [
            CatalogEntry(
                price_id="price_b",
                product_name="Pro v2",
                amount=1500,
                currency="usd",
            )
        ]
        service = SimpleNamespace(
            provider=SimpleNamespace(
                list_catalog=AsyncMock(side_effect=[sample_a, sample_b])
            )
        )

        # Freeze then advance time past the TTL between calls.
        fake_now = [1000.0]

        def _monotonic() -> float:
            return fake_now[0]

        with patch.object(catalog_module.time, "monotonic", _monotonic):
            assert await get_catalog(service) == sample_a  # type: ignore[arg-type]
            fake_now[0] += _CACHE_TTL_SECONDS + 1.0
            assert await get_catalog(service) == sample_b  # type: ignore[arg-type]

        assert service.provider.list_catalog.await_count == 2


# ---------------------------------------------------------------------------
# StripeProvider.list_catalog mapping
# ---------------------------------------------------------------------------


def _fake_price(
    price_id: str,
    unit_amount: int | None,
    currency: str = "usd",
    interval: str | None = "month",
    product_name: str = "Pro",
    product_active: bool = True,
) -> SimpleNamespace:
    """Shape the test payload like the real Stripe SDK attr object."""
    product = SimpleNamespace(name=product_name, active=product_active)
    recurring = SimpleNamespace(interval=interval) if interval else None
    return SimpleNamespace(
        id=price_id,
        unit_amount=unit_amount,
        currency=currency,
        recurring=recurring,
        product=product,
    )


class TestStripeListCatalogMapping:
    """StripeProvider.list_catalog filters archived/tiered rows correctly."""

    @pytest.mark.asyncio
    async def test_empty_when_api_key_missing(self) -> None:
        from app.services.payment.providers.stripe import StripeProvider

        provider = StripeProvider()
        provider._api_key = AsyncMock(return_value="")  # type: ignore[method-assign]
        assert await provider.list_catalog() == []

    @pytest.mark.asyncio
    async def test_maps_recurring_and_one_time(self) -> None:
        from app.services.payment.providers import stripe as stripe_mod
        from app.services.payment.providers.stripe import StripeProvider

        provider = StripeProvider()
        provider._api_key = AsyncMock(return_value="sk_test_fake")  # type: ignore[method-assign]

        response = SimpleNamespace(
            data=[
                _fake_price("price_monthly", 1000, interval="month"),
                _fake_price(
                    "price_lifetime", 50000, interval=None, product_name="Lifetime"
                ),
            ]
        )
        with patch.object(
            stripe_mod.stripe.Price,
            "list_async",
            new=AsyncMock(return_value=response),
        ):
            entries = await provider.list_catalog()

        assert len(entries) == 2
        by_id = {e.price_id: e for e in entries}
        assert by_id["price_monthly"].interval == "month"
        assert by_id["price_monthly"].price_type == PriceType.RECURRING
        assert by_id["price_lifetime"].interval is None
        assert by_id["price_lifetime"].price_type == PriceType.ONE_TIME
        assert by_id["price_lifetime"].product_name == "Lifetime"

    @pytest.mark.asyncio
    async def test_skips_archived_products_and_tiered_prices(self) -> None:
        from app.services.payment.providers import stripe as stripe_mod
        from app.services.payment.providers.stripe import StripeProvider

        provider = StripeProvider()
        provider._api_key = AsyncMock(return_value="sk_test_fake")  # type: ignore[method-assign]

        response = SimpleNamespace(
            data=[
                _fake_price("price_live", 1000),
                _fake_price("price_archived_product", 1000, product_active=False),
                _fake_price("price_tiered", None),  # unit_amount missing
            ]
        )
        with patch.object(
            stripe_mod.stripe.Price,
            "list_async",
            new=AsyncMock(return_value=response),
        ):
            entries = await provider.list_catalog()

        assert [e.price_id for e in entries] == ["price_live"]
