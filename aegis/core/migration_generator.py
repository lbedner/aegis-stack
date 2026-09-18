"""Revision generation for services that own tables.

A revision's contents come from the project's SQLModel classes, never from
a declaration here: ``generate_revisions`` runs the generated project's own
``app/cli/migrate_gen.py`` in its venv, which replays the existing revisions
onto a scratch database, autogenerates the difference against
``SQLModel.metadata``, and writes one revision per service. So a column is
declared in exactly one place - the model - and ``aegis init`` and
``aegis add`` produce the same schema as ``create_all``.

What stays here is what models cannot express: which services need a
revision at all (``get_services_needing_migrations``), the alembic tree a
project needs before it can hold one (``bootstrap_alembic``), and per
service a ``ServiceMigrationSpec`` naming the revision, its Postgres schema,
the object that proves it ran, and any mandatory data statement.

Usage:
    # During aegis init / update
    generate_revisions(project_path, get_services_needing_migrations(answers))

    # During aegis add
    if not service_has_migration(project_path, "ai"):
        generate_migration(project_path, "ai")
"""

import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, TemplateNotFound

from ..constants import (
    AnswerKeys,
    AuthLevels,
    StorageBackends,
)


@dataclass
class ServiceMigrationSpec:
    """What a service's revision is called, and what cannot be derived.

    The revision body comes from the SQLModel classes; this names the
    revision, the Postgres schema its tables live in, the object that
    proves it ran, and any data statement the models cannot express.
    """

    service_name: str
    description: str
    # Postgres schema all of this spec's tables live in. None keeps them
    # in the default schema (``public``) and renders byte-identically to
    # pre-schema migrations. Schemas are Postgres-only: SQLite ignores
    # this (it has no CREATE SCHEMA) and keeps every table in one DB.
    schema: str | None = None
    # Proof this migration already ran, for the startup hook that
    # re-adopts a persisted database by stamping instead of replaying
    # DDL. ``("table", name)``, ``("column", table, col)``,
    # ``("foreign_key", table, col)``, or ``("row", table, where)`` for a
    # data-only revision (data_sql). A migration without one opts out
    # of that recovery, so every shipped migration should carry it;
    # in-tree services declare theirs in ``migration_signatures.py``.
    stamp_signature: tuple[str, ...] | None = None
    # Raw statements run after the DDL in ``upgrade()``, for the rare data
    # a schema change makes mandatory (a row a new FK points at). Each
    # must be idempotent: ``aegis update`` can deliver a migration to a
    # database that already holds the row. Not reversed in ``downgrade``.
    data_sql: list[str] = field(default_factory=list)
    # Same job as ``data_sql`` but written as the body of ``upgrade()``
    # instead of one statement, for data whose SHAPE depends on the
    # database it lands in. The sentinel owner row is the case: the
    # column list it must name differs by auth level, and one service's
    # migration has no business knowing another's answers, so it asks
    # the database instead. Mutually exclusive with ``data_sql``.
    data_body: str = ""
    # Tables emptied BEFORE this service's DDL runs. Declared rather than
    # written as SQL because two places need it: the revision gets a DELETE
    # at the top of ``upgrade()``, and the generator is told the table will
    # be empty so a required column with nothing to backfill is still safe
    # to add to it. Only for derived rows something else can rewrite.
    cleared_tables: list[str] = field(default_factory=list)


# ============================================================================
# Service Migration Definitions
# ============================================================================

# ============================================================================
# Service migration specs
#
# What a revision CONTAINS comes from the models, derived per project by
# ``app/cli/migrate_gen.py``. A spec names the revision, the Postgres schema
# its tables live in, the proof object the startup hook re-adopts it by, and
# any data statement the models cannot express.
# ============================================================================


