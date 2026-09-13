"""
Tests for dynamic migration generator module.

These tests validate the migration generation functionality that creates
Alembic migration files on-demand for services like auth and AI.
"""

from pathlib import Path

import pytest

from aegis.core.migration_generator import (
    MIGRATION_SPECS,
    ORG_MIGRATION,
    VOICE_MIGRATION,
    get_existing_migrations,
    get_next_revision_id,
    get_previous_revision,
    get_services_needing_migrations,
    get_versions_dir,
    service_has_migration,
)


class TestGetServicesNeedingMigrations:
    """Test detection of which services need migrations based on context."""

    def test_auth_only(self) -> None:
        """Test auth service needs migrations."""
        context = {"include_auth": True, "include_ai": False, "ai_backend": "memory"}
        result = get_services_needing_migrations(context)
        assert result == ["auth", "auth_tokens"]

    def test_auth_with_yes_string(self) -> None:
        """Test auth service with 'yes' string (cookiecutter format)."""
        context = {"include_auth": "yes", "include_ai": "no", "ai_backend": "memory"}
        result = get_services_needing_migrations(context)
        assert result == ["auth", "auth_tokens"]

    def test_ai_with_sqlite(self) -> None:
        """Test AI service with sqlite backend needs migrations."""
        context = {"include_auth": False, "include_ai": True, "ai_backend": "sqlite"}
        result = get_services_needing_migrations(context)
        assert result == ["ai", "ai_agents", "ai_sentiment"]

    def test_ai_with_memory_no_migrations(self) -> None:
        """Test AI service with memory backend does NOT need migrations."""
        context = {"include_auth": False, "include_ai": True, "ai_backend": "memory"}
        result = get_services_needing_migrations(context)
        assert result == []

    def test_both_services(self) -> None:
        """Test both auth and AI services need migrations."""
        context = {"include_auth": True, "include_ai": True, "ai_backend": "sqlite"}
        result = get_services_needing_migrations(context)
        assert result == ["auth", "auth_tokens", "ai", "ai_agents", "ai_sentiment"]

    def test_neither_service(self) -> None:
        """Test no services need migrations."""
        context = {"include_auth": False, "include_ai": False, "ai_backend": "memory"}
        result = get_services_needing_migrations(context)
        assert result == []

    def test_blog_needs_migration(self) -> None:
        """Blog service needs migrations when selected."""
        context = {"include_blog": True, "include_ai": False, "ai_backend": "memory"}
        result = get_services_needing_migrations(context)
        assert result == ["blog"]

    def test_blog_needs_migration_with_yes_string(self) -> None:
        """Blog service supports Copier-style yes strings."""
        context = {"include_blog": "yes", "include_ai": False, "ai_backend": "memory"}
        result = get_services_needing_migrations(context)
        assert result == ["blog"]

    def test_documents_needs_migration(self) -> None:
        """The document store owns two tables; a fresh stack must migrate them."""
        context = {
            "include_documents": True,
            "include_ai": False,
            "ai_backend": "memory",
        }
        result = get_services_needing_migrations(context)
        assert result == ["documents"]

    def test_finance_needs_migration(self) -> None:
        """Finance service needs migrations when selected."""
        context = {
            "include_finance": True,
            "include_ai": False,
            "ai_backend": "memory",
        }
        assert get_services_needing_migrations(context) == ["finance"]

    def test_finance_needs_migration_with_yes_string(self) -> None:
        """Finance service supports Copier-style yes strings."""
        context = {
            "include_finance": "yes",
            "include_ai": False,
            "ai_backend": "memory",
        }
        assert get_services_needing_migrations(context) == ["finance"]

    def test_finance_auth_link_when_both(self) -> None:
        """finance + auth emits the owner-FK link migration, after auth+finance."""
        context = {
            "include_auth": True,
            "include_finance": True,
            "include_ai": False,
            "ai_backend": "memory",
        }
        result = get_services_needing_migrations(context)
        assert "finance_auth_link" in result
        # auth (user table) and finance base must precede the link.
        assert result.index("auth") < result.index("finance_auth_link")
        assert result.index("finance") < result.index("finance_auth_link")

    def test_no_finance_auth_link_without_auth(self) -> None:
        """Standalone finance emits no link migration."""
        context = {
            "include_finance": True,
            "include_ai": False,
            "ai_backend": "memory",
        }
        assert "finance_auth_link" not in get_services_needing_migrations(context)

    def test_auth_rbac_needs_migration(self) -> None:
        """Test auth_rbac migration needed when rbac level enabled."""
        context = {
            "include_auth": "yes",
            "include_auth_rbac": "yes",
            "include_ai": False,
            "ai_backend": "memory",
        }
        result = get_services_needing_migrations(context)
        assert "auth_rbac" in result

    def test_auth_rbac_needs_migration_via_auth_level(self) -> None:
        """Test auth_rbac detected via auth_level fallback."""
        context = {
            "include_auth": "yes",
            "auth_level": "rbac",
            "include_ai": False,
            "ai_backend": "memory",
        }
        result = get_services_needing_migrations(context)
        assert "auth_rbac" in result

    def test_auth_rbac_needs_migration_when_org(self) -> None:
        """Test auth_rbac also generated for org level (org implies rbac)."""
        context = {
            "include_auth": "yes",
            "auth_level": "org",
            "include_ai": False,
            "ai_backend": "memory",
        }
        result = get_services_needing_migrations(context)
        assert "auth_rbac" in result
        assert "auth_org" in result

    def test_auth_rbac_not_needed_for_basic(self) -> None:
        """Test auth_rbac not generated for basic auth."""
        context = {
            "include_auth": "yes",
            "auth_level": "basic",
            "include_ai": False,
            "ai_backend": "memory",
        }
        result = get_services_needing_migrations(context)
        assert "auth" in result
        assert "auth_rbac" not in result

    def test_auth_org_needs_migration(self) -> None:
        """Test auth_org service needs migration when org level enabled."""
        context = {
            "include_auth": "yes",
            "include_auth_org": "yes",
            "include_ai": False,
            "ai_backend": "memory",
        }
        result = get_services_needing_migrations(context)
        assert "auth_org" in result

    def test_auth_org_not_needed_without_org(self) -> None:
        """Test auth_org service not needed when org level disabled."""
        context = {
            "include_auth": "yes",
            "include_auth_org": "no",
            "include_ai": False,
            "ai_backend": "memory",
        }
        result = get_services_needing_migrations(context)
        assert "auth_org" not in result

    def test_auth_org_needs_migration_via_auth_level(self) -> None:
        """Test auth_org detected via auth_level fallback when include_auth_org missing."""
        context = {
            "include_auth": "yes",
            "auth_level": "org",
            "include_ai": False,
            "ai_backend": "memory",
        }
        result = get_services_needing_migrations(context)
        assert "auth_org" in result

    def test_auth_org_not_needed_without_auth(self) -> None:
        """Test auth_org service not needed when auth not included."""
        context = {
            "include_auth": False,
            "include_auth_org": "yes",
            "include_ai": False,
            "ai_backend": "memory",
        }
        result = get_services_needing_migrations(context)
        assert "auth_org" not in result


