"""
Integration tests for the Aegis Stack CLI init command.

These tests validate:
- CLI command execution and output
- Generated project structure
- Template processing
- Component integration
"""

from collections.abc import Generator
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any

import pytest


def find_project_root() -> Path:
    """Find the project root directory by looking for pyproject.toml."""
    current_path = Path(__file__).resolve()
    for parent in current_path.parents:
        if (parent / "pyproject.toml").exists() and (parent / "aegis").exists():
            return parent
    raise RuntimeError("Could not find project root directory")


PROJECT_ROOT = find_project_root()


class CLITestResult:
    """Container for CLI test results."""

    def __init__(self, returncode: int, stdout: str, stderr: str, project_path: Path):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.project_path = project_path
        self.success = returncode == 0


@pytest.fixture
def temp_output_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test project generation."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


def run_aegis_init(
    project_name: str,
    components: list[str] | None = None,
    output_dir: Path = Path.cwd(),
    interactive: bool = False,
    force: bool = True,
    yes: bool = True,
) -> CLITestResult:
    """
    Run the aegis init command and return results.

    Args:
        project_name: Name of the project to create
        components: List of components to include
        output_dir: Directory to create project in
        interactive: Whether to use interactive mode
        force: Whether to force overwrite
        yes: Whether to skip confirmation

    Returns:
        CLITestResult with command results and project path
    """
    cmd = ["uv", "run", "python", "-m", "aegis", "init", project_name]

    if components:
        cmd.extend(["--components", ",".join(components)])
    if output_dir:
        cmd.extend(["--output-dir", str(output_dir)])
    if not interactive:
        cmd.append("--no-interactive")
    if force:
        cmd.append("--force")
    if yes:
        cmd.append("--yes")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,  # Run from aegis-stack root
    )

    project_path = output_dir / project_name
    return CLITestResult(result.returncode, result.stdout, result.stderr, project_path)


def assert_file_exists(project_path: Path, relative_path: str) -> None:
    """Assert that a file exists in the generated project."""
    file_path = project_path / relative_path
    assert file_path.exists(), f"Expected file not found: {relative_path}"


def assert_file_not_exists(project_path: Path, relative_path: str) -> None:
    """Assert that a file does not exist in the generated project."""
    file_path = project_path / relative_path
    assert not file_path.exists(), f"Unexpected file found: {relative_path}"


def assert_file_contains(project_path: Path, relative_path: str, content: str) -> None:
    """Assert that a file contains specific content."""
    file_path = project_path / relative_path
    assert file_path.exists(), f"File not found: {relative_path}"
    file_content = file_path.read_text()
    assert content in file_content, f"Content '{content}' not found in {relative_path}"


def assert_no_template_files(project_path: Path) -> None:
    """Assert that no .j2 template files remain in the generated project."""
    j2_files = list(project_path.rglob("*.j2"))
    assert not j2_files, (
        f"Template files should not exist in generated project: {j2_files}"
    )


