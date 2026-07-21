"""
Dynamic migration generator for Aegis Stack services.

This module provides Django-style migration generation for services that require
database tables. It enables:
- Clean initial project generation with only needed migrations
- Adding services later via `aegis add` without migration conflicts
- DRY table definitions used for both scenarios

Usage:
    # During aegis init
    generate_migrations_for_services(project_path, ["auth", "ai"])

    # During aegis add
    if not service_has_migration(project_path, "ai"):
        generate_migration(project_path, "ai")
"""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, Template, TemplateNotFound

from ..constants import AnswerKeys, AuthLevels, StorageBackends


@dataclass
class ColumnSpec:
    """Specification for a database column."""

    name: str
    type: str  # SQLAlchemy type string, e.g., "sa.Integer()", "sa.String()"
    nullable: bool = True
    primary_key: bool = False
    default: str | None = None


@dataclass
class IndexSpec:
    """Specification for a database index.

    ``where`` is a partial-index predicate (SQL fragment, no leading
    ``WHERE``). When set, it's rendered as both ``sqlite_where`` and
    ``postgresql_where`` on ``op.create_index`` so the same predicate
    applies to both backends. Used for partial unique indexes such as
    ``UNIQUE (email) WHERE deleted_at IS NULL`` — supports soft-delete
    flows that need to reuse the column value after deletion.
    """

    name: str
    columns: list[str]
    unique: bool = False
    where: str | None = None


@dataclass
class ForeignKeySpec:
    """Specification for a foreign key constraint.

    ``ondelete`` is the SQL ``ON DELETE`` referential action, passed
    straight through to ``sa.ForeignKeyConstraint`` /
    ``op.create_foreign_key``. Defaults to ``None`` (no cascade — the
    database's default behaviour, typically "RESTRICT"). Set to
    ``"CASCADE"`` for project-owned children that should die with
    their owner so SQLAlchemy ``passive_deletes=True`` relationships
    actually work end-to-end.
    """

    columns: list[str]
    ref_table: str
    ref_columns: list[str]
    ondelete: str | None = None
    # Postgres schema of the referenced table, for cross-schema FKs
    # (e.g. payment.payment_customer -> auth.user). When None, the
    # referenced table is assumed to live in the owning spec's schema.
    ref_schema: str | None = None
    # Explicit constraint name for alter_tables FKs. Auto-derived as
    # ``fk_<table>_<col>_<ref_table>`` when None, but that can exceed
    # Postgres' 63-char identifier limit for long table/column names, so
    # long FKs pass a short explicit name here.
    name: str | None = None


@dataclass
class CheckConstraintSpec:
    """Specification for a CHECK constraint on a table.

    Used to enforce enum-style allowed values without a native PG enum type.
    Rendered into ``op.create_table`` so it works on both SQLite and Postgres.
    """

    name: str
    sqltext: str  # e.g. "origin IN ('collector', 'user')"


@dataclass
class TableSpec:
    """Specification for a database table."""

    name: str
    columns: list[ColumnSpec]
    indexes: list[IndexSpec] = field(default_factory=list)
    foreign_keys: list[ForeignKeySpec] = field(default_factory=list)
    check_constraints: list[CheckConstraintSpec] = field(default_factory=list)


@dataclass
class AlterTableSpec:
    """Specification for altering an existing table.

    Add operations: ``add_columns``, ``add_foreign_keys``, ``add_indexes``.
    Drop operations: ``drop_columns``, ``drop_indexes``.

    All operations on a single ``AlterTableSpec`` run inside a single
    ``op.batch_alter_table`` block so they're atomic and SQLite-safe.
    Drop operations run BEFORE add operations within the block, since
    a common pattern is "replace this column / index with that one"
    and the new versions can reuse names.
    """

    name: str
    add_columns: list[ColumnSpec] = field(default_factory=list)
    add_foreign_keys: list[ForeignKeySpec] = field(default_factory=list)
    add_indexes: list[IndexSpec] = field(default_factory=list)
    drop_columns: list[str] = field(default_factory=list)
    drop_indexes: list[str] = field(default_factory=list)


@dataclass
class ServiceMigrationSpec:
    """Migration specification for a service.

    ``forward_only=True`` is for migrations that drop columns or merge
    schemas in non-recoverable ways. The generated ``downgrade()``
    raises ``NotImplementedError`` instead of trying to revert.
    """

    service_name: str
    tables: list[TableSpec]
    description: str
    alter_tables: list[AlterTableSpec] = field(default_factory=list)
    forward_only: bool = False
    # Postgres schema all of this spec's tables live in. None keeps them
    # in the default schema (``public``) and renders byte-identically to
    # pre-schema migrations. Schemas are Postgres-only: SQLite ignores
    # this (it has no CREATE SCHEMA) and keeps every table in one DB.
    schema: str | None = None


# ============================================================================
# Service Migration Definitions
# ============================================================================

AUTH_MIGRATION = ServiceMigrationSpec(
    service_name="auth",
    description="Auth service tables",
    tables=[
        TableSpec(
            name="user",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("email", "sa.String()", nullable=False),
                ColumnSpec("full_name", "sa.String()", nullable=True),
                ColumnSpec("is_active", "sa.Boolean()", nullable=False, default="True"),
                ColumnSpec(
                    "is_verified", "sa.Boolean()", nullable=False, default="False"
                ),
                ColumnSpec("hashed_password", "sa.String()", nullable=False),
                ColumnSpec("last_login", "sa.DateTime()", nullable=True),
                ColumnSpec(
                    "failed_login_attempts", "sa.Integer()", nullable=False, default="0"
                ),
                ColumnSpec("locked_until", "sa.DateTime()", nullable=True),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=True),
                ColumnSpec("deleted_at", "sa.DateTime()", nullable=True),
            ],
            indexes=[
                # Partial unique: only enforces uniqueness over live rows
                # so a re-registration after soft delete can reuse the
                # email value. Both SQLite and Postgres support
                # ``CREATE UNIQUE INDEX ... WHERE ...``.
                IndexSpec(
                    "ix_user_email",
                    ["email"],
                    unique=True,
                    where="deleted_at IS NULL",
                ),
                IndexSpec("ix_user_deleted_at", ["deleted_at"]),
            ],
        ),
        # UserOAuthIdentity - links a user to a third-party identity.
        # One user can have many identities (GitHub + Google). The
        # (provider, provider_user_id) pair is unique to prevent identity
        # hijacking across accounts.
        TableSpec(
            name="user_oauth_identity",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("user_id", "sa.Integer()", nullable=False),
                ColumnSpec("provider", "sa.String(32)", nullable=False),
                # Stored as string to avoid caring whether the provider
                # uses int IDs (GitHub) or UUIDs (some others).
                ColumnSpec("provider_user_id", "sa.String(128)", nullable=False),
                ColumnSpec("provider_username", "sa.String(128)", nullable=True),
                ColumnSpec("provider_email", "sa.String(255)", nullable=True),
                ColumnSpec("avatar_url", "sa.String(512)", nullable=True),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec(
                    "uq_user_oauth_identity_provider_pid",
                    ["provider", "provider_user_id"],
                    unique=True,
                ),
                IndexSpec("ix_user_oauth_identity_user_id", ["user_id"]),
            ],
            foreign_keys=[
                ForeignKeySpec(["user_id"], "user", ["id"]),
            ],
            check_constraints=[
                CheckConstraintSpec(
                    name="ck_user_oauth_identity_provider",
                    sqltext="provider IN ('github', 'google')",
                ),
            ],
        ),
    ],
)

AUTH_RBAC_MIGRATION = ServiceMigrationSpec(
    service_name="auth_rbac",
    description="RBAC role column for user table",
    tables=[],
    alter_tables=[
        AlterTableSpec(
            name="user",
            add_columns=[
                ColumnSpec("role", "sa.String()", nullable=False, default="'user'"),
            ],
        ),
    ],
)

ORG_MIGRATION = ServiceMigrationSpec(
    service_name="auth_org",
    description="Organization and membership tables",
    tables=[
        TableSpec(
            name="organization",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("name", "sa.String()", nullable=False),
                ColumnSpec("slug", "sa.String()", nullable=False),
                ColumnSpec("description", "sa.String()", nullable=True),
                ColumnSpec("is_active", "sa.Boolean()", nullable=False, default="True"),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=True),
                ColumnSpec("deleted_at", "sa.DateTime()", nullable=True),
            ],
            indexes=[
                IndexSpec("ix_organization_name", ["name"]),
                # Partial unique on slug — same rationale as user.email.
                IndexSpec(
                    "ix_organization_slug",
                    ["slug"],
                    unique=True,
                    where="deleted_at IS NULL",
                ),
                IndexSpec("ix_organization_deleted_at", ["deleted_at"]),
            ],
        ),
        TableSpec(
            name="organization_member",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("organization_id", "sa.Integer()", nullable=False),
                ColumnSpec("user_id", "sa.Integer()", nullable=False),
                ColumnSpec("role", "sa.String()", nullable=False, default="'member'"),
                ColumnSpec("joined_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec(
                    "ix_org_member_org_user",
                    ["organization_id", "user_id"],
                    unique=True,
                ),
                IndexSpec(
                    "ix_org_member_organization_id",
                    ["organization_id"],
                ),
                IndexSpec(
                    "ix_org_member_user_id",
                    ["user_id"],
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(["organization_id"], "organization", ["id"]),
                ForeignKeySpec(["user_id"], "user", ["id"]),
            ],
        ),
        TableSpec(
            name="org_invite",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("organization_id", "sa.Integer()", nullable=False),
                ColumnSpec("email", "sa.String()", nullable=False),
                ColumnSpec("role", "sa.String()", nullable=False, default="'member'"),
                ColumnSpec("invited_by", "sa.Integer()", nullable=False),
                ColumnSpec(
                    "status", "sa.String()", nullable=False, default="'pending'"
                ),
                ColumnSpec("token", "sa.String()", nullable=False),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("expires_at", "sa.DateTime()", nullable=True),
            ],
            indexes=[
                IndexSpec("ix_org_invite_email", ["email"]),
                IndexSpec("ix_org_invite_org_id", ["organization_id"]),
                IndexSpec("ix_org_invite_token", ["token"], unique=True),
            ],
            foreign_keys=[
                ForeignKeySpec(["organization_id"], "organization", ["id"]),
                ForeignKeySpec(["invited_by"], "user", ["id"]),
            ],
        ),
    ],
)

AI_MIGRATION = ServiceMigrationSpec(
    service_name="ai",
    description="AI service tables (LLM catalog, usage tracking, conversations)",
    tables=[
        # LLM Vendor - no dependencies
        TableSpec(
            name="llm_vendor",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("name", "sa.String()", nullable=False),
                ColumnSpec("description", "sa.String()", nullable=True),
                ColumnSpec("color", "sa.String()", nullable=False, default="'#6B7280'"),
                ColumnSpec("icon_path", "sa.String()", nullable=False, default="''"),
                ColumnSpec("api_base", "sa.String()", nullable=True),
                ColumnSpec(
                    "auth_method", "sa.String()", nullable=False, default="'api-key'"
                ),
            ],
            indexes=[IndexSpec("ix_llm_vendor_name", ["name"], unique=True)],
        ),
        # Large Language Model - depends on llm_vendor
        TableSpec(
            name="large_language_model",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("model_id", "sa.String()", nullable=False),
                ColumnSpec("title", "sa.String()", nullable=False),
                ColumnSpec("description", "sa.String()", nullable=False, default="''"),
                ColumnSpec(
                    "context_window", "sa.Integer()", nullable=False, default="4096"
                ),
                ColumnSpec(
                    "training_data", "sa.String()", nullable=False, default="''"
                ),
                ColumnSpec(
                    "streamable", "sa.Boolean()", nullable=False, default="True"
                ),
                ColumnSpec("enabled", "sa.Boolean()", nullable=False, default="True"),
                ColumnSpec("color", "sa.String()", nullable=False, default="'#6B7280'"),
                ColumnSpec("icon_path", "sa.String()", nullable=False, default="''"),
                ColumnSpec("license", "sa.String()", nullable=True),
                ColumnSpec("source_url", "sa.String()", nullable=True),
                ColumnSpec("released_on", "sa.DateTime()", nullable=True),
                ColumnSpec("family", "sa.String()", nullable=True),
                ColumnSpec("llm_vendor_id", "sa.Integer()", nullable=True),
            ],
            indexes=[
                IndexSpec(
                    "ix_large_language_model_model_id", ["model_id"], unique=True
                ),
                IndexSpec("ix_large_language_model_llm_vendor_id", ["llm_vendor_id"]),
            ],
            foreign_keys=[ForeignKeySpec(["llm_vendor_id"], "llm_vendor", ["id"])],
        ),
        # LLM Deployment - depends on llm_vendor and large_language_model
        TableSpec(
            name="llm_deployment",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("llm_id", "sa.Integer()", nullable=False),
                ColumnSpec("llm_vendor_id", "sa.Integer()", nullable=False),
                ColumnSpec("speed", "sa.Integer()", nullable=False, default="50"),
                ColumnSpec(
                    "intelligence", "sa.Integer()", nullable=False, default="50"
                ),
                ColumnSpec("reasoning", "sa.Integer()", nullable=False, default="50"),
                ColumnSpec(
                    "output_max_tokens", "sa.Integer()", nullable=False, default="4096"
                ),
                ColumnSpec(
                    "function_calling", "sa.Boolean()", nullable=False, default="False"
                ),
                ColumnSpec(
                    "input_cache", "sa.Boolean()", nullable=False, default="False"
                ),
                ColumnSpec(
                    "structured_output", "sa.Boolean()", nullable=False, default="False"
                ),
            ],
            indexes=[
                IndexSpec("ix_llm_deployment_llm_id", ["llm_id"]),
                IndexSpec("ix_llm_deployment_llm_vendor_id", ["llm_vendor_id"]),
                IndexSpec(
                    "ix_llm_deployment_llm_vendor_unique",
                    ["llm_id", "llm_vendor_id"],
                    unique=True,
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(["llm_id"], "large_language_model", ["id"]),
                ForeignKeySpec(["llm_vendor_id"], "llm_vendor", ["id"]),
            ],
        ),
        # LLM Modality - depends on large_language_model
        TableSpec(
            name="llm_modality",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("llm_id", "sa.Integer()", nullable=False),
                ColumnSpec("modality", "sa.String()", nullable=False),
                ColumnSpec("direction", "sa.String()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_llm_modality_llm_id", ["llm_id"]),
                IndexSpec(
                    "ix_llm_modality_unique",
                    ["llm_id", "modality", "direction"],
                    unique=True,
                ),
            ],
            foreign_keys=[ForeignKeySpec(["llm_id"], "large_language_model", ["id"])],
        ),
        # LLM Price - depends on llm_vendor and large_language_model
        TableSpec(
            name="llm_price",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("llm_vendor_id", "sa.Integer()", nullable=False),
                ColumnSpec("llm_id", "sa.Integer()", nullable=False),
                ColumnSpec("input_cost_per_token", "sa.Float()", nullable=False),
                ColumnSpec("output_cost_per_token", "sa.Float()", nullable=False),
                ColumnSpec("cache_input_cost_per_token", "sa.Float()", nullable=True),
                ColumnSpec("effective_date", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_llm_price_llm_vendor_id", ["llm_vendor_id"]),
                IndexSpec("ix_llm_price_llm_id", ["llm_id"]),
                IndexSpec("ix_llm_price_effective_date", ["effective_date"]),
            ],
            foreign_keys=[
                ForeignKeySpec(["llm_vendor_id"], "llm_vendor", ["id"]),
                ForeignKeySpec(["llm_id"], "large_language_model", ["id"]),
            ],
        ),
        # LLM Usage - uses model_id string (decoupled from catalog lifecycle)
        TableSpec(
            name="llm_usage",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("model_id", "sa.String()", nullable=False),
                ColumnSpec("user_id", "sa.String()", nullable=True),
                ColumnSpec("timestamp", "sa.DateTime()", nullable=False),
                ColumnSpec("input_tokens", "sa.Integer()", nullable=False),
                ColumnSpec("output_tokens", "sa.Integer()", nullable=False),
                ColumnSpec("total_cost", "sa.Float()", nullable=False),
                ColumnSpec("success", "sa.Boolean()", nullable=False, default="True"),
                ColumnSpec("error_message", "sa.String()", nullable=True),
                ColumnSpec("action", "sa.String()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_llm_usage_model_id", ["model_id"]),
                IndexSpec("ix_llm_usage_user_id", ["user_id"]),
                IndexSpec("ix_llm_usage_timestamp", ["timestamp"]),
                IndexSpec("ix_llm_usage_action", ["action"]),
            ],
            foreign_keys=[],
        ),
        # Conversation - no LLM dependencies
        TableSpec(
            name="conversation",
            columns=[
                ColumnSpec(
                    "id",
                    "sa.String()",
                    nullable=False,
                    primary_key=True,
                ),
                ColumnSpec("title", "sa.String()", nullable=True),
                ColumnSpec("user_id", "sa.String()", nullable=False),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
                ColumnSpec("meta_data", "sa.JSON()", nullable=False, default="{}"),
            ],
            indexes=[IndexSpec("ix_conversation_user_id", ["user_id"])],
        ),
        # Conversation Message - depends on conversation
        TableSpec(
            name="conversation_message",
            columns=[
                ColumnSpec(
                    "id",
                    "sa.String()",
                    nullable=False,
                    primary_key=True,
                ),
                ColumnSpec(
                    "conversation_id",
                    "sa.String()",
                    nullable=False,
                ),
                ColumnSpec("role", "sa.String()", nullable=False),
                ColumnSpec("content", "sa.String()", nullable=False),
                ColumnSpec("timestamp", "sa.DateTime()", nullable=False),
                ColumnSpec("meta_data", "sa.JSON()", nullable=False, default="{}"),
            ],
            indexes=[
                IndexSpec(
                    "ix_conversation_message_conversation_id", ["conversation_id"]
                ),
                IndexSpec("ix_conversation_message_timestamp", ["timestamp"]),
            ],
            foreign_keys=[ForeignKeySpec(["conversation_id"], "conversation", ["id"])],
        ),
    ],
)

AGENTS_MIGRATION = ServiceMigrationSpec(
    service_name="ai_agents",
    description="AI agent registry tables (agents, tools, agent-tool links)",
    tables=[
        # Agent - the DB-driven agent definition. model_id is a plain
        # indexed string, NOT an FK to large_language_model: the catalog
        # is ETL-synced and rows churn, so agents stay decoupled from
        # catalog lifecycle exactly like llm_usage. NULL model_id means
        # "use the service's active model".
        TableSpec(
            name="agent",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("slug", "sa.String()", nullable=False),
                ColumnSpec("name", "sa.String()", nullable=False),
                ColumnSpec("description", "sa.String()", nullable=True),
                ColumnSpec("category", "sa.String()", nullable=True),
                ColumnSpec("model_id", "sa.String()", nullable=True),
                ColumnSpec("system_prompt", "sa.String()", nullable=False),
                ColumnSpec("temperature", "sa.Float()", nullable=False, default="0.7"),
                ColumnSpec(
                    "max_tokens", "sa.Integer()", nullable=False, default="1000"
                ),
                ColumnSpec("memory_modules", "sa.JSON()", nullable=False, default="[]"),
                ColumnSpec(
                    "knowledge_base_ids", "sa.JSON()", nullable=False, default="[]"
                ),
                ColumnSpec("is_active", "sa.Boolean()", nullable=False, default="True"),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_agent_slug", ["slug"], unique=True),
                IndexSpec("ix_agent_model_id", ["model_id"]),
            ],
        ),
        # Tool - registry rows keyed by name into the Python tool registry.
        TableSpec(
            name="tool",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("name", "sa.String()", nullable=False),
                ColumnSpec("description", "sa.String()", nullable=True),
                ColumnSpec("is_active", "sa.Boolean()", nullable=False, default="True"),
            ],
            indexes=[IndexSpec("ix_tool_name", ["name"], unique=True)],
        ),
        # AgentTool - join rows are agent-owned; CASCADE both sides so
        # deleting an agent or a tool cleans its links.
        TableSpec(
            name="agent_tool",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("agent_id", "sa.Integer()", nullable=False),
                ColumnSpec("tool_id", "sa.Integer()", nullable=False),
            ],
            indexes=[
                IndexSpec("uq_agent_tool_pair", ["agent_id", "tool_id"], unique=True),
                IndexSpec("ix_agent_tool_tool_id", ["tool_id"]),
            ],
            foreign_keys=[
                ForeignKeySpec(["agent_id"], "agent", ["id"], ondelete="CASCADE"),
                ForeignKeySpec(["tool_id"], "tool", ["id"], ondelete="CASCADE"),
            ],
        ),
        # MemoryModule - reusable prompt-context blocks agents opt into
        # via Agent.memory_modules. Hybrid by design: a row may carry
        # static prompt_content, a dynamic fetch_function, or both;
        # assembly is column-driven (there is deliberately no "kind").
        TableSpec(
            name="memory_module",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("slug", "sa.String()", nullable=False),
                ColumnSpec("name", "sa.String()", nullable=False),
                ColumnSpec("description", "sa.String()", nullable=True),
                ColumnSpec("category", "sa.String()", nullable=True),
                ColumnSpec("prompt_content", "sa.String()", nullable=True),
                ColumnSpec("fetch_function", "sa.String()", nullable=True),
                ColumnSpec("context_key", "sa.String()", nullable=False),
                ColumnSpec(
                    "supports_days_back",
                    "sa.Boolean()",
                    nullable=False,
                    default="False",
                ),
                ColumnSpec("default_days_back", "sa.Integer()", nullable=True),
                ColumnSpec("priority", "sa.Integer()", nullable=False, default="100"),
                ColumnSpec(
                    "token_estimate", "sa.Integer()", nullable=False, default="0"
                ),
                ColumnSpec("is_active", "sa.Boolean()", nullable=False, default="True"),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[IndexSpec("ix_memory_module_slug", ["slug"], unique=True)],
        ),
        # AgentUserMemory - one JSON memory document per user, written by
        # the built-in save_memory tool and injected (guarded) into chat
        # context. Same gate as the registry, so it rides the same spec.
        TableSpec(
            name="agent_user_memory",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("user_id", "sa.String()", nullable=False),
                ColumnSpec("memory", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_agent_user_memory_user_id", ["user_id"], unique=True),
            ],
        ),
    ],
)