class TestGetVersionsDir:
    """Test getting the alembic versions directory."""

    def test_returns_correct_path(self, tmp_path: Path) -> None:
        """Test that correct versions path is returned."""
        result = get_versions_dir(tmp_path)
        assert result == tmp_path / "alembic" / "versions"


class TestGetExistingMigrations:
    """Test detection of existing migration files."""

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Test returns empty list when no migrations exist."""
        result = get_existing_migrations(tmp_path)
        assert result == []

    def test_nonexistent_directory(self, tmp_path: Path) -> None:
        """Test returns empty list when versions dir doesn't exist."""
        result = get_existing_migrations(tmp_path / "nonexistent")
        assert result == []

    def test_finds_migrations(self, tmp_path: Path) -> None:
        """Test finds existing migration files."""
        versions_dir = tmp_path / "alembic" / "versions"
        versions_dir.mkdir(parents=True)

        # Create some migration files
        (versions_dir / "001_auth.py").touch()
        (versions_dir / "002_ai.py").touch()
        (versions_dir / "__init__.py").touch()  # Should be ignored

        result = get_existing_migrations(tmp_path)
        assert result == ["001", "002"]

    def test_sorts_by_filename(self, tmp_path: Path) -> None:
        """Test migrations are sorted by filename."""
        versions_dir = tmp_path / "alembic" / "versions"
        versions_dir.mkdir(parents=True)

        # Create in non-sorted order
        (versions_dir / "003_third.py").touch()
        (versions_dir / "001_first.py").touch()
        (versions_dir / "002_second.py").touch()

        result = get_existing_migrations(tmp_path)
        assert result == ["001", "002", "003"]


