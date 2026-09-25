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
from tests.cli.test_utils import run_aegis_command, run_project_command


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
            orgs = conn.execute("SELECT COUNT(*) FROM llm_org").fetchone()
        assert ("assistant",) in agents, "default agent should be seeded"
        assert orgs[0] > 0, "LLM catalog should be seeded"


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
        assert not (modals_dir / "database_modal").exists(), (
            "Base project should not have the database_modal package"
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
        assert (modals_dir / "database_modal" / "__init__.py").exists(), (
            "the database_modal package should exist after add-service auth"
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
    def test_add_ai_service_updates_the_modal_registry(
        self, project_factory: ProjectFactory
    ) -> None:
        """The dashboard has to know how to open the modal a new service
        brought with it. The map lives in ``modal_registry.py``, a shared
        file gated on ``include_ai`` - if the add path does not re-render
        it, the card is there and clicking it does nothing."""
        # Get cached base project copy
        project_path = project_factory("base")

        registry_path = (
            project_path / "app/components/frontend/dashboard/modal_registry.py"
        )

        # Verify base project doesn't have AI in modal_map
        assert registry_path.exists(), "modal_registry.py should exist"
        base_content = registry_path.read_text()
        assert "AIDetailDialog" not in base_content, (
            "Base project should not have AIDetailDialog in modal_registry.py"
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

        # Verify modal_registry.py now has AI modal mapping
        updated_content = registry_path.read_text()
        assert "AIDetailDialog" in updated_content, (
            "modal_registry.py should have AIDetailDialog after add-service ai"
        )
        assert '"service_ai": AIDetailDialog' in updated_content, (
            "modal_map should include 'service_ai': AIDetailDialog"
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


class TestAddAuthOntoFinance:
    def test_sentinel_owner_lands_after_user_exists(
        self, project_factory: ProjectFactory
    ) -> None:
        """#1110 on the add path: a standalone finance project gains auth.
        The owner FKs now arrive in a later revision than the finance
        tables, and the row they point at (user 0) must land in that pass,
        after ``user`` exists, so the run's order is auth, auth_tokens,
        finance_auth_link."""
        import sqlite3

        project_path = project_factory(
            components=["database", "scheduler"], services=["finance"]
        )
        versions_dir = project_path / "alembic" / "versions"
        before = sorted(p.name for p in versions_dir.glob("*.py"))
        assert not any("auth" in n for n in before)
        # The cache copy carries a venv whose interpreter links are only
        # valid at the cache's own path (as test_migrations_match_models
        # notes); the post-add ``alembic upgrade`` needs a working one.
        import shutil

        shutil.rmtree(project_path / ".venv", ignore_errors=True)
        # UV_PYTHON pins the interpreter for the aegis tool in CI (3.11);
        # the project resolves its own requires-python.
        sync = run_project_command(
            ["uv", "sync"],
            project_path,
            timeout=600,
            env_overrides={"VIRTUAL_ENV": "", "UV_PYTHON": ""},
        )
        assert sync.success, sync.stderr[-800:]

        result = run_aegis_command(
            "add-service", "auth", "--project-path", str(project_path), "--yes"
        )
        assert result.returncode == 0, f"Add-service failed: {result.stderr}"

        added = sorted({p.name for p in versions_dir.glob("*.py")} - set(before))
        suffixes = [n.split("_", 1)[1] for n in added]
        assert suffixes.index("auth.py") < suffixes.index("finance_auth_link.py")
        link = (
            versions_dir / added[suffixes.index("finance_auth_link.py")]
        ).read_text()
        assert "standalone@finance.local" in link

        db_path = project_path / "data" / "app.db"
        assert db_path.exists(), result.stdout[-1500:]
        db = sqlite3.connect(db_path)
        tables = {r[0] for r in db.execute("select name from sqlite_master")}
        assert "user" in tables, (sorted(tables), result.stdout[-1500:])
        assert db.execute("select id from user where id = 0").fetchall() == [(0,)]

    def test_sentinel_owned_rows_survive_the_fk(
        self, project_factory: ProjectFactory
    ) -> None:
        """The same add, onto a project that has actually been USED.

        The sibling above proves user 0 lands. It cannot prove the order
        is right, because it adds auth to an empty database: with no rows
        owned by the sentinel, an FK created before its target still
        holds. A standalone finance install stores insights under owner
        ``0`` (they are NOT-NULL owner - see ``generate_insights``), so a
        real one has rows the FK must not refuse. Found on an install
        with 154 of them, 2026-09-19.
        """
        import shutil
        import sqlite3

        project_path = project_factory(
            components=["database", "scheduler"], services=["finance"]
        )
        versions_dir = project_path / "alembic" / "versions"
        before = sorted(p.name for p in versions_dir.glob("*.py"))

        shutil.rmtree(project_path / ".venv", ignore_errors=True)
        no_venv = {"VIRTUAL_ENV": "", "UV_PYTHON": ""}
        sync = run_project_command(
            ["uv", "sync"], project_path, timeout=600, env_overrides=no_venv
        )
        assert sync.success, sync.stderr[-800:]

        # Bring the finance tables up before seeding: the point is a
        # database that was in use before auth arrived.
        migrate = run_project_command(
            # -c: the generated project keeps its config at
            # alembic/alembic.ini, as its own Makefile target does.
            ["uv", "run", "alembic", "-c", "alembic/alembic.ini", "upgrade", "head"],
            project_path,
            timeout=300,
            env_overrides=no_venv,
        )
        assert migrate.success, (migrate.stdout[-800:], migrate.stderr[-800:])

        db_path = project_path / "data" / "app.db"
        assert db_path.exists(), migrate.stdout[-800:]
        seeded = sqlite3.connect(db_path)
        seeded.execute(
            "INSERT INTO finance_insight (owner_user_id, insight_type, severity,"
            " title, dedup_key, data, status, is_read, metadata, created_at,"
            " updated_at) VALUES (0, 'fee', 'info', 'A fee worth avoiding',"
            " 'seeded-1', '{}', 'new', 0, '{}', CURRENT_TIMESTAMP,"
            " CURRENT_TIMESTAMP)"
        )
        seeded.commit()
        seeded.close()

        result = run_aegis_command(
            "add-service", "auth", "--project-path", str(project_path), "--yes"
        )
        assert result.returncode == 0, (
            "add-service failed on a finance project with sentinel-owned "
            f"rows:\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
        )

        added = sorted({p.name for p in versions_dir.glob("*.py")} - set(before))
        link_name = next(n for n in added if "finance_auth_link" in n)
        link = (versions_dir / link_name).read_text()

        # The invariant this test exists for, and the one SQLite cannot
        # show on its own: the row a foreign key points at has to be
        # written BEFORE the key. SQLite adds an FK by rebuilding the
        # table and does not re-validate the rows it copies, so a wrong
        # order passes here and fails on Postgres, which validates on
        # ADD CONSTRAINT. Assert the order in the file, not the outcome
        # in this engine.
        sentinel_at = link.find("standalone@finance.local")
        assert sentinel_at != -1, link

        # The link revision both writes the sentinel and adds the keys that
        # need it (#1217), so the row has to come first. SQLite would not
        # show a wrong order: it adds a key by rebuilding the table and
        # does not re-validate the rows it copies, while Postgres validates
        # on ADD CONSTRAINT.
        fk_at = min(
            (
                link.find(marker)
                for marker in ("create_foreign_key", "ForeignKeyConstraint")
                if link.find(marker) != -1
            ),
            default=-1,
        )
        assert fk_at != -1, "the link revision carries no owner keys:\n" + link
        if fk_at != -1:
            assert sentinel_at < fk_at, (
                "the sentinel row is written after the FK that needs it; "
                "SQLite tolerates this and Postgres will not:\n" + link
            )

        db = sqlite3.connect(db_path)
        # The row is still there, and now points at a user that exists.
        assert db.execute(
            "select owner_user_id from finance_insight where dedup_key = 'seeded-1'"
        ).fetchall() == [(0,)]
        assert db.execute("select id from user where id = 0").fetchall() == [(0,)]
        # And SQLite agrees the constraint is satisfied, which is the
        # whole question: the FK was added to a table that already had
        # rows in it.
        db.execute("PRAGMA foreign_keys=ON")
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []

        # #1217: the keys themselves. Generated as finance + auth, every
        # owner column references ``user``; finance first and auth later
        # left all of them without one, so the check above passed on a
        # database with nothing to check.
        finance_tables = [
            name
            for (name,) in db.execute(
                "select name from sqlite_master"
                " where type = 'table' and name like 'finance%'"
            )
        ]
        owned = [
            name
            for name in finance_tables
            if any(
                col[1] == "owner_user_id"
                for col in db.execute(f"PRAGMA table_info('{name}')")
            )
        ]
        unlinked = [
            name
            for name in owned
            if not any(
                fk[2] == "user" and fk[3] == "owner_user_id"
                for fk in db.execute(f"PRAGMA foreign_key_list('{name}')")
            )
        ]
        assert owned, "no finance table has an owner column"
        assert not unlinked, f"owner columns with no key to user: {unlinked}"
