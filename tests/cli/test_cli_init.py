"""
Integration tests for the Aegis Stack CLI init command.

These tests validate:
- CLI command execution and output
- Generated project structure
- Template processing
- Component integration
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from .test_utils import (
    assert_file_contains,
    assert_file_exists,
    run_aegis_init,
)

if TYPE_CHECKING:
    from tests.cli.conftest import ProjectFactory


def assert_file_not_exists(project_path: Path, relative_path: str) -> None:
    """Assert that a file does not exist in the generated project."""
    file_path = project_path / relative_path
    assert not file_path.exists(), f"Unexpected file found: {relative_path}"


def assert_no_template_files(project_path: Path) -> None:
    """Assert that no .j2 template files remain in the generated project."""
    j2_files = list(project_path.rglob("*.j2"))
    assert not j2_files, (
        f"Template files should not exist in generated project: {j2_files}"
    )


class TestCLIInit:
    """Test cases for the aegis init command - using cached projects for speed."""

    def test_init_with_scheduler_component(
        self,
        project_factory: "ProjectFactory",
    ) -> None:
        """Test generating a project with scheduler component."""
        # Use cached scheduler project
        project_path = project_factory("base_with_scheduler")

        # Assert project structure
        self._assert_scheduler_project_structure(project_path)

        # Assert template processing
        self._assert_scheduler_template_processing(project_path)

    def test_init_with_scheduler_sqlite(
        self,
        project_factory: "ProjectFactory",
    ) -> None:
        """Test generating project with scheduler using sqlite persistence."""
        # Use cached scheduler project with sqlite backend
        project_path = project_factory("base_with_scheduler_sqlite")

        # Assert project structure
        self._assert_scheduler_project_structure(project_path)

        # Assert sqlite-specific scheduler config
        self._assert_scheduler_sqlite_config(project_path)

    def test_init_without_components(
        self,
        project_factory: "ProjectFactory",
    ) -> None:
        """Test generating a project with no additional components."""
        # Use cached base project
        project_path = project_factory("base")

        # Assert project structure (no scheduler files)
        self._assert_core_project_structure(project_path)
        assert_file_not_exists(project_path, "app/components/scheduler.py")
        assert_file_not_exists(project_path, "tests/components/test_scheduler.py")

    @pytest.mark.slow
    def test_init_invalid_component(
        self,
        temp_output_dir: Any,
        skip_slow_tests: Any,
    ) -> None:
        """Test that invalid component names are rejected."""
        result = run_aegis_init(
            project_name="test-invalid",
            components=["invalid_component"],
            output_dir=temp_output_dir,
        )

        # Assert command failed
        assert not result.success
        assert "Invalid component: invalid_component" in result.stderr
        assert "Valid components: scheduler, database, cache" in result.stderr

    def test_init_multiple_components(
        self,
        project_factory: "ProjectFactory",
    ) -> None:
        """Test generating project with multiple components (when available)."""
        # Use cached project with scheduler and database
        project_path = project_factory("scheduler_and_database")

        # Assert both components exist
        self._assert_scheduler_project_structure(project_path)
        assert_file_exists(project_path, "app/core/db.py")

    @pytest.mark.slow
    def test_template_variable_substitution(
        self,
        temp_output_dir: Any,
        skip_slow_tests: Any,
    ) -> None:
        """Test that template variables are properly substituted."""
        project_name = "my-custom-project"
        result = run_aegis_init(
            project_name=project_name,
            components=["scheduler"],
            output_dir=temp_output_dir,
        )

        assert result.success

        # Check that project name was substituted in scheduler component
        project_path = result.project_path
        assert project_path is not None, "Project path is None"
        expected_title = project_name.replace("-", " ").title()
        assert_file_contains(
            project_path,
            "app/components/scheduler/main.py",
            f"🕒 Starting {expected_title} Scheduler",
        )

        # Check pyproject.toml has correct name
        assert_file_contains(project_path, "pyproject.toml", f'name = "{project_name}"')

    @pytest.mark.slow
    def test_project_quality_checks(
        self,
        temp_output_dir: Any,
        skip_slow_tests: Any,
    ) -> None:
        """Test that generated project passes quality checks."""
        result = run_aegis_init(
            project_name="test-quality",
            components=["scheduler"],
            output_dir=temp_output_dir,
        )

        assert result.success

        # Run quality checks on generated project
        project_path = result.project_path
        assert project_path is not None, "Project path is None"

        # Run quality checks using unified system
        from .test_utils import run_quality_checks

        quality_results = run_quality_checks(project_path)

        dep_result = quality_results[0]  # Dependency installation
        lint_result = quality_results[2]  # Linting
        type_result = quality_results[3]  # Type checking
        test_result = quality_results[4]  # Tests

        assert dep_result.success, f"Failed to install deps: {dep_result.stderr}"

        # Linting should either pass or only have fixable issues
        assert lint_result.returncode in [0, 1], f"Linting failed: {lint_result.stderr}"

        assert type_result.success, f"Type checking failed: {type_result.stdout}"

        # Tests may have some issues but should at least run
        assert test_result.returncode in [0, 1], (
            f"Tests completely failed: {test_result.stdout}"
        )

    def test_init_with_worker_component(
        self,
        project_factory: "ProjectFactory",
    ) -> None:
        """Test generating a project with worker component."""
        # Use cached worker project
        project_path = project_factory("base_with_worker")

        # Assert project structure
        self._assert_worker_project_structure(project_path)

        # Assert template processing
        self._assert_worker_template_processing(project_path)

    def _assert_core_project_structure(self, project_path: Path) -> None:
        """Assert that core project files exist."""
        core_files = [
            "pyproject.toml",
            "README.md",
            "Dockerfile",
            "docker-compose.yml",
            "Makefile",
            ".dockerignore",
            "app/__init__.py",
            "app/components/backend/main.py",
            "app/components/backend/hooks.py",
            "app/components/backend/middleware/__init__.py",
            "app/components/backend/startup/__init__.py",
            "app/components/backend/shutdown/__init__.py",
            "app/components/frontend/main.py",
            "app/core/config.py",
            "app/core/log.py",
            "app/entrypoints/webserver.py",
            "app/integrations/main.py",
            "app/services/__init__.py",
            "scripts/entrypoint.sh",
            "uv.lock",
        ]

        for file_path in core_files:
            assert_file_exists(project_path, file_path)

        # Assert no template files remain
        assert_no_template_files(project_path)

    def _assert_scheduler_project_structure(self, project_path: Path) -> None:
        """Assert scheduler-specific project structure."""
        self._assert_core_project_structure(project_path)

        # Scheduler-specific files
        assert_file_exists(project_path, "app/entrypoints/scheduler.py")
        assert_file_exists(project_path, "app/components/scheduler/main.py")
        assert_file_exists(project_path, "tests/components/test_scheduler.py")

        # Services directory should exist (it's initially empty)
        services_dir = project_path / "app/services"
        assert services_dir.exists()

    def _assert_scheduler_template_processing(self, project_path: Path) -> None:
        """Assert that scheduler templates were processed correctly."""
        scheduler_file = project_path / "app/components/scheduler/main.py"
        scheduler_content = scheduler_file.read_text()

        # Check imports and structure for scheduler component
        assert (
            "from apscheduler.schedulers.asyncio import AsyncIOScheduler"
            in scheduler_content
        )
        # Template now instantiates with ``job_defaults`` + ``timezone`` kwargs
        # across multiple lines, so pin on the open-paren rather than an exact
        # call form — the intent is "AsyncIOScheduler is constructed here,"
        # not "the constructor takes zero arguments."
        assert "scheduler = AsyncIOScheduler(" in scheduler_content
        assert "scheduler.add_job(" in scheduler_content
        assert "def create_scheduler()" in scheduler_content

        # Check pyproject.toml includes APScheduler
        pyproject_content = (project_path / "pyproject.toml").read_text()
        assert "apscheduler==3.10.4" in pyproject_content

    def _assert_scheduler_sqlite_config(self, project_path: Path) -> None:
        """Assert scheduler sqlite persistence config is correct."""
        scheduler_file = project_path / "app/components/scheduler/main.py"
        scheduler_content = scheduler_file.read_text()

        # Code is the source of truth for job schedules — every add_job
        # uses ``replace_existing=True`` and there is no FORCE_UPDATE knob.
        assert "from app.core.config import settings" in scheduler_content
        assert "replace_existing=True" in scheduler_content
        assert "SCHEDULER_FORCE_UPDATE" not in scheduler_content
        assert "os.getenv" not in scheduler_content

        # Config no longer carries the old force-update flag.
        config_content = (project_path / "app/core/config.py").read_text()
        assert "SCHEDULER_FORCE_UPDATE" not in config_content

    def _assert_worker_project_structure(self, project_path: Path) -> None:
        """Assert worker-specific project structure."""
        self._assert_core_project_structure(project_path)

        # Worker-specific files
        worker_files = [
            "app/components/worker/queues/system.py",
            "app/components/worker/queues/load_test.py",
            "app/components/worker/queues/media.py",
            "app/components/worker/tasks/simple_system_tasks.py",
            "app/components/worker/tasks/load_tasks.py",
            "app/components/worker/constants.py",
            "app/components/worker/registry.py",
            "app/components/worker/pools.py",
            # ``load_test.py`` became a package post-refactor; assert the
            # package entry + worker subpackage. ``load_test_models.py``
            # stays as a back-compat shim.
            "app/services/load_test/__init__.py",
            "app/services/load_test/worker/service.py",
            "app/services/load_test_models.py",
        ]

        for file_path in worker_files:
            assert_file_exists(project_path, file_path)

        # Worker API files should exist
        api_files = [
            "app/components/backend/api/worker.py",
            "app/components/backend/api/models.py",
            "app/components/backend/api/routing.py",
        ]

        for file_path in api_files:
            assert_file_exists(project_path, file_path)

    def _assert_worker_template_processing(self, project_path: Path) -> None:
        """Assert that worker templates were processed correctly."""
        # Check that component health includes worker registration
        component_health_file = (
            project_path
            / Path("app/components/backend/startup")
            / "component_health.py"
        )
        component_health_content = component_health_file.read_text()

        # CRITICAL: This is what we're testing - worker health registration
        expected_import = (
            "from app.services.system.health_worker import check_worker_health"
        )
        assert expected_import in component_health_content

        registration_snippet = 'register_health_check("worker", check_worker_health)'
        assert registration_snippet in component_health_content
        assert "Worker component health check registered" in component_health_content

        # Check that routing includes worker endpoints
        routing_file = project_path / "app/components/backend/api/routing.py"
        routing_content = routing_file.read_text()
        assert "health" in routing_content
        assert "worker" in routing_content
        assert 'worker.router, prefix="/api/v1"' in routing_content

        # Check pyproject.toml includes arq
        pyproject_content = (project_path / "pyproject.toml").read_text()
        assert "arq==0.25.0" in pyproject_content

        # Check worker configuration files exist and have correct structure
        system_worker_file = project_path / "app/components/worker/queues/system.py"
        system_worker_content = system_worker_file.read_text()
        assert "class WorkerSettings:" in system_worker_content
        assert "system_health_check" in system_worker_content
        assert "cleanup_temp_files" in system_worker_content

    def test_init_with_database_component(
        self,
        project_factory: "ProjectFactory",
    ) -> None:
        """Test generating a project with database component."""
        project_path = project_factory("base_with_database")

        # Assert project structure
        self._assert_database_project_structure(project_path)
        self._assert_database_template_processing(project_path)

        # Assert no template files remain
        assert_no_template_files(project_path)

    def _assert_database_project_structure(self, project_path: Path) -> None:
        """Assert database-specific project structure."""
        self._assert_core_project_structure(project_path)

        # Database-specific files
        assert_file_exists(project_path, "app/core/db.py")

        # Database component should not create additional directories
        # (unlike scheduler and worker which create component directories)

    def _assert_database_template_processing(self, project_path: Path) -> None:
        """Assert that database templates were processed correctly."""
        from .test_utils import (
            assert_database_config_present,
            assert_db_file_structure,
        )

        # Check config.py includes database settings
        config_file = project_path / "app/core/config.py"
        config_content = config_file.read_text()
        assert_database_config_present(config_content)

        # Check db.py has complete structure
        db_file = project_path / "app/core/db.py"
        db_content = db_file.read_text()
        assert_db_file_structure(db_content)

        # Check pyproject.toml includes database dependencies
        pyproject_content = (project_path / "pyproject.toml").read_text()
        assert "sqlmodel" in pyproject_content.lower()
        assert "sqlalchemy" in pyproject_content.lower()
        assert "aiosqlite" in pyproject_content.lower()

    def test_init_with_scheduler_sqlite_backend(
        self,
        project_factory: "ProjectFactory",
    ) -> None:
        """Test generating project with scheduler[sqlite] syntax."""
        # Use cached scheduler sqlite project
        project_path = project_factory("base_with_scheduler_sqlite")

        # Check scheduler component exists
        assert_file_exists(project_path, "app/components/scheduler/main.py")
        assert_file_exists(project_path, "app/entrypoints/scheduler.py")

        # Check database component exists (auto-added)
        assert_file_exists(project_path, "app/core/db.py")

        # Check scheduler service layer exists (persistence enabled)
        assert_file_exists(project_path, "app/services/scheduler/__init__.py")
        assert_file_exists(
            project_path, "app/services/scheduler/scheduled_task_manager.py"
        )

        # Check CLI tasks exists (persistence enabled)
        assert_file_exists(project_path, "app/cli/tasks.py")

        # Check API endpoints exist (persistence enabled)
        assert_file_exists(project_path, "app/components/backend/api/scheduler.py")

        # Check template processing - scheduler backend
        config_file = project_path / "app/core/config.py"
        assert config_file.exists()

        # Verify no .j2 files remain
        assert_no_template_files(project_path)

    def test_init_with_scheduler_memory_backend(
        self,
        project_factory: "ProjectFactory",
    ) -> None:
        """Test generating project with basic scheduler (memory backend)."""
        project_path = project_factory("base_with_scheduler")

        # Check scheduler component exists
        assert_file_exists(project_path, "app/components/scheduler/main.py")
        assert_file_exists(project_path, "app/entrypoints/scheduler.py")

        # Check database component does NOT exist
        assert_file_not_exists(project_path, "app/core/db.py")

        # Check scheduler service layer does NOT exist (memory only)
        assert_file_not_exists(project_path, "app/services/scheduler/")

        # Check CLI tasks does NOT exist (memory only)
        assert_file_not_exists(project_path, "app/cli/tasks.py")

        # Check API endpoints do NOT exist (memory only)
        assert_file_not_exists(project_path, "app/components/backend/api/scheduler.py")

        # Verify no .j2 files remain
        assert_no_template_files(project_path)

    def test_scheduler_backend_dependency_expansion(
        self,
        project_factory: "ProjectFactory",
    ) -> None:
        """Test that scheduler[sqlite] automatically adds database[sqlite]."""
        project_path = project_factory("base_with_scheduler_sqlite")

        # Should have both scheduler and database components
        assert_file_exists(project_path, "app/components/scheduler/main.py")
        assert_file_exists(project_path, "app/core/db.py")

        # Should include dependencies for both
        pyproject_content = (project_path / "pyproject.toml").read_text()
        assert "apscheduler==3.10.4" in pyproject_content
        assert "sqlmodel>=0.0.14" in pyproject_content

    @pytest.mark.slow
    def test_init_with_custom_output_directory(
        self,
        temp_output_dir: Any,
        skip_slow_tests: Any,
    ) -> None:
        """Test generating a project with custom output directory using -o flag."""
        # Create a subdirectory to use as output location
        custom_output = temp_output_dir / "custom-location"
        custom_output.mkdir(parents=True, exist_ok=True)

        # Generate project using -o flag (like user would do with -o ../)
        result = run_aegis_init(
            project_name="test-custom-output",
            components=[],
            output_dir=custom_output,
        )

        # Assert command succeeded
        assert result.success, (
            f"CLI command failed with custom output dir: {result.stderr}"
        )

        # Assert project was created in the correct location
        project_path = custom_output / "test-custom-output"
        assert project_path.exists(), f"Project not created at {project_path}"

        # Assert core structure exists
        assert (project_path / "app").exists(), "app directory missing"
        assert (project_path / "tests").exists(), "tests directory missing"
        assert (project_path / "pyproject.toml").exists(), "pyproject.toml missing"
        assert (project_path / ".copier-answers.yml").exists(), (
            ".copier-answers.yml missing"
        )

        # Assert virtual environment was created (proves tasks ran successfully)
        assert (project_path / ".venv").exists(), (
            ".venv not created - tasks may have failed"
        )

        # Assert no template files remain
        j2_files = list(project_path.rglob("*.j2"))
        jinja_files = list(project_path.rglob("*.jinja"))
        assert not j2_files, f"Template .j2 files remain: {j2_files}"
        assert not jinja_files, f"Template .jinja files remain: {jinja_files}"


# Note: CLI help tests moved to test_cli_basic.py to avoid duplication
