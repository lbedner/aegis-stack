"""
Tests for add-service migration generation.

This module tests that 'aegis add-service' properly bootstraps alembic
and generates migration files when adding services to base projects.

Uses project_factory fixture to get cached project skeletons instead of
regenerating projects from scratch for each test.
"""

import sqlite3

import pytest

from tests.cli.conftest import ProjectFactory
from tests.cli.test_utils import run_aegis_command


class TestAddServiceMigrationGeneration:
    """Test that add-service generates migrations correctly."""

    @pytest.mark.slow
    def test_add_auth_to_base_project_creates_alembic(
        self, project_factory: ProjectFactory
    ) -> None:
        """Test that adding auth service to base project bootstraps alembic."""
        # Get cached base project copy
        project_path = project_factory("base")

        # Verify base project has no alembic
        alembic_dir = project_path / "alembic"
        assert not alembic_dir.exists(), "Base project should not have alembic"

        # Add auth service
        result = run_aegis_command(
            "add-service",
            "auth",
            "--project-path",
            str(project_path),
            "--yes",
        )
        assert result.returncode == 0, f"Add-service failed: {result.stderr}"

        # Verify alembic was bootstrapped
        assert alembic_dir.exists(), "Alembic directory should exist after add-service"
        assert (alembic_dir / "alembic.ini").exists(), "alembic.ini should exist"
        assert (alembic_dir / "env.py").exists(), "env.py should exist"

        # Verify migration was generated
        versions_dir = alembic_dir / "versions"
        assert versions_dir.exists(), "versions directory should exist"

        migration_files = list(versions_dir.glob("001_auth.py"))
        assert len(migration_files) == 1, "Should have auth migration file"

        # Verify migration content
        migration_content = migration_files[0].read_text()
        assert "user" in migration_content, "Migration should create user table"
        assert "email" in migration_content, "Migration should have email column"

    @pytest.mark.slow
    def test_add_auth_to_project_with_existing_alembic_generates_migration_only(
        self, project_factory: ProjectFactory
    ) -> None:
        """Test adding auth to project that already has alembic from ai[sqlite]."""
        # Get cached ai[sqlite] project copy (already has alembic)
        project_path = project_factory("base_with_ai_sqlite_service")

        alembic_dir = project_path / "alembic"
        versions_dir = alembic_dir / "versions"

        # Verify ai migrations exist (catalog + agent registry)
        ai_migrations = list(versions_dir.glob("001_ai.py"))
        assert len(ai_migrations) == 1, "Should have ai migration"
        agents_migrations = list(versions_dir.glob("002_ai_agents.py"))
        assert len(agents_migrations) == 1, "Should have ai_agents migration"
        sentiment_migrations = list(versions_dir.glob("003_ai_sentiment.py"))
        assert len(sentiment_migrations) == 1, "Should have ai_sentiment migration"

        # Add auth service
        result = run_aegis_command(
            "add-service",
            "auth",
            "--project-path",
            str(project_path),
            "--yes",
        )
        assert result.returncode == 0, f"Add-service failed: {result.stderr}"

        # Verify auth migration was added with correct revision
        auth_migrations = list(versions_dir.glob("004_auth.py"))
        assert len(auth_migrations) == 1, "Should have auth migration as 004"

        # Verify revision chain
        auth_content = auth_migrations[0].read_text()
        assert "down_revision = '003'" in auth_content, (
            "Auth should chain after ai_sentiment"
        )


class TestAddServiceSeedsAgents:
    """``add-service ai[sqlite]`` must leave a seeded agent registry."""

    @pytest.mark.slow
    def test_add_ai_seeds_default_agent(self, project_factory: ProjectFactory) -> None:
        import shutil
        import sqlite3

        project_path = project_factory("base_with_database")
        # Cached venvs break when relocated; add-service re-syncs in place.
        shutil.rmtree(project_path / ".venv", ignore_errors=True)

        result = run_aegis_command(
            "add-service",
            "ai[sqlite]",
            "--project-path",
            str(project_path),
            "--yes",
        )
        assert result.returncode == 0, f"add-service failed: {result.stderr}"

        db_path = project_path / "data" / "app.db"
        assert db_path.exists(), "add-service should have created the database"
        with sqlite3.connect(db_path) as conn:
            agents = conn.execute("SELECT slug FROM agent").fetchall()
            vendors = conn.execute("SELECT COUNT(*) FROM llm_vendor").fetchone()
        assert ("assistant",) in agents, "default agent should be seeded"
        assert vendors[0] > 0, "LLM catalog should be seeded"


