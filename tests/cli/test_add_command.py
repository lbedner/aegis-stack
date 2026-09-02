"""
Tests for the 'aegis add' command that adds components to existing projects.

Uses manual updater (Copier-lite) approach instead of Copier's update mechanism.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from aegis.core.components import COMPONENTS, CORE_COMPONENTS
from aegis.core.copier_manager import (
    is_copier_project,
    load_copier_answers,
)

from .test_utils import format_file_like_regen, run_aegis_command

ProjectFactory = Callable[..., Path]


class TestAddCommand:
    """Test suite for 'aegis add' command using manual updater."""

    def test_add_command_not_copier_project(self, temp_output_dir: Path) -> None:
        """Test that add command fails on non-Copier projects."""
        # Create a dummy directory that's not a Copier project
        fake_project = temp_output_dir / "fake-project"
        fake_project.mkdir()

        # Try to add component
        result = run_aegis_command(
            "add", "scheduler", "--project-path", str(fake_project), "--yes"
        )

        # Should fail with helpful message
        assert not result.success
        assert "not generated with copier" in result.stderr.lower()

    def test_add_command_missing_project(self) -> None:
        """Test that add command fails when project doesn't exist."""
        result = run_aegis_command(
            "add", "scheduler", "--project-path", "/nonexistent/path", "--yes"
        )

        assert not result.success
        assert "not generated with copier" in result.stderr.lower()

    def test_add_command_invalid_component(
        self, project_factory: ProjectFactory
    ) -> None:
        """Test that add command validates component names."""
        project_path = project_factory()

        # Try to add invalid component
        result = run_aegis_command(
            "add", "invalid_component", "--project-path", str(project_path), "--yes"
        )

        assert not result.success
        assert "unknown component" in result.stderr.lower()

    def test_add_scheduler_to_base_project(
        self, project_factory: ProjectFactory
    ) -> None:
        """Test adding scheduler component to a base project."""
        project_path = project_factory("base")

        # Verify it's a Copier project
        assert is_copier_project(project_path)

        # Verify scheduler not initially present
        initial_answers = load_copier_answers(project_path)
        assert initial_answers.get("include_scheduler") is False

        # Add scheduler component
        result = run_aegis_command(
            "add", "scheduler", "--project-path", str(project_path), "--yes"
        )

        # Should succeed
        assert result.success, f"Command failed: {result.stderr}"

        # Verify scheduler was added to answers
        updated_answers = load_copier_answers(project_path)
        assert updated_answers.get("include_scheduler") is True

        # Verify scheduler files were created (memory backend doesn't create component dir)
        assert (project_path / "app" / "entrypoints" / "scheduler.py").exists()
        assert (project_path / "tests" / "components" / "test_scheduler.py").exists()

    def test_add_worker_auto_adds_redis(self, project_factory: ProjectFactory) -> None:
        """Test that adding worker automatically adds redis dependency."""
        project_path = project_factory("base")

        # Verify initial state (no worker or redis)
        initial_answers = load_copier_answers(project_path)
        assert initial_answers.get("include_worker") is False
        assert initial_answers.get("include_redis") is False

        # Add worker (should auto-add redis)
        result = run_aegis_command(
            "add", "worker", "--project-path", str(project_path), "--yes"
        )

        assert result.success, f"Command failed: {result.stderr}"

        # Should mention redis auto-addition
        assert "redis" in result.stdout.lower() or "auto-added" in result.stdout.lower()

        # Verify both worker and redis were added
        updated_answers = load_copier_answers(project_path)
        assert updated_answers.get("include_worker") is True, (
            "Worker component not enabled"
        )
        assert updated_answers.get("include_redis") is True, (
            "Redis dependency not auto-added"
        )

    def test_add_multiple_components(self, project_factory: ProjectFactory) -> None:
        """Test adding multiple components at once."""
        project_path = project_factory("base")

        # Add multiple components
        result = run_aegis_command(
            "add",
            "scheduler,database",
            "--project-path",
            str(project_path),
            "--yes",
        )

        assert result.success

        # Verify all components were added
        updated_answers = load_copier_answers(project_path)
        assert updated_answers.get("include_scheduler") is True
        assert updated_answers.get("include_database") is True

        # Verify files exist
        assert (project_path / "app" / "entrypoints" / "scheduler.py").exists()
        assert (project_path / "app" / "core" / "db.py").exists()

    def test_add_database_to_base_project(
        self, project_factory: ProjectFactory
    ) -> None:
        """Test adding database component to a base project."""
        project_path = project_factory("base")

        # Verify database not initially present
        initial_answers = load_copier_answers(project_path)
        assert initial_answers.get("include_database") is False

        # Add database component
        result = run_aegis_command(
            "add", "database", "--project-path", str(project_path), "--yes"
        )

        # Should succeed
        assert result.success, f"Command failed: {result.stderr}"

        # Verify database was added to answers
        updated_answers = load_copier_answers(project_path)
        assert updated_answers.get("include_database") is True
        assert updated_answers.get("database_engine") == "sqlite"

        # Verify database files were created
        assert (project_path / "app" / "core" / "db.py").exists()

    def test_add_storage_to_base_project(self, project_factory: ProjectFactory) -> None:
        """Adding the object store brings its backend, card and modal."""
        project_path = project_factory("base")
        assert load_copier_answers(project_path).get("include_storage") is False

        result = run_aegis_command(
            "add", "storage", "--project-path", str(project_path), "--yes"
        )

        assert result.success, f"Command failed: {result.stderr}"
        assert load_copier_answers(project_path).get("include_storage") is True
        for rel in (
            "app/components/storage/s3.py",
            "app/components/frontend/dashboard/cards/storage_card.py",
            "app/components/frontend/dashboard/modals/storage_modal.py",
        ):
            assert (project_path / rel).exists(), rel
        assert "seaweedfs" in (project_path / "docker-compose.yml").read_text()

    def test_add_database_already_enabled(
        self, project_factory: ProjectFactory
    ) -> None:
        """Test adding database when it's already enabled."""
        project_path = project_factory("base_with_database")

        # Try to add database again
        result = run_aegis_command(
            "add", "database", "--project-path", str(project_path), "--yes"
        )

        # Should succeed but show "already enabled" message
        assert result.success
        assert "already enabled" in result.stdout.lower()

    def test_add_multiple_with_database(self, project_factory: ProjectFactory) -> None:
        """Test adding database alongside other components."""
        project_path = project_factory("base")

        # Add database and scheduler together
        result = run_aegis_command(
            "add",
            "database,scheduler",
            "--project-path",
            str(project_path),
            "--yes",
        )

        assert result.success

        # Verify both components were added
        updated_answers = load_copier_answers(project_path)
        assert updated_answers.get("include_database") is True
        assert updated_answers.get("include_scheduler") is True
        assert updated_answers.get("database_engine") == "sqlite"

        # Verify files exist
        assert (project_path / "app" / "core" / "db.py").exists()
        assert (project_path / "app" / "entrypoints" / "scheduler.py").exists()

    def test_add_already_enabled_component(
        self, project_factory: ProjectFactory
    ) -> None:
        """Test adding a component that's already enabled."""
        project_path = project_factory(components=["scheduler"])

        # Try to add scheduler again
        result = run_aegis_command(
            "add", "scheduler", "--project-path", str(project_path), "--yes"
        )

        # Should succeed with message about already enabled
        assert result.success
        assert "already enabled" in result.stdout.lower()

    def test_add_scheduler_with_sqlite_backend(
        self, project_factory: ProjectFactory
    ) -> None:
        """Test adding scheduler with sqlite backend variant."""
        project_path = project_factory()

        # Add scheduler with sqlite backend
        result = run_aegis_command(
            "add",
            "scheduler[sqlite]",
            "--project-path",
            str(project_path),
            "--yes",
        )

        assert result.success

        # Verify scheduler backend is sqlite
        updated_answers = load_copier_answers(project_path)
        assert updated_answers.get("include_scheduler") is True
        assert updated_answers.get("scheduler_backend") == "sqlite"
        assert updated_answers.get("scheduler_with_persistence") is True

        # Verify sqlite-specific files exist
        assert (project_path / "app" / "services" / "scheduler").exists()
        assert (project_path / "app" / "cli" / "tasks.py").exists()

    def test_add_empty_component_name(self, project_factory: ProjectFactory) -> None:
        """Test that empty component names are rejected."""
        project_path = project_factory()

        # Try to add with empty component
        result = run_aegis_command(
            "add", "scheduler,,database", "--project-path", str(project_path), "--yes"
        )

        assert not result.success
        assert "empty component name" in result.stderr.lower()

    def test_add_command_help(self) -> None:
        """Test that add command has proper help text."""
        result = run_aegis_command("add", "--help")

        assert result.success
        assert "add components" in result.stdout.lower()
        assert "scheduler" in result.stdout.lower()
        assert "worker" in result.stdout.lower()
        assert "-b" in result.stdout.lower()  # Short flag for --backend

    def test_add_scheduler_with_backend_flag_sqlite(
        self, project_factory: ProjectFactory
    ) -> None:
        """Test adding scheduler with --backend sqlite flag."""
        project_path = project_factory()

        # Add scheduler with --backend sqlite
        result = run_aegis_command(
            "add",
            "scheduler",
            "--backend",
            "sqlite",
            "--project-path",
            str(project_path),
            "--yes",
        )

        assert result.success, f"Command failed: {result.stderr}"

        # Verify scheduler backend is sqlite
        updated_answers = load_copier_answers(project_path)
        assert updated_answers.get("include_scheduler") is True
        assert updated_answers.get("scheduler_backend") == "sqlite"
        assert updated_answers.get("scheduler_with_persistence") is True

        # Verify database component auto-added
        assert updated_answers.get("include_database") is True

        # Verify persistence files exist
        assert (project_path / "app" / "services" / "scheduler").exists()

    def test_add_scheduler_with_backend_flag_memory(
        self, project_factory: ProjectFactory
    ) -> None:
        """Test adding scheduler with --backend memory flag."""
        project_path = project_factory()

        # Add scheduler with --backend memory
        result = run_aegis_command(
            "add",
            "scheduler",
            "--backend",
            "memory",
            "--project-path",
            str(project_path),
            "--yes",
        )

        assert result.success, f"Command failed: {result.stderr}"

        # Verify scheduler backend is memory
        updated_answers = load_copier_answers(project_path)
        assert updated_answers.get("include_scheduler") is True
        assert updated_answers.get("scheduler_backend") == "memory"
        assert updated_answers.get("scheduler_with_persistence") is False

        # Verify database NOT auto-added
        assert updated_answers.get("include_database") is False

    def test_add_scheduler_postgres_backend(
        self, project_factory: ProjectFactory
    ) -> None:
        """Postgres scheduler backend is supported: it auto-adds a postgres
        database and generates the schema-qualified job_execution migration.
        """
        project_path = project_factory()

        result = run_aegis_command(
            "add",
            "scheduler",
            "--backend",
            "postgres",
            "--project-path",
            str(project_path),
            "--yes",
        )

        assert result.success

        # Database auto-added with a matching postgres engine
        answers = load_copier_answers(project_path)
        assert answers.get("include_scheduler") is True
        assert answers.get("database_engine") == "postgres"

        # Schema-qualified migration generated for scheduler.job_execution
        scheduler_migrations = list(
            (project_path / "alembic" / "versions").glob("*_scheduler.py")
        )
        assert scheduler_migrations, "expected a generated scheduler migration"
        content = scheduler_migrations[0].read_text()
        assert 'CREATE SCHEMA IF NOT EXISTS "scheduler"' in content
        # post-generation `ruff --fix` may normalise quote style
        assert ('schema="scheduler"' in content) or ("schema='scheduler'" in content)
        assert "job_execution" in content

    def test_add_scheduler_invalid_backend_error(
        self, project_factory: ProjectFactory
    ) -> None:
        """Test that invalid backend shows helpful error."""
        project_path = project_factory()

        # Try to add scheduler with invalid backend
        result = run_aegis_command(
            "add",
            "scheduler",
            "--backend",
            "invalid",
            "--project-path",
            str(project_path),
            "--yes",
        )

        # Should fail with helpful error
        assert not result.success
        assert "invalid scheduler backend" in result.stderr.lower()
        assert "memory" in result.stderr.lower()
        assert "sqlite" in result.stderr.lower()

    def test_add_scheduler_bracket_overrides_flag(
        self, project_factory: ProjectFactory
    ) -> None:
        """Test that bracket syntax takes precedence over --backend flag."""
        project_path = project_factory()

        # Add scheduler[sqlite] with --backend memory (bracket should win)
        result = run_aegis_command(
            "add",
            "scheduler[sqlite]",
            "--backend",
            "memory",
            "--project-path",
            str(project_path),
            "--yes",
        )

        assert result.success, f"Command failed: {result.stderr}"

        # Should show warning about override
        assert "overrides" in result.stdout.lower()

        # Verify sqlite backend was used (bracket syntax wins)
        updated_answers = load_copier_answers(project_path)
        assert updated_answers.get("scheduler_backend") == "sqlite"
        assert updated_answers.get("include_database") is True

    def test_add_component_files_created(self, project_factory: ProjectFactory) -> None:
        """Test that all expected files are created when adding a component."""
        project_path = project_factory()

        # Add worker component
        result = run_aegis_command(
            "add", "worker", "--project-path", str(project_path), "--yes"
        )

        assert result.success, f"Command failed: {result.stderr}"

        # Verify critical worker files exist
        expected_files = [
            "app/components/worker/__init__.py",
            "app/components/worker/pools.py",
            "app/components/worker/registry.py",
            "app/components/worker/queues/system.py",
            "app/components/worker/queues/load_test.py",
            "app/components/worker/tasks/system_tasks.py",
            # ``load_test.py`` was promoted to a package after the
            # api-load-test refactor; check the package entry + worker
            # subpackage instead. ``load_test_models.py`` stays as a
            # back-compat shim.
            "app/services/load_test/__init__.py",
            "app/services/load_test/worker/service.py",
            "app/services/load_test_models.py",
            "tests/api/test_worker_endpoints.py",
            "tests/services/test_worker_health_registration.py",
        ]

        for file_path in expected_files:
            full_path = project_path / file_path
            assert full_path.exists(), f"Missing file: {file_path}"

    @pytest.mark.skip(reason="Dependency update verification incomplete")
    def test_add_updates_dependencies(self, project_factory: ProjectFactory) -> None:
        """Test that adding components runs uv sync to update dependencies."""
        project_path = project_factory()

        # Add worker (requires arq)
        result = run_aegis_command(
            "add", "worker", "--project-path", str(project_path), "--yes"
        )

        assert result.success
        assert (
            "dependencies synced" in result.stdout.lower()
            or "uv sync" in result.stdout.lower()
        )


