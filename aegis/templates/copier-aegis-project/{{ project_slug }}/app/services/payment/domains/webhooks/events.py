"""Pydantic models for Stripe webhook event payloads.

Only the fields we actually consume in the ``webhooks`` mixins
are modelled. Every model uses ``extra="ignore"`` so Stripe's regular
field additions don't break us; renames or removals raise at the
model boundary where the failure is immediately visible (instead of
silently producing fallback values eight layers deep).

Shape verified against real ``GET /v1/events`` payloads under API
version ``2026-03-25.dahlia``. Two important shape quirks to know:

1. **Subscription items vs. invoice lines carry price info
   differently.** A subscription item has a full ``price`` dict
   (nickname, unit_amount, etc.). An invoice line has only
   ``pricing.price_details.{price, product}`` — id strings — and no
   nickname at all. The two events look superficially similar but
   require different models.

2. **``charge.refunded`` doesn't carry ``invoice``.** The
   ``charge.refunded`` event payload has ``payment_intent`` but not
   ``invoice``, even when the underlying charge was for a
   subscription invoice. The handler bridges that via
   ``payment_transaction.metadata.payment_intent`` (stashed at
   invoice-payment time).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

_TOLERANT = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Shared sub-types
# ---------------------------------------------------------------------------


class StripePeriod(BaseModel):
    """``{start, end}`` unix-timestamp pair used on invoice lines."""

    model_config = _TOLERANT
    start: int | None = None
    end: int | None = None


class StripeStatusTransitions(BaseModel):
    """``invoice.status_transitions`` — we only read ``paid_at``."""

    model_config = _TOLERANT
    paid_at: int | None = None


class StripeEvidenceDetails(BaseModel):
    """``dispute.evidence_details`` — we only read ``due_by``."""

    model_config = _TOLERANT
    due_by: int | None = None


# ---------------------------------------------------------------------------
# Subscription event — ``customer.subscription.{created,updated,deleted,trial_will_end}``
# ---------------------------------------------------------------------------


class StripeSubscriptionPrice(BaseModel):
    """The full ``price`` object as embedded on a subscription item.

    Subscription events embed prices in dict form (unlike invoice
    lines, which carry only id references — see ``StripeInvoicePriceDetails``).
    """

    model_config = _TOLERANT
    id: str | None = None
    nickname: str | None = None
    # Stripe sometimes returns ``product`` as a bare id string, other
    # times as an expanded dict (with ``name``). Both are accepted.
    product: str | dict[str, object] | None = None
    unit_amount: int | None = None
    currency: str | None = None


class StripeSubscriptionItem(BaseModel):
    model_config = _TOLERANT
    # In the 2025-* API versions Stripe moved the period from the
    # top-level subscription onto each item. The top-level fields
    # still exist for backward compatibility on older payloads.
    current_period_start: int | None = None
    current_period_end: int | None = None
    price: StripeSubscriptionPrice | None = None


class _StripeSubscriptionItemsContainer(BaseModel):
    model_config = _TOLERANT
    data: list[StripeSubscriptionItem] = Field(default_factory=list)


class StripeSubscription(BaseModel):
    model_config = _TOLERANT
    id: str
    customer: str | None = None
    status: str | None = None
    cancel_at_period_end: bool = False
    # Pre-2025 top-level period fields; per-item is preferred.
    current_period_start: int | None = None
    current_period_end: int | None = None
    trial_end: int | None = None
    items: _StripeSubscriptionItemsContainer = Field(
        default_factory=_StripeSubscriptionItemsContainer
    )

    @property
    def first_item(self) -> StripeSubscriptionItem | None:
        """Convenience: most subs we handle are single-item."""
        return self.items.data[0] if self.items.data else None


# ---------------------------------------------------------------------------
# Invoice event — ``invoice.{paid,payment_succeeded,payment_failed}``
# ---------------------------------------------------------------------------


class StripeInvoicePriceDetails(BaseModel):
    """``pricing.price_details`` on an invoice line — id strings only.

    Unlike the subscription-item ``price`` dict, the invoice line
    payload carries no nickname / unit_amount inline. To get the
    product's display name, callers must round-trip ``GET /v1/products/<id>``
    (see ``PaymentService._resolve_product_name`` if you ship that
    helper, or accept the price id as the fallback).
    """

    model_config = _TOLERANT
    price: str | None = None
    product: str | None = None


class StripeInvoiceLinePricing(BaseModel):
    model_config = _TOLERANT
    price_details: StripeInvoicePriceDetails | None = None
    # Stripe returns this as a *decimal string* (e.g. ``"999"``) on
    # invoice lines, vs. an int on subscription prices. Kept here as
    # the raw string; callers cast as needed.
    unit_amount_decimal: str | None = None


class StripeInvoiceLine(BaseModel):
    model_config = _TOLERANT
    pricing: StripeInvoiceLinePricing | None = None
    period: StripePeriod | None = None


class _StripeInvoiceLinesContainer(BaseModel):
    model_config = _TOLERANT
    data: list[StripeInvoiceLine] = Field(default_factory=list)


class StripeInvoice(BaseModel):
    model_config = _TOLERANT
    id: str
    number: str | None = None
    amount_paid: int | None = None
    amount_due: int | None = None
    total: int | None = None
    currency: str | None = None
    customer: str | None = None
    subscription: str | None = None
    payment_intent: str | None = None
    hosted_invoice_url: str | None = None
    created: int | None = None
    # Top-level period fields for older API payloads — the per-line
    # ``period`` is preferred on current versions.
    period_start: int | None = None
    period_end: int | None = None
    status_transitions: StripeStatusTransitions | None = None
    lines: _StripeInvoiceLinesContainer = Field(
        default_factory=_StripeInvoiceLinesContainer
    )

    @property
    def first_line(self) -> StripeInvoiceLine | None:
        """Convenience: most invoices we handle are single-line."""
        return self.lines.data[0] if self.lines.data else None


# ---------------------------------------------------------------------------
# Checkout session — ``checkout.session.completed``
# ---------------------------------------------------------------------------


class StripeCheckoutSession(BaseModel):
    model_config = _TOLERANT
    id: str
    customer: str | None = None
    payment_intent: str | None = None
    amount_total: int | None = None
    currency: str | None = None
    mode: str | None = None


# ---------------------------------------------------------------------------
# Charge — ``charge.refunded``
# ---------------------------------------------------------------------------


class StripeCharge(BaseModel):
    """Used by the ``charge.refunded`` handler.

    Note ``invoice`` is intentionally absent: on ``charge.refunded`` Stripe
    does NOT populate the invoice field on the charge object even when
    the original charge was for a subscription invoice. The handler
    must bridge through ``payment_transaction.metadata.payment_intent``
    (set at invoice-payment time) to find the row.
    """

    model_config = _TOLERANT
    id: str
    customer: str | None = None
    payment_intent: str | None = None
    amount: int | None = None
    amount_refunded: int | None = None
    currency: str | None = None
    created: int | None = None


# ---------------------------------------------------------------------------
# Dispute / Early Fraud Warning
# ---------------------------------------------------------------------------


class StripeDispute(BaseModel):
    model_config = _TOLERANT
    id: str
    charge: str | None = None
    status: str | None = None
    reason: str | None = None
    amount: int | None = None
    currency: str | None = None
    evidence_details: StripeEvidenceDetails | None = None


class StripeEarlyFraudWarning(BaseModel):
    model_config = _TOLERANT
    id: str
    charge: str | None = None
    fraud_type: str | None = None
    actionable: bool | None = None
