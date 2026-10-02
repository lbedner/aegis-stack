"""
Basic CLI tests that run quickly.

These tests focus on command parsing, help text, and basic functionality
without doing full project generation.
"""

import pytest

from .test_utils import run_aegis_command, run_cli_help_command, strip_ansi_codes

# They did generate, though: every accepted init built a whole project.
pytestmark = pytest.mark.usefixtures("init_without_generation")


class TestCLIBasics:
    """Test basic CLI functionality."""

    def test_cli_help(self) -> None:
        """Test main CLI help."""
        result = run_cli_help_command("--help")
        assert result.success, f"Help command failed: {result.stderr}"
        assert "Aegis Stack CLI" in result.stdout
        assert "init" in result.stdout
        assert "version" in result.stdout

    def test_init_help(self) -> None:
        """Test init command help."""
        result = run_cli_help_command("init", "--help")

        assert result.success, f"Init help command failed: {result.stderr}"

        # Remove ANSI color codes for reliable string matching
        clean_output = strip_ansi_codes(result.stdout)
        assert "Initialize a new Aegis Stack project" in clean_output
        assert "--components" in clean_output
        assert (
            "redis,worker,scheduler" in clean_output
        )  # Updated to match actual available components
        assert "--no-interactive" in clean_output
        assert "--force" in clean_output
        # Guided is the interactive default; --quick is the escape hatch
        # back to the classic one-line prompts.
        assert "--guided" in clean_output
        assert "--quick" in clean_output

    def test_version_command(self) -> None:
        """Test version command."""
        result = run_cli_help_command("version")
        assert result.success, f"Version command failed: {result.stderr}"
        assert "Aegis Stack CLI" in result.stdout
        assert "v" in result.stdout  # Should show version number

    def test_invalid_component_error(self) -> None:
        """Test that invalid components are rejected with clear error."""
        result = run_aegis_command(
            "init",
            "test-project",
            "--components",
            "invalid_component",
            "--no-interactive",
            "--yes",
        )
        assert not result.success, "Expected command to fail with invalid component"
        assert (
            "Unknown component: invalid_component" in result.stderr
        )  # Updated to match actual error message

    def test_missing_project_name(self) -> None:
        """Test that missing project name shows helpful error."""
        result = run_aegis_command("init")
        assert not result.success, "Expected command to fail with missing project name"
        # Should show usage information about missing project name


class TestComponentValidation:
    """Test component validation logic."""

    @pytest.mark.parametrize(
        "component", ["scheduler", "worker", "redis"]
    )  # Updated to match actual available components
    def test_valid_components(self, component: str) -> None:
        """Test that valid components are accepted (but don't generate project)."""
        # This test would normally fail at project creation, but we're just
        # testing that the component name is validated as correct
        result = run_aegis_command(
            "init",
            "test-project",
            "--components",
            component,
            "--no-interactive",
            "--yes",
            "--force",
            "--output-dir",
            "/tmp/test-non-existent-dir",
        )
        # Should not fail with "Invalid component" error
        assert "Invalid component" not in result.stderr

    def test_multiple_components(self) -> None:
        """Test multiple component validation."""
        result = run_aegis_command(
            "init",
            "test-project",
            "--components",
            "scheduler,worker",  # Updated to match actual available components
            "--no-interactive",
            "--yes",
            "--force",
            "--output-dir",
            "/tmp/test-non-existent-dir",
        )
        # Should not fail with component validation errors
        assert "Invalid component" not in result.stderr

    def test_mixed_valid_invalid_components(self) -> None:
        """Test mix of valid and invalid components."""
        result = run_aegis_command(
            "init",
            "test-project",
            "--components",
            "scheduler,invalid,worker",  # Updated to match actual available components
            "--no-interactive",
            "--yes",
        )
        assert not result.success, "Expected command to fail with invalid component"
        assert (
            "Unknown component: invalid" in result.stderr
        )  # Updated to match actual error message

    def test_scheduler_backend_syntax_validation(self) -> None:
        """Test scheduler[backend] syntax is accepted."""
        result = run_aegis_command(
            "init",
            "test-project",
            "--components",
            "scheduler[sqlite]",
            "--no-interactive",
            "--yes",
        )
        # Should not fail validation (though may fail due to no output dir)
        # The key thing is it shouldn't reject scheduler[sqlite] as invalid component
        assert "Unknown component" not in result.stderr
        assert (
            "scheduler[sqlite]" not in result.stderr
            or "invalid" not in result.stderr.lower()
        )

    def test_scheduler_auto_dependency_message(self) -> None:
        """Test that scheduler[sqlite] shows auto-dependency message."""
        result = run_aegis_command(
            "init",
            "test-project",
            "--components",
            "scheduler[sqlite]",
            "--no-interactive",
            "--yes",
        )
        # Should show auto-added database message (even if command fails for other
        # reasons)
        assert "Auto-added database[sqlite]" in result.stdout

    def test_scheduler_backend_detection_message(self) -> None:
        """Test scheduler backend detection message."""
        result = run_aegis_command(
            "init",
            "test-project",
            "--components",
            "scheduler[sqlite]",
            "--no-interactive",
            "--yes",
            "--force",
        )
        # Should show scheduler backend detection (the actual message is slightly
        # different)
        assert (
            "Auto-detected: Scheduler with sqlite persistence" in result.stdout
            or "📊 Auto-detected: Scheduler with sqlite persistence" in result.stdout
            or "Auto-detected: Scheduler with sqlite persistence" in result.stderr
            or "📊 Auto-detected: Scheduler with sqlite persistence" in result.stderr
        )