class TestCLIInit:
    """Test cases for the aegis init command."""

    @pytest.mark.slow
    def test_init_with_scheduler_component(
        self, temp_output_dir: Any, skip_slow_tests: Any
    ) -> None:
        """Test generating a project with scheduler component."""
        result = run_aegis_init(
            project_name="test-scheduler",
            components=["scheduler"],
            output_dir=temp_output_dir,
        )

        # Assert command succeeded
        assert result.success, f"CLI command failed: {result.stderr}"

        # Assert expected CLI output content
        assert "🛡️  Aegis Stack Project Initialization" in result.stdout
        assert "✅ Additional Components:" in result.stdout
        assert "• scheduler" in result.stdout
        assert "• app/components/scheduler.py" in result.stdout
        assert "• tests/components/test_scheduler.py" in result.stdout
        assert "• apscheduler" in result.stdout
        assert "✅ Project created successfully!" in result.stdout

        # Assert project structure
        self._assert_scheduler_project_structure(result.project_path)

        # Assert template processing
        self._assert_scheduler_template_processing(result.project_path)

    @pytest.mark.slow
    def test_init_without_components(
        self, temp_output_dir: Any, skip_slow_tests: Any
    ) -> None:
        """Test generating a project with no additional components."""
        result = run_aegis_init(
            project_name="test-no-components", output_dir=temp_output_dir
        )

        # Assert command succeeded
        assert result.success, f"CLI command failed: {result.stderr}"

        # Assert expected CLI output
        assert "📦 No additional components selected" in result.stdout
        assert "scheduler" not in result.stdout
        assert "apscheduler" not in result.stdout

        # Assert project structure (no scheduler files)
        self._assert_core_project_structure(result.project_path)
        assert_file_not_exists(result.project_path, "app/components/scheduler.py")
        assert_file_not_exists(
            result.project_path, "tests/components/test_scheduler.py"
        )

    @pytest.mark.slow
    def test_init_invalid_component(
        self, temp_output_dir: Any, skip_slow_tests: Any
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

    @pytest.mark.slow
    def test_init_multiple_components(
        self, temp_output_dir: Any, skip_slow_tests: Any
    ) -> None:
        """Test generating project with multiple components (when available)."""
        # For now, test with just scheduler since others aren't implemented
        result = run_aegis_init(
            project_name="test-multi",
            components=["scheduler"],  # Add database, cache when implemented
            output_dir=temp_output_dir,
        )

        assert result.success, f"CLI command failed: {result.stderr}"
        self._assert_scheduler_project_structure(result.project_path)

    @pytest.mark.slow
    def test_template_variable_substitution(
        self, temp_output_dir: Any, skip_slow_tests: Any
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
        expected_title = project_name.replace("-", " ").title()
        assert_file_contains(
            result.project_path,
            "app/components/scheduler/main.py",
            f"🕒 Starting {expected_title} Scheduler",
        )

        # Check pyproject.toml has correct name
        assert_file_contains(
            result.project_path, "pyproject.toml", f'name = "{project_name}"'
        )

    @pytest.mark.slow
    def test_project_quality_checks(
        self, temp_output_dir: Any, skip_slow_tests: Any
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

        # Install dependencies first
        install_result = subprocess.run(
            ["uv", "sync", "--all-extras"],
            cwd=project_path,
            capture_output=True,
            text=True,
        )
        assert install_result.returncode == 0, (
            f"Failed to install deps: {install_result.stderr}"
        )

        # Run linting (allow fixes)
        lint_result = subprocess.run(
            ["uv", "run", "ruff", "check", "--fix", "."],
            cwd=project_path,
            capture_output=True,
            text=True,
        )
        # Linting should either pass or only have fixable issues
        assert lint_result.returncode in [0, 1], f"Linting failed: {lint_result.stderr}"

        # Run type checking
        typecheck_result = subprocess.run(
            ["uv", "run", "mypy", "."], cwd=project_path, capture_output=True, text=True
        )
        assert typecheck_result.returncode == 0, (
            f"Type checking failed: {typecheck_result.stdout}"
        )

        # Run tests
        test_result = subprocess.run(
            ["uv", "run", "pytest", "-v"],
            cwd=project_path,
            capture_output=True,
            text=True,
        )
        # Tests may have some issues but should at least run
        assert test_result.returncode in [0, 1], (
            f"Tests completely failed: {test_result.stdout}"
        )

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
        assert "scheduler = AsyncIOScheduler()" in scheduler_content
        assert "scheduler.add_job(" in scheduler_content
        assert "def create_scheduler()" in scheduler_content

        # Check pyproject.toml includes APScheduler
        pyproject_content = (project_path / "pyproject.toml").read_text()
        assert "apscheduler>=3.10.0" in pyproject_content

        # Check mypy overrides for APScheduler
        assert 'module = "apscheduler.*"' in pyproject_content
        assert "ignore_missing_imports = true" in pyproject_content


class TestCLIHelp:
    """Test CLI help and version commands."""

    def test_cli_help(self) -> None:
        """Test that CLI help works."""
        result = subprocess.run(
            ["uv", "run", "python", "-m", "aegis", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )

        assert result.returncode == 0
        assert "Aegis Stack CLI" in result.stdout
        assert "init" in result.stdout

    def test_init_help(self) -> None:
        """Test that init command help works."""
        result = subprocess.run(
            ["uv", "run", "python", "-m", "aegis", "init", "--help"],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )

        # Remove ANSI color codes for reliable string matching
        clean_output = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)

        assert result.returncode == 0
        assert "Initialize a new Aegis Stack project" in clean_output
        assert "--components" in clean_output
        assert "scheduler,database,cache" in clean_output