class TestAddServiceNoMigrationNeeded:
    """Test services that don't need migrations."""

    @pytest.mark.slow
    def test_add_comms_service_does_not_create_alembic(
        self, project_factory: ProjectFactory
    ) -> None:
        """Test that comms service (no migrations) doesn't create alembic."""
        # Get cached base project copy
        project_path = project_factory("base")

        # Add comms service (not in MIGRATION_SPECS)
        result = run_aegis_command(
            "add-service",
            "comms",
            "--project-path",
            str(project_path),
            "--yes",
        )
        assert result.returncode == 0

        # Verify no alembic was created
        alembic_dir = project_path / "alembic"
        assert not alembic_dir.exists(), "Comms service should not create alembic"


class TestAddServiceFrontendFiles:
    """Test that add-service adds frontend dashboard files for auto-added components."""

    @pytest.mark.slow
    def test_add_auth_adds_database_frontend_files(
        self, project_factory: ProjectFactory
    ) -> None:
        """Test that adding auth also adds database_card.py when database is auto-added."""
        # Get cached base project copy
        project_path = project_factory("base")

        cards_dir = project_path / "app/components/frontend/dashboard/cards"
        modals_dir = project_path / "app/components/frontend/dashboard/modals"

        # Verify base project doesn't have database files
        assert not (cards_dir / "database_card.py").exists(), (
            "Base project should not have database_card.py"
        )
        assert not (modals_dir / "database_modal.py").exists(), (
            "Base project should not have database_modal.py"
        )

        # Add auth service (which auto-adds database)
        result = run_aegis_command(
            "add-service",
            "auth",
            "--project-path",
            str(project_path),
            "--yes",
        )
        assert result.returncode == 0, f"Add-service failed: {result.stderr}"

        # Verify database frontend files were added
        assert (cards_dir / "database_card.py").exists(), (
            "database_card.py should exist after add-service auth"
        )
        assert (modals_dir / "database_modal.py").exists(), (
            "database_modal.py should exist after add-service auth"
        )

        # Verify auth frontend files were added
        assert (cards_dir / "auth_card.py").exists(), (
            "auth_card.py should exist after add-service auth"
        )
        assert (modals_dir / "auth_modal.py").exists(), (
            "auth_modal.py should exist after add-service auth"
        )


class TestAddServiceSharedFileReRendering:
    """Test that add-service re-renders shared template files."""

    @pytest.mark.slow
    def test_add_ai_service_updates_card_utils(
        self, project_factory: ProjectFactory
    ) -> None:
        """Test that adding AI service updates card_utils.py with AI modal mapping."""
        # Get cached base project copy
        project_path = project_factory("base")

        card_utils_path = (
            project_path / "app/components/frontend/dashboard/cards/card_utils.py"
        )

        # Verify base project doesn't have AI in modal_map
        assert card_utils_path.exists(), "card_utils.py should exist"
        base_content = card_utils_path.read_text()
        assert "AIDetailDialog" not in base_content, (
            "Base project should not have AIDetailDialog in card_utils.py"
        )

        # Add ai service with bracket syntax to skip interactive prompts
        # Format: ai[backend,framework,provider1,...]
        result = run_aegis_command(
            "add-service",
            "ai[memory,pydantic-ai,openai]",
            "--project-path",
            str(project_path),
            "--yes",
        )
        assert result.returncode == 0, f"Add-service failed: {result.stderr}"

        # Verify card_utils.py now has AI modal mapping
        updated_content = card_utils_path.read_text()
        assert "AIDetailDialog" in updated_content, (
            "card_utils.py should have AIDetailDialog after add-service ai"
        )
        assert '"ai": AIDetailDialog' in updated_content, (
            "modal_map should include 'ai': AIDetailDialog"
        )


