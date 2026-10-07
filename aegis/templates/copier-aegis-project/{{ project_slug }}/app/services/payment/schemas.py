"""
Pydantic schemas for payment API requests and responses.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.formatting import is_local_path

from .constants import RefundReason


def _validate_redirect_url(value: str | None) -> str | None:
    """Reject Stripe redirect URLs that point off our own domain.

    Client-supplied ``success_url`` / ``cancel_url`` / ``return_url`` get
    forwarded to Stripe verbatim and used as the post-checkout / post-
    portal redirect target. Without this guard an attacker can craft
    ``/checkout`` with ``success_url=https://evil.com/?session_id=
    {CHECKOUT_SESSION_ID}`` and use the Stripe-hosted page as a phishing
    relay that leaks the session ID. We constrain redirect targets to
    the deploy's public host (relative paths are also allowed because
    they resolve against ``PUBLIC_BASE_URL`` server-side).
    """
    if value is None or value == "":
        return value
    # Lazy import — keeps the schemas module side-effect free for tests
    # that import without a fully-wired settings object.
    from app.core.config import settings

    # A root-relative path resolves against PUBLIC_BASE_URL server-side, so
    # it has no host to spoof, unless a browser would read it as one
    # (``//host``, ``/\\host``): ``is_local_path`` refuses those.
    if value.startswith("/"):
        if not is_local_path(value):
            raise ValueError("Redirect URL must stay on this site.")
        return value

    parsed = urlparse(value)
    allowed_host = urlparse(settings.PUBLIC_BASE_URL).hostname
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Redirect URL must be absolute http(s) or root-relative.")
    # Fail closed if the deploy is misconfigured: without a hostname on
    # ``PUBLIC_BASE_URL`` we can't compare anything, and silently
    # accepting any host would defeat the validator entirely.
    if not allowed_host:
        raise ValueError(
            "PUBLIC_BASE_URL is misconfigured (no hostname); cannot "
            "validate absolute redirect URL."
        )
    if parsed.hostname != allowed_host:
        raise ValueError(
            f"Redirect URL host '{parsed.hostname}' does not match the "
            f"deploy's public host. Use a relative path or a URL on "
            f"'{allowed_host}'."
        )
    return value

# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CheckoutRequest(BaseModel):
    """Request to create a checkout session."""

    price_id: str = Field(description="Stripe Price ID (e.g., price_xxx)")
    quantity: int = Field(default=1, ge=1)
    mode: str = Field(default="payment", description="payment or subscription")
    success_url: str | None = Field(
        default=None,
        description=(
            "URL to redirect after success. Falls back to PAYMENT_SUCCESS_URL "
            "setting when omitted."
        ),
    )
    cancel_url: str | None = Field(
        default=None,
        description=(
            "URL to redirect on cancel. Falls back to PAYMENT_CANCEL_URL "
            "setting when omitted."
        ),
    )

    @field_validator("success_url", "cancel_url")
    @classmethod
    def _validate_urls(cls, v: str | None) -> str | None:
        return _validate_redirect_url(v)

    @model_validator(mode="after")
    def _enforce_subscription_quantity(self) -> "CheckoutRequest":
        """Subscription checkouts must have ``quantity == 1``.

        Stripe technically allows ``quantity > 1`` on subscriptions for
        per-seat / per-unit pricing, but that's a deliberate product
        design (Teams plans, license counts) — not something a generic
        app should permit by default. For the common case of "one
        customer subscribes to one plan," allowing quantity > 1 just
        produces confusing inflated amounts. Apps that genuinely want
        seat-based pricing should remove this validator locally.
        """
        if self.mode == "subscription" and self.quantity != 1:
            raise ValueError(
                "Subscription checkouts must have quantity=1. For "
                "per-seat pricing, use a quantity-aware price in Stripe "
                "and remove this guard in your CheckoutRequest."
            )
        return self


class RefundRequest(BaseModel):
    """Request to refund a transaction."""

    amount: int | None = Field(
        default=None,
        ge=1,
        description="Amount to refund in cents (None for full refund)",
    )
    reason: str = Field(
        default=RefundReason.DEFAULT,
        description=(
            "Reason code. One of: duplicate, fraudulent, "
            "requested_by_customer, other. Values other than Stripe's "
            "accepted enum (duplicate/fraudulent/requested_by_customer) "
            "are stored locally but not sent to Stripe."
        ),
    )

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, v: str) -> str:
        if v not in RefundReason.ALL:
            raise ValueError(
                f"Invalid reason '{v}'. Must be one of: {', '.join(RefundReason.ALL)}"
            )
        return v


class ChangePlanRequest(BaseModel):
    """Request to swap the price on an existing subscription.

    Mirrors Stripe's ``Subscription.modify`` semantics: the same row
    stays in place, only the line-item price changes, and proration
    is handled per the requested behavior. Validates the
    ``proration_behavior`` enum at the schema boundary so the API
    returns a 422 (Pydantic) instead of bubbling Stripe's wording.
    """

    new_price_id: str = Field(
        description="Stripe Price ID to switch into (e.g., price_xxx)",
    )
    proration_behavior: str | None = Field(
        default=None,
        description=(
            "How Stripe should bill the price difference. "
            "``create_prorations`` (default): add proration line items "
            "to the upcoming invoice. ``always_invoice``: issue a "
            "separate invoice immediately for the prorated delta. "
            "``none``: switch takes effect at next renewal, no "
            "proration. ``None`` defers to the service's default."
        ),
    )

    @field_validator("proration_behavior")
    @classmethod
    def _validate_proration_behavior(cls, v: str | None) -> str | None:
        if v is None:
            return None
        allowed = {"create_prorations", "always_invoice", "none"}
        if v not in allowed:
            raise ValueError(
                f"Invalid proration_behavior {v!r}. "
                f"Must be one of: {', '.join(sorted(allowed))}"
            )
        return v


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class CheckoutResponse(BaseModel):
    """Response from creating a checkout session."""

    session_id: str
    checkout_url: str


class TransactionResponse(BaseModel):
    """Single transaction in API responses."""

    id: int
    provider_transaction_id: str
    type: str
    status: str
    amount: int
    currency: str
    description: str | None = None
    created_at: datetime


class TransactionListResponse(BaseModel):
    """Paginated list of transactions."""

    transactions: list[TransactionResponse]
    total: int
    page: int
    page_size: int


class SubscriptionResponse(BaseModel):
    """Single subscription in API responses.

    ``display_name`` is the marketing-friendly label for the row. The
    template ships a pass-through default that returns ``plan_name``
    verbatim, so callers always have *something* user-facing to render.
    Downstream apps with their own plan-slug shim (e.g. mapping Stripe
    product names like "Aegis Pulse" -> "Pro") can wrap or override
    ``from_row`` to inject their resolution.
    """

    id: int
    provider_subscription_id: str
    plan_name: str
    display_name: str
    status: str
    current_period_start: datetime
    current_period_end: datetime
    cancel_at_period_end: bool

    @classmethod
    def from_row(cls, sub: object) -> SubscriptionResponse:
        """Build a response from a ``PaymentSubscription`` ORM row.

        Centralises field mapping so every endpoint that serialises a
        subscription gets the same shape. Pulse-style apps with a
        ``plan_name`` -> ``display_name`` shim override this classmethod
        in their own subclass; the template default is the safe
        pass-through.
        """
        plan_name = sub.plan_name  # type: ignore[attr-defined]
        return cls(
            id=sub.id,  # type: ignore[attr-defined,arg-type]
            provider_subscription_id=sub.provider_subscription_id,  # type: ignore[attr-defined]
            plan_name=plan_name,
            display_name=plan_name or "",
            status=sub.status,  # type: ignore[attr-defined]
            current_period_start=sub.current_period_start,  # type: ignore[attr-defined]
            current_period_end=sub.current_period_end,  # type: ignore[attr-defined]
            cancel_at_period_end=sub.cancel_at_period_end,  # type: ignore[attr-defined]
        )


class SubscriptionListResponse(BaseModel):
    """List of subscriptions."""

    subscriptions: list[SubscriptionResponse]
    total: int


class PaymentStatusResponse(BaseModel):
    """Payment service status overview."""

    provider: str
    enabled: bool
    is_test_mode: bool
    total_transactions: int
    total_revenue_cents: int
    active_subscriptions: int
    currency: str = "usd"


class DisputeResponse(BaseModel):
    """A single dispute or early fraud warning."""

    id: int
    transaction_id: int
    provider_dispute_id: str
    status: str
    reason: str | None = None
    amount: int
    currency: str
    evidence_due_by: datetime | None = None
    event_type: str | None = None
    created_at: datetime
    updated_at: datetime


class DisputeListResponse(BaseModel):
    """List of disputes."""

    disputes: list[DisputeResponse]
    total: int


class CatalogEntryResponse(BaseModel):
    """One entry in the provider catalog."""

    price_id: str
    product_name: str
    amount: int
    currency: str
    interval: str | None = None
    price_type: str


class CatalogResponse(BaseModel):
    """Active catalog entries from the payment provider."""

    entries: list[CatalogEntryResponse]
    total: int


class RevenueTimeseriesPoint(BaseModel):
    """One day of succeeded-charge revenue."""

    date: str  # ISO date (YYYY-MM-DD)
    amount_cents: int


class RevenueTimeseriesResponse(BaseModel):
    """Daily revenue series, dense across the requested window."""

    points: list[RevenueTimeseriesPoint]
    days: int
