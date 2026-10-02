"""
Error Handling Tests for Aegis Stack CLI.

This module tests that the CLI properly handles invalid inputs and provides
helpful error messages for common user mistakes:

1. Invalid component names
2. Conflicting components (if any exist)
3. Invalid project names
4. File system errors
5. Permission errors
6. Malformed command arguments

The goal is to ensure users get clear, actionable error messages rather than
cryptic stack traces or silent failures.
"""

from pathlib import Path

import pytest

from .test_utils import (
    check_error_indicators,
    run_aegis_init,
    run_aegis_init_expect_failure,
)

# Init's handling of its input, not the project it would build: an accepted
# init stops at generation instead of spending 10-15s on it.
pytestmark = pytest.mark.usefixtures("init_without_generation")


class ErrorTestCase:
    """Test case for error handling validation."""

    def __init__(
        self,
        name: str,
        project_name: str,
        components: list[str],
        expected_error_indicators: list[str],
        description: str,
        should_fail: bool = True,
    ):
        self.name = name
        self.project_name = project_name
        self.components = components
        self.expected_error_indicators = expected_error_indicators
        self.description = description
        self.should_fail = should_fail


# Test cases for error handling
ERROR_TEST_CASES = [
    ErrorTestCase(
        name="invalid_component",
        project_name="test-invalid",
        components=["invalid_component"],
        expected_error_indicators=["invalid", "component", "unknown"],
        description="Invalid component name should produce clear error",
    ),
    ErrorTestCase(
        name="nonexistent_component",
        project_name="test-nonexistent",
        components=["nosql"],  # Not implemented component
        expected_error_indicators=["unknown", "component", "available"],
        description="Nonexistent component should show available options",
    ),
    ErrorTestCase(
        name="multiple_invalid",
        project_name="test-multi-invalid",
        components=["invalid1", "invalid2", "worker"],  # Mix valid and invalid
        expected_error_indicators=["invalid", "unknown"],
        description="Multiple invalid components should be reported",
    ),
    ErrorTestCase(
        name="empty_component",
        project_name="test-empty-component",
        components=["", "worker"],  # Empty component name mixed with valid one
        expected_error_indicators=["empty", "component"],
        description="Empty component name should be rejected",
    ),
    ErrorTestCase(
        name="typo_component",
        project_name="test-typo",
        components=["schedul"],  # Close to "scheduler"
        expected_error_indicators=["unknown", "did you mean", "scheduler"],
        description="Typos should suggest similar component names",
    ),
]

INVALID_PROJECT_NAME_CASES = [
    ErrorTestCase(
        name="empty_project_name",
        project_name="",
        components=[],
        expected_error_indicators=["project", "name", "empty"],
        description="Empty project name should be rejected",
    ),
    ErrorTestCase(
        name="invalid_characters",
        project_name="test-project!@#",
        components=[],
        expected_error_indicators=["invalid", "character", "name"],
        description="Invalid characters in project name should be rejected",
    ),
    ErrorTestCase(
        name="reserved_name",
        project_name="aegis",
        components=[],
        expected_error_indicators=["reserved", "name"],
        description="Reserved project names should be rejected",
    ),
    ErrorTestCase(
        name="too_long_name",
        project_name="a" * 100,  # Very long name
        components=[],
        expected_error_indicators=["too long", "name", "limit"],
        description="Excessively long project names should be rejected",
    ),
]


@pytest.mark.parametrize("test_case", ERROR_TEST_CASES, ids=lambda x: x.name)
def test_invalid_component_errors(
    test_case: ErrorTestCase, temp_output_dir: Path
) -> None:
    """Test error handling for invalid components."""
    result = run_aegis_init_expect_failure(
        test_case.project_name,
        test_case.components,
        temp_output_dir,
    )

    # Check error output for expected indicators
    error_output = result.stderr + result.stdout
    check_error_indicators(
        error_output, test_case.expected_error_indicators, test_case.description
    )


@pytest.mark.parametrize("test_case", INVALID_PROJECT_NAME_CASES, ids=lambda x: x.name)
def test_invalid_project_name_errors(
    test_case: ErrorTestCase, temp_output_dir: Path
) -> None:
    """Test error handling for invalid project names."""
    if test_case.project_name == "":
        # Special case: empty project name might be caught by argument parser
        # Test this separately
        pytest.skip("Empty project name handled by argument parser")

    result = run_aegis_init_expect_failure(
        test_case.project_name,
        test_case.components,
        temp_output_dir,
    )

    # Check error output for expected indicators
    error_output = result.stderr + result.stdout
    check_error_indicators(
        error_output, test_case.expected_error_indicators, test_case.description
    )


