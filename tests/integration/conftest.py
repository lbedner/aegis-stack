"""
Pytest configuration for integration tests.

Provides session-scoped caching fixtures for update integration tests
to avoid regenerating projects for each test.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# =============================================================================
# Template Path Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def template_path() -> Path:
    """Get path to aegis-stack repository root (session-scoped)."""
    return Path(__file__).parents[2]


@pytest.fixture(scope="session")
def old_commit_hash(template_path: Path) -> str:
    """Get commit hash from an older commit for testing upgrades (session-scoped)."""
    for commits_back in [10, 5, 1]:
        result = subprocess.run(
            ["git", "rev-parse", f"HEAD~{commits_back}"],
            cwd=template_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()

    pytest.skip("Insufficient git history (shallow clone)")
    return ""


@pytest.fixture(scope="session")
def head_commit_hash(template_path: Path) -> str:
    """Get current HEAD commit hash (session-scoped)."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=template_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


# =============================================================================
# Session-Scoped Project Caches
# =============================================================================


@pytest.fixture(scope="session")
def old_version_project_cache(
    tmp_path_factory: pytest.TempPathFactory,
    old_commit_hash: str,
) -> Path:
    """
    Generate a project from an old commit ONCE per test session.

    This dramatically reduces test time by avoiding duplicate generation.
    Tests that need an "updatable project" should copy from this cache.
    """
    cache_dir = tmp_path_factory.mktemp("update-test-cache")

    print(f"\nGenerating cached old-version project (commit: {old_commit_hash[:8]})...")

    result = subprocess.run(
        [
            "aegis",
            "init",
            "cached-old-project",
            "--to-version",
            old_commit_hash,
            "--python-version",
            "3.11",
            "--no-interactive",
            "--yes",
        ],
        cwd=cache_dir,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to generate cached old-version project:\n"
            f"STDOUT: {result.stdout}\n"
            f"STDERR: {result.stderr}"
        )

    project_path = cache_dir / "cached-old-project"
    print(f"Cached old-version project ready at: {project_path}")
    return project_path


@pytest.fixture(scope="session")
def head_project_cache(
    tmp_path_factory: pytest.TempPathFactory,
    head_commit_hash: str,
) -> Path:
    """
    Generate a project from HEAD ONCE per test session.

    Tests that need a current-version project should copy from this cache.
    """
    cache_dir = tmp_path_factory.mktemp("head-cache")

    print(f"\nGenerating cached HEAD project (commit: {head_commit_hash[:8]})...")

    result = subprocess.run(
        [
            "aegis",
            "init",
            "cached-head-project",
            "--to-version",
            head_commit_hash,
            # The project is rendered and formatted for the interpreter that
            # will run it: a 3.14 render is not importable on 3.11 (post-gen
            # ruff unquotes forward references under deferred annotations),
            # and the update path executes project code under this venv.
            "--python-version",
            f"{sys.version_info.major}.{sys.version_info.minor}",
            "--no-interactive",
            "--yes",
        ],
        cwd=cache_dir,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to generate cached HEAD project:\n"
            f"STDOUT: {result.stdout}\n"
            f"STDERR: {result.stderr}"
        )

    project_path = cache_dir / "cached-head-project"
    print(f"Cached HEAD project ready at: {project_path}")
    return project_path


# =============================================================================
# Per-Test Project Fixtures (copy from cache)
# =============================================================================


def _copy_project_without_venv(src: Path, dest: Path) -> None:
    """Copy project directory excluding .venv to avoid stale Python issues."""

    def ignore_venv(_directory: str, files: list[str]) -> list[str]:
        """Ignore .venv directory during copy."""
        return [".venv"] if ".venv" in files else []

    shutil.copytree(src, dest, ignore=ignore_venv)


@pytest.fixture
def updatable_project(old_version_project_cache: Path, tmp_path: Path) -> Path:
    """
    Copy cached old-version project to fresh temp dir for each test.

    Use this fixture when you need a project generated from an old commit
    that you want to update to a newer version.

    Note: Excludes .venv to avoid stale Python interpreter issues.
    """
    dest = tmp_path / "test-project"
    _copy_project_without_venv(old_version_project_cache, dest)
    return dest


@pytest.fixture
def head_project(head_project_cache: Path, tmp_path: Path) -> Path:
    """
    Copy cached HEAD project to fresh temp dir for each test.

    Use this fixture when you need a project at the current version.

    Note: Excludes .venv to avoid stale Python interpreter issues.
    """
    dest = tmp_path / "test-project"
    _copy_project_without_venv(head_project_cache, dest)
    return dest