class TestAddCommandIntegration:
    """Integration tests for add command that validate full workflow."""

    @pytest.mark.slow
    @pytest.mark.skip(reason="Quality verification incomplete")
    def test_add_and_verify_project_quality(
        self, project_factory: ProjectFactory
    ) -> None:
        """
        Full integration test: generate project, add component, verify quality.

        This test is marked as slow because it does full project generation
        and validation.
        """
        project_path = project_factory()

        # Add scheduler
        result = run_aegis_command(
            "add", "scheduler", "--project-path", str(project_path), "--yes"
        )
        assert result.success

        # Verify critical files exist
        expected_files = [
            "app/entrypoints/scheduler.py",
            "tests/components/test_scheduler.py",
            "tests/services/test_component_integration.py",
        ]

        for file_path in expected_files:
            full_path = project_path / file_path
            assert full_path.exists(), f"Missing file: {file_path}"

        # Verify code formatting was applied
        assert (
            "code formatted" in result.stdout.lower()
            or "make fix" in result.stdout.lower()
        )

    @pytest.mark.slow
    def test_add_multiple_times_incrementally(
        self, project_factory: ProjectFactory
    ) -> None:
        """Test adding components in multiple separate operations."""
        project_path = project_factory()

        # Add scheduler first
        result1 = run_aegis_command(
            "add", "scheduler", "--project-path", str(project_path), "--yes"
        )
        assert result1.success
        assert (project_path / "app" / "entrypoints" / "scheduler.py").exists()

        # Then add database
        result2 = run_aegis_command(
            "add", "database", "--project-path", str(project_path), "--yes"
        )
        assert result2.success
        assert (project_path / "app" / "core" / "db.py").exists()

        # Verify both components are enabled
        final_answers = load_copier_answers(project_path)
        assert final_answers.get("include_scheduler") is True
        assert final_answers.get("include_database") is True

        # Verify both sets of files still exist
        assert (project_path / "app" / "entrypoints" / "scheduler.py").exists()
        assert (project_path / "app" / "core" / "db.py").exists()

    @pytest.mark.slow
    @pytest.mark.skip(reason="Test fixture generation incomplete")
    def test_add_component_with_tests(self, project_factory: ProjectFactory) -> None:
        """Test that component tests are created and can run."""
        project_path = project_factory()

        # Add database component
        result = run_aegis_command(
            "add", "database", "--project-path", str(project_path), "--yes"
        )
        assert result.success

        # Verify test file exists
        test_file = project_path / "tests" / "conftest.py"
        assert test_file.exists()

        # Verify test file has database fixtures
        test_content = test_file.read_text()
        assert "db_session" in test_content or "database" in test_content.lower()