def _sentinel_owner_insert(user_ref_schema: str | None) -> str:
    """The body of ``upgrade()`` for the finance sentinel owner row.

    ``user.role`` exists only under auth RBAC and is NOT NULL with no
    server default, so an insert that never names it fails outright on an
    org-level stack (``NOT NULL constraint failed: user.role``). Which
    columns to name is therefore a property of the database this revision
    lands in, not of the answers that generated it — and an ``aegis
    update`` that raises the auth level later moves it. So the revision
    asks the table, the way ``cleared_tables`` asks whether a table is
    there, rather than being told at generation time.
    """
    user_table = f'"{user_ref_schema}"."user"' if user_ref_schema else '"user"'
    reflect = (
        f'sa.inspect(op.get_bind()).get_columns("user", schema={user_ref_schema!r})'
        if user_ref_schema
        else 'sa.inspect(op.get_bind()).get_columns("user")'
    )
    return f"""    columns = {{c["name"] for c in {reflect}}}
    role_column = ", role" if "role" in columns else ""
    role_value = ", 'user'" if "role" in columns else ""
    op.execute(
        f'INSERT INTO {user_table} '
        f"(id, email, is_active, is_verified, hashed_password, "
        f"failed_login_attempts, created_at{{role_column}}) "
        # Boolean literals, not 0: Postgres refuses an integer in a boolean
        # column and SQLite accepts FALSE (3.23+), so one serves both.
        f"SELECT 0, 'standalone@finance.local', FALSE, FALSE, '!', 0, "
        f"CURRENT_TIMESTAMP{{role_value}} "
        f'WHERE NOT EXISTS (SELECT 1 FROM {user_table} WHERE id = 0)'
    )"""


AUTH_MIGRATION = ServiceMigrationSpec(
    service_name="auth",
    description="Auth service tables",
)

AUTH_RBAC_MIGRATION = ServiceMigrationSpec(
    service_name="auth_rbac",
    description="RBAC role column for user table",
)

ORG_MIGRATION = ServiceMigrationSpec(
    service_name="auth_org",
    description="Organization and membership tables",
)

AI_MIGRATION = ServiceMigrationSpec(
    service_name="ai",
    description="AI service tables (LLM catalog, usage tracking, conversations)",
    # ``llm_deployment`` and ``llm_price`` are catalog rows, written by the
    # LLM sync and derived from it entirely. When a revision adds a required
    # column they cannot supply (``org_id``, from the vendor-to-org change),
    # the rows that predate it have no value to take, and there is nothing
    # in them worth a mapping migration: clear them and let ``llm sync``
    # write them again. ``llm_usage`` is history and is never touched.
    cleared_tables=["llm_deployment", "llm_price"],
)

AGENTS_MIGRATION = ServiceMigrationSpec(
    service_name="ai_agents",
    description="AI agent registry tables (agents, tools, agent-tool links)",
)

KNOWLEDGE_MIGRATION = ServiceMigrationSpec(
    service_name="ai_knowledge",
    description="Knowledge base metadata (agent-scoped RAG collections)",
)

SENTIMENT_MIGRATION = ServiceMigrationSpec(
    service_name="ai_sentiment",
    description="Conversation sentiment analysis results",
)

AUTH_TOKENS_MIGRATION = ServiceMigrationSpec(
    service_name="auth_tokens",
    description="Auth token tables (password reset, email verification, refresh)",
)

VOICE_MIGRATION = ServiceMigrationSpec(
    service_name="ai_voice",
    description="AI voice service table (TTS and STT usage tracking)",
)

INSIGHTS_MIGRATION = ServiceMigrationSpec(
    service_name="insights",
    description="Insights service tables (sources, metrics, records, events)",
)

PAYMENT_MIGRATION = ServiceMigrationSpec(
    service_name="payment",
    description="Payment service tables (providers, customers, transactions, subscriptions, disputes)",
)

PAYMENT_AUTH_LINK_MIGRATION = ServiceMigrationSpec(
    service_name="payment_auth_link",
    description="Link payment_customer.user_id to user.id (auth + payment)",
)

DOCUMENTS_MIGRATION = ServiceMigrationSpec(
    service_name="documents",
    description="Document store: the paper, addressed by its own content",
)

FINANCE_MIGRATION = ServiceMigrationSpec(
    service_name="finance",
    description="Finance service tables (currencies, fx rates)",
)