KNOWLEDGE_MIGRATION = ServiceMigrationSpec(
    service_name="ai_knowledge",
    description="Knowledge base metadata (agent-scoped RAG collections)",
    tables=[
        # A knowledge base maps 1:1 onto a Chroma collection by name;
        # agents scope retrieval via Agent.knowledge_base_ids holding
        # these names.
        TableSpec(
            name="knowledge_base",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("name", "sa.String()", nullable=False),
                ColumnSpec("description", "sa.String()", nullable=True),
                ColumnSpec("category", "sa.String()", nullable=True),
                ColumnSpec("meta_data", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec("is_active", "sa.Boolean()", nullable=False, default="True"),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[IndexSpec("ix_knowledge_base_name", ["name"], unique=True)],
        ),
        # A source document within a KB; ``loaded`` gates ingestion state
        # and ``chunking_strategy`` picks the chunker preset per source.
        TableSpec(
            name="knowledge_base_source",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("knowledge_base_id", "sa.Integer()", nullable=False),
                ColumnSpec("name", "sa.String()", nullable=False),
                ColumnSpec("file_path", "sa.String()", nullable=True),
                ColumnSpec("content_type", "sa.String()", nullable=True),
                ColumnSpec(
                    "chunking_strategy",
                    "sa.String()",
                    nullable=False,
                    default="'paragraph'",
                ),
                ColumnSpec("loaded", "sa.Boolean()", nullable=False, default="False"),
                ColumnSpec("meta_data", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec(
                    "ix_knowledge_base_source_knowledge_base_id",
                    ["knowledge_base_id"],
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(
                    ["knowledge_base_id"],
                    "knowledge_base",
                    ["id"],
                    ondelete="CASCADE",
                ),
            ],
            check_constraints=[
                CheckConstraintSpec(
                    name="ck_knowledge_base_source_chunking_strategy",
                    sqltext=(
                        "chunking_strategy IN "
                        "('paragraph', 'sentence', 'fixed', 'code')"
                    ),
                ),
            ],
        ),
    ],
)

SENTIMENT_MIGRATION = ServiceMigrationSpec(
    service_name="ai_sentiment",
    description="Conversation sentiment analysis results",
    tables=[
        # One verdict per conversation (unique conversation_id enforces
        # score-once); rows die with their conversation via CASCADE.
        TableSpec(
            name="sentiment_analysis",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("conversation_id", "sa.String()", nullable=False),
                ColumnSpec("overall_sentiment", "sa.String()", nullable=False),
                ColumnSpec("overall_score", "sa.Float()", nullable=False),
                ColumnSpec("assistant_performance", "sa.String()", nullable=False),
                ColumnSpec("issues", "sa.JSON()", nullable=False, default="[]"),
                ColumnSpec("summary", "sa.String()", nullable=True),
                ColumnSpec("model_id", "sa.String()", nullable=True),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec(
                    "ix_sentiment_analysis_conversation_id",
                    ["conversation_id"],
                    unique=True,
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(
                    ["conversation_id"],
                    "conversation",
                    ["id"],
                    ondelete="CASCADE",
                ),
            ],
            check_constraints=[
                CheckConstraintSpec(
                    name="ck_sentiment_analysis_overall_sentiment",
                    sqltext=(
                        "overall_sentiment IN "
                        "('positive', 'neutral', 'negative', 'frustrated')"
                    ),
                ),
                CheckConstraintSpec(
                    name="ck_sentiment_analysis_assistant_performance",
                    sqltext=("assistant_performance IN ('good', 'acceptable', 'poor')"),
                ),
            ],
        ),
    ],
)

AUTH_TOKENS_MIGRATION = ServiceMigrationSpec(
    service_name="auth_tokens",
    description="Auth token tables (password reset, email verification, refresh)",
    tables=[
        TableSpec(
            name="password_reset_token",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("user_id", "sa.Integer()", nullable=False),
                ColumnSpec("token", "sa.String()", nullable=False),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("used", "sa.Boolean()", nullable=False, default="'false'"),
            ],
            indexes=[
                IndexSpec("ix_password_reset_token_user_id", ["user_id"]),
                IndexSpec("ix_password_reset_token_token", ["token"], unique=True),
            ],
            foreign_keys=[
                ForeignKeySpec(["user_id"], "user", ["id"]),
            ],
        ),
        TableSpec(
            name="email_verification_token",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("user_id", "sa.Integer()", nullable=False),
                ColumnSpec("token", "sa.String()", nullable=False),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("used", "sa.Boolean()", nullable=False, default="'false'"),
            ],
            indexes=[
                IndexSpec("ix_email_verification_token_user_id", ["user_id"]),
                IndexSpec("ix_email_verification_token_token", ["token"], unique=True),
            ],
            foreign_keys=[
                ForeignKeySpec(["user_id"], "user", ["id"]),
            ],
        ),
        # Refresh token + session metadata. ``family_id`` groups all
        # rotations of one device's session; ``source``/``user_agent``/
        # ``ip``/``last_used_at`` power the active-sessions UI (#633).
        # SQLite-only deployments previously got this table via
        # ``SQLModel.metadata.create_all()``; Postgres deployments were
        # broken without this migration spec.
        TableSpec(
            name="refresh_token",
            columns=[
                ColumnSpec("token", "sa.String(64)", nullable=False, primary_key=True),
                ColumnSpec("user_id", "sa.Integer()", nullable=False),
                ColumnSpec("family_id", "sa.String(36)", nullable=False),
                ColumnSpec("expires_at", "sa.DateTime()", nullable=False),
                ColumnSpec("revoked_at", "sa.DateTime()", nullable=True),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("source", "sa.String(32)", nullable=True),
                ColumnSpec("user_agent", "sa.String(512)", nullable=True),
                ColumnSpec("ip", "sa.String(64)", nullable=True),
                ColumnSpec("last_used_at", "sa.DateTime()", nullable=True),
            ],
            indexes=[
                IndexSpec("ix_refresh_token_user_id", ["user_id"]),
                IndexSpec("ix_refresh_token_family_id", ["family_id"]),
                IndexSpec("ix_refresh_token_source", ["source"]),
            ],
            foreign_keys=[
                ForeignKeySpec(["user_id"], "user", ["id"]),
            ],
        ),
    ],
)

VOICE_MIGRATION = ServiceMigrationSpec(
    service_name="ai_voice",
    description="AI voice service table (TTS and STT usage tracking)",
    tables=[
        TableSpec(
            name="voice_usage",
            columns=[
                # === Core (all rows) ===
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec(
                    "usage_type", "sa.String()", nullable=False
                ),  # "tts" | "stt"
                ColumnSpec(
                    "provider", "sa.String()", nullable=False
                ),  # openai, groq, whisper_local
                ColumnSpec(
                    "model", "sa.String()", nullable=True
                ),  # tts-1, whisper-1, etc.
                ColumnSpec("user_id", "sa.String()", nullable=True),
                ColumnSpec("timestamp", "sa.DateTime(timezone=True)", nullable=False),
                ColumnSpec("latency_ms", "sa.Integer()", nullable=True),
                ColumnSpec("total_cost", "sa.Float()", nullable=False, default="0.0"),
                ColumnSpec("success", "sa.Boolean()", nullable=False, default="True"),
                ColumnSpec("error_message", "sa.String()", nullable=True),
                # === TTS-specific (null for STT) ===
                ColumnSpec("voice", "sa.String()", nullable=True),  # alloy, nova, etc.
                ColumnSpec(
                    "input_characters", "sa.Integer()", nullable=True
                ),  # text length
                ColumnSpec(
                    "output_duration_seconds", "sa.Float()", nullable=True
                ),  # audio length
                ColumnSpec(
                    "output_audio_bytes", "sa.Integer()", nullable=True
                ),  # audio size
                # === STT-specific (null for TTS) ===
                ColumnSpec(
                    "input_duration_seconds", "sa.Float()", nullable=True
                ),  # audio length
                ColumnSpec(
                    "input_audio_bytes", "sa.Integer()", nullable=True
                ),  # audio size
                ColumnSpec(
                    "output_characters", "sa.Integer()", nullable=True
                ),  # transcription length
                ColumnSpec(
                    "detected_language", "sa.String()", nullable=True
                ),  # en, es, etc.
            ],
            indexes=[
                IndexSpec("ix_voice_usage_usage_type", ["usage_type"]),
                IndexSpec("ix_voice_usage_provider", ["provider"]),
                IndexSpec("ix_voice_usage_user_id", ["user_id"]),
                IndexSpec("ix_voice_usage_timestamp", ["timestamp"]),
            ],
        ),
    ],
)