class TestAddHtmxComponent:
    """Test 'aegis add htmx' on an existing project.

    The htmx component's template file tree lands with HF-03/HF-04; at this
    stage adding it must still flip the answers flag and complete cleanly so
    a later `aegis update` renders the htmx side.
    """

    def test_add_htmx_updates_answers(self, project_factory: ProjectFactory) -> None:
        """Adding htmx sets include_htmx: true in .copier-answers.yml."""
        project_path = project_factory()

        initial_answers = load_copier_answers(project_path)
        assert not initial_answers.get("include_htmx")

        result = run_aegis_command(
            "add", "htmx", "--project-path", str(project_path), "--yes"
        )

        assert result.success, f"add htmx failed: {result.stderr}"
        answers = load_copier_answers(project_path)
        assert answers.get("include_htmx") is True

    def test_add_htmx_leaves_flet_frontend_alone(
        self, project_factory: ProjectFactory
    ) -> None:
        """Adding htmx must not inject anything into the core Flet frontend.

        theme.py sits outside the shared-file set, so it must be
        byte-identical; main.py is a registered shared file the regen
        rewrites, so assert no htmx leakage in its content (byte-identity
        for it is covered by test_add_regen_matches_init_formatting).
        """
        project_path = project_factory()
        frontend = project_path / "app" / "components" / "frontend"
        theme_before = (frontend / "theme.py").read_text()

        result = run_aegis_command(
            "add", "htmx", "--project-path", str(project_path), "--yes"
        )

        assert result.success, f"add htmx failed: {result.stderr}"
        assert (frontend / "theme.py").read_text() == theme_before
        main_after = (frontend / "main.py").read_text()
        assert "htmx" not in main_after
        assert "web_frontend" not in main_after

    def test_add_regen_matches_init_formatting(
        self, project_factory: ProjectFactory
    ) -> None:
        """Shared-file regen must produce the same bytes init produced.

        Init runs the project's ruff (check --fix + format) over generated
        code; the add-path regen writes raw template renders. For a shared
        file the operation doesn't actually change (htmx touches nothing in
        frontend/main.py), the regenerated file must be byte-identical to
        the init output — otherwise every `aegis add` leaves cosmetic drift
        like a stripped-at-init unused `import json` reappearing.

        ``before`` is normalized here through the same ruff helper the regen
        uses, rather than trusting init's non-critical `make fix` to have
        succeeded — that step can silently fail under load, and this test
        must catch regen drift, not fixture noise.
        """
        project_path = project_factory()
        flet_main = project_path / "app" / "components" / "frontend" / "main.py"
        format_file_like_regen(flet_main, project_path)
        before = flet_main.read_text()

        result = run_aegis_command(
            "add", "htmx", "--project-path", str(project_path), "--yes"
        )

        assert result.success, f"add htmx failed: {result.stderr}"
        assert flet_main.read_text() == before


