"""
Tests for Python version specification functionality.

These tests validate:
- Python version validation in CLI
- Python version propagation to templates
- .python-version file generation
- uv sync --python flag usage
"""

from typing import Any

import pytest

from .test_utils import (
    assert_file_contains,
    assert_file_exists,
    run_aegis_command,
    run_aegis_init,
)


class TestPythonVersionValidation:
    """Test Python version validation in CLI."""

    def test_valid_python_versions(self) -> None:
        """Test that valid Python versions are accepted."""
        for version in ["3.11", "3.12", "3.13", "3.14"]:
            result = run_aegis_command(
                "init",
                "test-project",
                "--python-version",
                version,
                "--help",  # Don't actually create project
            )
            # Help should work with valid versions
            assert (
                result.success
                or "Initialize a new Aegis Stack project" in result.stdout
            )

    def test_invalid_python_version(self) -> None:
        """Test that invalid Python versions are rejected."""
        result = run_aegis_command(
            "init", "test-project", "--python-version", "3.10", "--no-interactive"
        )
        assert not result.success
        assert (
            "Invalid Python version" in result.stderr
            or "Invalid Python version" in result.stdout
        )

    def test_invalid_python_version_format(self) -> None:
        """Test that malformed Python versions are rejected."""
        result = run_aegis_command(
            "init", "test-project", "--python-version", "invalid", "--no-interactive"
        )
        assert not result.success
        assert (
            "Invalid Python version" in result.stderr
            or "Invalid Python version" in result.stdout
        )