FINANCE_AUTH_LINK_MIGRATION = ServiceMigrationSpec(
    service_name="finance_auth_link",
    description="Link finance owner_user_id columns to user.id (auth + finance)",
    data_body=_sentinel_owner_insert(None),
)

BLOG_MIGRATION = ServiceMigrationSpec(
    service_name="blog",
    description="Blog service tables (posts, tags, post/tag links)",
)

SCHEDULER_MIGRATION = ServiceMigrationSpec(
    service_name="scheduler",
    description="Scheduler job execution history",
    schema="scheduler",
)


# Default registry-facing variant is the shared-mode shape. Per-user mode
# rebuilds the spec at generation time via _build_insights_migration(True).


# Finance service tables. Built up incrementally across the finance schema
# tickets; all live in the default (public) schema so SQLite stacks get the
# migration too (a Postgres-only ``schema=`` would forfeit that). Money and
# scaled-integer columns use BigInteger — net worth / brokerage balances and
# ``*_e8`` quantities/rates overflow int32.


# Postgres schema finance tables live in (dropped on SQLite, which has none).
# Kept as a module-level alias for readability at the table-builder call sites.

# Every finance table with an ``owner_user_id`` column. The auth-link migration
# adds an FK from each to ``user.id`` when the auth service is present. Grows as
# owner-scoped tables land across the schema tickets.


# The sentinel row is written unqualified: ``user`` lives in the default
# schema on Postgres too, so one statement serves both engines.


# ============================================================================
# Component Migration Definitions
# ============================================================================

# The scheduler is a COMPONENT (not a service) and this is the first
# component-owned table. It lives in a dedicated ``scheduler`` Postgres
# schema so component tables stay namespaced apart from service tables.
# On SQLite (no schema support) the table lands unqualified in the single
# database file — see the model's engine-gated ``__table_args__``.

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


class MigrationGenerationError(RuntimeError):
    """The project's revision generator failed; carries its stderr."""


GENERATE_REVISIONS_TIMEOUT = 300


_REVISION_FRAME = re.compile(r'File "[^"]*[/\\]versions[/\\]([^"/\\]+\.py)"')


def _replay_hint(stderr: str) -> str:
    """Name the revision a scratch replay died in, when one is in the traceback.

    ``migrate_gen`` replays the project's whole chain onto an empty scratch
    database, so a revision that needs rows raises there with only its own
    message — true, and useless. The traceback names the file; say what it
    means, last, where a tail read will find it.
    """
    frames = _REVISION_FRAME.findall(stderr)
    if not frames:
        return ""
    return (
        f"\n\n{frames[-1]} failed replaying the migration chain onto an empty "
        "scratch database. That database has no rows by construction: make "
        "the revision tolerate an empty database."
    )


def _cleared_tables_for(service: str) -> list[str]:
    spec = _get_migration_specs().get(service)
    return list(spec.cleared_tables) if spec else []


def generate_revisions(
    project_path: Path,
    services: list[str],
    python_version: str | None = None,
) -> list[Path]:
    """Derive revisions from the project's models, one per service.

    The models live in the project and import its dependencies, so the
    generator (``app/cli/migrate_gen.py``) runs in the project's venv via
    ``uv run --project``; aegis itself never renders a table. A service
    whose tables are already covered by an earlier revision produces no
    file, which is what makes re-running this idempotent.

    Returns the revision files this call wrote, in name order.
    """
    if not services:
        return []
    versions_dir = get_versions_dir(project_path)
    versions_dir.mkdir(parents=True, exist_ok=True)
    before = set(versions_dir.glob("*.py"))
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    # UV_PYTHON pins the interpreter for the *aegis* tool (3.11 in CI and
    # the release jobs). The generated project has its own requires-python
    # and must be allowed to resolve its own; inheriting the pin fails the
    # run outright on a project that asks for 3.14.
    env.pop("UV_PYTHON", None)
    cmd = ["uv", "run", "--project", str(project_path)]
    if python_version:
        cmd.extend(["--python", python_version])
    # By environment, not by flag: ``--to-version <older tag>`` hands the
    # project a migrate_gen that predates this knob, and an unknown argument
    # is fatal to argparse while an unread variable costs nothing.
    cleared = sorted({t for name in services for t in _cleared_tables_for(name)})
    if cleared:
        env["AEGIS_CLEARED_TABLES"] = ",".join(cleared)
    cmd.extend(["python", "-m", "app.cli.migrate_gen", *services])
    result = subprocess.run(
        cmd,
        cwd=project_path,
        capture_output=True,
        text=True,
        timeout=GENERATE_REVISIONS_TIMEOUT,
        env=env,
    )
    if result.returncode != 0:
        raise MigrationGenerationError(
            f"migrate_gen failed for {', '.join(services)}:\n"
            f"{result.stderr[-2000:]}{_replay_hint(result.stderr)}"
        )
    written = sorted(set(versions_dir.glob("*.py")) - before)
    written.extend(_place_data_statements(project_path, services, written))
    return sorted(written)


