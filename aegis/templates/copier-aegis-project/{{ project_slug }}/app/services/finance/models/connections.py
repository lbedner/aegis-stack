"""Provider connections and the sync events they raise.

An institution, a link to it, and the webhook deliveries that
link produces. Credential columns are ciphertext, masked in ``__repr__``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    Index,
)
from sqlmodel import Field, SQLModel

from app.services.finance.models.base import (
    _ENCRYPTED_COLUMNS,
    _FK,
    _SCHEMA,
    _utcnow,
)

# ---------------------------------------------------------------------------
# Group A — connections & sync
# ---------------------------------------------------------------------------


class FinanceInstitution(SQLModel, table=True):
    """Provider-agnostic institution directory (one row per provider view).

    Shared/global reference (not user-scoped). Carries the per-institution
    capability flags the connection layer gates on (AMEX has no liabilities,
    Chase uses tokenized account numbers, etc.).
    """

    __tablename__ = "finance_institution"
    __table_args__ = (
        Index(
            "uq_finance_institution_provider_extid",
            "provider",
            "provider_institution_id",
            unique=True,
            sqlite_where=Column("provider_institution_id").isnot(None),
            postgresql_where=Column("provider_institution_id").isnot(None),
        ),
        CheckConstraint(
            "provider IN ('plaid', 'snaptrade', 'coinbase', 'exchange_key', "
            "'onchain', 'manual')",
            name="ck_finance_institution_provider",
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    provider: str = Field(max_length=16, index=True)
    # Plaid ins_xxx / SnapTrade brokerage id — provider taxonomy, plain text.
    provider_institution_id: str | None = Field(default=None)
    name: str = Field(max_length=128, index=True)
    domain: str | None = Field(default=None, max_length=255)
    logo_url: str | None = Field(default=None)
    primary_color: str | None = Field(default=None, max_length=16)
    url: str | None = Field(default=None)
    country: str | None = Field(default=None, max_length=2)
    oauth_required: bool = Field(default=False)
    uses_tokenized_account_numbers: bool = Field(default=False)
    uses_app_to_app: bool = Field(default=False)
    supported_products: list[Any] = Field(
        default_factory=list, sa_column=Column("supported_products", JSON)
    )
    metadata_: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON)
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class FinanceConnection(SQLModel, table=True):
    """A provider-polymorphic connection (Plaid Item, SnapTrade authorization,
    exchange api-key, on-chain wallet, or manual).

    One fat row: inline AES-GCM-encrypted credential columns, a JSON capability
    matrix, inline health/status, and the sync cursor. Credentials are ciphertext
    at rest (encrypted in the service layer) and masked in ``__repr__``.
    ``owner_user_id`` has no model-level FK: the FK to ``user.id`` is added by
    the finance_auth_link migration only when the auth service is present, so
    finance runs standalone (single-user) too.
    """

    __tablename__ = "finance_connection"
    __table_args__ = (
        Index("ix_finance_connection_owner_status", "owner_user_id", "status"),
        Index(
            "uq_finance_connection_provider_item",
            "provider",
            "provider_item_id",
            unique=True,
            sqlite_where=(
                Column("provider_item_id").isnot(None) & Column("deleted_at").is_(None)
            ),
            postgresql_where=(
                Column("provider_item_id").isnot(None) & Column("deleted_at").is_(None)
            ),
        ),
        Index(
            "uq_finance_connection_wallet",
            "owner_user_id",
            "provider",
            "wallet_address",
            unique=True,
            sqlite_where=Column("wallet_address").isnot(None),
            postgresql_where=Column("wallet_address").isnot(None),
        ),
        CheckConstraint(
            "provider IN ('plaid', 'snaptrade', 'coinbase', 'exchange_key', "
            "'onchain', 'manual')",
            name="ck_finance_connection_provider",
        ),
        CheckConstraint(
            "connection_type IN ('oauth_access_token', 'api_key_secret', "
            "'onchain_address', 'aggregator_token', 'manual')",
            name="ck_finance_connection_type",
        ),
        CheckConstraint(
            "environment IN ('sandbox', 'production')",
            name="ck_finance_connection_environment",
        ),
        CheckConstraint(
            "status IN ('healthy', 'login_required', 'pending_expiration', "
            "'pending_disconnect', 'consent_expired', 'revoked', 'error', "
            "'loading', 'manual')",
            name="ck_finance_connection_status",
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int | None = Field(default=None, index=True)
    organization_id: int | None = Field(default=None, index=True)
    institution_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_institution.id", index=True
    )
    provider: str = Field(max_length=16)
    connection_type: str = Field(max_length=20)
    provider_item_id: str | None = Field(default=None)
    label: str | None = Field(default=None, max_length=255)
    environment: str = Field(default="sandbox", max_length=16)
    # Encrypted at rest via FinanceService (ciphertext text columns).
    access_token_encrypted: str | None = Field(default=None)
    api_key_encrypted: str | None = Field(default=None)
    api_secret_encrypted: str | None = Field(default=None)
    api_passphrase_encrypted: str | None = Field(default=None)
    refresh_token_encrypted: str | None = Field(default=None)
    # Public on-chain address is not a secret.
    wallet_address: str | None = Field(default=None)
    wallet_chain: str | None = Field(default=None)
    capabilities: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("capabilities", JSON)
    )
    status: str = Field(default="healthy", max_length=24)
    status_detail: str | None = Field(default=None)
    last_error_code: str | None = Field(default=None)
    needs_user_action: bool = Field(default=False, index=True)
    sync_cursor: str | None = Field(default=None)
    days_requested: int | None = Field(default=None)
    consent_expiration_at: datetime | None = Field(default=None)
    last_successful_sync_at: datetime | None = Field(default=None)
    last_sync_attempt_at: datetime | None = Field(default=None)
    removed_at: datetime | None = Field(default=None)
    deleted_at: datetime | None = Field(default=None, index=True)
    metadata_: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON)
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    def __repr__(self) -> str:
        """Logging-safe repr — credential columns masked."""
        creds = {
            col: ("***" if getattr(self, col, None) else None)
            for col in _ENCRYPTED_COLUMNS
        }
        return (
            f"FinanceConnection(id={self.id!r}, provider={self.provider!r}, "
            f"owner_user_id={self.owner_user_id!r}, status={self.status!r}, "
            f"creds={creds})"
        )


class FinanceWebhookEvent(SQLModel, table=True):
    """Idempotent inbound provider-webhook log; dedups on provider_event_id so a
    re-delivered webhook is a no-op, and is the replay/debug buffer."""

    __tablename__ = "finance_webhook_event"
    __table_args__ = (
        Index("ix_finance_webhook_status_received", "status", "received_at"),
        Index(
            "uq_finance_webhook_event",
            "provider",
            "provider_event_id",
            unique=True,
            sqlite_where=Column("provider_event_id").isnot(None),
            postgresql_where=Column("provider_event_id").isnot(None),
        ),
        CheckConstraint(
            "provider IN ('plaid', 'snaptrade', 'coinbase')",
            name="ck_finance_webhook_provider",
        ),
        CheckConstraint(
            "status IN ('received', 'processed', 'ignored', 'error')",
            name="ck_finance_webhook_status",
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    connection_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_connection.id", index=True
    )
    provider: str = Field(max_length=16)
    provider_item_id: str | None = Field(default=None, index=True)
    webhook_type: str | None = Field(default=None)
    webhook_code: str | None = Field(default=None)
    provider_event_id: str | None = Field(default=None)
    payload: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("payload", JSON)
    )
    status: str = Field(default="received", max_length=16)
    error: str | None = Field(default=None)
    received_at: datetime = Field(default_factory=_utcnow)
    processed_at: datetime | None = Field(default=None)
