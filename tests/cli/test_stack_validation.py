"""
Stack Validation Tests for Aegis Stack CLI.

This module tests that generated stacks can build successfully and pass all
quality checks. For each stack combination, we validate:

1. Dependency Installation (uv sync)
2. CLI Installation (uv pip install -e .)
3. Code Quality (make check: lint + typecheck + test)
4. CLI Script Functionality (basic command validation)

These tests ensure that generated projects are not just syntactically correct
but actually functional and ready for development.
"""

from pathlib import Path
from typing import Any

import pytest

from .test_stack_generation import STACK_COMBINATIONS, StackCombination
from .test_utils import CLITestResult, run_quality_checks

pytestmark = pytest.mark.xdist_group("generated_stacks")

# Note: ValidationResult merged into CLITestResult in test_utils.py


class StackValidator:
    """Handles validation of generated stack projects using unified command system."""

    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.results: list[CLITestResult] = []

    def get_summary(self) -> dict[str, Any]:
        """Get validation summary."""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.success)
        failed = total - passed
        total_duration = sum(r.duration for r in self.results)

        return {
            "total_steps": total,
            "passed": passed,
            "failed": failed,
            "success_rate": passed / total if total > 0 else 0,
            "total_duration": total_duration,
            "results": self.results,
        }


def get_stack_validator(
    get_generated_stack: Any, combination: StackCombination
) -> tuple[CLITestResult, Path]:
    """Get pre-generated stack path for validation."""
    # Get the pre-generated stack
    _, result = get_generated_stack(combination.name)

    return result, result.project_path


@pytest.mark.parametrize("combination", STACK_COMBINATIONS, ids=lambda x: x.name)
@pytest.mark.slow
def test_stack_full_validation(
    combination: StackCombination,
    get_generated_stack: Any,
) -> None:
    """Validate every generated stack end-to-end in a single pipeline pass.

    Previously this matrix had 5 separate parametrized tests
    (dependency_installation, cli_installation, code_quality,
    cli_functionality, health_commands) and each one re-invoked
    ``run_quality_checks`` from scratch — running the full
    ``uv sync → uv pip install -e . → ruff → ty → pytest`` pipeline
    five times per stack just to assert different slices of the same
    result list. With 13 stacks that meant 65 pipeline executions per
    ``make test-stacks-build`` run.

    Now the pipeline runs once per stack and every check (deps, CLI
    install, lint, typecheck, pytest, ``--help``, ``health status --help``)
    asserts against that single result set.
    """
    from .test_utils import run_project_command

    result, project_path = get_stack_validator(get_generated_stack, combination)

    assert result.success, f"Failed to generate {combination.description}"

    quality_results = run_quality_checks(project_path)
    dep_result = quality_results[0]
    cli_install_result = quality_results[1]
    lint_result = quality_results[2]
    type_result = quality_results[3]
    pytest_result = quality_results[4]

    assert dep_result.success, (
        f"Dependency installation failed for {combination.description}\n"
        f"Duration: {dep_result.duration:.1f}s\n"
        f"Error: {dep_result.error_message}\n"
        f"STDOUT: {dep_result.stdout}\n"
        f"STDERR: {dep_result.stderr}"
    )

    assert cli_install_result.success, (
        f"CLI installation failed for {combination.description}\n"
        f"Duration: {cli_install_result.duration:.1f}s\n"
        f"Error: {cli_install_result.error_message}\n"
        f"STDOUT: {cli_install_result.stdout}\n"
        f"STDERR: {cli_install_result.stderr}"
    )

    # Lint runs ``ruff check --fix``, so anything auto-fixable is already gone;
    # a non-zero exit means unfixable violations ship in generated output. Hold
    # it to the same strictness as the dep / install / typecheck / pytest gates
    # (issue #866) — a generated project must lint clean, not merely not crash.
    assert lint_result.success, (
        f"Linting failed for {combination.description}\n"
        f"Duration: {lint_result.duration:.1f}s\n"
        f"Error: {lint_result.error_message}\n"
        f"STDOUT: {lint_result.stdout}\n"
        f"STDERR: {lint_result.stderr}"
    )

    assert type_result.success, (
        f"Type checking failed for {combination.description}\n"
        f"Duration: {type_result.duration:.1f}s\n"
        f"Error: {type_result.error_message}\n"
        f"STDOUT: {type_result.stdout}\n"
        f"STDERR: {type_result.stderr}"
    )

    # Every stack's internal pytest must pass — this gate was historically
    # only enforced by ``test_full_stack_validation_pipeline`` (worker only),
    # which let regressions in the other stacks land silently.
    assert pytest_result.success, (
        f"pytest failed inside {combination.description}\n"
        f"Duration: {pytest_result.duration:.1f}s\n"
        f"Error: {pytest_result.error_message}\n"
        f"STDOUT: {pytest_result.stdout}\n"
        f"STDERR: {pytest_result.stderr}"
    )

    cli_test_result = run_project_command(
        ["uv", "run", combination.project_slug, "--help"],
        project_path,
        step_name="CLI Script Test",
        env_overrides={"VIRTUAL_ENV": ""},
    )
    assert cli_test_result.success, (
        f"CLI script test failed for {combination.description}\n"
        f"Duration: {cli_test_result.duration:.1f}s\n"
        f"Error: {cli_test_result.error_message}\n"
        f"STDOUT: {cli_test_result.stdout}\n"
        f"STDERR: {cli_test_result.stderr}"
    )

    health_result = run_project_command(
        ["uv", "run", combination.project_slug, "health", "status", "--help"],
        project_path,
        step_name="Health Command Test",
        env_overrides={"VIRTUAL_ENV": ""},
    )
    assert health_result.success, (
        f"Health command test failed for {combination.description}\n"
        f"Duration: {health_result.duration:.1f}s\n"
        f"Error: {health_result.error_message}\n"
        f"STDOUT: {health_result.stdout}\n"
        f"STDERR: {health_result.stderr}"
    )

    # Agent registry smoke: a sqlite-backed ai stack must come out of
    # generation with a seeded, inspectable registry (postgres stacks
    # have no database running during matrix validation).
    has_sqlite_ai = any(
        service.startswith("ai[") and "sqlite" in service
        for service in (combination.services or [])
    )
    if has_sqlite_ai:
        agents_result = run_project_command(
            ["uv", "run", combination.project_slug, "agents", "list"],
            project_path,
            step_name="Agents Registry Test",
            env_overrides={"VIRTUAL_ENV": ""},
        )
        assert agents_result.success, (
            f"agents list failed for {combination.description}\n"
            f"Duration: {agents_result.duration:.1f}s\n"
            f"Error: {agents_result.error_message}\n"
            f"STDOUT: {agents_result.stdout}\n"
            f"STDERR: {agents_result.stderr}"
        )
        assert "assistant" in agents_result.stdout, (
            f"seeded default agent missing for {combination.description}\n"
            f"STDOUT: {agents_result.stdout}"
        )


