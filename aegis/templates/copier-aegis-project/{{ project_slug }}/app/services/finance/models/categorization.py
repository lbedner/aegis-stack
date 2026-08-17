"""How a transaction gets named and grouped.

Categories and their aliases, merchants, tags, and the rules that
assign them.
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
    _FK,
    _SCHEMA,
    _utcnow,
)

# ---------------------------------------------------------------------------
# Group D (ref) — categories, merchants, tags, rules
# ---------------------------------------------------------------------------
#
# ``category_id`` / ``merchant_id`` on FinanceTransaction and
# FinanceTransactionSplit are plain columns above; their FK constraints are
# added in the generated migration's alter_tables now that these target tables
# exist. ``owner_user_id`` has no model FK (added by finance_auth_link when auth
# is present); a NULL owner marks a system/global seed row.


class FinanceCategory(SQLModel, table=True):
    """Owned two-level category tree (seeded from Plaid PFC), user-editable.

    ``owner_user_id`` NULL is a system/global seed row; a user's edits create
    owned rows. Self-referencing hierarchy via ``parent_id``. ``slug`` is unique
    per scope: once globally for seeds, once per owner for user rows.
    """

    __tablename__ = "finance_category"
    __table_args__ = (
        Index("ix_finance_category_owner", "owner_user_id"),
        Index("ix_finance_category_parent", "parent_id"),
        Index("ix_finance_category_pfc", "plaid_pfc_detailed"),
        Index(
            "uq_finance_category_system_slug",
            "slug",
            unique=True,
            sqlite_where=Column("owner_user_id").is_(None),
            postgresql_where=Column("owner_user_id").is_(None),
        ),
        Index(
            "uq_finance_category_user_slug",
            "owner_user_id",
            "slug",
            unique=True,
            sqlite_where=Column("owner_user_id").isnot(None),
            postgresql_where=Column("owner_user_id").isnot(None),
        ),
        CheckConstraint(
            "classification IN ('income', 'expense', 'transfer')",
            name="ck_finance_category_classification",
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int | None = Field(default=None)
    organization_id: int | None = Field(default=None)
    parent_id: int | None = Field(default=None, foreign_key=f"{_FK}finance_category.id")
    name: str = Field(max_length=128)
    slug: str = Field(max_length=96)
    classification: str = Field(max_length=12)
    plaid_pfc_primary: str | None = Field(default=None)
    plaid_pfc_detailed: str | None = Field(default=None)
    icon: str | None = Field(default=None, max_length=64)
    color: str | None = Field(default=None, max_length=16)
    is_system: bool = Field(default=False)
    is_archived: bool = Field(default=False)
    sort_order: int = Field(default=0)
    tax_line: str | None = Field(default=None)
    metadata_: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON)
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class FinanceCategoryAlias(SQLModel, table=True):
    """Free-text category string (QIF/Chase/AMEX/Plaid PFC) -> canonical
    category. N:1 lookup keyed on normalized text; unmatched imports fall back
    to the seeded ``uncategorized`` category."""

    __tablename__ = "finance_category_alias"
    __table_args__ = (
        Index("ix_finance_catalias_owner", "owner_user_id"),
        Index("ix_finance_catalias_category", "category_id"),
        Index("ix_finance_catalias_normalized", "normalized_alias"),
        Index(
            "uq_finance_catalias_owner_norm",
            "owner_user_id",
            "normalized_alias",
            unique=True,
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int | None = Field(default=None)
    category_id: int = Field(foreign_key=f"{_FK}finance_category.id")
    alias_text: str
    normalized_alias: str
    source: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)


class FinanceMerchant(SQLModel, table=True):
    """Normalized payee directory — the prerequisite for recurring/subscription
    detection. ``owner_user_id`` NULL is a global/provider-seeded payee. The raw
    description stays on the transaction; ``service_type`` powers the
    duplicate-service ("two music subscriptions") insight."""

    __tablename__ = "finance_merchant"
    __table_args__ = (
        Index("ix_finance_merchant_owner", "owner_user_id"),
        Index("ix_finance_merchant_org", "organization_id"),
        Index("ix_finance_merchant_normalized", "normalized_name"),
        Index("ix_finance_merchant_default_cat", "default_category_id"),
        Index("ix_finance_merchant_deleted", "deleted_at"),
        Index(
            "uq_finance_merchant_global",
            "normalized_name",
            unique=True,
            sqlite_where=(
                Column("owner_user_id").is_(None) & Column("deleted_at").is_(None)
            ),
            postgresql_where=(
                Column("owner_user_id").is_(None) & Column("deleted_at").is_(None)
            ),
        ),
        Index(
            "uq_finance_merchant_user",
            "owner_user_id",
            "normalized_name",
            unique=True,
            sqlite_where=(
                Column("owner_user_id").isnot(None) & Column("deleted_at").is_(None)
            ),
            postgresql_where=(
                Column("owner_user_id").isnot(None) & Column("deleted_at").is_(None)
            ),
        ),
        Index(
            "uq_finance_merchant_provider",
            "source",
            "provider_merchant_id",
            unique=True,
            sqlite_where=Column("provider_merchant_id").isnot(None),
            postgresql_where=Column("provider_merchant_id").isnot(None),
        ),
        CheckConstraint(
            "source IN ('plaid', 'user', 'system', 'rule', 'snaptrade')",
            name="ck_finance_merchant_source",
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int | None = Field(default=None)
    organization_id: int | None = Field(default=None)
    name: str = Field(max_length=255)
    normalized_name: str = Field(max_length=255)
    source: str = Field(max_length=12)
    provider_merchant_id: str | None = Field(default=None)
    logo_url: str | None = Field(default=None)
    website_url: str | None = Field(default=None)
    default_category_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_category.id"
    )
    service_type: str | None = Field(default=None)
    deleted_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class FinanceTag(SQLModel, table=True):
    """First-class tags (Quicken ``/Class`` axis plus user tags), orthogonal to
    categories. Always user-owned (no global seeds)."""

    __tablename__ = "finance_tag"
    __table_args__ = (
        Index("ix_finance_tag_owner", "owner_user_id"),
        Index("ix_finance_tag_org", "organization_id"),
        Index("ix_finance_tag_deleted", "deleted_at"),
        Index(
            "uq_finance_tag_owner_name",
            "owner_user_id",
            "normalized_name",
            unique=True,
            sqlite_where=Column("deleted_at").is_(None),
            postgresql_where=Column("deleted_at").is_(None),
        ),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int = Field()
    organization_id: int | None = Field(default=None)
    name: str = Field(max_length=64)
    normalized_name: str = Field(max_length=64)
    color: str | None = Field(default=None, max_length=16)
    deleted_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class FinanceTransactionTag(SQLModel, table=True):
    """M2M join transaction <-> tag, at split-line grain when ``split_id`` is
    set. Composite PK ``(transaction_id, tag_id)`` — a pure join table."""

    __tablename__ = "finance_transaction_tag"
    __table_args__ = (
        Index("ix_finance_txntag_tag", "tag_id"),
        Index("ix_finance_txntag_split", "split_id"),
        {"schema": _SCHEMA},
    )

    transaction_id: int = Field(
        foreign_key=f"{_FK}finance_transaction.id", primary_key=True
    )
    tag_id: int = Field(foreign_key=f"{_FK}finance_tag.id", primary_key=True)
    split_id: int | None = Field(
        default=None, foreign_key=f"{_FK}finance_transaction_split.id"
    )
    created_at: datetime = Field(default_factory=_utcnow)


class FinanceRule(SQLModel, table=True):
    """User automation rules (auto-categorize, mark-transfer, rename payee,
    ignore/flag), priority-ordered, with conditions/actions as JSON. Precedence
    is provider -> ml -> rule -> user. Reserved until the rules UI ships."""

    __tablename__ = "finance_rule"
    __table_args__ = (
        Index("ix_finance_rule_owner", "owner_user_id"),
        Index("ix_finance_rule_org", "organization_id"),
        Index("ix_finance_rule_owner_priority", "owner_user_id", "priority"),
        Index("ix_finance_rule_deleted", "deleted_at"),
        {"schema": _SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int = Field()
    organization_id: int | None = Field(default=None)
    name: str = Field(max_length=128)
    priority: int = Field(default=100)
    is_enabled: bool = Field(default=True)
    conditions: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("conditions", JSON)
    )
    actions: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("actions", JSON)
    )
    stop_processing: bool = Field(default=False)
    match_count: int = Field(default=0)
    last_matched_at: datetime | None = Field(default=None)
    deleted_at: datetime | None = Field(default=None)
    metadata_: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON)
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