class TestAddServiceAutoMigration:
    """Test that add-service automatically runs migrations."""

    @pytest.mark.slow
    @pytest.mark.skip(
        reason="Auto-migration feature needs investigation - database not created"
    )
    def test_add_auth_auto_runs_migrations(
        self, project_factory: ProjectFactory
    ) -> None:
        """Test that adding auth service automatically creates database tables."""
        # Get cached base project copy
        project_path = project_factory("base")

        # Add auth service (should auto-run migrations)
        result = run_aegis_command(
            "add-service",
            "auth",
            "--project-path",
            str(project_path),
            "--yes",
        )
        assert result.returncode == 0, f"Add-service failed: {result.stderr}"

        # Verify database file was created
        db_path = project_path / "data" / "app.db"
        assert db_path.exists(), "Database file should exist after auto-migration"

        # Verify user table exists (meaning migrations ran)
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='user'"
        )
        tables = cursor.fetchall()
        conn.close()

        assert len(tables) == 1, "User table should exist after auto-migration"


class TestAddServiceAIBackendMigrations:
    """Test that AI service migrations depend on backend selection."""

    @pytest.mark.slow
    def test_add_ai_memory_does_not_create_alembic(
        self, project_factory: ProjectFactory
    ) -> None:
        """Test that adding AI service with memory backend does NOT create alembic."""
        # Get cached base project copy
        project_path = project_factory("base")

        alembic_dir = project_path / "alembic"

        # Verify no alembic before
        assert not alembic_dir.exists(), "Base project should not have alembic"

        # Add AI service with memory backend (no migrations needed)
        result = run_aegis_command(
            "add-service",
            "ai[memory,pydantic-ai,openai]",
            "--project-path",
            str(project_path),
            "--yes",
        )
        assert result.returncode == 0, f"Add-service failed: {result.stderr}"

        # Verify alembic was NOT created
        assert not alembic_dir.exists(), (
            "AI with memory backend should NOT create alembic directory"
        )

    @pytest.mark.slow
    def test_add_ai_sqlite_creates_alembic(
        self, project_factory: ProjectFactory
    ) -> None:
        """Test that adding AI service with sqlite backend DOES create alembic."""
        # Get cached base project copy
        project_path = project_factory("base")

        alembic_dir = project_path / "alembic"
        versions_dir = alembic_dir / "versions"

        # Verify no alembic before
        assert not alembic_dir.exists(), "Base project should not have alembic"

        # Add AI service with sqlite backend (migrations needed)
        result = run_aegis_command(
            "add-service",
            "ai[sqlite,pydantic-ai,openai]",
            "--project-path",
            str(project_path),
            "--yes",
        )
        assert result.returncode == 0, f"Add-service failed: {result.stderr}"

        # Verify alembic WAS created
        assert alembic_dir.exists(), (
            "AI with sqlite backend should create alembic directory"
        )
        assert versions_dir.exists(), "versions directory should exist"

        # Verify AI migration was generated
        ai_migrations = list(versions_dir.glob("*_ai.py"))
        assert len(ai_migrations) == 1, "Should have exactly one AI migration"

    @pytest.mark.slow
    def test_add_ai_memory_does_not_trigger_migration_output(
        self, project_factory: ProjectFactory
    ) -> None:
        """Test that adding AI with memory backend doesn't show migration output."""
        project_path = project_factory("base")

        result = run_aegis_command(
            "add-service",
            "ai[memory,pydantic-ai,openai]",
            "--project-path",
            str(project_path),
            "--yes",
        )
        assert result.returncode == 0, f"Add-service failed: {result.stderr}"

        # Should NOT contain migration-related output
        assert "Bootstrapping alembic" not in result.stdout
        assert "Applying database migrations" not in result.stdout
        assert "Generated migration" not in result.stdout