_DATA_REVISION = '''"""{description}

Revision ID: {revision}
Revises: {down_revision}
Create Date: {create_date}

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = {revision!r}
down_revision = {down_revision!r}
branch_labels = None
depends_on = None


def upgrade() -> None:
{body}


def downgrade() -> None:
    pass
'''


def _data_lines(statements: list[str]) -> str:
    return "\n".join(f'    op.execute("""{stmt}""")' for stmt in statements)


def _upgrade_body(spec: "ServiceMigrationSpec") -> str:
    """What this spec adds to ``upgrade()``: statements, or a raw body."""
    return spec.data_body or _data_lines(spec.data_sql)


_CLEAR_TABLE = """    if sa.inspect(op.get_bind()).has_table("{table}"):
        op.execute("DELETE FROM {table}")"""


def _prepend_to_upgrade(name: str, src: str, tables: list[str]) -> str:
    """Empty ``tables`` at the top of ``upgrade()``, before any DDL.

    A row that a new NOT NULL column cannot be filled for has to be gone
    before the column lands, not after, so this cannot ride at the end the
    way ``data_sql`` does.

    Guarded on the table existing, because the same revision is what
    CREATES it on a fresh project: there the clear runs against nothing and
    must not be an error.
    """
    marker = "def upgrade() -> None:\n"
    if marker not in src:
        raise MigrationGenerationError(
            f"{name}: no upgrade() to anchor data statements"
        )
    head, _, tail = src.partition(marker)
    clears = "\n".join(_CLEAR_TABLE.format(table=t) for t in tables)
    return f"{head}{marker}{clears}\n{tail}"


def _place_data_statements(
    project_path: Path, services: list[str], written: list[Path]
) -> list[Path]:
    """Give every service's ``data_sql`` a revision to run in.

    The models decide the DDL; ``data_sql`` is the one thing they cannot
    describe (a row a new FK points at, #1110). It rides in the revision
    the run just wrote for its service, or - when the models produced
    nothing for that service, as ``finance_auth_link`` does now that its
    FKs are inline in ``finance`` - in a data-only revision written here.
    Each statement must be idempotent: ``aegis update`` can deliver a
    revision to a database that already holds the row.

    Returns the data-only revisions this call created.
    """
    specs = _get_migration_specs()
    created: list[Path] = []
    for service in services:
        spec = specs.get(service)
        if spec is None or not (spec.data_sql or spec.data_body or spec.cleared_tables):
            continue
        own = [p for p in written if p.name.endswith(f"_{service}.py")]
        if own:
            src = own[0].read_text()
            if spec.cleared_tables:
                src = _prepend_to_upgrade(own[0].name, src, spec.cleared_tables)
            if spec.data_sql or spec.data_body:
                head, sep, tail = src.rpartition("\n\n\ndef downgrade")
                if not sep:
                    raise MigrationGenerationError(
                        f"{own[0].name}: no downgrade() to anchor data statements"
                    )
                src = f"{head}\n{_upgrade_body(spec)}{sep}{tail}"
            own[0].write_text(src)
        elif (spec.data_sql or spec.data_body) and not service_has_migration(
            project_path, service
        ):
            revision = get_next_revision_id(project_path)
            path = get_versions_dir(project_path) / f"{revision}_{service}.py"
            path.write_text(
                _DATA_REVISION.format(
                    description=spec.description,
                    revision=revision,
                    down_revision=get_previous_revision(project_path),
                    create_date=datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f"),
                    body=_upgrade_body(spec),
                )
            )
            created.append(path)
    return created