class TestGetNextRevisionId:
    """Test getting the next revision ID."""

    def test_first_migration(self, tmp_path: Path) -> None:
        """Test returns '001' for first migration."""
        result = get_next_revision_id(tmp_path)
        assert result == "001"

    def test_increments_existing(self, tmp_path: Path) -> None:
        """Test increments from existing migrations."""
        versions_dir = tmp_path / "alembic" / "versions"
        versions_dir.mkdir(parents=True)
        (versions_dir / "001_auth.py").touch()
        (versions_dir / "002_ai.py").touch()

        result = get_next_revision_id(tmp_path)
        assert result == "003"


class TestGetPreviousRevision:
    """Test getting the previous revision ID."""

    def test_no_migrations(self, tmp_path: Path) -> None:
        """Test returns None when no migrations exist."""
        result = get_previous_revision(tmp_path)
        assert result is None

    def test_returns_last_revision(self, tmp_path: Path) -> None:
        """Test returns the most recent revision."""
        versions_dir = tmp_path / "alembic" / "versions"
        versions_dir.mkdir(parents=True)
        (versions_dir / "001_auth.py").touch()
        (versions_dir / "002_ai.py").touch()

        result = get_previous_revision(tmp_path)
        assert result == "002"


class TestServiceHasMigration:
    """Test detection of existing service migrations."""

    def test_no_migrations(self, tmp_path: Path) -> None:
        """Test returns False when no migrations exist."""
        result = service_has_migration(tmp_path, "auth")
        assert result is False

    def test_migration_exists(self, tmp_path: Path) -> None:
        """Test returns True when service migration exists."""
        versions_dir = tmp_path / "alembic" / "versions"
        versions_dir.mkdir(parents=True)
        (versions_dir / "001_auth.py").touch()

        result = service_has_migration(tmp_path, "auth")
        assert result is True

    def test_different_service(self, tmp_path: Path) -> None:
        """Test returns False for different service."""
        versions_dir = tmp_path / "alembic" / "versions"
        versions_dir.mkdir(parents=True)
        (versions_dir / "001_auth.py").touch()

        result = service_has_migration(tmp_path, "ai")
        assert result is False


class TestOrgMigrationSpec:
    """Test organization migration specification."""

    def test_org_spec_exists(self) -> None:
        """Test org migration spec is defined in MIGRATION_SPECS."""
        assert "auth_org" in MIGRATION_SPECS
        assert ORG_MIGRATION.service_name == "auth_org"


class TestVoiceMigrationSpec:
    """Test AI voice migration specification.

    The voice migration creates the voice_usage table for tracking
    TTS (Text-to-Speech) and STT (Speech-to-Text) usage.
    """

    def test_ai_voice_spec_exists(self) -> None:
        """Test ai_voice migration spec is defined in MIGRATION_SPECS."""
        assert "ai_voice" in MIGRATION_SPECS
        assert VOICE_MIGRATION.service_name == "ai_voice"

    def test_voice_migration_description(self) -> None:
        """Voice migration should have a descriptive description."""
        assert "voice" in VOICE_MIGRATION.description.lower()
        assert "tts" in VOICE_MIGRATION.description.lower()
        assert "stt" in VOICE_MIGRATION.description.lower()