class TestPythonVersionGeneration:
    """Test Python version in generated projects."""

    @pytest.mark.slow
    def test_default_python_version(
        self,
        temp_output_dir: Any,
        skip_slow_tests: Any,
    ) -> None:
        """Test that default Python version is 3.14."""
        result = run_aegis_init(
            project_name="test-default-python",
            output_dir=temp_output_dir,
        )

        assert result.success, f"CLI command failed: {result.stderr}"
        project_path = result.project_path
        assert project_path is not None

        # Check .python-version file contains 3.14
        assert_file_exists(project_path, ".python-version")
        python_version_file = project_path / ".python-version"
        content = python_version_file.read_text().strip()
        assert content == "3.14", f"Expected Python 3.14, got {content}"

        # Check pyproject.toml has correct requires-python
        assert_file_exists(project_path, "pyproject.toml")
        assert_file_contains(
            project_path, "pyproject.toml", 'requires-python = ">=3.14"'
        )

        # Check Dockerfile has correct Python version
        assert_file_contains(project_path, "Dockerfile", "FROM python:3.14-slim")

    @pytest.mark.slow
    def test_python_version_3_11(
        self,
        temp_output_dir: Any,
        skip_slow_tests: Any,
    ) -> None:
        """Test generating project with Python 3.11."""
        result = run_aegis_init(
            project_name="test-python-311",
            output_dir=temp_output_dir,
            python_version="3.11",
        )

        assert result.success, f"CLI command failed: {result.stderr}"
        project_path = result.project_path
        assert project_path is not None

        # Check .python-version file
        python_version_file = project_path / ".python-version"
        assert python_version_file.exists()
        content = python_version_file.read_text().strip()
        assert content == "3.11", f"Expected Python 3.11, got {content}"

        # Check pyproject.toml
        assert_file_contains(
            project_path, "pyproject.toml", 'requires-python = ">=3.11"'
        )

        # Check Dockerfile has correct Python version
        assert_file_contains(project_path, "Dockerfile", "FROM python:3.11-slim")

    @pytest.mark.slow
    def test_python_version_3_12(
        self,
        temp_output_dir: Any,
        skip_slow_tests: Any,
    ) -> None:
        """Test generating project with Python 3.12."""
        result = run_aegis_init(
            project_name="test-python-312",
            output_dir=temp_output_dir,
            python_version="3.12",
        )

        assert result.success, f"CLI command failed: {result.stderr}"
        project_path = result.project_path
        assert project_path is not None

        # Check .python-version file
        python_version_file = project_path / ".python-version"
        assert python_version_file.exists()
        content = python_version_file.read_text().strip()
        assert content == "3.12", f"Expected Python 3.12, got {content}"

        # Check pyproject.toml
        assert_file_contains(
            project_path, "pyproject.toml", 'requires-python = ">=3.12"'
        )

        # Check Dockerfile has correct Python version
        assert_file_contains(project_path, "Dockerfile", "FROM python:3.12-slim")

    @pytest.mark.slow
    def test_python_version_3_13(
        self,
        temp_output_dir: Any,
        skip_slow_tests: Any,
    ) -> None:
        """Test generating project with Python 3.13."""
        result = run_aegis_init(
            project_name="test-python-313",
            output_dir=temp_output_dir,
            python_version="3.13",
        )

        assert result.success, f"CLI command failed: {result.stderr}"
        project_path = result.project_path
        assert project_path is not None

        # Check .python-version file
        python_version_file = project_path / ".python-version"
        assert python_version_file.exists()
        content = python_version_file.read_text().strip()
        assert content == "3.13", f"Expected Python 3.13, got {content}"

        # Check pyproject.toml
        assert_file_contains(
            project_path, "pyproject.toml", 'requires-python = ">=3.13"'
        )

        # Check Dockerfile has correct Python version
        assert_file_contains(project_path, "Dockerfile", "FROM python:3.13-slim")

    @pytest.mark.slow
    def test_python_version_3_14(
        self,
        temp_output_dir: Any,
        skip_slow_tests: Any,
    ) -> None:
        """Test generating project with Python 3.14."""
        result = run_aegis_init(
            project_name="test-python-314",
            output_dir=temp_output_dir,
            python_version="3.14",
        )

        assert result.success, f"CLI command failed: {result.stderr}"
        project_path = result.project_path
        assert project_path is not None

        # Check .python-version file
        python_version_file = project_path / ".python-version"
        assert python_version_file.exists()
        content = python_version_file.read_text().strip()
        assert content == "3.14", f"Expected Python 3.14, got {content}"

        # Check pyproject.toml
        assert_file_contains(
            project_path, "pyproject.toml", 'requires-python = ">=3.14"'
        )

        # Check Dockerfile has correct Python version
        assert_file_contains(project_path, "Dockerfile", "FROM python:3.14-slim")

    @pytest.mark.slow
    def test_python_version_3_14_with_rag(
        self,
        temp_output_dir: Any,
        skip_slow_tests: Any,
    ) -> None:
        """RAG no longer clamps the project to 3.13 (onnxruntime ships 3.14 wheels)."""
        result = run_aegis_init(
            project_name="test-python-314-rag",
            output_dir=temp_output_dir,
            python_version="3.14",
            services=["ai[rag]"],
        )

        assert result.success, f"CLI command failed: {result.stderr}"
        project_path = result.project_path
        assert project_path is not None

        content = (project_path / ".python-version").read_text().strip()
        assert content == "3.14", f"Expected Python 3.14, got {content}"
        assert_file_contains(
            project_path, "pyproject.toml", 'requires-python = ">=3.14,<3.15"'
        )

    @pytest.mark.slow
    def test_python_version_with_components(
        self,
        temp_output_dir: Any,
        skip_slow_tests: Any,
    ) -> None:
        """Test Python version with components selected."""
        result = run_aegis_init(
            project_name="test-python-components",
            components=["scheduler", "worker"],
            output_dir=temp_output_dir,
            python_version="3.12",
        )

        assert result.success, f"CLI command failed: {result.stderr}"
        project_path = result.project_path
        assert project_path is not None

        # Check .python-version file
        python_version_file = project_path / ".python-version"
        assert python_version_file.exists()
        content = python_version_file.read_text().strip()
        assert content == "3.12", f"Expected Python 3.12, got {content}"

        # Verify components were generated correctly
        assert_file_exists(project_path, "app/components/scheduler")
        assert_file_exists(project_path, "app/components/worker")