def generate_migration(
    project_path: Path,
    service_name: str,
    context: dict[str, Any] | None = None,
) -> Path | None:
    """Write the revision for one service, derived from the project's models.

    ``context`` is accepted for callers that still pass it; the models
    already carry every engine and variant decision. Returns the file
    written, or None when the service's tables are all in earlier revisions.
    """
    del context
    written = generate_revisions(project_path, [service_name])
    return written[0] if written else None


def generate_missing_migrations(
    project_path: Path, answers: dict[str, Any]
) -> list[Path]:
    """Write every migration the project's answers call for that has no
    revision yet. An auth level upgrade is the common case: the answers
    now say ``auth_level: org``, so ``auth_rbac`` and ``auth_org`` are
    needed and missing. Shared by ``add-service`` and the resolver's
    ``ManualUpdater.add_service`` so both tails agree."""
    return generate_revisions(project_path, get_services_needing_migrations(answers))


def generate_plugin_migrations(
    project_path: Path,
    plugin_spec: Any,
    context: dict[str, Any] | None = None,
) -> list[Path]:
    """Write every migration a plugin declares, once.

    Third-party plugins are not in the static registry ``generate_migration``
    resolves names against, but ``aegis add <plugin>`` holds the spec in
    hand, so its ``migrations`` list is rendered directly. Each spec gets
    the same engine gating in-tree services get, and one that already has
    a file in ``alembic/versions`` is skipped, so re-adding a plugin never
    stacks a duplicate revision.

    Returns the paths written, in declaration order.
    """
    del context
    names = [m.service_name for m in getattr(plugin_spec, "migrations", None) or []]
    return generate_revisions(project_path, names)


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

    # Documents service (always needs database)
    include_documents = context.get(AnswerKeys.DOCUMENTS)
    if include_documents == "yes" or include_documents is True:
        services.append("documents")

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

    # Scheduler component: its job store and execution-history tables, on
    # any persistent backend. A component, not a service, but it rides the
    # same rail. Appended last: no FK to any service table.
    include_scheduler = context.get(AnswerKeys.SCHEDULER)
    scheduler_backend = context.get(
        AnswerKeys.SCHEDULER_BACKEND, StorageBackends.MEMORY
    )
    if (
        include_scheduler == "yes" or include_scheduler is True
    ) and scheduler_backend != StorageBackends.MEMORY:
        services.append("scheduler")

    # Per-user vs shared insights is one folded migration — generation
    # picks the shape from the context flag (see ``generate_migration``).

    return services


# ============================================================================
# Alembic Bootstrap
# ============================================================================

# Files to create when bootstrapping alembic infrastructure
ALEMBIC_PIN = "alembic==1.16.5"

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

    _pin_alembic(project_path)
    return created_files


def _pin_alembic(project_path: Path) -> None:
    """Add alembic to the project's dependencies if it isn't there.

    A project whose answers call for no migrations ships without alembic;
    a plugin that declares migrations makes it need one. The template's
    own gate covers in-tree services (the answers change and pyproject is
    re-rendered), but a plugin is not an answer. ``uv run`` syncs the
    environment before the generator runs, so writing the pin is enough.
    """
    pyproject = project_path / "pyproject.toml"
    if not pyproject.is_file():
        return
    content = pyproject.read_text()
    marker = "dependencies = [\n"
    if marker not in content:
        return
    head, _, tail = content.partition(marker)
    # Only the dependency list decides: every database project also names
    # alembic in its poe tasks further down the file.
    if "alembic" in tail[: tail.index("]")]:
        return
    pyproject.write_text(f'{head}{marker}    "{ALEMBIC_PIN}",\n{tail}')
