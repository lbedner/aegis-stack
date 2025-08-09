"""
Basic CLI tests that run quickly.

These tests focus on command parsing, help text, and basic functionality
without doing full project generation.
"""

from pathlib import Path
import re
import subprocess
from typing import Any

import pytest


def run_cli_command(
    *args: Any, expect_success: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run a CLI command and return the result."""
    cmd = ["uv", "run", "python", "-m", "aegis"] + list(args)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent.parent,  # aegis-stack root
        timeout=10,  # Quick timeout for basic commands
    )

    if expect_success:
        assert result.returncode == 0, f"Command failed: {result.stderr}"

    return result


class TestCLIBasics:
    """Test basic CLI functionality."""

    def test_cli_help(self) -> None:
        """Test main CLI help."""
        result = run_cli_command("--help")
        assert "Aegis Stack CLI" in result.stdout
        assert "init" in result.stdout
        assert "version" in result.stdout

    def test_init_help(self) -> None:
        """Test init command help."""
        result = run_cli_command("init", "--help")

        # Remove ANSI color codes for reliable string matching
        clean_output = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
        assert "Initialize a new Aegis Stack project" in clean_output
        assert "--components" in clean_output
        assert "scheduler,database,cache" in clean_output
        assert "--no-interactive" in clean_output
        assert "--force" in clean_output

    def test_version_command(self) -> None:
        """Test version command."""
        result = run_cli_command("version")
        assert "Aegis Stack CLI" in result.stdout
        assert "v" in result.stdout  # Should show version number

    def test_invalid_component_error(self) -> None:
        """Test that invalid components are rejected with clear error."""
        result = run_cli_command(
            "init",
            "test-project",
            "--components",
            "invalid_component",
            "--no-interactive",
            "--yes",
            expect_success=False,
        )
        assert result.returncode == 1
        assert "Invalid component: invalid_component" in result.stderr
        assert "Valid components: scheduler, database, cache" in result.stderr

    def test_missing_project_name(self) -> None:
        """Test that missing project name shows helpful error."""
        result = run_cli_command("init", expect_success=False)
        assert result.returncode != 0
        # Should show usage information about missing project name


class TestComponentValidation:
    """Test component validation logic."""

    @pytest.mark.parametrize("component", ["scheduler", "database", "cache"])
    def test_valid_components(self, component: str) -> None:
        """Test that valid components are accepted (but don't generate project)."""
        # This test would normally fail at project creation, but we're just
        # testing that the component name is validated as correct
        result = run_cli_command(
            "init",
            "test-project",
            "--components",
            component,
            "--no-interactive",
            "--yes",
            "--force",
            "--output-dir",
            "/tmp/test-non-existent-dir",
            expect_success=False,  # Will fail for other reasons
        )
        # Should not fail with "Invalid component" error
        assert "Invalid component" not in result.stderr

    def test_multiple_components(self) -> None:
        """Test multiple component validation."""
        result = run_cli_command(
            "init",
            "test-project",
            "--components",
            "scheduler,database",
            "--no-interactive",
            "--yes",
            "--force",
            "--output-dir",
            "/tmp/test-non-existent-dir",
            expect_success=False,  # Will fail for other reasons
        )
        # Should not fail with component validation errors
        assert "Invalid component" not in result.stderr

    def test_mixed_valid_invalid_components(self) -> None:
        """Test mix of valid and invalid components."""
        result = run_cli_command(
            "init",
            "test-project",
            "--components",
            "scheduler,invalid,database",
            "--no-interactive",
            "--yes",
            expect_success=False,
        )
        assert "Invalid component: invalid" in result.stderr
