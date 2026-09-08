"""
Payment service database models.

Five tables:
- PaymentProvider: Configured payment providers (Stripe, etc.)
- PaymentCustomer: Links app users to provider customer IDs
- PaymentTransaction: All payment events (charges, refunds)
- PaymentSubscription: Active subscription tracking
- PaymentDispute: Chargebacks, early fraud warnings, and their lifecycle

Plus one non-table value type:
- PaymentStatusSummary: in-process snapshot returned by PaymentService
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, Column, Index, UniqueConstraint, text
from sqlmodel import Field, Relationship, SQLModel

from app.core.time import utcnow

# ---------------------------------------------------------------------------
# PaymentProvider
# ---------------------------------------------------------------------------


class PaymentProvider(SQLModel, table=True):
    """Configured payment provider (e.g., Stripe)."""

    __tablename__ = "payment_provider"

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(unique=True, index=True, max_length=32)
    display_name: str = Field(max_length=64)
    enabled: bool = Field(default=True)
    is_test_mode: bool = Field(default=True)
    metadata_: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON)
    )
    created_at: datetime = Field(
        default_factory=lambda: utcnow()
    )

    # Relationships
    customers: list["PaymentCustomer"] = Relationship(back_populates="provider")
    transactions: list["PaymentTransaction"] = Relationship(back_populates="provider")


# ---------------------------------------------------------------------------
# PaymentCustomer
# ---------------------------------------------------------------------------


class PaymentCustomer(SQLModel, table=True):
    """Links an app user to a payment provider customer."""

    __tablename__ = "payment_customer"
    __table_args__ = (
        UniqueConstraint(
            "provider_id", "provider_customer_id", name="uq_provider_customer"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    # user_id is nullable: anonymous checkouts (guest carts, donations,
    # pre-signup SaaS trials) have no app user yet. When the auth service
    # is included, a FK constraint to user.id is added via migration.
    user_id: int | None = Field(default=None, index=True)
    provider_id: int = Field(foreign_key="payment_provider.id", index=True)
    provider_customer_id: str = Field(index=True, max_length=128)
    email: str | None = Field(default=None, max_length=255)
    metadata_: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON)
    )
    created_at: datetime = Field(
        default_factory=lambda: utcnow()
    )

    # Relationships
    provider: PaymentProvider = Relationship(back_populates="customers")
    transactions: list["PaymentTransaction"] = Relationship(back_populates="customer")
    subscriptions: list["PaymentSubscription"] = Relationship(back_populates="customer")


# ---------------------------------------------------------------------------
# PaymentTransaction
# ---------------------------------------------------------------------------


class PaymentTransaction(SQLModel, table=True):
    """A single payment event (charge, refund, etc.)."""

    __tablename__ = "payment_transaction"
    __table_args__ = (
        Index("ix_payment_txn_status_created", "status", "created_at"),
        Index("ix_payment_txn_provider_created", "provider_id", "created_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    provider_id: int = Field(foreign_key="payment_provider.id", index=True)
    customer_id: int | None = Field(
        default=None, foreign_key="payment_customer.id", index=True
    )
    provider_transaction_id: str = Field(unique=True, index=True, max_length=128)
    type: str = Field(max_length=32)
    status: str = Field(max_length=32, index=True)
    amount: int = Field(default=0)  # Smallest currency unit (cents)
    currency: str = Field(max_length=3, default="usd")
    description: str | None = Field(default=None, max_length=512)
    metadata_: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON)
    )
    created_at: datetime = Field(
        default_factory=lambda: utcnow()
    )
    updated_at: datetime = Field(
        default_factory=lambda: utcnow()
    )

    # Relationships
    provider: PaymentProvider = Relationship(back_populates="transactions")
    customer: PaymentCustomer | None = Relationship(back_populates="transactions")
    disputes: list["PaymentDispute"] = Relationship(back_populates="transaction")


# ---------------------------------------------------------------------------
# PaymentSubscription
# ---------------------------------------------------------------------------


class PaymentSubscription(SQLModel, table=True):
    """Active subscription tracking.

    Invariant: at most one currently-active subscription per customer.
    ``active`` and ``trialing`` are functionally the same for access-
    gating purposes - both grant the user paid features, whether or
    not Stripe is currently charging. ``past_due``, ``incomplete``,
    ``canceled``, etc. are NOT part of the active set; they're
    historical and may exist alongside a fresh active row.

    The partial unique index below enforces this at the database
    layer. Postgres only - SQLite supports partial indexes but
    SQLAlchemy's reflection of ``postgresql_where`` doesn't translate
    cleanly, so on SQLite this index degenerates to a non-partial
    unique on ``customer_id`` and would over-constrain (canceled +
    active couldn't coexist for the same customer). Most production
    deployments are Postgres so this is the right default; drop the
    declaration here if you ship on SQLite and rely on the app-layer
    gate alone.
    """

    __tablename__ = "payment_subscription"
    __table_args__ = (
        Index(
            "uq_payment_subscription_active_per_customer",
            "customer_id",
            unique=True,
            # Both dialects need the filter declared explicitly -
            # SQLAlchemy doesn't broadcast ``postgresql_where`` to
            # other backends. Without ``sqlite_where`` SQLite would
            # build a plain ``UNIQUE (customer_id)`` (no WHERE),
            # over-constraining the table by also forbidding a
            # canceled-row + active-row coexistence for the same
            # customer.
            postgresql_where=text("status IN ('active', 'trialing')"),
            sqlite_where=text("status IN ('active', 'trialing')"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    customer_id: int = Field(foreign_key="payment_customer.id", index=True)
    provider_subscription_id: str = Field(unique=True, index=True, max_length=128)
    plan_name: str = Field(max_length=64)
    status: str = Field(max_length=32, index=True)
    current_period_start: datetime
    current_period_end: datetime
    cancel_at_period_end: bool = Field(default=False)
    metadata_: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON)
    )
    created_at: datetime = Field(
        default_factory=lambda: utcnow()
    )
    updated_at: datetime = Field(
        default_factory=lambda: utcnow()
    )

    # Relationships
    customer: PaymentCustomer = Relationship(back_populates="subscriptions")


# ---------------------------------------------------------------------------
# PaymentDispute
# ---------------------------------------------------------------------------


class PaymentDispute(SQLModel, table=True):
    """Chargeback or early fraud warning on a transaction.

    One row per dispute event. A charge may have zero or more disputes
    over its lifetime (e.g., an EFW followed by an actual chargeback,
    or multiple disputes on partial captures). Each row tracks its own
    lifecycle via the `status` field.
    """

    __tablename__ = "payment_dispute"
    __table_args__ = (
        Index("ix_payment_dispute_status_created", "status", "created_at"),
        Index("ix_payment_dispute_txn_created", "transaction_id", "created_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    transaction_id: int = Field(foreign_key="payment_transaction.id", index=True)

    # The provider's identifier. For a chargeback this is `dp_xxx`; for an
    # early fraud warning it is `issfr_xxx`. Both get stored here so we can
    # correlate events back to their provider-side objects.
    provider_dispute_id: str = Field(unique=True, index=True, max_length=128)

    # Lifecycle status. See constants.DisputeStatus for allowed values.
    # EFW → warning_issued; chargeback created → needs_response; Stripe
    # auto-responds via your evidence submission → under_review; closed →
    # won / lost / charge_refunded.
    status: str = Field(max_length=32, index=True)

    # Stripe's reason code (e.g. fraudulent, product_not_received,
    # unrecognized, duplicate). Free-form string to avoid coupling to
    # Stripe's evolving reason taxonomy.
    reason: str | None = Field(default=None, max_length=64)

    amount: int = Field(default=0)  # Smallest currency unit
    currency: str = Field(max_length=3, default="usd")

    # Deadline to submit evidence (chargebacks only; null for EFWs).
    evidence_due_by: datetime | None = Field(default=None)

    # The original webhook event type that created or last updated this row.
    # Useful for debugging and for "did we ever see an EFW for this charge?".
    event_type: str | None = Field(default=None, max_length=64)

    metadata_: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON)
    )
    created_at: datetime = Field(
        default_factory=lambda: utcnow()
    )
    updated_at: datetime = Field(
        default_factory=lambda: utcnow()
    )

    # Relationships
    transaction: PaymentTransaction = Relationship(back_populates="disputes")


# ---------------------------------------------------------------------------
# PaymentStatusSummary (non-table value type)
# ---------------------------------------------------------------------------


class PaymentStatusSummary(BaseModel):
    """Typed snapshot of payment service state.

    Holds actual SQLModel instances, not serialized dicts. Callers that need
    JSON (API handlers, dashboard metadata) call ``model_dump(mode="json")``
    at their own boundary; callers that stay in-process (CLI) read attributes
    directly.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    provider_key: str
    provider_display_name: str
    enabled: bool
    is_test_mode: bool
    healthy: bool
    health_message: str | None = None
    api_version: str | None = None
    total_transactions: int
    total_revenue_cents: int
    active_subscriptions: int
    open_disputes: int
    recent_transactions: list[PaymentTransaction]
    # Enriched subscription dicts: each carries the raw PaymentSubscription
    # columns plus ``customer_name`` / ``customer_email`` so the dashboard
    # can render a meaningful "who" column without a second round-trip.
    recent_subscriptions: list[dict[str, Any]]
    recent_disputes: list[PaymentDispute]