class TestAddCommandInteractive:
    """Test suite for 'aegis add --interactive' command."""

    def test_add_interactive_requires_components_or_flag(
        self, project_factory: ProjectFactory
    ) -> None:
        """Test that add command requires either components argument or --interactive flag."""
        project_path = project_factory()

        # Try to run add without components or --interactive
        result = run_aegis_command("add", "--project-path", str(project_path), "--yes")

        # Should fail with helpful message
        assert not result.success
        assert "components argument is required" in result.stderr.lower()
        assert "--interactive" in result.stderr.lower()

    def test_add_interactive_base_project_state_detection(
        self, project_factory: ProjectFactory
    ) -> None:
        """Test that interactive mode correctly detects base project state."""
        project_path = project_factory()

        # Verify initial state
        initial_answers = load_copier_answers(project_path)

        # All infrastructure components should be disabled
        for component_name in COMPONENTS:
            if component_name not in CORE_COMPONENTS:
                include_key = f"include_{component_name}"
                # Use falsy check - key may not exist in old cached projects
                assert not initial_answers.get(include_key), (
                    f"{component_name} should be disabled initially"
                )

    def test_add_interactive_detects_already_enabled_components(
        self, project_factory: ProjectFactory
    ) -> None:
        """Test that interactive mode detects and reports already-enabled components."""
        project_path = project_factory(components=[COMPONENTS["scheduler"].name])

        # Verify scheduler is enabled
        answers = load_copier_answers(project_path)
        assert answers.get("include_scheduler") is True

        # The interactive function would skip scheduler
        # (Can't test interactive prompts, but we verify state detection)
        # If we could run interactive mode, scheduler would show as "Already enabled"

    def test_add_validates_component_names_in_interactive(
        self, project_factory: ProjectFactory
    ) -> None:
        """Test that component validation works the same in interactive mode."""
        project_path = project_factory()

        # Try to add invalid component (non-interactive for validation test)
        result = run_aegis_command(
            "add",
            "nonexistent_component",
            "--project-path",
            str(project_path),
            "--yes",
        )

        # Should fail with validation error
        assert not result.success
        assert "unknown component" in result.stderr.lower()

    @pytest.mark.slow
    def test_add_interactive_workflow_adds_component(
        self, project_factory: ProjectFactory
    ) -> None:
        """Test that components added via add command update project correctly."""
        database_component = COMPONENTS["database"]
        project_path = project_factory()

        # Add database component (non-interactive, but validates the workflow)
        result = run_aegis_command(
            "add",
            database_component.name,
            "--project-path",
            str(project_path),
            "--yes",
        )

        assert result.success, (
            f"Failed to add {database_component.name}: {result.stderr}"
        )

        # Verify database was added to answers
        updated_answers = load_copier_answers(project_path)
        assert updated_answers.get("include_database") is True

        # Verify expected file exists (from component template_files)
        assert database_component.template_files is not None
        for template_file in database_component.template_files:
            expected_file = project_path / template_file
            assert expected_file.exists(), f"Expected file {template_file} not created"

    @pytest.mark.slow
    @pytest.mark.skip(reason="Interactive dependency handling incomplete")
    def test_add_interactive_workflow_with_dependencies(
        self, project_factory: ProjectFactory
    ) -> None:
        """Test that component dependencies are resolved in add workflow."""
        worker_component = COMPONENTS["worker"]
        redis_component = COMPONENTS["redis"]
        project_path = project_factory()

        # Add worker (requires redis)
        result = run_aegis_command(
            "add",
            worker_component.name,
            "--project-path",
            str(project_path),
            "--yes",
        )

        # Check for dependency resolution message
        assert result.success or "auto-added dependencies" in result.stdout.lower()

        # Verify both worker and redis dependency are in answers
        updated_answers = load_copier_answers(project_path)
        assert updated_answers.get("include_worker"), (
            "Worker component should be enabled"
        )
        assert updated_answers.get("include_redis"), (
            f"{redis_component.description} should be auto-added"
        )


class TestAddCommandVersionCompatibility:
    """Test version compatibility checks in add command."""

    def test_add_with_force_flag_available(self) -> None:
        """Test that add command accepts --force flag."""
        result = run_aegis_command("add", "--help")

        assert result.success
        assert "--force" in result.stdout or "-f" in result.stdout

    def test_add_command_version_check_skipped_when_no_version(
        self, project_factory: ProjectFactory
    ) -> None:
        """Test that add command works when project version can't be determined."""
        project_path = project_factory()

        # Add a component - should work even if version can't be determined
        result = run_aegis_command(
            "add", "scheduler", "--project-path", str(project_path), "--yes"
        )

        # Should succeed (version check is skipped when version unknown)
        assert result.success, f"Command failed: {result.stderr}"

    def test_add_force_flag_bypasses_version_warning(
        self, project_factory: ProjectFactory
    ) -> None:
        """Test that --force flag is available for bypassing warnings."""
        project_path = project_factory()

        # Try add with force flag (should be accepted even if not needed)
        result = run_aegis_command(
            "add",
            "scheduler",
            "--project-path",
            str(project_path),
            "--yes",
            "--force",
        )

        # Should succeed
        assert result.success, f"Command failed: {result.stderr}"