class TestGetServicesNeedingMigrationsVoice:
    """Test detection of ai_voice service needing migrations."""

    def test_ai_voice_needs_migration_when_enabled(self) -> None:
        """AI voice should need migration when all conditions met."""
        context = {
            "include_auth": False,
            "include_ai": True,
            "ai_backend": "sqlite",
            "ai_voice": True,
        }
        result = get_services_needing_migrations(context)
        assert "ai_voice" in result

    def test_ai_voice_needs_migration_with_yes_string(self) -> None:
        """AI voice should work with 'yes' string (cookiecutter format)."""
        context = {
            "include_auth": False,
            "include_ai": "yes",
            "ai_backend": "sqlite",
            "ai_voice": "yes",
        }
        result = get_services_needing_migrations(context)
        assert "ai_voice" in result

    def test_ai_voice_not_needed_when_disabled(self) -> None:
        """AI voice should not need migration when voice disabled."""
        context = {
            "include_auth": False,
            "include_ai": True,
            "ai_backend": "sqlite",
            "ai_voice": False,
        }
        result = get_services_needing_migrations(context)
        assert "ai_voice" not in result

    def test_ai_voice_not_needed_without_persistence(self) -> None:
        """AI voice should not need migration with memory backend."""
        context = {
            "include_auth": False,
            "include_ai": True,
            "ai_backend": "memory",
            "ai_voice": True,
        }
        result = get_services_needing_migrations(context)
        assert "ai_voice" not in result

    def test_ai_voice_not_needed_without_ai(self) -> None:
        """AI voice should not need migration without AI service."""
        context = {
            "include_auth": False,
            "include_ai": False,
            "ai_backend": "sqlite",
            "ai_voice": True,
        }
        result = get_services_needing_migrations(context)
        assert "ai_voice" not in result

    def test_full_stack_with_voice(self) -> None:
        """Full stack with auth, AI, and voice should have all migrations."""
        context = {
            "include_auth": True,
            "include_ai": True,
            "ai_backend": "sqlite",
            "ai_voice": True,
        }
        result = get_services_needing_migrations(context)
        assert result == [
            "auth",
            "auth_tokens",
            "ai",
            "ai_agents",
            "ai_sentiment",
            "ai_voice",
        ]


class TestAgentsMigration:
    """The agent registry rides its own spec, gated exactly like ``ai``."""

    def test_ai_with_sqlite_includes_agents(self) -> None:
        """A persistence backend pulls in the agent registry migration."""
        context = {"include_auth": False, "include_ai": True, "ai_backend": "sqlite"}
        result = get_services_needing_migrations(context)
        assert "ai_agents" in result
        # Chains directly after the ai catalog tables.
        assert result.index("ai_agents") == result.index("ai") + 1

    def test_ai_with_memory_excludes_agents(self) -> None:
        """Memory backend means no agent tables (code-fallback config)."""
        context = {"include_auth": False, "include_ai": True, "ai_backend": "memory"}
        result = get_services_needing_migrations(context)
        assert "ai_agents" not in result

    def test_agents_in_migration_specs(self) -> None:
        """The spec is registered on the ai service."""
        from aegis.core.migration_generator import AGENTS_MIGRATION

        assert "ai_agents" in MIGRATION_SPECS
        assert AGENTS_MIGRATION.service_name == "ai_agents"


class TestKnowledgeMigration:
    """KB metadata tables gate on ai + persistence + the rag flag."""

    def test_ai_sqlite_with_rag_includes_knowledge(self) -> None:
        context = {
            "include_auth": False,
            "include_ai": True,
            "ai_backend": "sqlite",
            "ai_rag": True,
        }
        result = get_services_needing_migrations(context)
        assert "ai_knowledge" in result
        assert result.index("ai_knowledge") == result.index("ai_agents") + 1

    def test_no_rag_flag_excludes_knowledge(self) -> None:
        context = {"include_auth": False, "include_ai": True, "ai_backend": "sqlite"}
        result = get_services_needing_migrations(context)
        assert "ai_knowledge" not in result

    def test_rag_with_memory_backend_excludes_knowledge(self) -> None:
        context = {
            "include_auth": False,
            "include_ai": True,
            "ai_backend": "memory",
            "ai_rag": True,
        }
        result = get_services_needing_migrations(context)
        assert "ai_knowledge" not in result


class TestSentimentMigration:
    """Sentiment rides its own spec, gated on ai + persistence."""

    def test_ai_with_sqlite_includes_sentiment(self) -> None:
        context = {"include_auth": False, "include_ai": True, "ai_backend": "sqlite"}
        result = get_services_needing_migrations(context)
        assert "ai_sentiment" in result
        assert result.index("ai_sentiment") > result.index("ai_agents")

    def test_ai_with_memory_excludes_sentiment(self) -> None:
        context = {"include_auth": False, "include_ai": True, "ai_backend": "memory"}
        result = get_services_needing_migrations(context)
        assert "ai_sentiment" not in result


