"""
Base payment provider interface.

All payment providers implement this contract. The pattern mirrors
the insights collector base class — each provider handles one external
payment service (Stripe, PayPal, etc.).
"""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.services.payment.constants import PriceInterval, PriceType


class CheckoutResult(BaseModel):
    """Result of creating a checkout session."""

    session_id: str
    checkout_url: str
    provider_key: str


class TransactionResult(BaseModel):
    """Result of fetching a transaction from the provider."""

    provider_transaction_id: str
    status: str
    amount: int
    currency: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RefundResult(BaseModel):
    """Result of processing a refund."""

    provider_refund_id: str
    status: str
    amount: int
    currency: str


class CustomerResult(BaseModel):
    """Result of creating/fetching a customer."""

    provider_customer_id: str
    email: str | None = None


class PlanChangeResult(BaseModel):
    """Result of changing a subscription's plan in place.

    Returned by ``change_subscription_plan``. Carries the updated
    subscription's status so the caller can confirm the provider
    accepted the modification before tagging emails, plus the
    prorated amount so we can surface "we charged $X today" copy
    if the proration_behavior issues an immediate invoice.
    """

    provider_subscription_id: str
    status: str
    new_price_id: str
    proration_amount_cents: int = 0


class WebhookEvent(BaseModel):
    """Parsed and verified webhook event."""

    event_type: str
    provider_key: str
    data: dict[str, Any] = Field(default_factory=dict)


class ProviderHealth(BaseModel):
    """Health check result for a payment provider."""

    provider_key: str
    healthy: bool
    is_test_mode: bool = True
    message: str = ""
    api_version: str | None = None


class CatalogEntry(BaseModel):
    """One row in the provider's sellable catalog, shaped for the dropdown.

    Not a mirror of Stripe's raw Price/Product objects — only the fields the
    Actions tab needs to render a pickable item. Derived fresh each poll,
    never stored.
    """

    price_id: str
    product_name: str
    amount: int  # smallest currency unit
    currency: str
    # One of ``PriceInterval.ALL`` for recurring, ``None`` for one-time.
    interval: str | None = None
    # One of ``PriceType.ALL``.
    price_type: str = PriceType.ONE_TIME

    @field_validator("interval")
    @classmethod
    def _validate_interval(cls, v: str | None) -> str | None:
        if v is not None and v not in PriceInterval.ALL:
            raise ValueError(
                f"Invalid interval '{v}'. Must be one of: "
                f"{', '.join(sorted(PriceInterval.ALL))}"
            )
        return v

    @field_validator("price_type")
    @classmethod
    def _validate_price_type(cls, v: str) -> str:
        if v not in PriceType.ALL:
            raise ValueError(
                f"Invalid price_type '{v}'. Must be one of: "
                f"{', '.join(sorted(PriceType.ALL))}"
            )
        return v


class BasePaymentProvider(ABC):
    """Base class for all payment providers."""

    @property
    @abstractmethod
    def provider_key(self) -> str:
        """Unique identifier for this provider (e.g., 'stripe')."""
        ...

    @abstractmethod
    async def create_checkout(
        self,
        price_id: str,
        quantity: int,
        mode: str,
        success_url: str,
        cancel_url: str,
        customer_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        trial_period_days: int | None = None,
    ) -> CheckoutResult:
        """Create a checkout session. Returns a URL to redirect the user to.

        ``trial_period_days``: when set and ``mode == 'subscription'``,
        the provider starts the subscription in a trial state for N
        days. Ignored for one-shot ``payment`` mode.
        """
        ...

    @abstractmethod
    async def get_transaction(self, provider_transaction_id: str) -> TransactionResult:
        """Fetch transaction details from the provider."""
        ...

    @abstractmethod
    async def refund(
        self,
        provider_transaction_id: str,
        amount: int | None = None,
        reason: str | None = None,
    ) -> RefundResult:
        """Refund a transaction (full or partial).

        ``reason`` is one of the values in ``constants.RefundReason``.
        Providers must map it to their own accepted enum (or drop values
        the provider's API doesn't accept) to avoid upstream validation
        errors.
        """
        ...

    @abstractmethod
    async def change_subscription_plan(
        self,
        provider_subscription_id: str,
        new_price_id: str,
        *,
        proration_behavior: str = "create_prorations",
    ) -> PlanChangeResult:
        """Swap the price on an existing subscription in place.

        Implements the real plan-change flow: the customer's existing
        subscription stays the same row in the provider, but its line
        item gets a new price. Stripe (and any reasonable provider)
        handles proration automatically — billing the difference now
        and recalculating the renewal — so the customer doesn't end
        up with two parallel subscriptions on the same product.

        ``proration_behavior`` follows Stripe's enum:
        ``"create_prorations"`` (default — bill the difference on the
        upcoming invoice), ``"always_invoice"`` (issue a separate
        prorated invoice immediately), or ``"none"`` (no charge —
        the switch takes effect at next renewal).
        """
        ...

    @abstractmethod
    async def create_customer(
        self, email: str, name: str | None = None
    ) -> CustomerResult:
        """Create a customer record in the provider."""
        ...

    @abstractmethod
    async def verify_webhook(self, payload: bytes, signature: str) -> WebhookEvent:
        """Verify webhook signature and parse the event."""
        ...

    @abstractmethod
    async def health_check(self) -> ProviderHealth:
        """Check provider API connectivity."""
        ...

    @abstractmethod
    async def list_catalog(self) -> list[CatalogEntry]:
        """Return the provider's active sellable catalog.

        Concrete providers join their own "product" and "price" concepts
        and emit a flat list of ``CatalogEntry`` rows suitable for a
        checkout-creation dropdown. Inactive / archived prices should be
        filtered out here, not in the caller.
        """
        ...