@pytest.mark.slow
def test_full_stack_validation_pipeline(get_generated_stack: Any) -> None:
    """Test complete validation pipeline for a representative stack."""
    from .test_utils import run_project_command

    # Use worker stack as it includes most components
    combination = next(c for c in STACK_COMBINATIONS if c.name == "worker")

    result, project_path = get_stack_validator(get_generated_stack, combination)
    assert result.success, f"Failed to generate {combination.description}"

    # Run complete validation pipeline
    quality_results = run_quality_checks(project_path)

    # Test CLI script functionality
    cli_test_result = run_project_command(
        ["uv", "run", combination.project_slug, "--help"],
        project_path,
        step_name="CLI Script Test",
        env_overrides={"VIRTUAL_ENV": ""},
    )

    # Test health command
    health_result = run_project_command(
        ["uv", "run", combination.project_slug, "health", "status", "--help"],
        project_path,
        step_name="Health Command Test",
        env_overrides={"VIRTUAL_ENV": ""},
    )

    # Collect all results
    all_results = quality_results + [cli_test_result, health_result]

    # Validation summary
    total = len(all_results)
    passed = sum(1 for r in all_results if r.success)
    total_duration = sum(r.duration for r in all_results)

    # Every step must pass, lint included: ``ruff check --fix`` has already
    # applied fixable findings, so a lint failure is an unfixable violation
    # shipping in generated output (issue #866).
    critical_failures = [r for r in all_results if not r.success]

    # Dump full stdout/stderr for any failing critical step. ``CLITestResult``'s
    # default ``__str__`` only renders a one-line summary, which is fine for
    # local runs but useless in CI when the matrix runner is the only place
    # a transient failure reproduces. Surface enough output here that the
    # next CI run is self-diagnosing.
    failure_blocks = []
    for r in critical_failures:
        failure_blocks.append(
            f"  - {r}\n    STDOUT:\n{r.stdout}\n    STDERR:\n{r.stderr}"
        )

    assert len(critical_failures) == 0, (
        f"Validation pipeline failed for {combination.description}\n"
        f"Summary: {passed}/{total} passed in {total_duration:.1f}s\n"
        f"Failed steps:\n" + "\n".join(failure_blocks)
    )

    # Verify reasonable performance
    assert total_duration < 300, (
        f"Validation took too long: {total_duration:.1f}s > 300s"
    )


@pytest.mark.slow
def test_validation_performance_benchmarks() -> None:
    """Test that validation steps complete within reasonable time limits."""
    # Expected time limits for each step
    time_limits = {
        "Dependency Installation": 180,  # 3 minutes
        "CLI Installation": 60,  # 1 minute
        "Code Quality Check": 120,  # 2 minutes
        "CLI Script Test": 30,  # 30 seconds
        "Health Command Test": 30,  # 30 seconds
    }

    # This is more of a documentation test - actual timing validation
    # happens in the individual test methods via timeout parameters
    assert all(limit > 0 for limit in time_limits.values())
    assert sum(time_limits.values()) < 600  # Total under 10 minutes


def test_validation_error_handling() -> None:
    """Test that validation methods properly handle and report errors."""
    # Create validator with non-existent project path
    invalid_path = Path("/tmp/non-existent-project")
    validator = StackValidator(invalid_path)

    # Test basic validation summary functionality
    summary = validator.get_summary()

    # Should have proper summary structure
    assert isinstance(summary, dict)
    assert "total_steps" in summary
    assert "passed" in summary
    assert "failed" in summary
    assert "success_rate" in summary
    assert "total_duration" in summary
    assert "results" in summary
