"""
Comprehensive tests for adding worker component via 'aegis add worker'.

These tests focus specifically on worker component addition workflows,
including Redis dependency resolution, shared file regeneration, and
health check registration.
"""

from typing import TYPE_CHECKING

from aegis.core.copier_manager import load_copier_answers

from .test_utils import run_aegis_command

if TYPE_CHECKING:
    from tests.cli.conftest import ProjectFactory


class TestAddWorkerComponent:
    """Test suite for adding worker component to existing projects."""

    def test_add_worker_to_base_project(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test adding worker component to a fresh base project."""
        # Use cached base project (no components)
        project_path = project_factory("base")

        # Verify initial state
        initial_answers = load_copier_answers(project_path)
        assert initial_answers.get("include_worker") is False
        assert initial_answers.get("include_redis") is False

        # Add worker component
        result = run_aegis_command(
            "add", "worker", "--project-path", str(project_path), "--yes"
        )

        assert result.success, f"Command failed: {result.stderr}"

        # Verify worker and redis were added
        updated_answers = load_copier_answers(project_path)
        assert updated_answers.get("include_worker") is True
        assert updated_answers.get("include_redis") is True

    def test_add_worker_when_redis_already_enabled(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test adding worker when Redis is already in the project."""
        # Use cached project with Redis already enabled
        # (This simulates a project that manually enabled redis for caching)
        project_path = project_factory("base_with_redis")

        # Verify Redis is already enabled
        initial_answers = load_copier_answers(project_path)
        assert initial_answers.get("include_redis") is True
        assert initial_answers.get("include_worker") is False

        # Add worker component
        result = run_aegis_command(
            "add", "worker", "--project-path", str(project_path), "--yes"
        )

        assert result.success, f"Command failed: {result.stderr}"

        # Verify worker was added, redis remains enabled
        updated_answers = load_copier_answers(project_path)
        assert updated_answers.get("include_worker") is True
        assert updated_answers.get("include_redis") is True

    def test_add_worker_shared_files_regenerated(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that adding worker regenerates shared files with worker imports."""
        # Use cached base project
        project_path = project_factory("base")

        # Read shared files BEFORE adding worker
        component_health_before = (
            project_path
            / "app"
            / "components"
            / "backend"
            / "startup"
            / "component_health.py"
        ).read_text()
        # WorkerCard is built by the overseer card factory, not by
        # ``frontend/main.py`` — but both are shared files the add path
        # must regenerate, which is what this test is about.
        cards_factory_before = (
            project_path / "app" / "components" / "frontend" / "overseer" / "cards.py"
        ).read_text()
        cards_init_before = (
            project_path
            / "app"
            / "components"
            / "frontend"
            / "dashboard"
            / "cards"
            / "__init__.py"
        ).read_text()

        # Worker health check should NOT be present
        assert "worker" not in component_health_before.lower()
        assert "WorkerCard" not in cards_factory_before
        assert "WorkerCard" not in cards_init_before

        # Add worker component
        result = run_aegis_command(
            "add", "worker", "--project-path", str(project_path), "--yes"
        )

        assert result.success, f"Command failed: {result.stderr}"

        # Read shared files AFTER adding worker
        component_health_after = (
            project_path
            / "app"
            / "components"
            / "backend"
            / "startup"
            / "component_health.py"
        ).read_text()
        cards_factory_after = (
            project_path / "app" / "components" / "frontend" / "overseer" / "cards.py"
        ).read_text()
        cards_init_after = (
            project_path
            / "app"
            / "components"
            / "frontend"
            / "dashboard"
            / "cards"
            / "__init__.py"
        ).read_text()

        # Worker health check SHOULD be present
        assert "worker" in component_health_after.lower()
        assert "check_worker_health" in component_health_after

        # Worker card imports SHOULD be present
        assert "WorkerCard" in cards_factory_after
        assert "WorkerCard" in cards_init_after

    def test_add_worker_creates_component_directory(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that worker component directory and files are created."""
        # Use cached base project
        project_path = project_factory("base")

        # Verify worker directory doesn't exist
        worker_dir = project_path / "app" / "components" / "worker"
        assert not worker_dir.exists()

        # Add worker component
        result = run_aegis_command(
            "add", "worker", "--project-path", str(project_path), "--yes"
        )

        assert result.success, f"Command failed: {result.stderr}"

        # Verify worker directory and key files exist
        assert worker_dir.exists()
        assert (worker_dir / "__init__.py").exists()
        assert (worker_dir / "pools.py").exists()
        assert (worker_dir / "registry.py").exists()
        assert (worker_dir / "queues" / "system.py").exists()
        assert (worker_dir / "tasks" / "system_tasks.py").exists()

    def test_add_worker_creates_service_files(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that worker service files (load test) are created."""
        # Use cached base project
        project_path = project_factory("base")

        # Add worker component
        result = run_aegis_command(
            "add", "worker", "--project-path", str(project_path), "--yes"
        )

        assert result.success, f"Command failed: {result.stderr}"

        # Verify load test service files exist. The service was refactored
        # from a flat ``load_test.py`` into a package; ``load_test_models.py``
        # remains as a back-compat shim.
        assert (
            project_path / "app" / "services" / "load_test" / "__init__.py"
        ).exists()
        assert (
            project_path / "app" / "services" / "load_test" / "worker" / "service.py"
        ).exists()
        assert (project_path / "app" / "services" / "load_test_models.py").exists()

    def test_add_worker_creates_test_files(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that worker test files are created."""
        # Use cached base project
        project_path = project_factory("base")

        # Add worker component
        result = run_aegis_command(
            "add", "worker", "--project-path", str(project_path), "--yes"
        )

        assert result.success, f"Command failed: {result.stderr}"

        # Verify worker test files exist
        assert (project_path / "tests" / "api" / "test_worker_endpoints.py").exists()
        assert (
            project_path / "tests" / "services" / "test_worker_health_registration.py"
        ).exists()

    def test_add_worker_creates_dashboard_card(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that worker dashboard card file is created."""
        # Use cached base project
        project_path = project_factory("base")

        # Add worker component
        result = run_aegis_command(
            "add", "worker", "--project-path", str(project_path), "--yes"
        )

        assert result.success, f"Command failed: {result.stderr}"

        # Verify worker card file exists
        worker_card = (
            project_path
            / "app"
            / "components"
            / "frontend"
            / "dashboard"
            / "cards"
            / "worker_card.py"
        )
        assert worker_card.exists()

        # Verify it contains the WorkerCard class
        card_content = worker_card.read_text()
        assert "class WorkerCard" in card_content
        assert "arq" in card_content.lower()  # Should mention arq

    def test_add_worker_with_other_components(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test adding worker to a project that already has other components."""
        # Use cached project with scheduler
        project_path = project_factory("base_with_scheduler")

        # Verify initial state
        initial_answers = load_copier_answers(project_path)
        assert initial_answers.get("include_scheduler") is True
        assert initial_answers.get("include_worker") is False

        # Add worker component
        result = run_aegis_command(
            "add", "worker", "--project-path", str(project_path), "--yes"
        )

        assert result.success, f"Command failed: {result.stderr}"

        # Verify both scheduler and worker are enabled
        updated_answers = load_copier_answers(project_path)
        assert updated_answers.get("include_scheduler") is True
        assert updated_answers.get("include_worker") is True
        assert updated_answers.get("include_redis") is True

    def test_add_worker_updates_pyproject_toml(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that pyproject.toml is updated with arq dependency."""
        # Use cached base project
        project_path = project_factory("base")

        # Read pyproject.toml before
        pyproject_before = (project_path / "pyproject.toml").read_text()
        assert "arq" not in pyproject_before.lower()

        # Add worker component
        result = run_aegis_command(
            "add", "worker", "--project-path", str(project_path), "--yes"
        )

        assert result.success, f"Command failed: {result.stderr}"

        # Read pyproject.toml after
        pyproject_after = (project_path / "pyproject.toml").read_text()

        # Should contain arq dependency
        assert "arq" in pyproject_after.lower()
        # Should also contain redis dependency
        assert "redis" in pyproject_after.lower()

    def test_add_worker_updates_docker_compose(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that docker-compose.yml is updated with worker and redis services."""
        # Use cached base project
        project_path = project_factory("base")

        # Read docker-compose.yml before
        docker_compose_before = (project_path / "docker-compose.yml").read_text()
        assert "worker-system" not in docker_compose_before
        assert "redis" not in docker_compose_before

        # Add worker component
        result = run_aegis_command(
            "add", "worker", "--project-path", str(project_path), "--yes"
        )

        assert result.success, f"Command failed: {result.stderr}"

        # Read docker-compose.yml after
        docker_compose_after = (project_path / "docker-compose.yml").read_text()

        # Should contain worker services
        assert "worker-system" in docker_compose_after
        assert "worker-load-test" in docker_compose_after
        # Should contain redis service
        assert "redis:" in docker_compose_after


class TestAddWorkerEdgeCases:
    """Test edge cases and error conditions for worker addition."""

    def test_add_worker_already_enabled(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test adding worker when it's already enabled."""
        # Use cached project with worker already enabled
        project_path = project_factory("base_with_worker")

        # Try to add worker again
        result = run_aegis_command(
            "add", "worker", "--project-path", str(project_path), "--yes"
        )

        # Should succeed with message about already enabled
        assert result.success
        assert "already enabled" in result.stdout.lower()

    def test_add_worker_with_multiple_components_at_once(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test adding worker along with other components in one command."""
        # Use cached base project
        project_path = project_factory("base")

        # Add worker and scheduler together
        result = run_aegis_command(
            "add", "worker,scheduler", "--project-path", str(project_path), "--yes"
        )

        assert result.success, f"Command failed: {result.stderr}"

        # Verify all components were added
        updated_answers = load_copier_answers(project_path)
        assert updated_answers.get("include_worker") is True
        assert updated_answers.get("include_scheduler") is True
        assert updated_answers.get("include_redis") is True  # Auto-added for worker

    def test_add_worker_preserves_existing_files(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that adding worker doesn't overwrite existing customizations."""
        # Use cached base project
        project_path = project_factory("base")

        # Create a custom file that should be preserved
        custom_file = project_path / "app" / "services" / "custom_service.py"
        custom_file.parent.mkdir(parents=True, exist_ok=True)
        custom_content = "# Custom service - do not delete"
        custom_file.write_text(custom_content)

        # Add worker component
        result = run_aegis_command(
            "add", "worker", "--project-path", str(project_path), "--yes"
        )

        assert result.success, f"Command failed: {result.stderr}"

        # Verify custom file still exists with original content
        assert custom_file.exists()
        assert custom_file.read_text().strip() == custom_content.strip()