def _build_insights_migration(per_user: bool) -> ServiceMigrationSpec:
    """Build the insights migration spec.

    The insights service ships in two shapes, picked by ``insights_per_user``:

    * **Shared mode** (``per_user=False``): just the base tables — source,
      metric_type, metric, event, record. No tenancy. Single-tenant + env
      var driven. No goals (goals are per-user-scoped).
    * **Per-user mode** (``per_user=True``): adds the ``project`` table,
      stamps every metric/event row with a non-null ``project_id`` FK,
      adds ``created_by_user_id`` to events, and creates the user-scoped
      ``insight_goal`` table (with its own ``project_id`` FK).

    Folded into one migration per mode so a fresh DB gets a coherent
    schema in a single revision instead of three layered ones, and there's
    no destructive forward-only step needed for the per-user shape.
    """
    tables: list[TableSpec] = []

    if per_user:
        # `project` must come first — every insights table FKs to it.
        # Org-tenancy: every project belongs to an ``organization`` (auth-
        # shipped). ``owner_user_id`` stays as the implicit owner-membership
        # lookup; once v2 org-aware reads land, ownership transitions to
        # membership-based and ``owner_user_id`` can be dropped.
        tables.append(
            TableSpec(
                name="project",
                columns=[
                    ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                    ColumnSpec("slug", "sa.String(64)", nullable=False),
                    ColumnSpec("name", "sa.String(128)", nullable=False),
                    ColumnSpec("owner_user_id", "sa.Integer()", nullable=False),
                    ColumnSpec("organization_id", "sa.Integer()", nullable=False),
                    ColumnSpec("github_owner", "sa.String(64)", nullable=True),
                    ColumnSpec("github_repo", "sa.String(128)", nullable=True),
                    # github_token / plausible_api_key store ciphertext;
                    # encrypt/decrypt happens in ProjectService.
                    ColumnSpec("github_token", "sa.String(512)", nullable=True),
                    ColumnSpec("pypi_package", "sa.String(128)", nullable=True),
                    ColumnSpec("plausible_site", "sa.String(256)", nullable=True),
                    ColumnSpec("plausible_api_key", "sa.String(512)", nullable=True),
                    ColumnSpec("reddit_subreddits", "sa.String(256)", nullable=True),
                    ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                    ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
                ],
                indexes=[
                    IndexSpec("ix_project_owner_user_id", ["owner_user_id"]),
                    IndexSpec("ix_project_organization_id", ["organization_id"]),
                    IndexSpec("ix_project_slug", ["slug"]),
                    # Slug uniqueness follows the new ownership primitive:
                    # one slug per org, but two different orgs can each
                    # have a project named ``my-thing``.
                    IndexSpec(
                        "uq_project_organization_slug",
                        ["organization_id", "slug"],
                        unique=True,
                    ),
                ],
                foreign_keys=[
                    ForeignKeySpec(["owner_user_id"], "user", ["id"]),
                    ForeignKeySpec(["organization_id"], "organization", ["id"]),
                ],
            )
        )

    # InsightSource — lookup table for data sources.
    tables.append(
        TableSpec(
            name="insight_source",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("key", "sa.String(64)", nullable=False),
                ColumnSpec("display_name", "sa.String(128)", nullable=False),
                ColumnSpec("collection_interval_hours", "sa.Integer()", nullable=True),
                ColumnSpec(
                    "requires_auth", "sa.Boolean()", nullable=False, default="False"
                ),
                ColumnSpec("enabled", "sa.Boolean()", nullable=False, default="True"),
                ColumnSpec("last_collected_at", "sa.DateTime()", nullable=True),
                ColumnSpec("metadata", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_insight_source_key", ["key"], unique=True),
            ],
        )
    )

    # InsightMetricType — metric registry, FK to source.
    tables.append(
        TableSpec(
            name="insight_metric_type",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("source_id", "sa.Integer()", nullable=False),
                ColumnSpec("key", "sa.String(64)", nullable=False),
                ColumnSpec("display_name", "sa.String(128)", nullable=False),
                ColumnSpec("unit", "sa.String(32)", nullable=False),
                ColumnSpec("metadata", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_insight_metric_type_key", ["key"]),
                IndexSpec("ix_insight_metric_type_source_id", ["source_id"]),
                IndexSpec(
                    "uq_metric_type_source_key",
                    ["source_id", "key"],
                    unique=True,
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(["source_id"], "insight_source", ["id"]),
            ],
        )
    )

    # InsightMetric — core time-series data. Per-user mode adds project_id.
    metric_columns = [
        ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
        ColumnSpec("date", "sa.DateTime()", nullable=False),
        ColumnSpec("metric_type_id", "sa.Integer()", nullable=False),
        ColumnSpec("value", "sa.Float()", nullable=False, default="0.0"),
        ColumnSpec("period", "sa.String(32)", nullable=False),
        ColumnSpec("metadata", "sa.JSON()", nullable=False, default="{}"),
        ColumnSpec("created_at", "sa.DateTime()", nullable=False),
    ]
    metric_indexes = [
        IndexSpec("ix_insight_metric_type_date", ["metric_type_id", "date"]),
        IndexSpec("ix_insight_metric_date", ["date"]),
        IndexSpec("ix_insight_metric_metric_type_id", ["metric_type_id"]),
    ]
    metric_fks = [
        ForeignKeySpec(["metric_type_id"], "insight_metric_type", ["id"]),
    ]
    if per_user:
        metric_columns.append(ColumnSpec("project_id", "sa.Integer()", nullable=False))
        metric_indexes.extend(
            [
                IndexSpec("ix_insight_metric_project_id", ["project_id"]),
                IndexSpec("ix_insight_metric_project_date", ["project_id", "date"]),
            ]
        )
        # ON DELETE CASCADE so SQLAlchemy ``passive_deletes=True`` on
        # ``Project.metrics`` resolves end-to-end at the DB level.
        metric_fks.append(
            ForeignKeySpec(["project_id"], "project", ["id"], ondelete="CASCADE")
        )
    tables.append(
        TableSpec(
            name="insight_metric",
            columns=metric_columns,
            indexes=metric_indexes,
            foreign_keys=metric_fks,
        )
    )

    # InsightRecord — all-time records per metric type. Not per-project: a
    # record is the global high-water mark for a metric and lives in the
    # shared lookup space alongside metric_type.
    tables.append(
        TableSpec(
            name="insight_record",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("metric_type_id", "sa.Integer()", nullable=False),
                ColumnSpec("value", "sa.Float()", nullable=False, default="0.0"),
                ColumnSpec("date_achieved", "sa.DateTime()", nullable=False),
                ColumnSpec("previous_value", "sa.Float()", nullable=True),
                ColumnSpec("previous_date", "sa.DateTime()", nullable=True),
                ColumnSpec("context", "sa.String(512)", nullable=True),
                ColumnSpec("metadata", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec(
                    "ix_insight_record_metric_type_id",
                    ["metric_type_id"],
                    unique=True,
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(["metric_type_id"], "insight_metric_type", ["id"]),
            ],
        )
    )

    # InsightEvent — contextual markers. Per-user mode adds project_id +
    # created_by_user_id; shared mode keeps just the base columns.
    event_columns = [
        ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
        ColumnSpec("date", "sa.DateTime()", nullable=False),
        ColumnSpec("event_type", "sa.String(64)", nullable=False),
        ColumnSpec("description", "sa.String(1024)", nullable=False),
        ColumnSpec("metadata", "sa.JSON()", nullable=False, default="{}"),
        # `origin` distinguishes collector output from user-created
        # annotations so the API/UI only exposes user rows for editing.
        ColumnSpec("origin", "sa.String(16)", nullable=False, default="'collector'"),
        ColumnSpec("created_at", "sa.DateTime()", nullable=False),
    ]
    event_indexes = [
        IndexSpec("ix_insight_event_date", ["date"]),
        IndexSpec("ix_insight_event_type_date", ["event_type", "date"]),
        IndexSpec("ix_insight_event_origin", ["origin"]),
        IndexSpec("ix_insight_event_origin_date", ["origin", "date"]),
    ]
    event_fks: list[ForeignKeySpec] = []
    if per_user:
        event_columns.append(ColumnSpec("project_id", "sa.Integer()", nullable=False))
        event_columns.append(
            ColumnSpec("created_by_user_id", "sa.Integer()", nullable=True)
        )
        event_indexes.extend(
            [
                IndexSpec("ix_insight_event_project_id", ["project_id"]),
                IndexSpec("ix_insight_event_project_date", ["project_id", "date"]),
                IndexSpec(
                    "ix_insight_event_created_by_user_id", ["created_by_user_id"]
                ),
            ]
        )
        event_fks.extend(
            [
                # CASCADE on the project FK so deleting a project also
                # drops its events; the user FK stays a plain RESTRICT
                # so deleting a user with authored events errors loudly
                # instead of silently nuking history.
                ForeignKeySpec(["project_id"], "project", ["id"], ondelete="CASCADE"),
                ForeignKeySpec(["created_by_user_id"], "user", ["id"]),
            ]
        )
    tables.append(
        TableSpec(
            name="insight_event",
            columns=event_columns,
            indexes=event_indexes,
            foreign_keys=event_fks,
            check_constraints=[
                CheckConstraintSpec(
                    name="ck_insight_event_origin",
                    sqltext="origin IN ('collector', 'user')",
                ),
            ],
        )
    )

    if per_user:
        # InsightGoal — per-user goals scoped to a project. ``user_id`` is
        # the goal owner (today: project owner; v2 may differ for shared
        # projects). ``project_id`` is the FK that every read filters on.
        tables.append(
            TableSpec(
                name="insight_goal",
                columns=[
                    ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                    ColumnSpec("user_id", "sa.Integer()", nullable=False),
                    ColumnSpec("project_id", "sa.Integer()", nullable=False),
                    ColumnSpec("metric_key", "sa.String(64)", nullable=False),
                    ColumnSpec("kind", "sa.String(16)", nullable=False),
                    ColumnSpec("target_value", "sa.Float()", nullable=False),
                    ColumnSpec("window_days", "sa.Integer()", nullable=True),
                    ColumnSpec("target_date", "sa.Date()", nullable=True),
                    ColumnSpec(
                        "status",
                        "sa.String(16)",
                        nullable=False,
                        default="'active'",
                    ),
                    ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                    ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
                ],
                indexes=[
                    IndexSpec("ix_insight_goal_user_id", ["user_id"]),
                    IndexSpec("ix_insight_goal_project_id", ["project_id"]),
                    IndexSpec("ix_insight_goal_metric_key", ["metric_key"]),
                    IndexSpec("ix_insight_goal_user_status", ["user_id", "status"]),
                    IndexSpec(
                        "ix_insight_goal_project_metric",
                        ["project_id", "metric_key"],
                    ),
                ],
                foreign_keys=[
                    # User FK stays plain RESTRICT (deleting a user with
                    # goals errors loudly). Project FK cascades so
                    # deleting a project drops its goals along with the
                    # rest of its row tree.
                    ForeignKeySpec(["user_id"], "user", ["id"]),
                    ForeignKeySpec(
                        ["project_id"], "project", ["id"], ondelete="CASCADE"
                    ),
                ],
                check_constraints=[
                    CheckConstraintSpec(
                        name="ck_insight_goal_kind",
                        sqltext="kind IN ('absolute', 'delta', 'rate')",
                    ),
                    CheckConstraintSpec(
                        name="ck_insight_goal_status",
                        sqltext="status IN ('active', 'achieved', 'abandoned')",
                    ),
                    CheckConstraintSpec(
                        name="ck_insight_goal_metric_key",
                        sqltext=(
                            "metric_key IN ("
                            "'github.stars', 'github.clones', 'github.unique_cloners', "
                            "'github.views', 'github.unique_visitors', 'github.forks', "
                            "'github.releases', 'pypi.downloads', 'docs.visitors', "
                            "'docs.pageviews'"
                            ")"
                        ),
                    ),
                ],
            )
        )

    description = (
        "Per-user insights tables (project, source/metric_type/metric/event/record, goal)"
        if per_user
        else "Insights service tables (sources, metrics, records, events)"
    )
    return ServiceMigrationSpec(
        service_name="insights",
        description=description,
        tables=tables,
    )


# Default registry-facing variant is the shared-mode shape. Per-user mode
# rebuilds the spec at generation time via _build_insights_migration(True).
INSIGHTS_MIGRATION = _build_insights_migration(per_user=False)


PAYMENT_MIGRATION = ServiceMigrationSpec(
    service_name="payment",
    description="Payment service tables (providers, customers, transactions, subscriptions, disputes)",
    tables=[
        TableSpec(
            name="payment_provider",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("key", "sa.String(32)", nullable=False),
                ColumnSpec("display_name", "sa.String(64)", nullable=False),
                ColumnSpec("enabled", "sa.Boolean()", nullable=False, default="True"),
                ColumnSpec(
                    "is_test_mode", "sa.Boolean()", nullable=False, default="True"
                ),
                ColumnSpec("metadata", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_payment_provider_key", ["key"], unique=True),
            ],
        ),
        TableSpec(
            name="payment_customer",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                # user_id is nullable: anonymous checkouts (guest carts,
                # donations, pre-signup SaaS trials) have no app user yet.
                # An FK to `user.id` is added by the `payment_auth_link`
                # migration when both services are included.
                ColumnSpec("user_id", "sa.Integer()", nullable=True),
                ColumnSpec("provider_id", "sa.Integer()", nullable=False),
                ColumnSpec("provider_customer_id", "sa.String(128)", nullable=False),
                ColumnSpec("email", "sa.String(255)", nullable=True),
                ColumnSpec("metadata", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_payment_customer_user_id", ["user_id"]),
                IndexSpec("ix_payment_customer_provider_id", ["provider_id"]),
                IndexSpec(
                    "ix_payment_customer_provider_customer_id",
                    ["provider_customer_id"],
                ),
                IndexSpec(
                    "uq_provider_customer",
                    ["provider_id", "provider_customer_id"],
                    unique=True,
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(["provider_id"], "payment_provider", ["id"]),
            ],
        ),
        TableSpec(
            name="payment_transaction",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("provider_id", "sa.Integer()", nullable=False),
                ColumnSpec("customer_id", "sa.Integer()", nullable=True),
                ColumnSpec("provider_transaction_id", "sa.String(128)", nullable=False),
                ColumnSpec("type", "sa.String(32)", nullable=False),
                ColumnSpec("status", "sa.String(32)", nullable=False),
                ColumnSpec("amount", "sa.Integer()", nullable=False, default="0"),
                ColumnSpec("currency", "sa.String(3)", nullable=False, default="'usd'"),
                ColumnSpec("description", "sa.String(512)", nullable=True),
                ColumnSpec("metadata", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec(
                    "ix_payment_transaction_provider_transaction_id",
                    ["provider_transaction_id"],
                    unique=True,
                ),
                IndexSpec("ix_payment_transaction_provider_id", ["provider_id"]),
                IndexSpec("ix_payment_transaction_customer_id", ["customer_id"]),
                IndexSpec("ix_payment_transaction_status", ["status"]),
                IndexSpec("ix_payment_txn_status_created", ["status", "created_at"]),
                IndexSpec(
                    "ix_payment_txn_provider_created",
                    ["provider_id", "created_at"],
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(["provider_id"], "payment_provider", ["id"]),
                ForeignKeySpec(["customer_id"], "payment_customer", ["id"]),
            ],
        ),
        TableSpec(
            name="payment_subscription",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("customer_id", "sa.Integer()", nullable=False),
                ColumnSpec(
                    "provider_subscription_id", "sa.String(128)", nullable=False
                ),
                ColumnSpec("plan_name", "sa.String(64)", nullable=False),
                ColumnSpec("status", "sa.String(32)", nullable=False),
                ColumnSpec("current_period_start", "sa.DateTime()", nullable=False),
                ColumnSpec("current_period_end", "sa.DateTime()", nullable=False),
                ColumnSpec(
                    "cancel_at_period_end",
                    "sa.Boolean()",
                    nullable=False,
                    default="False",
                ),
                ColumnSpec("metadata", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec(
                    "ix_payment_subscription_provider_subscription_id",
                    ["provider_subscription_id"],
                    unique=True,
                ),
                IndexSpec("ix_payment_subscription_customer_id", ["customer_id"]),
                IndexSpec("ix_payment_subscription_status", ["status"]),
            ],
            foreign_keys=[
                ForeignKeySpec(["customer_id"], "payment_customer", ["id"]),
            ],
        ),
        TableSpec(
            name="payment_dispute",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("transaction_id", "sa.Integer()", nullable=False),
                ColumnSpec("provider_dispute_id", "sa.String(128)", nullable=False),
                ColumnSpec("status", "sa.String(32)", nullable=False),
                ColumnSpec("reason", "sa.String(64)", nullable=True),
                ColumnSpec("amount", "sa.Integer()", nullable=False, default="0"),
                ColumnSpec("currency", "sa.String(3)", nullable=False, default="'usd'"),
                ColumnSpec("evidence_due_by", "sa.DateTime()", nullable=True),
                ColumnSpec("event_type", "sa.String(64)", nullable=True),
                ColumnSpec("metadata", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec(
                    "ix_payment_dispute_provider_dispute_id",
                    ["provider_dispute_id"],
                    unique=True,
                ),
                IndexSpec("ix_payment_dispute_transaction_id", ["transaction_id"]),
                IndexSpec("ix_payment_dispute_status", ["status"]),
                IndexSpec(
                    "ix_payment_dispute_status_created",
                    ["status", "created_at"],
                ),
                IndexSpec(
                    "ix_payment_dispute_txn_created",
                    ["transaction_id", "created_at"],
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(["transaction_id"], "payment_transaction", ["id"]),
            ],
        ),
    ],
)

PAYMENT_AUTH_LINK_MIGRATION = ServiceMigrationSpec(
    service_name="payment_auth_link",
    description="Link payment_customer.user_id to user.id (auth + payment)",
    tables=[],
    alter_tables=[
        AlterTableSpec(
            name="payment_customer",
            add_foreign_keys=[
                ForeignKeySpec(["user_id"], "user", ["id"]),
            ],
        ),
    ],
)


# Finance service tables. Built up incrementally across the finance schema
# tickets; all live in the default (public) schema so SQLite stacks get the
# migration too (a Postgres-only ``schema=`` would forfeit that). Money and
# scaled-integer columns use BigInteger — net worth / brokerage balances and
# ``*_e8`` quantities/rates overflow int32.
FINANCE_MIGRATION = ServiceMigrationSpec(
    service_name="finance",
    description="Finance service tables (currencies, fx rates)",
    tables=[
        # ----- Group F: reference data -------------------------------------
        TableSpec(
            name="finance_currency",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                # ISO-4217 or crypto ticker, lowercase (usd, eur, btc, usdc).
                ColumnSpec("code", "sa.String(16)", nullable=False),
                ColumnSpec("name", "sa.String(64)", nullable=False),
                ColumnSpec("symbol", "sa.String(8)", nullable=True),
                # Minor-unit exponent: usd=2, jpy=0, btc=8.
                ColumnSpec("decimals", "sa.Integer()", nullable=False, default="2"),
                ColumnSpec("kind", "sa.String(8)", nullable=False, default="'fiat'"),
                ColumnSpec("is_active", "sa.Boolean()", nullable=False, default="True"),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_finance_currency_code", ["code"], unique=True),
                IndexSpec("ix_finance_currency_kind", ["kind"]),
            ],
            check_constraints=[
                CheckConstraintSpec(
                    "ck_finance_currency_kind", "kind IN ('fiat', 'crypto')"
                ),
                CheckConstraintSpec(
                    "ck_finance_currency_decimals", "decimals BETWEEN 0 AND 18"
                ),
            ],
        ),
        TableSpec(
            name="finance_fx_rate",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("base_currency", "sa.String(16)", nullable=False),
                ColumnSpec("quote_currency", "sa.String(16)", nullable=False),
                ColumnSpec("rate_date", "sa.Date()", nullable=False),
                # 1 base = rate_e8 / 1e8 quote. BigInteger: crypto rates × 1e8
                # overflow int32.
                ColumnSpec("rate_e8", "sa.BigInteger()", nullable=False),
                ColumnSpec(
                    "source", "sa.String(16)", nullable=False, default="'manual'"
                ),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec(
                    "ix_finance_fxrate_pair_date",
                    ["base_currency", "quote_currency", "rate_date"],
                ),
                IndexSpec(
                    "uq_finance_fxrate",
                    ["base_currency", "quote_currency", "rate_date", "source"],
                    unique=True,
                ),
            ],
            foreign_keys=[
                # RESTRICT (default): currencies are reference data, never
                # deleted out from under a rate.
                ForeignKeySpec(["base_currency"], "finance_currency", ["code"]),
                ForeignKeySpec(["quote_currency"], "finance_currency", ["code"]),
            ],
            check_constraints=[
                CheckConstraintSpec(
                    "ck_finance_fxrate_source",
                    "source IN ('manual', 'ecb', 'exchange_api', 'coingecko', "
                    "'provider', 'derived')",
                ),
                CheckConstraintSpec(
                    "ck_finance_fxrate_distinct", "base_currency <> quote_currency"
                ),
            ],
        ),
        # ----- Group A: connections & sync ---------------------------------
        TableSpec(
            name="finance_institution",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("provider", "sa.String(16)", nullable=False),
                # Plaid ins_xxx / SnapTrade brokerage id. Growing -> TEXT.
                ColumnSpec("provider_institution_id", "sa.Text()", nullable=True),
                ColumnSpec("name", "sa.String(128)", nullable=False),
                ColumnSpec("domain", "sa.String(255)", nullable=True),
                ColumnSpec("logo_url", "sa.Text()", nullable=True),
                ColumnSpec("primary_color", "sa.String(16)", nullable=True),
                ColumnSpec("url", "sa.Text()", nullable=True),
                ColumnSpec("country", "sa.String(2)", nullable=True),
                ColumnSpec(
                    "oauth_required", "sa.Boolean()", nullable=False, default="False"
                ),
                ColumnSpec(
                    "uses_tokenized_account_numbers",
                    "sa.Boolean()",
                    nullable=False,
                    default="False",
                ),
                ColumnSpec(
                    "uses_app_to_app", "sa.Boolean()", nullable=False, default="False"
                ),
                ColumnSpec(
                    "supported_products", "sa.JSON()", nullable=False, default="[]"
                ),
                ColumnSpec("metadata", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_finance_institution_provider", ["provider"]),
                IndexSpec("ix_finance_institution_name", ["name"]),
                IndexSpec(
                    "uq_finance_institution_provider_extid",
                    ["provider", "provider_institution_id"],
                    unique=True,
                    where="provider_institution_id IS NOT NULL",
                ),
            ],
            check_constraints=[
                CheckConstraintSpec(
                    "ck_finance_institution_provider",
                    "provider IN ('plaid', 'snaptrade', 'coinbase', "
                    "'exchange_key', 'onchain', 'manual')",
                ),
            ],
        ),
        TableSpec(
            name="finance_connection",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                # owner_user_id is nullable: finance runs standalone (single
                # user) without auth. The FK to user.id is added by
                # finance_auth_link when the auth service is also included.
                ColumnSpec("owner_user_id", "sa.Integer()", nullable=True),
                # organization_id is a reserved column (org tenancy not active
                # yet); no FK until orgs go live.
                ColumnSpec("organization_id", "sa.Integer()", nullable=True),
                ColumnSpec("institution_id", "sa.Integer()", nullable=True),
                ColumnSpec("provider", "sa.String(16)", nullable=False),
                ColumnSpec("connection_type", "sa.String(20)", nullable=False),
                ColumnSpec("provider_item_id", "sa.Text()", nullable=True),
                ColumnSpec("label", "sa.String(255)", nullable=True),
                ColumnSpec(
                    "environment",
                    "sa.String(16)",
                    nullable=False,
                    default="'sandbox'",
                ),
                # AES-GCM ciphertext, encrypted/decrypted in the service layer.
                ColumnSpec("access_token_encrypted", "sa.Text()", nullable=True),
                ColumnSpec("api_key_encrypted", "sa.Text()", nullable=True),
                ColumnSpec("api_secret_encrypted", "sa.Text()", nullable=True),
                ColumnSpec("api_passphrase_encrypted", "sa.Text()", nullable=True),
                ColumnSpec("refresh_token_encrypted", "sa.Text()", nullable=True),
                # Public on-chain address is not a secret.
                ColumnSpec("wallet_address", "sa.Text()", nullable=True),
                ColumnSpec("wallet_chain", "sa.Text()", nullable=True),
                ColumnSpec("capabilities", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec(
                    "status", "sa.String(24)", nullable=False, default="'healthy'"
                ),
                ColumnSpec("status_detail", "sa.Text()", nullable=True),
                ColumnSpec("last_error_code", "sa.Text()", nullable=True),
                ColumnSpec(
                    "needs_user_action",
                    "sa.Boolean()",
                    nullable=False,
                    default="False",
                ),
                ColumnSpec("sync_cursor", "sa.Text()", nullable=True),
                ColumnSpec("days_requested", "sa.Integer()", nullable=True),
                ColumnSpec("consent_expiration_at", "sa.DateTime()", nullable=True),
                ColumnSpec("last_successful_sync_at", "sa.DateTime()", nullable=True),
                ColumnSpec("last_sync_attempt_at", "sa.DateTime()", nullable=True),
                ColumnSpec("removed_at", "sa.DateTime()", nullable=True),
                ColumnSpec("deleted_at", "sa.DateTime()", nullable=True),
                ColumnSpec("metadata", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_finance_connection_owner", ["owner_user_id"]),
                IndexSpec("ix_finance_connection_org", ["organization_id"]),
                IndexSpec("ix_finance_connection_institution", ["institution_id"]),
                IndexSpec("ix_finance_connection_needs_action", ["needs_user_action"]),
                IndexSpec("ix_finance_connection_deleted", ["deleted_at"]),
                IndexSpec(
                    "ix_finance_connection_owner_status",
                    ["owner_user_id", "status"],
                ),
                IndexSpec(
                    "uq_finance_connection_provider_item",
                    ["provider", "provider_item_id"],
                    unique=True,
                    where="provider_item_id IS NOT NULL AND deleted_at IS NULL",
                ),
                IndexSpec(
                    "uq_finance_connection_wallet",
                    ["owner_user_id", "provider", "wallet_address"],
                    unique=True,
                    where="wallet_address IS NOT NULL",
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(
                    ["institution_id"],
                    "finance_institution",
                    ["id"],
                    ondelete="SET NULL",
                ),
            ],
            check_constraints=[
                CheckConstraintSpec(
                    "ck_finance_connection_provider",
                    "provider IN ('plaid', 'snaptrade', 'coinbase', "
                    "'exchange_key', 'onchain', 'manual')",
                ),
                CheckConstraintSpec(
                    "ck_finance_connection_type",
                    "connection_type IN ('oauth_access_token', 'api_key_secret', "
                    "'onchain_address', 'aggregator_token', 'manual')",
                ),
                CheckConstraintSpec(
                    "ck_finance_connection_environment",
                    "environment IN ('sandbox', 'production')",
                ),
                CheckConstraintSpec(
                    "ck_finance_connection_status",
                    "status IN ('healthy', 'login_required', 'pending_expiration', "
                    "'pending_disconnect', 'consent_expired', 'revoked', 'error', "
                    "'loading', 'manual')",
                ),
            ],
        ),
        TableSpec(
            name="finance_webhook_event",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("connection_id", "sa.Integer()", nullable=True),
                ColumnSpec("provider", "sa.String(16)", nullable=False),
                ColumnSpec("provider_item_id", "sa.Text()", nullable=True),
                ColumnSpec("webhook_type", "sa.Text()", nullable=True),
                ColumnSpec("webhook_code", "sa.Text()", nullable=True),
                ColumnSpec("provider_event_id", "sa.Text()", nullable=True),
                ColumnSpec("payload", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec(
                    "status", "sa.String(16)", nullable=False, default="'received'"
                ),
                ColumnSpec("error", "sa.Text()", nullable=True),
                ColumnSpec("received_at", "sa.DateTime()", nullable=False),
                ColumnSpec("processed_at", "sa.DateTime()", nullable=True),
            ],
            indexes=[
                IndexSpec("ix_finance_webhook_connection", ["connection_id"]),
                IndexSpec("ix_finance_webhook_item", ["provider_item_id"]),
                IndexSpec(
                    "ix_finance_webhook_status_received", ["status", "received_at"]
                ),
                IndexSpec(
                    "uq_finance_webhook_event",
                    ["provider", "provider_event_id"],
                    unique=True,
                    where="provider_event_id IS NOT NULL",
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(
                    ["connection_id"],
                    "finance_connection",
                    ["id"],
                    ondelete="CASCADE",
                ),
            ],
            check_constraints=[
                CheckConstraintSpec(
                    "ck_finance_webhook_provider",
                    "provider IN ('plaid', 'snaptrade', 'coinbase')",
                ),
                CheckConstraintSpec(
                    "ck_finance_webhook_status",
                    "status IN ('received', 'processed', 'ignored', 'error')",
                ),
            ],
        ),
        # ----- Group B: accounts & balances --------------------------------
        TableSpec(
            name="finance_account",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("owner_user_id", "sa.Integer()", nullable=True),
                ColumnSpec("organization_id", "sa.Integer()", nullable=True),
                # NULL connection => a manual asset (real estate, vehicle, etc.).
                ColumnSpec("connection_id", "sa.Integer()", nullable=True),
                ColumnSpec("institution_id", "sa.Integer()", nullable=True),
                ColumnSpec("provider", "sa.String(16)", nullable=False),
                ColumnSpec("provider_account_id", "sa.Text()", nullable=True),
                # Stable across relinks (a new Item mints a new provider id).
                ColumnSpec("persistent_account_id", "sa.Text()", nullable=True),
                ColumnSpec("name", "sa.String(255)", nullable=False),
                ColumnSpec("official_name", "sa.String(255)", nullable=True),
                ColumnSpec("mask", "sa.String(8)", nullable=True),
                # Plaid top-level type / subtype — growing taxonomy, TEXT.
                ColumnSpec("type", "sa.Text()", nullable=True),
                ColumnSpec("subtype", "sa.Text()", nullable=True),
                # Normalized internal type + classification, STORED for signing.
                ColumnSpec("account_type", "sa.String(24)", nullable=False),
                ColumnSpec("classification", "sa.String(12)", nullable=False),
                ColumnSpec(
                    "currency", "sa.String(16)", nullable=False, default="'usd'"
                ),
                ColumnSpec("current_balance", "sa.BigInteger()", nullable=True),
                ColumnSpec("available_balance", "sa.BigInteger()", nullable=True),
                ColumnSpec("credit_limit", "sa.BigInteger()", nullable=True),
                ColumnSpec("balance_as_of", "sa.DateTime()", nullable=True),
                ColumnSpec(
                    "is_manual", "sa.Boolean()", nullable=False, default="False"
                ),
                ColumnSpec(
                    "is_hidden", "sa.Boolean()", nullable=False, default="False"
                ),
                ColumnSpec(
                    "is_closed", "sa.Boolean()", nullable=False, default="False"
                ),
                ColumnSpec(
                    "is_on_budget", "sa.Boolean()", nullable=False, default="True"
                ),
                ColumnSpec("linked_at", "sa.DateTime()", nullable=True),
                ColumnSpec("last_synced_at", "sa.DateTime()", nullable=True),
                ColumnSpec("deleted_at", "sa.DateTime()", nullable=True),
                ColumnSpec("metadata", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_finance_account_owner", ["owner_user_id"]),
                IndexSpec("ix_finance_account_org", ["organization_id"]),
                IndexSpec("ix_finance_account_connection", ["connection_id"]),
                IndexSpec("ix_finance_account_institution", ["institution_id"]),
                IndexSpec("ix_finance_account_persistent", ["persistent_account_id"]),
                IndexSpec("ix_finance_account_deleted", ["deleted_at"]),
                IndexSpec(
                    "ix_finance_account_owner_type", ["owner_user_id", "account_type"]
                ),
                IndexSpec(
                    "ix_finance_account_owner_classification",
                    ["owner_user_id", "classification"],
                ),
                IndexSpec(
                    "uq_finance_account_provider",
                    ["connection_id", "provider_account_id"],
                    unique=True,
                    where="provider_account_id IS NOT NULL AND deleted_at IS NULL",
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(
                    ["connection_id"],
                    "finance_connection",
                    ["id"],
                    ondelete="CASCADE",
                ),
                ForeignKeySpec(
                    ["institution_id"],
                    "finance_institution",
                    ["id"],
                    ondelete="SET NULL",
                ),
                ForeignKeySpec(["currency"], "finance_currency", ["code"]),
            ],
            check_constraints=[
                CheckConstraintSpec(
                    "ck_finance_account_type",
                    "account_type IN ('checking', 'savings', 'credit_card', 'loan', "
                    "'investment', 'brokerage', 'crypto', 'property', 'vehicle', "
                    "'cash', 'other_asset', 'other_liability')",
                ),
                CheckConstraintSpec(
                    "ck_finance_account_classification",
                    "classification IN ('asset', 'liability')",
                ),
                CheckConstraintSpec(
                    "ck_finance_account_provider",
                    "provider IN ('plaid', 'snaptrade', 'coinbase', 'exchange_key', "
                    "'onchain', 'manual')",
                ),
            ],
        ),
        TableSpec(
            name="finance_liability_detail",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("owner_user_id", "sa.Integer()", nullable=True),
                ColumnSpec("account_id", "sa.Integer()", nullable=False),
                ColumnSpec("liability_type", "sa.Text()", nullable=True),
                ColumnSpec("last_statement_balance", "sa.BigInteger()", nullable=True),
                ColumnSpec("last_statement_issue_date", "sa.Date()", nullable=True),
                ColumnSpec("last_payment_amount", "sa.BigInteger()", nullable=True),
                ColumnSpec("last_payment_date", "sa.Date()", nullable=True),
                ColumnSpec("minimum_payment_amount", "sa.BigInteger()", nullable=True),
                ColumnSpec("next_payment_due_date", "sa.Date()", nullable=True),
                ColumnSpec("origination_date", "sa.Date()", nullable=True),
                ColumnSpec("origination_principal", "sa.BigInteger()", nullable=True),
                ColumnSpec("outstanding_balance", "sa.BigInteger()", nullable=True),
                # basis points (avoids Decimal): 19.99% APR = 1999.
                ColumnSpec("interest_rate_bps", "sa.Integer()", nullable=True),
                ColumnSpec("ytd_interest_paid", "sa.BigInteger()", nullable=True),
                ColumnSpec("ytd_principal_paid", "sa.BigInteger()", nullable=True),
                ColumnSpec("loan_term_months", "sa.Integer()", nullable=True),
                ColumnSpec("is_overdue", "sa.Boolean()", nullable=True),
                ColumnSpec("aprs", "sa.JSON()", nullable=False, default="[]"),
                ColumnSpec(
                    "currency", "sa.String(16)", nullable=False, default="'usd'"
                ),
                ColumnSpec("raw", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_finance_liability_owner", ["owner_user_id"]),
                IndexSpec("ix_finance_liability_account", ["account_id"]),
                IndexSpec("uq_finance_liability_account", ["account_id"], unique=True),
            ],
            foreign_keys=[
                ForeignKeySpec(
                    ["account_id"], "finance_account", ["id"], ondelete="CASCADE"
                ),
                ForeignKeySpec(["currency"], "finance_currency", ["code"]),
            ],
        ),
        TableSpec(
            name="finance_balance_snapshot",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("account_id", "sa.Integer()", nullable=False),
                ColumnSpec("owner_user_id", "sa.Integer()", nullable=True),
                ColumnSpec("organization_id", "sa.Integer()", nullable=True),
                ColumnSpec("balance_date", "sa.Date()", nullable=False),
                ColumnSpec("balance", "sa.BigInteger()", nullable=False, default="0"),
                ColumnSpec("available_balance", "sa.BigInteger()", nullable=True),
                ColumnSpec("cash_balance", "sa.BigInteger()", nullable=True),
                ColumnSpec("holdings_value", "sa.BigInteger()", nullable=True),
                ColumnSpec(
                    "currency", "sa.String(16)", nullable=False, default="'usd'"
                ),
                ColumnSpec("base_currency_value", "sa.BigInteger()", nullable=True),
                ColumnSpec("source", "sa.String(16)", nullable=False, default="'sync'"),
                ColumnSpec(
                    "is_estimated", "sa.Boolean()", nullable=False, default="False"
                ),
            ],
            indexes=[
                IndexSpec(
                    "ix_finance_balsnap_account_date", ["account_id", "balance_date"]
                ),
                IndexSpec(
                    "ix_finance_balsnap_owner_date", ["owner_user_id", "balance_date"]
                ),
                IndexSpec(
                    "uq_finance_balsnap",
                    ["account_id", "balance_date"],
                    unique=True,
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(
                    ["account_id"], "finance_account", ["id"], ondelete="CASCADE"
                ),
                ForeignKeySpec(["currency"], "finance_currency", ["code"]),
            ],
            check_constraints=[
                CheckConstraintSpec(
                    "ck_finance_balsnap_source",
                    "source IN ('sync', 'provider', 'computed', 'carried_forward', "
                    "'manual')",
                ),
            ],
        ),
        TableSpec(
            name="finance_net_worth_snapshot",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("owner_user_id", "sa.Integer()", nullable=True),
                ColumnSpec("organization_id", "sa.Integer()", nullable=True),
                ColumnSpec("as_of_date", "sa.Date()", nullable=False),
                ColumnSpec(
                    "total_assets_amount",
                    "sa.BigInteger()",
                    nullable=False,
                    default="0",
                ),
                ColumnSpec(
                    "total_liabilities_amount",
                    "sa.BigInteger()",
                    nullable=False,
                    default="0",
                ),
                ColumnSpec(
                    "net_worth_amount", "sa.BigInteger()", nullable=False, default="0"
                ),
                ColumnSpec("cash_amount", "sa.BigInteger()", nullable=True),
                ColumnSpec("investments_amount", "sa.BigInteger()", nullable=True),
                ColumnSpec("other_assets_amount", "sa.BigInteger()", nullable=True),
                ColumnSpec(
                    "currency", "sa.String(16)", nullable=False, default="'usd'"
                ),
                ColumnSpec("breakdown", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec(
                    "is_estimated", "sa.Boolean()", nullable=False, default="False"
                ),
            ],
            indexes=[
                IndexSpec(
                    "ix_finance_networth_owner_date", ["owner_user_id", "as_of_date"]
                ),
                IndexSpec(
                    "ix_finance_networth_org_date", ["organization_id", "as_of_date"]
                ),
                IndexSpec(
                    "uq_finance_networth",
                    ["owner_user_id", "as_of_date", "currency"],
                    unique=True,
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(["currency"], "finance_currency", ["code"]),
            ],
        ),
        TableSpec(
            name="finance_valuation",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("owner_user_id", "sa.Integer()", nullable=True),
                ColumnSpec("organization_id", "sa.Integer()", nullable=True),
                ColumnSpec("account_id", "sa.Integer()", nullable=False),
                ColumnSpec("as_of_date", "sa.Date()", nullable=False),
                ColumnSpec("value", "sa.BigInteger()", nullable=False, default="0"),
                ColumnSpec(
                    "currency", "sa.String(16)", nullable=False, default="'usd'"
                ),
                ColumnSpec(
                    "source", "sa.String(16)", nullable=False, default="'manual'"
                ),
                ColumnSpec("source_ref", "sa.Text()", nullable=True),
                ColumnSpec(
                    "is_estimate", "sa.Boolean()", nullable=False, default="False"
                ),
                ColumnSpec("fetched_at", "sa.DateTime()", nullable=True),
                ColumnSpec("is_stale", "sa.Boolean()", nullable=False, default="False"),
                ColumnSpec("stale_after_days", "sa.Integer()", nullable=True),
                ColumnSpec("note", "sa.Text()", nullable=True),
                ColumnSpec("metadata", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec(
                    "ix_finance_valuation_owner_date", ["owner_user_id", "as_of_date"]
                ),
                IndexSpec(
                    "ix_finance_valuation_account_date", ["account_id", "as_of_date"]
                ),
                IndexSpec("ix_finance_valuation_source", ["source"]),
                IndexSpec(
                    "uq_finance_valuation",
                    ["account_id", "as_of_date", "source"],
                    unique=True,
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(
                    ["account_id"], "finance_account", ["id"], ondelete="CASCADE"
                ),
                ForeignKeySpec(["currency"], "finance_currency", ["code"]),
            ],
            check_constraints=[
                CheckConstraintSpec(
                    "ck_finance_valuation_source",
                    "source IN ('manual', 'zillow', 'kbb', 'exchange_api', 'onchain', "
                    "'plaid', 'snaptrade', 'coingecko', 'reconciliation')",
                ),
            ],
        ),
        # ----- Group C (core): transactions, splits, transfers -------------
        # forward/circular FK columns (transfer_group_id, category_id,
        # merchant_id, recurring_stream_id, import_batch_id) are created here
        # WITHOUT their FK; the constraints are added in FINANCE_MIGRATION's
        # alter_tables (transfer_group, this ticket) or later tickets'
        # alter_tables (category/merchant/recurring/import) once the target
        # tables exist — all in the same generated migration file, so the FKs
        # apply after every table is created.
        TableSpec(
            name="finance_transaction",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("owner_user_id", "sa.Integer()", nullable=True),
                ColumnSpec("organization_id", "sa.Integer()", nullable=True),
                ColumnSpec("account_id", "sa.Integer()", nullable=False),
                ColumnSpec("connection_id", "sa.Integer()", nullable=True),
                ColumnSpec("import_batch_id", "sa.Integer()", nullable=True),
                # Dedup: LANE 1 = (account_id, source, external_id);
                # LANE 2 = (account_id, import_hash). ck_dedup_lane forbids both.
                ColumnSpec("source", "sa.String(16)", nullable=False),
                ColumnSpec("external_id", "sa.Text()", nullable=True),
                ColumnSpec("external_id_source", "sa.Text()", nullable=True),
                ColumnSpec("import_hash", "sa.String(64)", nullable=True),
                ColumnSpec(
                    "within_day_ordinal", "sa.Integer()", nullable=False, default="0"
                ),
                ColumnSpec(
                    "dedup_status", "sa.String(16)", nullable=False, default="'unique'"
                ),
                ColumnSpec("canonical_transaction_id", "sa.Integer()", nullable=True),
                ColumnSpec(
                    "source_precedence", "sa.Integer()", nullable=False, default="0"
                ),
                # Sign-normalized (negative = outflow); raw_amount as delivered.
                ColumnSpec("amount", "sa.BigInteger()", nullable=False, default="0"),
                ColumnSpec("raw_amount", "sa.BigInteger()", nullable=True),
                ColumnSpec("raw_sign_convention", "sa.Text()", nullable=True),
                ColumnSpec(
                    "currency", "sa.String(16)", nullable=False, default="'usd'"
                ),
                ColumnSpec("unofficial_currency_code", "sa.Text()", nullable=True),
                ColumnSpec("date", "sa.Date()", nullable=False),
                ColumnSpec("authorized_date", "sa.Date()", nullable=True),
                ColumnSpec("datetime", "sa.DateTime()", nullable=True),
                ColumnSpec("name", "sa.Text()", nullable=True),
                ColumnSpec("original_description", "sa.Text()", nullable=True),
                ColumnSpec("merchant_id", "sa.Integer()", nullable=True),
                ColumnSpec("merchant_name", "sa.Text()", nullable=True),
                ColumnSpec("merchant_entity_id", "sa.Text()", nullable=True),
                ColumnSpec("memo", "sa.Text()", nullable=True),
                ColumnSpec("check_number", "sa.String(32)", nullable=True),
                ColumnSpec("payment_channel", "sa.Text()", nullable=True),
                ColumnSpec("pfc_primary", "sa.Text()", nullable=True),
                ColumnSpec("pfc_detailed", "sa.Text()", nullable=True),
                ColumnSpec("pfc_confidence_level", "sa.Text()", nullable=True),
                ColumnSpec("category_id", "sa.Integer()", nullable=True),
                ColumnSpec(
                    "category_source",
                    "sa.String(12)",
                    nullable=False,
                    default="'unset'",
                ),
                ColumnSpec(
                    "is_user_categorized",
                    "sa.Boolean()",
                    nullable=False,
                    default="False",
                ),
                ColumnSpec(
                    "is_reviewed", "sa.Boolean()", nullable=False, default="False"
                ),
                ColumnSpec("pending", "sa.Boolean()", nullable=False, default="False"),
                ColumnSpec("pending_provider_id", "sa.Text()", nullable=True),
                ColumnSpec("pending_transaction_id", "sa.Integer()", nullable=True),
                ColumnSpec(
                    "status", "sa.String(12)", nullable=False, default="'posted'"
                ),
                ColumnSpec(
                    "is_transfer", "sa.Boolean()", nullable=False, default="False"
                ),
                ColumnSpec("transfer_group_id", "sa.Integer()", nullable=True),
                ColumnSpec(
                    "transfer_pair_transaction_id", "sa.Integer()", nullable=True
                ),
                ColumnSpec("is_split", "sa.Boolean()", nullable=False, default="False"),
                ColumnSpec(
                    "excluded_from_reports",
                    "sa.Boolean()",
                    nullable=False,
                    default="False",
                ),
                ColumnSpec(
                    "is_reversal", "sa.Boolean()", nullable=False, default="False"
                ),
                ColumnSpec("reverses_transaction_id", "sa.Integer()", nullable=True),
                ColumnSpec("recurring_stream_id", "sa.Integer()", nullable=True),
                ColumnSpec(
                    "reconciled_status",
                    "sa.String(12)",
                    nullable=False,
                    default="'uncleared'",
                ),
                ColumnSpec("location", "sa.JSON()", nullable=True),
                ColumnSpec("counterparties", "sa.JSON()", nullable=True),
                ColumnSpec("raw_payload", "sa.JSON()", nullable=True),
                ColumnSpec(
                    "is_removed", "sa.Boolean()", nullable=False, default="False"
                ),
                ColumnSpec("removed_at", "sa.DateTime()", nullable=True),
                ColumnSpec("deleted_at", "sa.DateTime()", nullable=True),
                ColumnSpec("metadata", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_finance_txn_owner_date", ["owner_user_id", "date"]),
                IndexSpec("ix_finance_txn_account_date", ["account_id", "date"]),
                IndexSpec(
                    "ix_finance_txn_owner_cat_date",
                    ["owner_user_id", "category_id", "date"],
                ),
                IndexSpec("ix_finance_txn_merchant", ["merchant_id"]),
                IndexSpec("ix_finance_txn_merchant_entity", ["merchant_entity_id"]),
                IndexSpec("ix_finance_txn_category", ["category_id"]),
                IndexSpec("ix_finance_txn_connection", ["connection_id"]),
                IndexSpec("ix_finance_txn_batch", ["import_batch_id"]),
                IndexSpec("ix_finance_txn_recurring", ["recurring_stream_id"]),
                IndexSpec("ix_finance_txn_transfer_group", ["transfer_group_id"]),
                IndexSpec("ix_finance_txn_canonical", ["canonical_transaction_id"]),
                IndexSpec("ix_finance_txn_pending_link", ["pending_transaction_id"]),
                IndexSpec("ix_finance_txn_pair", ["transfer_pair_transaction_id"]),
                IndexSpec("ix_finance_txn_reverses", ["reverses_transaction_id"]),
                IndexSpec("ix_finance_txn_pending", ["pending"]),
                IndexSpec("ix_finance_txn_is_transfer", ["is_transfer"]),
                IndexSpec("ix_finance_txn_deleted", ["deleted_at"]),
                IndexSpec(
                    "uq_finance_txn_external",
                    ["account_id", "source", "external_id"],
                    unique=True,
                    where="external_id IS NOT NULL AND deleted_at IS NULL",
                ),
                IndexSpec(
                    "uq_finance_txn_hash",
                    ["account_id", "import_hash"],
                    unique=True,
                    where=(
                        "external_id IS NULL AND import_hash IS NOT NULL "
                        "AND deleted_at IS NULL"
                    ),
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(
                    ["account_id"], "finance_account", ["id"], ondelete="CASCADE"
                ),
                ForeignKeySpec(
                    ["connection_id"],
                    "finance_connection",
                    ["id"],
                    ondelete="SET NULL",
                ),
                ForeignKeySpec(["currency"], "finance_currency", ["code"]),
                # Self-FKs (nullable) — pending/canonical/pair/reversal linkage.
                ForeignKeySpec(
                    ["canonical_transaction_id"],
                    "finance_transaction",
                    ["id"],
                    ondelete="SET NULL",
                ),
                ForeignKeySpec(
                    ["pending_transaction_id"],
                    "finance_transaction",
                    ["id"],
                    ondelete="SET NULL",
                ),
                ForeignKeySpec(
                    ["transfer_pair_transaction_id"],
                    "finance_transaction",
                    ["id"],
                    ondelete="SET NULL",
                ),
                ForeignKeySpec(
                    ["reverses_transaction_id"],
                    "finance_transaction",
                    ["id"],
                    ondelete="SET NULL",
                ),
            ],
            check_constraints=[
                CheckConstraintSpec(
                    "ck_finance_txn_source",
                    "source IN ('plaid', 'snaptrade', 'ofx', 'qfx', 'qif', 'csv', "
                    "'manual', 'coinbase', 'onchain', 'simplefin', 'teller')",
                ),
                CheckConstraintSpec(
                    "ck_finance_txn_status",
                    "status IN ('pending', 'posted', 'removed')",
                ),
                CheckConstraintSpec(
                    "ck_finance_txn_dedup_status",
                    "dedup_status IN ('unique', 'primary', 'duplicate', 'linked')",
                ),
                CheckConstraintSpec(
                    "ck_finance_txn_category_source",
                    "category_source IN ('provider', 'ml', 'rule', 'user', 'unset')",
                ),
                CheckConstraintSpec(
                    "ck_finance_txn_reconciled",
                    "reconciled_status IN ('uncleared', 'cleared', 'reconciled')",
                ),
                # A row occupies exactly one dedup lane.
                CheckConstraintSpec(
                    "ck_finance_txn_dedup_lane",
                    "NOT (external_id IS NOT NULL AND import_hash IS NOT NULL)",
                ),
            ],
        ),
        TableSpec(
            name="finance_transaction_split",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("owner_user_id", "sa.Integer()", nullable=True),
                ColumnSpec("parent_transaction_id", "sa.Integer()", nullable=False),
                ColumnSpec("category_id", "sa.Integer()", nullable=True),
                ColumnSpec("merchant_id", "sa.Integer()", nullable=True),
                ColumnSpec("amount", "sa.BigInteger()", nullable=False, default="0"),
                ColumnSpec(
                    "currency", "sa.String(16)", nullable=False, default="'usd'"
                ),
                ColumnSpec("memo", "sa.Text()", nullable=True),
                ColumnSpec("sort_order", "sa.Integer()", nullable=False, default="0"),
                ColumnSpec("note", "sa.Text()", nullable=True),
            ],
            indexes=[
                IndexSpec("ix_finance_split_parent", ["parent_transaction_id"]),
                IndexSpec("ix_finance_split_owner", ["owner_user_id"]),
                IndexSpec("ix_finance_split_category", ["category_id"]),
                IndexSpec("ix_finance_split_merchant", ["merchant_id"]),
                IndexSpec(
                    "uq_finance_split_parent_sort",
                    ["parent_transaction_id", "sort_order"],
                    unique=True,
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(
                    ["parent_transaction_id"],
                    "finance_transaction",
                    ["id"],
                    ondelete="CASCADE",
                ),
                ForeignKeySpec(["currency"], "finance_currency", ["code"]),
            ],
        ),
        TableSpec(
            name="finance_transfer",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("owner_user_id", "sa.Integer()", nullable=True),
                ColumnSpec("organization_id", "sa.Integer()", nullable=True),
                ColumnSpec("from_account_id", "sa.Integer()", nullable=True),
                ColumnSpec("to_account_id", "sa.Integer()", nullable=True),
                ColumnSpec("from_transaction_id", "sa.Integer()", nullable=True),
                ColumnSpec("to_transaction_id", "sa.Integer()", nullable=True),
                ColumnSpec("amount", "sa.BigInteger()", nullable=True),
                ColumnSpec(
                    "currency", "sa.String(16)", nullable=False, default="'usd'"
                ),
                ColumnSpec("transfer_date", "sa.Date()", nullable=True),
                ColumnSpec("transfer_group_key", "sa.Text()", nullable=True),
                ColumnSpec(
                    "is_credit_card_payment",
                    "sa.Boolean()",
                    nullable=False,
                    default="False",
                ),
                ColumnSpec("match_method", "sa.String(20)", nullable=False),
                ColumnSpec("confidence", "sa.Integer()", nullable=True),
                ColumnSpec(
                    "status", "sa.String(12)", nullable=False, default="'suggested'"
                ),
            ],
            indexes=[
                IndexSpec("ix_finance_transfer_owner", ["owner_user_id"]),
                IndexSpec("ix_finance_transfer_from_account", ["from_account_id"]),
                IndexSpec("ix_finance_transfer_to_account", ["to_account_id"]),
                IndexSpec("ix_finance_transfer_from_txn", ["from_transaction_id"]),
                IndexSpec("ix_finance_transfer_to_txn", ["to_transaction_id"]),
                IndexSpec("ix_finance_transfer_group_key", ["transfer_group_key"]),
                IndexSpec(
                    "uq_finance_transfer_from",
                    ["from_transaction_id"],
                    unique=True,
                    where="from_transaction_id IS NOT NULL",
                ),
                IndexSpec(
                    "uq_finance_transfer_to",
                    ["to_transaction_id"],
                    unique=True,
                    where="to_transaction_id IS NOT NULL",
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(
                    ["from_account_id"],
                    "finance_account",
                    ["id"],
                    ondelete="SET NULL",
                ),
                ForeignKeySpec(
                    ["to_account_id"], "finance_account", ["id"], ondelete="SET NULL"
                ),
                ForeignKeySpec(
                    ["from_transaction_id"],
                    "finance_transaction",
                    ["id"],
                    ondelete="CASCADE",
                ),
                ForeignKeySpec(
                    ["to_transaction_id"],
                    "finance_transaction",
                    ["id"],
                    ondelete="CASCADE",
                ),
                ForeignKeySpec(["currency"], "finance_currency", ["code"]),
            ],
            check_constraints=[
                CheckConstraintSpec(
                    "ck_finance_transfer_method",
                    "match_method IN ('auto_amount_date', 'plaid_transfer', "
                    "'user_manual', 'rule')",
                ),
                CheckConstraintSpec(
                    "ck_finance_transfer_status",
                    "status IN ('suggested', 'confirmed', 'rejected')",
                ),
                CheckConstraintSpec(
                    "ck_finance_transfer_distinct",
                    "from_transaction_id IS NULL OR to_transaction_id IS NULL "
                    "OR from_transaction_id <> to_transaction_id",
                ),
            ],
        ),
        # ----- Group D (ref): categories, merchants, tags, rules ----------
        # These resolve the category_id / merchant_id forward FKs left as plain
        # columns on finance_transaction and finance_transaction_split; the FKs
        # are added below in alter_tables, after these target tables exist.
        TableSpec(
            name="finance_category",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                # NULL owner = system/global seed row (Plaid PFC tree).
                ColumnSpec("owner_user_id", "sa.Integer()", nullable=True),
                ColumnSpec("organization_id", "sa.Integer()", nullable=True),
                ColumnSpec("parent_id", "sa.Integer()", nullable=True),
                ColumnSpec("name", "sa.String(128)", nullable=False),
                ColumnSpec("slug", "sa.String(96)", nullable=False),
                ColumnSpec("classification", "sa.String(12)", nullable=False),
                ColumnSpec("plaid_pfc_primary", "sa.Text()", nullable=True),
                ColumnSpec("plaid_pfc_detailed", "sa.Text()", nullable=True),
                ColumnSpec("icon", "sa.String(64)", nullable=True),
                ColumnSpec("color", "sa.String(16)", nullable=True),
                ColumnSpec(
                    "is_system", "sa.Boolean()", nullable=False, default="False"
                ),
                ColumnSpec(
                    "is_archived", "sa.Boolean()", nullable=False, default="False"
                ),
                ColumnSpec("sort_order", "sa.Integer()", nullable=False, default="0"),
                ColumnSpec("tax_line", "sa.Text()", nullable=True),
                ColumnSpec("metadata", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_finance_category_owner", ["owner_user_id"]),
                IndexSpec("ix_finance_category_parent", ["parent_id"]),
                IndexSpec("ix_finance_category_pfc", ["plaid_pfc_detailed"]),
                IndexSpec(
                    "uq_finance_category_system_slug",
                    ["slug"],
                    unique=True,
                    where="owner_user_id IS NULL",
                ),
                IndexSpec(
                    "uq_finance_category_user_slug",
                    ["owner_user_id", "slug"],
                    unique=True,
                    where="owner_user_id IS NOT NULL",
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(
                    ["parent_id"], "finance_category", ["id"], ondelete="SET NULL"
                ),
            ],
            check_constraints=[
                CheckConstraintSpec(
                    "ck_finance_category_classification",
                    "classification IN ('income', 'expense', 'transfer')",
                ),
            ],
        ),
        TableSpec(
            name="finance_category_alias",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("owner_user_id", "sa.Integer()", nullable=True),
                ColumnSpec("category_id", "sa.Integer()", nullable=False),
                ColumnSpec("alias_text", "sa.Text()", nullable=False),
                ColumnSpec("normalized_alias", "sa.Text()", nullable=False),
                ColumnSpec("source", "sa.Text()", nullable=True),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_finance_catalias_owner", ["owner_user_id"]),
                IndexSpec("ix_finance_catalias_category", ["category_id"]),
                IndexSpec("ix_finance_catalias_normalized", ["normalized_alias"]),
                IndexSpec(
                    "uq_finance_catalias_owner_norm",
                    ["owner_user_id", "normalized_alias"],
                    unique=True,
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(
                    ["category_id"], "finance_category", ["id"], ondelete="CASCADE"
                ),
            ],
        ),
        TableSpec(
            name="finance_merchant",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                # NULL owner = global/provider-seeded merchant.
                ColumnSpec("owner_user_id", "sa.Integer()", nullable=True),
                ColumnSpec("organization_id", "sa.Integer()", nullable=True),
                ColumnSpec("name", "sa.String(255)", nullable=False),
                ColumnSpec("normalized_name", "sa.String(255)", nullable=False),
                ColumnSpec("source", "sa.String(12)", nullable=False),
                ColumnSpec("provider_merchant_id", "sa.Text()", nullable=True),
                ColumnSpec("logo_url", "sa.Text()", nullable=True),
                ColumnSpec("website_url", "sa.Text()", nullable=True),
                ColumnSpec("default_category_id", "sa.Integer()", nullable=True),
                ColumnSpec("service_type", "sa.Text()", nullable=True),
                ColumnSpec("deleted_at", "sa.DateTime()", nullable=True),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_finance_merchant_owner", ["owner_user_id"]),
                IndexSpec("ix_finance_merchant_org", ["organization_id"]),
                IndexSpec("ix_finance_merchant_normalized", ["normalized_name"]),
                IndexSpec("ix_finance_merchant_default_cat", ["default_category_id"]),
                IndexSpec("ix_finance_merchant_deleted", ["deleted_at"]),
                IndexSpec(
                    "uq_finance_merchant_global",
                    ["normalized_name"],
                    unique=True,
                    where="owner_user_id IS NULL AND deleted_at IS NULL",
                ),
                IndexSpec(
                    "uq_finance_merchant_user",
                    ["owner_user_id", "normalized_name"],
                    unique=True,
                    where="owner_user_id IS NOT NULL AND deleted_at IS NULL",
                ),
                IndexSpec(
                    "uq_finance_merchant_provider",
                    ["source", "provider_merchant_id"],
                    unique=True,
                    where="provider_merchant_id IS NOT NULL",
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(
                    ["default_category_id"],
                    "finance_category",
                    ["id"],
                    ondelete="SET NULL",
                ),
            ],
            check_constraints=[
                CheckConstraintSpec(
                    "ck_finance_merchant_source",
                    "source IN ('plaid', 'user', 'system', 'rule', 'snaptrade')",
                ),
            ],
        ),
        TableSpec(
            name="finance_tag",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("owner_user_id", "sa.Integer()", nullable=False),
                ColumnSpec("organization_id", "sa.Integer()", nullable=True),
                ColumnSpec("name", "sa.String(64)", nullable=False),
                ColumnSpec("normalized_name", "sa.String(64)", nullable=False),
                ColumnSpec("color", "sa.String(16)", nullable=True),
                ColumnSpec("deleted_at", "sa.DateTime()", nullable=True),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_finance_tag_owner", ["owner_user_id"]),
                IndexSpec("ix_finance_tag_org", ["organization_id"]),
                IndexSpec("ix_finance_tag_deleted", ["deleted_at"]),
                IndexSpec(
                    "uq_finance_tag_owner_name",
                    ["owner_user_id", "normalized_name"],
                    unique=True,
                    where="deleted_at IS NULL",
                ),
            ],
        ),
        TableSpec(
            name="finance_transaction_tag",
            columns=[
                # Composite PK (transaction_id, tag_id) — pure join table.
                ColumnSpec(
                    "transaction_id", "sa.Integer()", nullable=False, primary_key=True
                ),
                ColumnSpec("tag_id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("split_id", "sa.Integer()", nullable=True),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_finance_txntag_tag", ["tag_id"]),
                IndexSpec("ix_finance_txntag_split", ["split_id"]),
            ],
            foreign_keys=[
                ForeignKeySpec(
                    ["transaction_id"],
                    "finance_transaction",
                    ["id"],
                    ondelete="CASCADE",
                ),
                ForeignKeySpec(["tag_id"], "finance_tag", ["id"], ondelete="CASCADE"),
                ForeignKeySpec(
                    ["split_id"],
                    "finance_transaction_split",
                    ["id"],
                    ondelete="CASCADE",
                ),
            ],
        ),
        TableSpec(
            name="finance_rule",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("owner_user_id", "sa.Integer()", nullable=False),
                ColumnSpec("organization_id", "sa.Integer()", nullable=True),
                ColumnSpec("name", "sa.String(128)", nullable=False),
                ColumnSpec("priority", "sa.Integer()", nullable=False, default="100"),
                ColumnSpec(
                    "is_enabled", "sa.Boolean()", nullable=False, default="True"
                ),
                ColumnSpec("conditions", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec("actions", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec(
                    "stop_processing", "sa.Boolean()", nullable=False, default="False"
                ),
                ColumnSpec("match_count", "sa.Integer()", nullable=False, default="0"),
                ColumnSpec("last_matched_at", "sa.DateTime()", nullable=True),
                ColumnSpec("deleted_at", "sa.DateTime()", nullable=True),
                ColumnSpec("metadata", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_finance_rule_owner", ["owner_user_id"]),
                IndexSpec("ix_finance_rule_org", ["organization_id"]),
                IndexSpec(
                    "ix_finance_rule_owner_priority", ["owner_user_id", "priority"]
                ),
                IndexSpec("ix_finance_rule_deleted", ["deleted_at"]),
            ],
        ),
        # ----- Group E (investments): securities, prices, holdings, trades -
        TableSpec(
            name="finance_security",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                # Global catalog — no owner. All taxonomy fields are plain text.
                ColumnSpec("provider", "sa.Text()", nullable=True),
                ColumnSpec("provider_security_id", "sa.Text()", nullable=True),
                ColumnSpec("figi", "sa.Text()", nullable=True),
                ColumnSpec("cusip", "sa.String(16)", nullable=True),
                ColumnSpec("isin", "sa.String(16)", nullable=True),
                ColumnSpec("sedol", "sa.String(16)", nullable=True),
                ColumnSpec("ticker", "sa.String(32)", nullable=True),
                ColumnSpec("name", "sa.Text()", nullable=True),
                ColumnSpec("security_type", "sa.Text()", nullable=True),
                ColumnSpec("exchange_mic", "sa.String(10)", nullable=True),
                ColumnSpec("exchange_operating_mic", "sa.String(10)", nullable=True),
                ColumnSpec("country_code", "sa.String(2)", nullable=True),
                ColumnSpec("currency", "sa.String(16)", nullable=True),
                ColumnSpec(
                    "is_cash_equivalent",
                    "sa.Boolean()",
                    nullable=False,
                    default="False",
                ),
                ColumnSpec(
                    "is_crypto", "sa.Boolean()", nullable=False, default="False"
                ),
                ColumnSpec("coingecko_id", "sa.Text()", nullable=True),
                ColumnSpec("onchain_contract", "sa.Text()", nullable=True),
                ColumnSpec("onchain_chain", "sa.Text()", nullable=True),
                ColumnSpec("close_price", "sa.BigInteger()", nullable=True),
                ColumnSpec("price_scale", "sa.Integer()", nullable=False, default="2"),
                ColumnSpec("close_price_as_of", "sa.Date()", nullable=True),
                ColumnSpec("metadata", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_finance_security_ticker", ["ticker"]),
                IndexSpec("ix_finance_security_cusip", ["cusip"]),
                IndexSpec("ix_finance_security_isin", ["isin"]),
                IndexSpec(
                    "ix_finance_security_provider_secid", ["provider_security_id"]
                ),
                IndexSpec("ix_finance_security_type", ["security_type"]),
                IndexSpec(
                    "uq_finance_security_provider",
                    ["provider", "provider_security_id"],
                    unique=True,
                    where="provider_security_id IS NOT NULL",
                ),
                IndexSpec(
                    "uq_finance_security_figi",
                    ["figi"],
                    unique=True,
                    where="figi IS NOT NULL",
                ),
                IndexSpec(
                    "uq_finance_security_cusip",
                    ["cusip"],
                    unique=True,
                    where="cusip IS NOT NULL",
                ),
                IndexSpec(
                    "uq_finance_security_isin",
                    ["isin"],
                    unique=True,
                    where="isin IS NOT NULL",
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(["currency"], "finance_currency", ["code"]),
            ],
        ),
        TableSpec(
            name="finance_security_price",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("security_id", "sa.Integer()", nullable=False),
                ColumnSpec("price_date", "sa.Date()", nullable=False),
                ColumnSpec("close_price", "sa.BigInteger()", nullable=False),
                ColumnSpec("price_scale", "sa.Integer()", nullable=False, default="2"),
                ColumnSpec("currency", "sa.String(16)", nullable=False),
                ColumnSpec("source", "sa.String(16)", nullable=False),
            ],
            indexes=[
                IndexSpec(
                    "ix_finance_secprice_security_date",
                    ["security_id", "price_date"],
                ),
                IndexSpec(
                    "uq_finance_secprice",
                    ["security_id", "price_date", "source"],
                    unique=True,
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(
                    ["security_id"], "finance_security", ["id"], ondelete="CASCADE"
                ),
                ForeignKeySpec(["currency"], "finance_currency", ["code"]),
            ],
            check_constraints=[
                CheckConstraintSpec(
                    "ck_finance_secprice_source",
                    "source IN ('plaid', 'snaptrade', 'exchange_api', 'onchain', "
                    "'coingecko', 'manual', 'market_data')",
                ),
            ],
        ),
        TableSpec(
            name="finance_holding",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("owner_user_id", "sa.Integer()", nullable=False),
                ColumnSpec("organization_id", "sa.Integer()", nullable=True),
                ColumnSpec("account_id", "sa.Integer()", nullable=False),
                ColumnSpec("security_id", "sa.Integer()", nullable=False),
                ColumnSpec("as_of_date", "sa.Date()", nullable=False),
                # Units x 1e8 (fractional shares + crypto).
                ColumnSpec("quantity_e8", "sa.BigInteger()", nullable=False),
                ColumnSpec("cost_basis", "sa.BigInteger()", nullable=True),
                ColumnSpec("average_cost", "sa.BigInteger()", nullable=True),
                ColumnSpec("price", "sa.BigInteger()", nullable=True),
                ColumnSpec("price_scale", "sa.Integer()", nullable=False, default="2"),
                ColumnSpec("institution_value", "sa.BigInteger()", nullable=True),
                ColumnSpec("vested_quantity_e8", "sa.BigInteger()", nullable=True),
                ColumnSpec("currency", "sa.String(16)", nullable=False),
                ColumnSpec("source", "sa.Text()", nullable=True),
                ColumnSpec("deleted_at", "sa.DateTime()", nullable=True),
                ColumnSpec("metadata", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_finance_holding_owner", ["owner_user_id"]),
                IndexSpec("ix_finance_holding_account", ["account_id"]),
                IndexSpec("ix_finance_holding_security", ["security_id"]),
                IndexSpec(
                    "ix_finance_holding_account_date", ["account_id", "as_of_date"]
                ),
                IndexSpec("ix_finance_holding_deleted", ["deleted_at"]),
                IndexSpec(
                    "uq_finance_holding",
                    ["account_id", "security_id", "as_of_date"],
                    unique=True,
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(
                    ["account_id"], "finance_account", ["id"], ondelete="CASCADE"
                ),
                # RESTRICT: a security with holdings can't be deleted (plain FK
                # = NO ACTION, same guard, matching the currency-FK convention).
                ForeignKeySpec(["security_id"], "finance_security", ["id"]),
                ForeignKeySpec(["currency"], "finance_currency", ["code"]),
            ],
        ),
        TableSpec(
            name="finance_trade",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("owner_user_id", "sa.Integer()", nullable=False),
                ColumnSpec("organization_id", "sa.Integer()", nullable=True),
                ColumnSpec("account_id", "sa.Integer()", nullable=False),
                ColumnSpec("security_id", "sa.Integer()", nullable=True),
                ColumnSpec("transaction_id", "sa.Integer()", nullable=True),
                ColumnSpec("connection_id", "sa.Integer()", nullable=True),
                # Forward FK (finance_import_batch, FIN-10) — plain column here.
                ColumnSpec("import_batch_id", "sa.Integer()", nullable=True),
                # Same dual-lane dedup as cash transactions.
                ColumnSpec("source", "sa.String(16)", nullable=False),
                ColumnSpec("external_id", "sa.Text()", nullable=True),
                ColumnSpec("external_id_source", "sa.Text()", nullable=True),
                ColumnSpec("import_hash", "sa.String(64)", nullable=True),
                ColumnSpec("type", "sa.String(16)", nullable=False),
                ColumnSpec("subtype", "sa.Text()", nullable=True),
                ColumnSpec("quantity_e8", "sa.BigInteger()", nullable=True),
                ColumnSpec("price", "sa.BigInteger()", nullable=True),
                ColumnSpec("price_scale", "sa.Integer()", nullable=False, default="2"),
                ColumnSpec("amount", "sa.BigInteger()", nullable=False, default="0"),
                ColumnSpec("raw_amount", "sa.BigInteger()", nullable=True),
                ColumnSpec("fees", "sa.BigInteger()", nullable=True),
                ColumnSpec("currency", "sa.String(16)", nullable=False),
                ColumnSpec("trade_date", "sa.Date()", nullable=False),
                ColumnSpec("settle_date", "sa.Date()", nullable=True),
                ColumnSpec("datetime", "sa.DateTime()", nullable=True),
                ColumnSpec("name", "sa.Text()", nullable=True),
                ColumnSpec("pending", "sa.Boolean()", nullable=False, default="False"),
                ColumnSpec("raw_payload", "sa.JSON()", nullable=True),
                ColumnSpec(
                    "is_removed", "sa.Boolean()", nullable=False, default="False"
                ),
                ColumnSpec("deleted_at", "sa.DateTime()", nullable=True),
                ColumnSpec("metadata", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec(
                    "ix_finance_trade_owner_date", ["owner_user_id", "trade_date"]
                ),
                IndexSpec(
                    "ix_finance_trade_account_date", ["account_id", "trade_date"]
                ),
                IndexSpec("ix_finance_trade_security", ["security_id"]),
                IndexSpec("ix_finance_trade_transaction", ["transaction_id"]),
                IndexSpec("ix_finance_trade_connection", ["connection_id"]),
                IndexSpec("ix_finance_trade_batch", ["import_batch_id"]),
                IndexSpec("ix_finance_trade_deleted", ["deleted_at"]),
                IndexSpec(
                    "uq_finance_trade_external",
                    ["account_id", "source", "external_id"],
                    unique=True,
                    where="external_id IS NOT NULL AND deleted_at IS NULL",
                ),
                IndexSpec(
                    "uq_finance_trade_hash",
                    ["account_id", "import_hash"],
                    unique=True,
                    where=(
                        "external_id IS NULL AND import_hash IS NOT NULL "
                        "AND deleted_at IS NULL"
                    ),
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(
                    ["account_id"], "finance_account", ["id"], ondelete="CASCADE"
                ),
                ForeignKeySpec(
                    ["security_id"], "finance_security", ["id"], ondelete="SET NULL"
                ),
                ForeignKeySpec(
                    ["transaction_id"],
                    "finance_transaction",
                    ["id"],
                    ondelete="SET NULL",
                ),
                ForeignKeySpec(
                    ["connection_id"],
                    "finance_connection",
                    ["id"],
                    ondelete="SET NULL",
                ),
                ForeignKeySpec(["currency"], "finance_currency", ["code"]),
            ],
            check_constraints=[
                CheckConstraintSpec(
                    "ck_finance_trade_source",
                    "source IN ('plaid', 'snaptrade', 'ofx', 'qfx', 'csv', "
                    "'manual', 'coinbase', 'onchain')",
                ),
                CheckConstraintSpec(
                    "ck_finance_trade_type",
                    "type IN ('buy', 'sell', 'dividend', 'interest', 'fee', "
                    "'tax', 'transfer_in', 'transfer_out', 'deposit', "
                    "'withdrawal', 'reinvest', 'split', 'cancel', 'other')",
                ),
                CheckConstraintSpec(
                    "ck_finance_trade_dedup_lane",
                    "NOT (external_id IS NOT NULL AND import_hash IS NOT NULL)",
                ),
            ],
        ),
        # ----- Group F (analytics / import): recurring streams, budgets,
        # baselines, insights, import pipeline, attachments, changelog -----
        # finance_recurring_stream resolves finance_transaction.recurring_
        # stream_id; finance_import_batch resolves the import_batch_id forward
        # FKs on finance_transaction and finance_trade (all added below in
        # alter_tables once these tables exist).
        TableSpec(
            name="finance_recurring_stream",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("owner_user_id", "sa.Integer()", nullable=False),
                ColumnSpec("organization_id", "sa.Integer()", nullable=True),
                ColumnSpec("account_id", "sa.Integer()", nullable=True),
                ColumnSpec("merchant_id", "sa.Integer()", nullable=True),
                ColumnSpec("category_id", "sa.Integer()", nullable=True),
                ColumnSpec("connection_id", "sa.Integer()", nullable=True),
                ColumnSpec("provider_stream_id", "sa.Text()", nullable=True),
                ColumnSpec("name", "sa.String(255)", nullable=False),
                ColumnSpec("normalized_payee", "sa.Text()", nullable=True),
                ColumnSpec("direction", "sa.String(8)", nullable=False),
                ColumnSpec("frequency", "sa.String(16)", nullable=False),
                ColumnSpec("average_amount", "sa.BigInteger()", nullable=True),
                ColumnSpec("last_amount", "sa.BigInteger()", nullable=True),
                ColumnSpec("expected_amount", "sa.BigInteger()", nullable=True),
                ColumnSpec(
                    "amount_is_variable",
                    "sa.Boolean()",
                    nullable=False,
                    default="False",
                ),
                ColumnSpec("amount_tolerance_bps", "sa.Integer()", nullable=True),
                ColumnSpec(
                    "currency", "sa.String(16)", nullable=False, default="'usd'"
                ),
                ColumnSpec("first_date", "sa.Date()", nullable=True),
                ColumnSpec("last_date", "sa.Date()", nullable=True),
                ColumnSpec("next_expected_date", "sa.Date()", nullable=True),
                ColumnSpec(
                    "occurrence_count", "sa.Integer()", nullable=False, default="0"
                ),
                ColumnSpec(
                    "status",
                    "sa.String(16)",
                    nullable=False,
                    default="'early_detection'",
                ),
                ColumnSpec("confidence", "sa.Integer()", nullable=True),
                ColumnSpec(
                    "is_subscription",
                    "sa.Boolean()",
                    nullable=False,
                    default="False",
                ),
                ColumnSpec("is_active", "sa.Boolean()", nullable=False, default="True"),
                ColumnSpec(
                    "is_user_confirmed",
                    "sa.Boolean()",
                    nullable=False,
                    default="False",
                ),
                ColumnSpec("is_muted", "sa.Boolean()", nullable=False, default="False"),
                ColumnSpec("service_type", "sa.Text()", nullable=True),
                ColumnSpec("source", "sa.String(12)", nullable=False),
                ColumnSpec("deleted_at", "sa.DateTime()", nullable=True),
                ColumnSpec("metadata", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_finance_recurring_owner", ["owner_user_id"]),
                IndexSpec("ix_finance_recurring_account", ["account_id"]),
                IndexSpec("ix_finance_recurring_merchant", ["merchant_id"]),
                IndexSpec("ix_finance_recurring_category", ["category_id"]),
                IndexSpec("ix_finance_recurring_connection", ["connection_id"]),
                IndexSpec(
                    "ix_finance_recurring_next",
                    ["owner_user_id", "next_expected_date"],
                ),
                IndexSpec("ix_finance_recurring_status", ["status"]),
                IndexSpec("ix_finance_recurring_deleted", ["deleted_at"]),
                IndexSpec(
                    "uq_finance_recurring_provider",
                    ["connection_id", "provider_stream_id"],
                    unique=True,
                    where="provider_stream_id IS NOT NULL",
                ),
                IndexSpec(
                    "uq_finance_recurring_detected",
                    ["owner_user_id", "account_id", "direction", "normalized_payee"],
                    unique=True,
                    where="provider_stream_id IS NULL",
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(
                    ["account_id"], "finance_account", ["id"], ondelete="CASCADE"
                ),
                ForeignKeySpec(
                    ["merchant_id"], "finance_merchant", ["id"], ondelete="SET NULL"
                ),
                ForeignKeySpec(
                    ["category_id"], "finance_category", ["id"], ondelete="SET NULL"
                ),
                ForeignKeySpec(
                    ["connection_id"],
                    "finance_connection",
                    ["id"],
                    ondelete="SET NULL",
                ),
                ForeignKeySpec(["currency"], "finance_currency", ["code"]),
            ],
            check_constraints=[
                CheckConstraintSpec(
                    "ck_finance_recurring_direction",
                    "direction IN ('inflow', 'outflow')",
                ),
                CheckConstraintSpec(
                    "ck_finance_recurring_frequency",
                    "frequency IN ('weekly', 'biweekly', 'semi_monthly', "
                    "'monthly', 'bimonthly', 'quarterly', 'semi_annually', "
                    "'annually', 'irregular', 'unknown')",
                ),
                CheckConstraintSpec(
                    "ck_finance_recurring_status",
                    "status IN ('early_detection', 'mature', 'inactive', 'cancelled')",
                ),
                CheckConstraintSpec(
                    "ck_finance_recurring_source",
                    "source IN ('plaid', 'derived', 'user')",
                ),
            ],
        ),
        TableSpec(
            name="finance_budget",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("owner_user_id", "sa.Integer()", nullable=False),
                ColumnSpec("organization_id", "sa.Integer()", nullable=True),
                ColumnSpec("name", "sa.String(128)", nullable=False),
                ColumnSpec("period", "sa.String(16)", nullable=False),
                ColumnSpec("start_date", "sa.Date()", nullable=False),
                ColumnSpec("end_date", "sa.Date()", nullable=True),
                ColumnSpec(
                    "currency", "sa.String(16)", nullable=False, default="'usd'"
                ),
                ColumnSpec("philosophy", "sa.Text()", nullable=True),
                ColumnSpec("rollover", "sa.Boolean()", nullable=False, default="False"),
                ColumnSpec("is_active", "sa.Boolean()", nullable=False, default="True"),
                ColumnSpec("deleted_at", "sa.DateTime()", nullable=True),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_finance_budget_owner", ["owner_user_id"]),
                IndexSpec("ix_finance_budget_org", ["organization_id"]),
                IndexSpec("ix_finance_budget_deleted", ["deleted_at"]),
                IndexSpec(
                    "uq_finance_budget_owner_name_start",
                    ["owner_user_id", "name", "start_date"],
                    unique=True,
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(["currency"], "finance_currency", ["code"]),
            ],
            check_constraints=[
                CheckConstraintSpec(
                    "ck_finance_budget_period",
                    "period IN ('monthly', 'weekly', 'quarterly', 'yearly', 'custom')",
                ),
            ],
        ),
        TableSpec(
            name="finance_budget_category",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("owner_user_id", "sa.Integer()", nullable=False),
                ColumnSpec("budget_id", "sa.Integer()", nullable=False),
                # NULL category = the budget's overall line.
                ColumnSpec("category_id", "sa.Integer()", nullable=True),
                ColumnSpec("period_month", "sa.Integer()", nullable=True),
                ColumnSpec(
                    "allocated_amount", "sa.BigInteger()", nullable=False, default="0"
                ),
                ColumnSpec("goal_amount", "sa.BigInteger()", nullable=True),
                ColumnSpec(
                    "carryover_amount", "sa.BigInteger()", nullable=False, default="0"
                ),
                ColumnSpec(
                    "rollover_enabled",
                    "sa.Boolean()",
                    nullable=False,
                    default="False",
                ),
                ColumnSpec(
                    "currency", "sa.String(16)", nullable=False, default="'usd'"
                ),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_finance_budgetcat_owner", ["owner_user_id"]),
                IndexSpec("ix_finance_budgetcat_budget", ["budget_id"]),
                IndexSpec("ix_finance_budgetcat_category", ["category_id"]),
                IndexSpec("ix_finance_budgetcat_month", ["period_month"]),
                IndexSpec(
                    "uq_finance_budgetcat",
                    ["budget_id", "category_id", "period_month"],
                    unique=True,
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(
                    ["budget_id"], "finance_budget", ["id"], ondelete="CASCADE"
                ),
                ForeignKeySpec(
                    ["category_id"], "finance_category", ["id"], ondelete="CASCADE"
                ),
                ForeignKeySpec(["currency"], "finance_currency", ["code"]),
            ],
        ),
        TableSpec(
            name="finance_spending_baseline",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("owner_user_id", "sa.Integer()", nullable=False),
                ColumnSpec("category_id", "sa.Integer()", nullable=True),
                ColumnSpec("merchant_id", "sa.Integer()", nullable=True),
                ColumnSpec("window_months", "sa.Integer()", nullable=False),
                ColumnSpec("period_month", "sa.Integer()", nullable=False),
                ColumnSpec(
                    "trailing_avg_amount",
                    "sa.BigInteger()",
                    nullable=False,
                    default="0",
                ),
                ColumnSpec(
                    "currency", "sa.String(16)", nullable=False, default="'usd'"
                ),
                ColumnSpec("computed_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_finance_baseline_owner", ["owner_user_id"]),
                IndexSpec("ix_finance_baseline_category", ["category_id"]),
                IndexSpec("ix_finance_baseline_merchant", ["merchant_id"]),
                IndexSpec(
                    "uq_finance_baseline",
                    [
                        "owner_user_id",
                        "category_id",
                        "merchant_id",
                        "window_months",
                        "period_month",
                    ],
                    unique=True,
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(
                    ["category_id"], "finance_category", ["id"], ondelete="CASCADE"
                ),
                ForeignKeySpec(
                    ["merchant_id"], "finance_merchant", ["id"], ondelete="CASCADE"
                ),
                ForeignKeySpec(["currency"], "finance_currency", ["code"]),
            ],
            check_constraints=[
                CheckConstraintSpec(
                    "ck_finance_baseline_window",
                    "window_months IN (3, 6, 12)",
                ),
            ],
        ),
        TableSpec(
            name="finance_insight",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("owner_user_id", "sa.Integer()", nullable=False),
                ColumnSpec("organization_id", "sa.Integer()", nullable=True),
                ColumnSpec("insight_type", "sa.Text()", nullable=False),
                ColumnSpec("severity", "sa.String(16)", nullable=False),
                ColumnSpec("title", "sa.Text()", nullable=False),
                ColumnSpec("body", "sa.Text()", nullable=True),
                ColumnSpec("related_account_id", "sa.Integer()", nullable=True),
                ColumnSpec("related_transaction_id", "sa.Integer()", nullable=True),
                ColumnSpec("related_category_id", "sa.Integer()", nullable=True),
                ColumnSpec("related_stream_id", "sa.Integer()", nullable=True),
                ColumnSpec("detected_amount", "sa.BigInteger()", nullable=True),
                ColumnSpec("currency", "sa.String(16)", nullable=True),
                ColumnSpec("dedup_key", "sa.Text()", nullable=False),
                ColumnSpec("period_start", "sa.Date()", nullable=True),
                ColumnSpec("period_end", "sa.Date()", nullable=True),
                ColumnSpec("data", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec("status", "sa.String(12)", nullable=False, default="'new'"),
                ColumnSpec("is_read", "sa.Boolean()", nullable=False, default="False"),
                ColumnSpec("dismissed_at", "sa.DateTime()", nullable=True),
                ColumnSpec("metadata", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_finance_insight_owner", ["owner_user_id"]),
                IndexSpec("ix_finance_insight_org", ["organization_id"]),
                IndexSpec("ix_finance_insight_type", ["insight_type"]),
                IndexSpec("ix_finance_insight_status", ["status"]),
                IndexSpec("ix_finance_insight_account", ["related_account_id"]),
                IndexSpec("ix_finance_insight_transaction", ["related_transaction_id"]),
                IndexSpec("ix_finance_insight_category", ["related_category_id"]),
                IndexSpec("ix_finance_insight_stream", ["related_stream_id"]),
                IndexSpec(
                    "ix_finance_insight_owner_read", ["owner_user_id", "is_read"]
                ),
                IndexSpec(
                    "uq_finance_insight_dedup",
                    ["owner_user_id", "dedup_key"],
                    unique=True,
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(
                    ["related_account_id"],
                    "finance_account",
                    ["id"],
                    ondelete="CASCADE",
                ),
                ForeignKeySpec(
                    ["related_transaction_id"],
                    "finance_transaction",
                    ["id"],
                    ondelete="CASCADE",
                ),
                ForeignKeySpec(
                    ["related_category_id"],
                    "finance_category",
                    ["id"],
                    ondelete="SET NULL",
                ),
                ForeignKeySpec(
                    ["related_stream_id"],
                    "finance_recurring_stream",
                    ["id"],
                    ondelete="SET NULL",
                    name="fk_finance_insight_stream",
                ),
                ForeignKeySpec(["currency"], "finance_currency", ["code"]),
            ],
            check_constraints=[
                CheckConstraintSpec(
                    "ck_finance_insight_severity",
                    "severity IN ('info', 'warning', 'critical')",
                ),
                CheckConstraintSpec(
                    "ck_finance_insight_status",
                    "status IN ('new', 'seen', 'dismissed', 'actioned')",
                ),
            ],
        ),
        TableSpec(
            name="finance_import_profile",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                # NULL owner = system seed profile (Chase CC, AMEX v2, ...).
                ColumnSpec("owner_user_id", "sa.Integer()", nullable=True),
                ColumnSpec("organization_id", "sa.Integer()", nullable=True),
                ColumnSpec("institution_id", "sa.Integer()", nullable=True),
                ColumnSpec("name", "sa.String(128)", nullable=False),
                ColumnSpec("source_format", "sa.String(8)", nullable=False),
                ColumnSpec(
                    "header_signature", "sa.JSON()", nullable=False, default="{}"
                ),
                ColumnSpec("column_mapping", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec("date_format", "sa.Text()", nullable=True),
                ColumnSpec("amount_sign_convention", "sa.String(20)", nullable=False),
                ColumnSpec("decimal_separator", "sa.String(1)", nullable=True),
                ColumnSpec("thousands_separator", "sa.String(1)", nullable=True),
                ColumnSpec(
                    "currency", "sa.String(16)", nullable=False, default="'usd'"
                ),
                ColumnSpec(
                    "is_system", "sa.Boolean()", nullable=False, default="False"
                ),
                ColumnSpec("deleted_at", "sa.DateTime()", nullable=True),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_finance_importprofile_owner", ["owner_user_id"]),
                IndexSpec("ix_finance_importprofile_org", ["organization_id"]),
                IndexSpec("ix_finance_importprofile_institution", ["institution_id"]),
                IndexSpec("ix_finance_importprofile_deleted", ["deleted_at"]),
                IndexSpec(
                    "uq_finance_importprofile_owner_name",
                    ["owner_user_id", "name"],
                    unique=True,
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(
                    ["institution_id"],
                    "finance_institution",
                    ["id"],
                    ondelete="SET NULL",
                ),
                ForeignKeySpec(["currency"], "finance_currency", ["code"]),
            ],
            check_constraints=[
                CheckConstraintSpec(
                    "ck_finance_importprofile_format",
                    "source_format IN ('csv', 'ofx', 'qfx', 'qif')",
                ),
                CheckConstraintSpec(
                    "ck_finance_importprofile_sign",
                    "amount_sign_convention IN ('outflow_negative', "
                    "'outflow_positive', 'split_debit_credit')",
                ),
            ],
        ),
        TableSpec(
            name="finance_import_batch",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("owner_user_id", "sa.Integer()", nullable=False),
                ColumnSpec("organization_id", "sa.Integer()", nullable=True),
                ColumnSpec("connection_id", "sa.Integer()", nullable=True),
                ColumnSpec("account_id", "sa.Integer()", nullable=True),
                ColumnSpec("import_profile_id", "sa.Integer()", nullable=True),
                ColumnSpec("source_type", "sa.String(16)", nullable=False),
                ColumnSpec("file_name", "sa.String(255)", nullable=True),
                ColumnSpec("file_sha256", "sa.Text()", nullable=True),
                ColumnSpec("sync_cursor_before", "sa.Text()", nullable=True),
                ColumnSpec("sync_cursor_after", "sa.Text()", nullable=True),
                ColumnSpec("rows_total", "sa.Integer()", nullable=False, default="0"),
                ColumnSpec(
                    "rows_inserted", "sa.Integer()", nullable=False, default="0"
                ),
                ColumnSpec("rows_updated", "sa.Integer()", nullable=False, default="0"),
                ColumnSpec(
                    "rows_duplicate", "sa.Integer()", nullable=False, default="0"
                ),
                ColumnSpec("rows_error", "sa.Integer()", nullable=False, default="0"),
                ColumnSpec(
                    "status", "sa.String(16)", nullable=False, default="'pending'"
                ),
                ColumnSpec("error", "sa.Text()", nullable=True),
                ColumnSpec("started_at", "sa.DateTime()", nullable=True),
                ColumnSpec("finished_at", "sa.DateTime()", nullable=True),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_finance_importbatch_owner", ["owner_user_id"]),
                IndexSpec("ix_finance_importbatch_org", ["organization_id"]),
                IndexSpec("ix_finance_importbatch_connection", ["connection_id"]),
                IndexSpec("ix_finance_importbatch_account", ["account_id"]),
                IndexSpec("ix_finance_importbatch_profile", ["import_profile_id"]),
                IndexSpec("ix_finance_importbatch_status", ["status"]),
                IndexSpec(
                    "ix_finance_importbatch_owner_started",
                    ["owner_user_id", "started_at"],
                ),
                IndexSpec(
                    "uq_finance_importbatch_file",
                    ["owner_user_id", "file_sha256"],
                    unique=True,
                    where="file_sha256 IS NOT NULL",
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(
                    ["connection_id"],
                    "finance_connection",
                    ["id"],
                    ondelete="SET NULL",
                ),
                ForeignKeySpec(
                    ["account_id"], "finance_account", ["id"], ondelete="SET NULL"
                ),
                ForeignKeySpec(
                    ["import_profile_id"],
                    "finance_import_profile",
                    ["id"],
                    ondelete="SET NULL",
                    name="fk_finance_importbatch_profile",
                ),
            ],
            check_constraints=[
                CheckConstraintSpec(
                    "ck_finance_importbatch_source",
                    "source_type IN ('plaid_sync', 'snaptrade_sync', 'ofx', "
                    "'qfx', 'qif', 'csv', 'manual')",
                ),
                CheckConstraintSpec(
                    "ck_finance_importbatch_status",
                    "status IN ('pending', 'processing', 'committed', 'failed', "
                    "'rolled_back')",
                ),
            ],
        ),
        TableSpec(
            name="finance_import_batch_row",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("import_batch_id", "sa.Integer()", nullable=False),
                ColumnSpec("owner_user_id", "sa.Integer()", nullable=False),
                ColumnSpec("account_id", "sa.Integer()", nullable=True),
                ColumnSpec("row_number", "sa.Integer()", nullable=False),
                ColumnSpec("raw_line", "sa.Text()", nullable=True),
                ColumnSpec("parsed", "sa.JSON()", nullable=False, default="{}"),
                ColumnSpec("content_hash", "sa.String(64)", nullable=True),
                ColumnSpec("fitid", "sa.Text()", nullable=True),
                ColumnSpec("parsed_status", "sa.String(12)", nullable=False),
                ColumnSpec("matched_transaction_id", "sa.Integer()", nullable=True),
                ColumnSpec("matched_trade_id", "sa.Integer()", nullable=True),
                ColumnSpec("reason", "sa.Text()", nullable=True),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_finance_importrow_batch", ["import_batch_id"]),
                IndexSpec("ix_finance_importrow_owner", ["owner_user_id"]),
                IndexSpec("ix_finance_importrow_account", ["account_id"]),
                IndexSpec(
                    "ix_finance_importrow_matched_txn", ["matched_transaction_id"]
                ),
                IndexSpec("ix_finance_importrow_matched_trade", ["matched_trade_id"]),
                IndexSpec("ix_finance_importrow_hash", ["content_hash"]),
                IndexSpec(
                    "uq_finance_importrow_batch_num",
                    ["import_batch_id", "row_number"],
                    unique=True,
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(
                    ["import_batch_id"],
                    "finance_import_batch",
                    ["id"],
                    ondelete="CASCADE",
                    name="fk_finance_importrow_batch",
                ),
                ForeignKeySpec(
                    ["account_id"], "finance_account", ["id"], ondelete="SET NULL"
                ),
                ForeignKeySpec(
                    ["matched_transaction_id"],
                    "finance_transaction",
                    ["id"],
                    ondelete="SET NULL",
                    name="fk_finance_importrow_matched_txn",
                ),
                ForeignKeySpec(
                    ["matched_trade_id"],
                    "finance_trade",
                    ["id"],
                    ondelete="SET NULL",
                    name="fk_finance_importrow_matched_trade",
                ),
            ],
            check_constraints=[
                CheckConstraintSpec(
                    "ck_finance_importrow_status",
                    "parsed_status IN ('parsed', 'inserted', 'updated', "
                    "'duplicate', 'error', 'matched', 'skipped')",
                ),
            ],
        ),
        TableSpec(
            name="finance_attachment",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("owner_user_id", "sa.Integer()", nullable=False),
                ColumnSpec("organization_id", "sa.Integer()", nullable=True),
                ColumnSpec("transaction_id", "sa.Integer()", nullable=True),
                ColumnSpec("account_id", "sa.Integer()", nullable=True),
                ColumnSpec("file_name", "sa.Text()", nullable=False),
                ColumnSpec("content_type", "sa.Text()", nullable=True),
                ColumnSpec("byte_size", "sa.Integer()", nullable=True),
                ColumnSpec("storage_key", "sa.Text()", nullable=False),
                ColumnSpec("sha256", "sa.Text()", nullable=True),
                ColumnSpec("deleted_at", "sa.DateTime()", nullable=True),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_finance_attachment_owner", ["owner_user_id"]),
                IndexSpec("ix_finance_attachment_org", ["organization_id"]),
                IndexSpec("ix_finance_attachment_transaction", ["transaction_id"]),
                IndexSpec("ix_finance_attachment_account", ["account_id"]),
                IndexSpec("ix_finance_attachment_deleted", ["deleted_at"]),
                IndexSpec(
                    "uq_finance_attachment_owner_sha",
                    ["owner_user_id", "sha256"],
                    unique=True,
                    where="sha256 IS NOT NULL",
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(
                    ["transaction_id"],
                    "finance_transaction",
                    ["id"],
                    ondelete="CASCADE",
                ),
                ForeignKeySpec(
                    ["account_id"], "finance_account", ["id"], ondelete="CASCADE"
                ),
            ],
        ),
        TableSpec(
            name="finance_transaction_changelog",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("transaction_id", "sa.Integer()", nullable=False),
                ColumnSpec("owner_user_id", "sa.Integer()", nullable=False),
                ColumnSpec("field", "sa.Text()", nullable=False),
                ColumnSpec("old_value", "sa.Text()", nullable=True),
                ColumnSpec("new_value", "sa.Text()", nullable=True),
                ColumnSpec("change_source", "sa.Text()", nullable=False),
                ColumnSpec("sync_cursor", "sa.Text()", nullable=True),
                ColumnSpec("changed_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_finance_changelog_transaction", ["transaction_id"]),
                IndexSpec("ix_finance_changelog_owner", ["owner_user_id"]),
                IndexSpec("ix_finance_changelog_changed", ["changed_at"]),
            ],
            foreign_keys=[
                ForeignKeySpec(
                    ["transaction_id"],
                    "finance_transaction",
                    ["id"],
                    ondelete="CASCADE",
                    name="fk_finance_changelog_txn",
                ),
            ],
        ),
    ],
    alter_tables=[
        # Circular FK: finance_transaction.transfer_group_id ->
        # finance_transfer.id (finance_transfer references finance_transaction),
        # plus the category_id / merchant_id forward FKs now that Group D tables
        # exist. One batch per table (SQLite recreates the table per batch).
        AlterTableSpec(
            name="finance_transaction",
            add_foreign_keys=[
                ForeignKeySpec(
                    ["transfer_group_id"],
                    "finance_transfer",
                    ["id"],
                    ondelete="SET NULL",
                ),
                ForeignKeySpec(
                    ["category_id"], "finance_category", ["id"], ondelete="SET NULL"
                ),
                ForeignKeySpec(
                    ["merchant_id"], "finance_merchant", ["id"], ondelete="SET NULL"
                ),
                # Short explicit names: the auto-derived
                # fk_finance_transaction_recurring_stream_id_finance_recurring_
                # stream exceeds Postgres' 63-char identifier limit.
                ForeignKeySpec(
                    ["recurring_stream_id"],
                    "finance_recurring_stream",
                    ["id"],
                    ondelete="SET NULL",
                    name="fk_finance_txn_recurring_stream",
                ),
                ForeignKeySpec(
                    ["import_batch_id"],
                    "finance_import_batch",
                    ["id"],
                    ondelete="SET NULL",
                    name="fk_finance_txn_import_batch",
                ),
            ],
        ),
        AlterTableSpec(
            name="finance_transaction_split",
            add_foreign_keys=[
                ForeignKeySpec(
                    ["category_id"], "finance_category", ["id"], ondelete="SET NULL"
                ),
                ForeignKeySpec(
                    ["merchant_id"], "finance_merchant", ["id"], ondelete="SET NULL"
                ),
            ],
        ),
        AlterTableSpec(
            name="finance_trade",
            add_foreign_keys=[
                ForeignKeySpec(
                    ["import_batch_id"],
                    "finance_import_batch",
                    ["id"],
                    ondelete="SET NULL",
                    name="fk_finance_trade_import_batch",
                ),
            ],
        ),
    ],
)


# Postgres schema finance tables live in (dropped on SQLite, which has none).
FINANCE_SCHEMA = "finance"

# Every finance table with an ``owner_user_id`` column. The auth-link migration
# adds an FK from each to ``user.id`` when the auth service is present. Grows as
# owner-scoped tables land across the schema tickets.
_FINANCE_OWNED_TABLES: tuple[str, ...] = (
    "finance_connection",
    "finance_account",
    "finance_liability_detail",
    "finance_balance_snapshot",
    "finance_net_worth_snapshot",
    "finance_valuation",
    "finance_transaction",
    "finance_transaction_split",
    "finance_transfer",
    "finance_category",
    "finance_category_alias",
    "finance_merchant",
    "finance_tag",
    "finance_rule",
    "finance_holding",
    "finance_trade",
    "finance_recurring_stream",
    "finance_budget",
    "finance_budget_category",
    "finance_spending_baseline",
    "finance_insight",
    "finance_import_profile",
    "finance_import_batch",
    "finance_import_batch_row",
    "finance_attachment",
    "finance_transaction_changelog",
)


def _build_finance_auth_link(
    *, schema: str | None, user_ref_schema: str | None
) -> ServiceMigrationSpec:
    """Owner FK from each owner-scoped finance table to the auth ``user`` table.

    Emitted only when BOTH finance and auth are included (see
    get_services_needing_migrations), so a standalone (no-auth) finance stack
    never references a missing table. ON DELETE CASCADE: a deleted user takes
    their finance data with them.

    On Postgres the finance tables live in the ``finance`` schema while ``user``
    lives in ``public``, so these are cross-schema FKs: ``schema`` puts the
    batch-alter on the finance-schema tables and ``user_ref_schema`` qualifies
    the referent. On SQLite both are None (single unqualified DB).
    """
    return ServiceMigrationSpec(
        service_name="finance_auth_link",
        description="Link finance owner_user_id columns to user.id (auth + finance)",
        tables=[],
        schema=schema,
        alter_tables=[
            AlterTableSpec(
                name=table,
                add_foreign_keys=[
                    ForeignKeySpec(
                        ["owner_user_id"],
                        "user",
                        ["id"],
                        ondelete="CASCADE",
                        ref_schema=user_ref_schema,
                    ),
                ],
            )
            for table in _FINANCE_OWNED_TABLES
        ],
    )


# Static (SQLite / default) variant; the Postgres schema-qualified variant is
# built on demand in _resolve_spec.
FINANCE_AUTH_LINK_MIGRATION = _build_finance_auth_link(
    schema=None, user_ref_schema=None
)


BLOG_MIGRATION = ServiceMigrationSpec(
    service_name="blog",
    description="Blog service tables (posts, tags, post/tag links)",
    tables=[
        TableSpec(
            name="blog_post",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("title", "sa.String(200)", nullable=False),
                ColumnSpec("slug", "sa.String(220)", nullable=False),
                ColumnSpec("excerpt", "sa.String(500)", nullable=True),
                ColumnSpec("content", "sa.Text()", nullable=False),
                ColumnSpec(
                    "status", "sa.String(16)", nullable=False, default="'draft'"
                ),
                ColumnSpec("author_id", "sa.Integer()", nullable=True),
                ColumnSpec("author_name", "sa.String(200)", nullable=True),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
                ColumnSpec("updated_at", "sa.DateTime()", nullable=False),
                ColumnSpec("published_at", "sa.DateTime()", nullable=True),
                ColumnSpec("seo_title", "sa.String(200)", nullable=True),
                ColumnSpec("seo_description", "sa.String(320)", nullable=True),
                ColumnSpec("hero_image_url", "sa.String(1024)", nullable=True),
                ColumnSpec("syndicate_targets", "sa.JSON()", nullable=True),
            ],
            indexes=[
                IndexSpec("ix_blog_post_slug", ["slug"], unique=True),
                IndexSpec("ix_blog_post_status", ["status"]),
                IndexSpec("ix_blog_post_author_id", ["author_id"]),
                IndexSpec("ix_blog_post_created_at", ["created_at"]),
                IndexSpec("ix_blog_post_published_at", ["published_at"]),
            ],
            check_constraints=[
                CheckConstraintSpec(
                    name="ck_blog_post_status",
                    sqltext="status IN ('draft', 'published', 'archived')",
                ),
            ],
        ),
        TableSpec(
            name="blog_tag",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("name", "sa.String(80)", nullable=False),
                ColumnSpec("slug", "sa.String(100)", nullable=False),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_blog_tag_name", ["name"], unique=True),
                IndexSpec("ix_blog_tag_slug", ["slug"], unique=True),
            ],
        ),
        TableSpec(
            name="blog_post_tag",
            columns=[
                ColumnSpec("post_id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("tag_id", "sa.Integer()", nullable=False, primary_key=True),
                ColumnSpec("created_at", "sa.DateTime()", nullable=False),
            ],
            indexes=[
                IndexSpec("ix_blog_post_tag_post_id", ["post_id"]),
                IndexSpec("ix_blog_post_tag_tag_id", ["tag_id"]),
            ],
            foreign_keys=[
                ForeignKeySpec(["post_id"], "blog_post", ["id"], ondelete="CASCADE"),
                ForeignKeySpec(["tag_id"], "blog_tag", ["id"], ondelete="CASCADE"),
            ],
        ),
    ],
)


# ============================================================================
# Component Migration Definitions
# ============================================================================

# The scheduler is a COMPONENT (not a service) and this is the first
# component-owned table. It lives in a dedicated ``scheduler`` Postgres
# schema so component tables stay namespaced apart from service tables.
# On SQLite (no schema support) the table lands unqualified in the single
# database file — see the model's engine-gated ``__table_args__``.
SCHEDULER_MIGRATION = ServiceMigrationSpec(
    service_name="scheduler",
    description="Scheduler job execution history",
    schema="scheduler",
    tables=[
        TableSpec(
            name="job_execution",
            columns=[
                ColumnSpec("id", "sa.Integer()", nullable=False, primary_key=True),
                # job_id is APScheduler's job id (e.g. "insight_plausible"),
                # not an FK: the apscheduler_jobs row can be deleted while
                # history is retained, so job_name is denormalized too.
                ColumnSpec("job_id", "sa.String(191)", nullable=False),
                ColumnSpec("job_name", "sa.String(255)", nullable=False, default="''"),
                ColumnSpec("scheduled_run_time", "sa.DateTime()", nullable=True),
                ColumnSpec("started_at", "sa.DateTime()", nullable=False),
                ColumnSpec("finished_at", "sa.DateTime()", nullable=True),
                ColumnSpec("duration_ms", "sa.Float()", nullable=True),
                # running | success | failed | missed
                ColumnSpec(
                    "status", "sa.String(16)", nullable=False, default="'running'"
                ),
                ColumnSpec("error_message", "sa.Text()", nullable=True),
                ColumnSpec("traceback", "sa.Text()", nullable=True),
            ],
            indexes=[
                IndexSpec("ix_job_execution_job_id", ["job_id"]),
                IndexSpec("ix_job_execution_started_at", ["started_at"]),
                IndexSpec("ix_job_execution_status", ["status"]),
                # Composite for the dominant query: last N runs of one job.
                IndexSpec("ix_job_execution_job_started", ["job_id", "started_at"]),
            ],
        ),
    ],
)

# Registry of all service migrations.
#
# R4-A: derived lazily from each ``PluginSpec.migrations`` list (see
# ``aegis/core/services.py`` for the in-tree declarations and
# ``aegis/core/migration_spec.py`` for the plugin-author-facing facade).
# Pre-R4 this was a literal ``dict[str, ServiceMigrationSpec]`` here;
# moving it onto the specs lets third-party plugins ship their own
# migrations without forking core, while preserving the same
# ``MIGRATION_SPECS["auth"]`` lookup shape for existing callers
# (``copier_manager.py``, ``add_service.py``, the test suite).
#
# Lazy because ``services.py`` imports the named ``*_MIGRATION``
# constants from this module — eager construction here would create a
# circular import at module load time. ``__getattr__`` defers the
# ``services`` import until first access of ``MIGRATION_SPECS``, by
# which point the services registry is fully built.

_MIGRATION_SPECS_CACHE: dict[str, ServiceMigrationSpec] | None = None


def _get_migration_specs() -> dict[str, ServiceMigrationSpec]:
    """Return the (lazily built) migration registry.

    Plugins discovered via entry points (Phase B of the plugin system)
    will need to invalidate ``_MIGRATION_SPECS_CACHE`` after registering
    new specs; for R4-A the in-tree registry is static, so the dict is
    built once and reused.
    """
    global _MIGRATION_SPECS_CACHE
    if _MIGRATION_SPECS_CACHE is None:
        from .components import COMPONENTS
        from .migration_spec import collect_migrations
        from .services import SERVICES

        # Components are collected alongside services so component-owned
        # tables (e.g. the scheduler's job_execution) get the same
        # spec-driven migration rail. Both subclass PluginSpec, so
        # collect_migrations reads ``.migrations`` off either uniformly.
        _MIGRATION_SPECS_CACHE = collect_migrations(
            [*SERVICES.values(), *COMPONENTS.values()]
        )
    return _MIGRATION_SPECS_CACHE


def __getattr__(name: str) -> Any:
    """Module-level lazy access for ``MIGRATION_SPECS``.

    Used when callers do ``from migration_generator import MIGRATION_SPECS``;
    code inside this module references the cache via ``_get_migration_specs()``
    instead, since module-level ``__getattr__`` does not fire for internal
    name lookups.
    """
    if name == "MIGRATION_SPECS":
        return _get_migration_specs()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ============================================================================
# Migration File Template
# ============================================================================

MIGRATION_TEMPLATE = '''"""{{ description }}

Revision ID: {{ revision }}
Revises: {{ down_revision }}
Create Date: {{ create_date }}

"""
from datetime import UTC, datetime

import sqlalchemy as sa
import sqlmodel

from alembic import op

# revision identifiers, used by Alembic.
revision = '{{ revision }}'
down_revision = {{ down_revision_repr }}
branch_labels = None
depends_on = None


def upgrade() -> None:
    """{{ upgrade_description }}"""
{%- if schema %}
    op.execute('CREATE SCHEMA IF NOT EXISTS "{{ schema }}"')
{%- endif %}
{% for table in tables %}
    # Create {{ table.name }} table
    op.create_table(
        '{{ table.name }}',
{% for column in table.columns %}
{% set pk_attr = ", primary_key=True" if column.primary_key else "" %}
{% set default_attr = ", default=" ~ column.default if column.default else "" %}
        sa.Column('{{ column.name }}', {{ column.type }}, nullable={{ column.nullable }}{{ pk_attr }}{{ default_attr }}),
{% endfor %}
{% if table.primary_keys %}
        sa.PrimaryKeyConstraint({% for pk in table.primary_keys %}'{{ pk }}'{% if not loop.last %}, {% endif %}{% endfor %}){% if table.foreign_keys or table.check_constraints or schema %},{% endif %}

{% endif %}
{% for fk in table.foreign_keys %}
        sa.ForeignKeyConstraint({{ fk.columns }}, ['{{ fk.ref_schema_qualified }}{{ fk.ref_table }}.{{ fk.ref_columns[0] }}']{% if fk.ondelete %}, ondelete='{{ fk.ondelete }}'{% endif %}){% if not loop.last or table.check_constraints or schema %},{% endif %}

{% endfor %}
{% for chk in table.check_constraints %}
        sa.CheckConstraint("{{ chk.sqltext }}", name='{{ chk.name }}'){% if not loop.last or schema %},{% endif %}

{% endfor %}
{%- if schema %}
        schema='{{ schema }}',
{%- endif %}
    )
{% for index in table.indexes %}
    op.create_index(op.f('{{ index.name }}'), '{{ table.name }}', {{ index.columns }}{% if index.unique %}, unique=True{% endif %}{% if index.where %}, sqlite_where=sa.text("{{ index.where }}"), postgresql_where=sa.text("{{ index.where }}"){% endif %}{% if schema %}, schema='{{ schema }}'{% endif %})
{% endfor %}

{% endfor %}
{% for alter in alter_tables %}
    # Alter {{ alter.name }} table — batch_alter_table is required for
    # SQLite, which doesn't support ALTER for FK constraints. Postgres
    # treats it as plain ALTER, so this is portable across both backends.
    # Drops run before adds so names can be reused (e.g. swap an index
    # from one column set to another with the same name).
    with op.batch_alter_table('{{ alter.name }}'{% if schema %}, schema='{{ schema }}'{% endif %}) as batch_op:
{% for index_name in alter.drop_indexes %}
        batch_op.drop_index('{{ index_name }}')
{% endfor %}
{% for column_name in alter.drop_columns %}
        batch_op.drop_column('{{ column_name }}')
{% endfor %}
{% for column in alter.add_columns %}
        batch_op.add_column(sa.Column('{{ column.name }}', {{ column.type }}, nullable={{ column.nullable }}{% if column.server_default %}, server_default={{ column.server_default }}{% endif %}))
{% endfor %}
{% for fk in alter.add_foreign_keys %}
        batch_op.create_foreign_key('{{ fk.constraint_name }}', '{{ fk.ref_table }}', {{ fk.columns }}, {{ fk.ref_columns }}{% if fk.ondelete %}, ondelete='{{ fk.ondelete }}'{% endif %}{% if fk.ref_schema %}, referent_schema='{{ fk.ref_schema }}'{% endif %})
{% endfor %}
{% for index in alter.add_indexes %}
        batch_op.create_index('{{ index.name }}', {{ index.columns }}{% if index.unique %}, unique=True{% endif %}{% if index.where %}, sqlite_where=sa.text("{{ index.where }}"), postgresql_where=sa.text("{{ index.where }}"){% endif %})
{% endfor %}

{% endfor %}

def downgrade() -> None:
    """Reverse {{ service_name }} migration."""
{% if forward_only %}
    raise NotImplementedError(
        "Migration {{ service_name }} is forward-only — it drops columns "
        "or merges schemas in non-recoverable ways. Restore from backup "
        "to roll back."
    )
{% else %}
{% for alter in alter_tables|reverse %}
    with op.batch_alter_table('{{ alter.name }}'{% if schema %}, schema='{{ schema }}'{% endif %}) as batch_op:
{% for index in alter.add_indexes|reverse %}
        batch_op.drop_index('{{ index.name }}')
{% endfor %}
{% for fk in alter.add_foreign_keys|reverse %}
        batch_op.drop_constraint('{{ fk.constraint_name }}', type_='foreignkey')
{% endfor %}
{% for column in alter.add_columns|reverse %}
        batch_op.drop_column('{{ column.name }}')
{% endfor %}
{% endfor %}
{% for table in tables|reverse %}
{% for index in table.indexes %}
    op.drop_index(op.f('{{ index.name }}'), table_name='{{ table.name }}'{% if schema %}, schema='{{ schema }}'{% endif %})
{% endfor %}
    op.drop_table('{{ table.name }}'{% if schema %}, schema='{{ schema }}'{% endif %})
{% endfor %}
{% endif %}
'''


# ============================================================================
# Core Functions
# ============================================================================


def get_versions_dir(project_path: Path) -> Path:
    """Get the alembic versions directory for a project."""
    return project_path / "alembic" / "versions"


def get_existing_migrations(project_path: Path) -> list[str]:
    """
    Get list of existing migration revision IDs in a project.

    Returns revision IDs sorted by filename (which determines order).
    """
    versions_dir = get_versions_dir(project_path)
    if not versions_dir.exists():
        return []

    migrations = []
    for f in sorted(versions_dir.glob("*.py")):
        if f.name.startswith("__"):
            continue
        # Extract revision from filename (e.g., "001_auth.py" -> "001")
        parts = f.stem.split("_")
        if parts and parts[0].isdigit():
            migrations.append(parts[0])

    return migrations


def get_next_revision_id(project_path: Path) -> str:
    """
    Get the next revision ID for a new migration.

    Uses simple numeric IDs: 001, 002, 003, etc.
    """
    existing = get_existing_migrations(project_path)
    if not existing:
        return "001"

    # Find highest existing revision number
    max_rev = max(int(rev) for rev in existing)
    return f"{max_rev + 1:03d}"


def get_previous_revision(project_path: Path) -> str | None:
    """Get the most recent revision ID, or None if no migrations exist."""
    existing = get_existing_migrations(project_path)
    if not existing:
        return None
    return existing[-1]


def service_has_migration(project_path: Path, service_name: str) -> bool:
    """
    Check if a service already has a migration in the project.

    Looks for migration files containing the service name.
    """
    versions_dir = get_versions_dir(project_path)
    if not versions_dir.exists():
        return False

    # Look for files with service name in filename
    for _f in versions_dir.glob(f"*_{service_name}.py"):
        return True

    return False


def _render_migration(
    spec: ServiceMigrationSpec,
    revision: str,
    down_revision: str | None,
) -> str:
    """Render a migration file from a service spec."""
    template = Template(MIGRATION_TEMPLATE)

    # Prepare table data for template
    tables_data = []
    for table in spec.tables:
        # Find primary key columns
        primary_keys = [col.name for col in table.columns if col.primary_key]

        tables_data.append(
            {
                "name": table.name,
                "columns": [
                    {
                        "name": col.name,
                        "type": col.type,
                        "nullable": col.nullable,
                        "primary_key": col.primary_key,
                        "default": col.default,
                    }
                    for col in table.columns
                ],
                "indexes": [
                    {
                        "name": idx.name,
                        "columns": idx.columns,
                        "unique": idx.unique,
                        "where": idx.where,
                    }
                    for idx in table.indexes
                ],
                "foreign_keys": [
                    {
                        "columns": fk.columns,
                        "ref_table": fk.ref_table,
                        "ref_columns": fk.ref_columns,
                        "ondelete": fk.ondelete,
                        # Cross-schema FKs qualify the referent; intra-spec
                        # FKs default to the spec's own schema. Empty string
                        # when neither is set (unqualified, == today).
                        "ref_schema_qualified": (
                            f"{fk.ref_schema or spec.schema}."
                            if (fk.ref_schema or spec.schema)
                            else ""
                        ),
                    }
                    for fk in table.foreign_keys
                ],
                "check_constraints": [
                    {"name": chk.name, "sqltext": chk.sqltext}
                    for chk in table.check_constraints
                ],
                "primary_keys": primary_keys,
            }
        )

    # Prepare alter table data for template
    alter_tables_data = []
    for alter in spec.alter_tables:
        cols = []
        for col in alter.add_columns:
            # For add_column, server_default needs sa.text() wrapper
            server_default = None
            if col.default is not None:
                server_default = f'sa.text("{col.default}")'
            cols.append(
                {
                    "name": col.name,
                    "type": col.type,
                    "nullable": col.nullable,
                    "server_default": server_default,
                }
            )
        fks = [
            {
                "columns": fk.columns,
                "ref_table": fk.ref_table,
                "ref_columns": fk.ref_columns,
                "ondelete": fk.ondelete,
                "ref_schema": fk.ref_schema or spec.schema,
                # Explicit name (short, for the 63-char Postgres limit) or the
                # auto-derived default. Used identically on create and drop.
                "constraint_name": (
                    fk.name or f"fk_{alter.name}_{fk.columns[0]}_{fk.ref_table}"
                ),
            }
            for fk in alter.add_foreign_keys
        ]
        add_idxs = [
            {
                "name": idx.name,
                "columns": idx.columns,
                "unique": idx.unique,
                "where": idx.where,
            }
            for idx in alter.add_indexes
        ]
        alter_tables_data.append(
            {
                "name": alter.name,
                "add_columns": cols,
                "add_foreign_keys": fks,
                "add_indexes": add_idxs,
                "drop_columns": list(alter.drop_columns),
                "drop_indexes": list(alter.drop_indexes),
            }
        )

    # Build upgrade description
    if spec.tables and spec.alter_tables:
        upgrade_description = f"Create and alter {spec.service_name} service tables."
    elif spec.alter_tables:
        upgrade_description = f"Add {spec.service_name} columns."
    else:
        upgrade_description = f"Create {spec.service_name} service tables."

    return template.render(
        description=spec.description,
        service_name=spec.service_name,
        upgrade_description=upgrade_description,
        revision=revision,
        down_revision=down_revision,
        down_revision_repr=f"'{down_revision}'" if down_revision else "None",
        create_date=datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f"),
        tables=tables_data,
        alter_tables=alter_tables_data,
        forward_only=spec.forward_only,
        schema=spec.schema,
    )


def _resolve_spec(
    service_name: str,
    context: dict[str, Any] | None,
) -> ServiceMigrationSpec | None:
    """Look up a migration spec, applying any context-driven overrides.

    The ``insights`` spec ships in two shapes — shared mode (default) and
    per-user mode (``insights_per_user=true``). Both render to a single
    ``00X_insights.py`` migration file; only the shape changes. Other
    services pass through to the static spec unchanged.
    """
    migration_specs = _get_migration_specs()
    if service_name not in migration_specs:
        return None

    if service_name == "insights" and context is not None:
        flag = context.get(AnswerKeys.INSIGHTS_PER_USER)
        per_user = flag == "yes" or flag is True
        if per_user:
            return _build_insights_migration(per_user=True)

    # Finance tables live in a dedicated Postgres ``finance`` schema; SQLite has
    # no schemas, so there they stay unqualified. Resolve the schema-qualified
    # variant only for a Postgres target.
    if service_name in ("finance", "finance_auth_link") and context is not None:
        engine = context.get(AnswerKeys.DATABASE_ENGINE, StorageBackends.SQLITE)
        if engine == StorageBackends.POSTGRES:
            if service_name == "finance":
                return replace(migration_specs["finance"], schema=FINANCE_SCHEMA)
            # user lives in the default (public) schema, finance_connection in
            # the finance schema — cross-schema FK.
            return _build_finance_auth_link(
                schema=FINANCE_SCHEMA, user_ref_schema="public"
            )

    return migration_specs[service_name]


def generate_migration(
    project_path: Path,
    service_name: str,
    context: dict[str, Any] | None = None,
) -> Path | None:
    """
    Generate a migration file for a service.

    Args:
        project_path: Path to the project directory
        service_name: Name of the service (e.g., "auth", "ai")
        context: Optional generation context (copier flags). Used to pick
            between spec variants — e.g. ``insights_per_user`` toggles the
            insights spec between shared and per-user shape.

    Returns:
        Path to the generated migration file, or None if service not found
    """
    spec = _resolve_spec(service_name, context)
    if spec is None:
        return None

    versions_dir = get_versions_dir(project_path)

    # Ensure versions directory exists
    versions_dir.mkdir(parents=True, exist_ok=True)

    # Get revision info
    revision = get_next_revision_id(project_path)
    down_revision = get_previous_revision(project_path)

    # Render migration content
    content = _render_migration(spec, revision, down_revision)

    # Write migration file
    filename = f"{revision}_{service_name}.py"
    migration_path = versions_dir / filename

    migration_path.write_text(content)

    return migration_path


def generate_migrations_for_services(
    project_path: Path,
    services: list[str],
    context: dict[str, Any] | None = None,
) -> list[Path]:
    """
    Generate migrations for multiple services in order.

    Args:
        project_path: Path to the project directory
        services: List of service names in desired order
        context: Optional generation context forwarded to ``generate_migration``
            so spec variants (e.g. insights per-user) pick the right shape.

    Returns:
        List of paths to generated migration files
    """
    generated = []
    migration_specs = _get_migration_specs()

    for service_name in services:
        if service_name not in migration_specs:
            continue

        # Skip if migration already exists
        if service_has_migration(project_path, service_name):
            continue

        migration_path = generate_migration(project_path, service_name, context)
        if migration_path:
            generated.append(migration_path)

    return generated


def get_services_needing_migrations(context: dict[str, Any]) -> list[str]:
    """
    Determine which services need migrations based on context.

    Args:
        context: Dictionary with service flags (e.g., from cookiecutter/copier)

    Returns:
        List of service names that need migrations
    """
    services = []

    # Auth service (base user table)
    include_auth = context.get(AnswerKeys.AUTH)
    if include_auth == "yes" or include_auth is True:
        services.append("auth")

    # Auth token tables (password reset, email verification) - always with auth
    if include_auth == "yes" or include_auth is True:
        services.append("auth_tokens")

    # Auth RBAC columns (rbac or org level)
    include_auth_rbac = context.get(AnswerKeys.AUTH_RBAC)
    auth_level = context.get(AnswerKeys.AUTH_LEVEL)
    rbac_enabled = (
        include_auth_rbac == "yes"
        or include_auth_rbac is True
        or (
            isinstance(auth_level, str)
            and auth_level.lower() in (AuthLevels.RBAC, AuthLevels.ORG)
        )
    )
    if (include_auth == "yes" or include_auth is True) and rbac_enabled:
        services.append("auth_rbac")

    # Auth org tables (only with org-level auth)
    include_auth_org = context.get(AnswerKeys.AUTH_ORG)
    org_enabled = (
        include_auth_org == "yes"
        or include_auth_org is True
        or (isinstance(auth_level, str) and auth_level.lower() == AuthLevels.ORG)
    )
    if (include_auth == "yes" or include_auth is True) and org_enabled:
        services.append("auth_org")

    # AI service (only with persistence backend)
    include_ai = context.get(AnswerKeys.AI)
    ai_backend = context.get(AnswerKeys.AI_BACKEND, StorageBackends.MEMORY)
    if (
        include_ai == "yes" or include_ai is True
    ) and ai_backend != StorageBackends.MEMORY:
        services.append("ai")

    # AI agent registry - rides the exact same gate as the ai catalog
    # tables: agents are the service's default architecture, and the DB
    # config source exists whenever there is a persistence backend.
    if (
        include_ai == "yes" or include_ai is True
    ) and ai_backend != StorageBackends.MEMORY:
        services.append("ai_agents")

    # KB metadata (only with AI persistence AND the rag flag)
    ai_rag = context.get(AnswerKeys.AI_RAG)
    if (
        (include_ai == "yes" or include_ai is True)
        and ai_backend != StorageBackends.MEMORY
        and (ai_rag == "yes" or ai_rag is True)
    ):
        services.append("ai_knowledge")

    # Sentiment analysis (with AI persistence; the conversation table is
    # its FK target). The job that populates it is settings-gated off.
    if (
        include_ai == "yes" or include_ai is True
    ) and ai_backend != StorageBackends.MEMORY:
        services.append("ai_sentiment")

    # AI Voice service (only if AI with persistence and voice enabled)
    ai_voice = context.get(AnswerKeys.AI_VOICE)
    if (
        (include_ai == "yes" or include_ai is True)
        and ai_backend != StorageBackends.MEMORY
        and (ai_voice == "yes" or ai_voice is True)
    ):
        services.append("ai_voice")

    # Insights service (always needs database)
    include_insights = context.get(AnswerKeys.INSIGHTS)
    include_insights_on = include_insights == "yes" or include_insights is True
    if include_insights_on:
        services.append("insights")

    # Payment service (always needs database)
    include_payment = context.get(AnswerKeys.PAYMENT)
    include_payment_on = include_payment == "yes" or include_payment is True
    if include_payment_on:
        services.append("payment")

    # Payment + Auth: add FK from payment_customer.user_id -> user.id.
    # Only meaningful when BOTH services are included; runs after both
    # base migrations so the `user` table exists when the FK is created.
    include_auth_on = include_auth == "yes" or include_auth is True
    if include_payment_on and include_auth_on:
        services.append("payment_auth_link")

    # Blog service (always needs database)
    include_blog = context.get(AnswerKeys.BLOG)
    include_blog_on = include_blog == "yes" or include_blog is True
    if include_blog_on:
        services.append("blog")

    # Finance service (always needs database).
    include_finance = context.get(AnswerKeys.FINANCE)
    include_finance_on = include_finance == "yes" or include_finance is True
    if include_finance_on:
        services.append("finance")

    # Finance + Auth: add FK from finance_connection.owner_user_id -> user.id.
    # Only when BOTH are included; runs after both base migrations so `user`
    # exists. include_auth_on is defined above (payment_auth_link block).
    if include_finance_on and include_auth_on:
        services.append("finance_auth_link")

    # Scheduler component — the job_execution history table. Postgres ONLY:
    # the table lives in a ``scheduler`` schema, and the migration emits
    # ``CREATE SCHEMA`` which SQLite can't run. SQLite scheduler stacks
    # create the (unqualified) table via SQLModel.metadata.create_all
    # instead, so they need no migration file. A component, not a service,
    # but it rides the same rail. Appended last: no FK to any service table.
    include_scheduler = context.get(AnswerKeys.SCHEDULER)
    scheduler_backend = context.get(
        AnswerKeys.SCHEDULER_BACKEND, StorageBackends.MEMORY
    )
    if (
        include_scheduler == "yes" or include_scheduler is True
    ) and scheduler_backend == StorageBackends.POSTGRES:
        services.append("scheduler")

    # Per-user vs shared insights is one folded migration — generation
    # picks the shape from the context flag (see ``generate_migration``).

    return services


# ============================================================================
# Alembic Bootstrap
# ============================================================================

# Files to create when bootstrapping alembic infrastructure
ALEMBIC_TEMPLATE_FILES = [
    "alembic/alembic.ini",
    "alembic/env.py",
    "alembic/script.py.mako",
]


def bootstrap_alembic(
    project_path: Path, jinja_env: Environment, context: dict[str, Any]
) -> list[str]:
    """
    Bootstrap alembic infrastructure by rendering template files.

    This is called when adding a service that needs migrations to a project
    that doesn't yet have alembic set up.

    Args:
        project_path: Path to the project directory
        jinja_env: Jinja2 environment configured for the template directory
        context: Template context (copier answers)

    Returns:
        List of created file paths (relative to project)
    """
    created_files: list[str] = []
    project_slug_placeholder = "{{ project_slug }}"

    for file_path in ALEMBIC_TEMPLATE_FILES:
        # Try with .jinja extension first
        template_name = f"{project_slug_placeholder}/{file_path}.jinja"
        try:
            template = jinja_env.get_template(template_name)
            content = template.render(context)

            output_path = project_path / file_path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(content)
            created_files.append(file_path)
            continue
        except TemplateNotFound:
            # Expected: try loading without .jinja extension (for files like script.py.mako)
            pass

        # Try without .jinja extension (for script.py.mako which is not templated)
        template_name_no_ext = f"{project_slug_placeholder}/{file_path}"
        try:
            template = jinja_env.get_template(template_name_no_ext)
            content = template.render(context)

            output_path = project_path / file_path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(content)
            created_files.append(file_path)
        except TemplateNotFound:
            # Template not found with either extension - file may be optional or not templated
            pass

    # Create versions directory with .gitkeep
    versions_dir = get_versions_dir(project_path)
    versions_dir.mkdir(parents=True, exist_ok=True)
    gitkeep = versions_dir / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.touch()

    return created_files