class TestSchedulerComponentMigration:
    """The scheduler component rides the service migration rail."""

    def test_scheduler_in_registry(self) -> None:
        """Component migration is collected alongside services."""
        assert "scheduler" in MIGRATION_SPECS
        assert MIGRATION_SPECS["scheduler"].schema == "scheduler"

    def test_selected_for_postgres(self) -> None:
        """Postgres scheduler persistence selects the schema'd migration."""
        context = {"include_scheduler": True, "scheduler_backend": "postgres"}
        assert "scheduler" in get_services_needing_migrations(context)

    def test_selected_for_sqlite(self) -> None:
        """Any persistent job store gets its tables from a revision."""
        context = {"include_scheduler": True, "scheduler_backend": "sqlite"}
        assert "scheduler" in get_services_needing_migrations(context)

    def test_not_selected_for_memory(self) -> None:
        context = {"include_scheduler": True, "scheduler_backend": "memory"}
        assert "scheduler" not in get_services_needing_migrations(context)

    def test_not_selected_when_absent(self) -> None:
        context = {"include_auth": True}
        assert "scheduler" not in get_services_needing_migrations(context)


class TestMigrationsAreIdempotentOnPrepopulatedSQLite:
    """SQLite projects run ``SQLModel.metadata.create_all`` at startup
    (``app/core/db.py``), so their database already holds every table the
    models define - ahead of any migration. A revision the project predates
    is then delivered by ``aegis update`` and its ``create_table`` collides
    with a table ``create_all`` already made (#1024: ``table
    password_reset_token already exists``).

    Postgres projects are migration-only and never hit this, so the guard
    is exactly what the ticket asked for: inspector-checked per table, one
    chain serving both a pre-populated and a fresh database.
    """

    def _apply(self, source: str, url: str) -> None:
        """Execute a rendered migration's ``upgrade()`` against ``url``."""
        import sys
        import types

        import sqlalchemy as sa
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        # Rendered migrations ``import sqlmodel`` (a generated-project
        # dependency the framework venv does not carry). Only ``upgrade()``
        # is under test, so a stub module satisfies the import.
        stub = types.ModuleType("sqlmodel")
        stub.sql = types.ModuleType("sqlmodel.sql")  # type: ignore[attr-defined]
        stub.sql.sqltypes = types.ModuleType("sqlmodel.sql.sqltypes")  # type: ignore[attr-defined]
        stub.sql.sqltypes.AutoString = sa.String  # type: ignore[attr-defined]
        saved = {
            k: sys.modules.get(k)
            for k in ("sqlmodel", "sqlmodel.sql", "sqlmodel.sql.sqltypes")
        }
        sys.modules["sqlmodel"] = stub
        sys.modules["sqlmodel.sql"] = stub.sql  # type: ignore[attr-defined]
        sys.modules["sqlmodel.sql.sqltypes"] = stub.sql.sqltypes  # type: ignore[attr-defined]
        try:
            engine = sa.create_engine(url)
            with engine.begin() as conn:
                ctx = MigrationContext.configure(conn)
                with Operations.context(ctx):
                    ns: dict = {}
                    exec(compile(source, "<migration>", "exec"), ns)
                    ns["upgrade"]()
            engine.dispose()
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v

    def test_add_column_on_existing_table_still_fails_loudly(
        self, tmp_path: Path
    ) -> None:
        """The table guard must NOT extend to ``add_column``: a column that
        already exists is a real schema conflict (#1023-shaped), not
        ``create_all`` pre-creation, and hiding it would hide the bug."""
        import sqlalchemy as sa

        url = f"sqlite:///{tmp_path / 'app.db'}"
        engine = sa.create_engine(url)
        with engine.begin() as conn:
            conn.execute(sa.text("CREATE TABLE t (id INTEGER PRIMARY KEY, x TEXT)"))
        engine.dispose()

        source = (
            "from alembic import op\nimport sqlalchemy as sa\n"
            "def upgrade():\n"
            "    with op.batch_alter_table('t') as b:\n"
            "        b.add_column(sa.Column('x', sa.String(), nullable=True))\n"
        )
        with pytest.raises(Exception):
            self._apply(source, url)