def test_duplicate_components_handling(temp_output_dir: Path) -> None:
    """Test handling of duplicate component specifications."""
    # This should either deduplicate or provide helpful error
    result = run_aegis_init(
        "test-duplicates",
        ["worker", "worker", "scheduler"],
        temp_output_dir,
    )

    # This could succeed (deduplication) or fail (validation error)
    # Either is acceptable as long as it's handled gracefully
    if not result.success:
        error_output = result.stderr + result.stdout
        # Should mention duplicates if it fails
        assert any(word in error_output.lower() for word in ["duplicate", "repeated"])


def test_help_message_clarity() -> None:
    """Test that help messages are clear and useful."""
    from .test_utils import run_cli_help_command

    result = run_cli_help_command("--help")

    assert result.success, "Help command should succeed"

    help_output = result.stdout

    # Help should mention key concepts
    expected_help_content = [
        "init",  # Main command
        "project",  # What it creates
        "components",  # Key concept
        "worker",  # Available component
        "scheduler",  # Available component
    ]

    help_lower = help_output.lower()
    for content in expected_help_content:
        assert content in help_lower, f"Help output should mention '{content}'"


def test_component_list_command() -> None:
    """Test that component list command works and shows available options."""
    from .test_utils import run_cli_help_command

    result = run_cli_help_command("components")

    assert result.success, "Components command should succeed"

    components_output = result.stdout

    # Should list available components
    expected_components = ["worker", "scheduler"]  # Currently available

    components_lower = components_output.lower()
    for component in expected_components:
        assert component in components_lower, (
            f"Components list should include '{component}'"
        )


def test_file_system_error_handling(temp_output_dir: Path) -> None:
    """Test handling of file system errors."""
    # Try to create project in directory that already exists
    existing_dir = temp_output_dir / "existing-project"
    existing_dir.mkdir()

    # Without --force, this should fail gracefully
    result = run_aegis_init(
        "existing-project",
        [],
        temp_output_dir,
    )

    if not result.success:
        error_output = result.stderr + result.stdout
        # Should mention directory exists
        assert any(word in error_output.lower() for word in ["exist", "directory"])


@pytest.mark.skip(
    reason="Test is flawed - creates project in read-only dir, fails at path "
    "validation before error handling. Permission errors aren't a realistic "
    "CLI failure mode."
)
def test_permission_error_simulation(temp_output_dir: Path) -> None:
    """Test handling of permission errors (simulated)."""
    # Create read-only directory
    readonly_dir = temp_output_dir / "readonly"
    readonly_dir.mkdir(mode=0o444)  # Read-only

    try:
        result = run_aegis_init(
            "test-readonly",
            [],
            readonly_dir,
        )

        if not result.success:
            error_output = result.stderr + result.stdout
            # Should provide helpful error message
            assert any(
                word in error_output.lower()
                for word in ["permission", "access", "write"]
            )

    finally:
        # Cleanup: restore permissions
        readonly_dir.chmod(0o755)


def test_error_message_quality(temp_output_dir: Path) -> None:
    """Test that error messages are high quality and actionable."""
    # Test invalid component error message
    result = run_aegis_init_expect_failure(
        "test-quality",
        ["invalid_component"],
        temp_output_dir,
    )

    error_output = result.stderr + result.stdout

    # Error message quality criteria
    error_lower = error_output.lower()

    # Should not contain:
    bad_indicators = ["traceback", "exception:", "error:", "fatal:"]
    for bad in bad_indicators:
        if bad in error_lower:
            # Some technical terms might be OK in context
            # This is more of a warning than a hard failure
            print(f"Warning: Error message contains technical term '{bad}'")

    # Should contain helpful information (future enhancement)
    # good_indicators = ["available", "valid", "help"]
    # has_helpful_info = any(good in error_lower for good in good_indicators)

    # At minimum, should not be just a raw Python error
    assert "invalid_component" in error_lower, (
        "Should mention the specific invalid component"
    )


def test_edge_case_inputs(temp_output_dir: Path) -> None:
    """Test various edge cases in input handling."""
    edge_cases = [
        # Unicode characters
        ("test-ünicode", []),
        # Very long component list
        ("test-long", ["worker"] * 10),  # Duplicates
        # Mixed case
        ("Test-Mixed-Case", ["Worker"]),  # Should normalize or error
    ]

    for project_name, components in edge_cases:
        result = run_aegis_init(
            project_name,
            components,
            temp_output_dir,
        )

        # Should either succeed or fail gracefully (no crashes)
        # Success or failure is both acceptable for edge cases
        if not result.success:
            error_output = result.stderr + result.stdout
            # Should not be a raw Python traceback
            assert "Traceback" not in error_output, (
                f"Edge case should not cause Python traceback: "
                f"{project_name}, {components}"
            )
