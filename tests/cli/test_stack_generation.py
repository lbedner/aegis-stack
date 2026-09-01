"""
Stack Generation Matrix Tests for Aegis Stack CLI.

This module tests all valid component combinations to ensure every possible
stack configuration generates successfully and produces valid project structures.

Test Matrix:
1. base                       (backend + frontend only)
2. base + scheduler           (APScheduler component)
3. base + worker              (Redis + arq workers; covers redis component transitively)
4. base + worker + scheduler  (full processing stack)
5. service rows (auth_basic, auth_org, ai_service, insights, payment, blog, comms)
   each pair the service with the components it needs (database, scheduler,
   etc.), so the database component is exercised through the service rows
   rather than as its own row.
6. everything                 (kitchen sink)

Each combination must:
- Generate without errors
- Create correct file structure
- Include proper dependencies
- Generate valid Docker configuration
- Pass basic validation checks
"""

from typing import Any

import pytest

from .test_utils import (
    validate_docker_compose,
    validate_project_structure,
    validate_pyproject_dependencies,
)

pytestmark = pytest.mark.xdist_group("generated_stacks")


class StackCombination:
    """Represents a stack component combination for testing."""

    def __init__(
        self,
        name: str,
        components: list[str],
        description: str,
        expected_files: list[str],
        expected_docker_services: list[str],
        expected_pyproject_deps: list[str],
        services: list[str] | None = None,
    ):
        self.name = name
        self.components = components
        self.services = services or []
        self.description = description
        self.expected_files = expected_files
        self.expected_docker_services = expected_docker_services
        self.expected_pyproject_deps = expected_pyproject_deps

    @property
    def components_str(self) -> str:
        """Get components as comma-separated string for CLI."""
        return ",".join(self.components) if self.components else ""

    @property
    def project_name(self) -> str:
        """Get project name for this combination."""
        return f"test-{self.name}"

    @property
    def project_slug(self) -> str:
        """Get installed-script slug (``aegis init`` hyphenates underscores).

        Combinations named with underscores (``auth_basic``, ``ai_service``)
        produce ``test-auth_basic`` as a raw name, but the generated project's
        ``[project.scripts]`` entry — and therefore the ``uv run <name>`` CLI
        invocation — uses the hyphenated form (``test-auth-basic``). Tests
        that spawn the installed script must use this property; tests that
        refer to the raw name (e.g. as an ``aegis init`` argument) use
        ``project_name``.
        """
        return self.project_name.replace("_", "-")


# Define all valid stack combinations
STACK_COMBINATIONS = [
    StackCombination(
        name="base",
        components=[],
        description="Base stack with backend and frontend only",
        expected_files=[
            "app/components/backend/",
            "app/components/frontend/",
            "app/entrypoints/webserver.py",
            "docker-compose.yml",
            "pyproject.toml",
            "Makefile",
        ],
        expected_docker_services=["webserver"],
        expected_pyproject_deps=["fastapi", "flet", "uvicorn"],
    ),
    # ``redis`` stack dropped from the matrix — ``worker`` and ``full`` both
    # pull redis transitively, so a redis-only row added no unique coverage.
    # The ``base_with_redis`` cache entry in conftest.py is still used by
    # tests/cli/test_add_worker.py, so it stays.
    StackCombination(
        name="scheduler",
        components=["scheduler"],
        description="Base stack with scheduler (APScheduler only, no Redis)",
        expected_files=[
            "app/components/backend/",
            "app/components/frontend/",
            "app/components/scheduler/",
            "app/entrypoints/webserver.py",
            "app/entrypoints/scheduler.py",
            "docker-compose.yml",
        ],
        expected_docker_services=["webserver", "scheduler"],
        expected_pyproject_deps=["fastapi", "flet", "apscheduler"],
    ),
    StackCombination(
        name="worker",
        components=["worker"],
        description="Base stack with worker queues (includes Redis)",
        expected_files=[
            "app/components/backend/",
            "app/components/frontend/",
            "app/components/worker/",
            "app/entrypoints/webserver.py",
            "docker-compose.yml",
        ],
        expected_docker_services=[
            "webserver",
            "redis",
            "worker-system",
            "worker-load-test",
        ],
        expected_pyproject_deps=["fastapi", "flet", "arq", "redis"],
    ),
    StackCombination(
        name="full",
        components=["worker", "scheduler"],
        description="Full processing stack with both worker and scheduler",
        expected_files=[
            "app/components/backend/",
            "app/components/frontend/",
            "app/components/worker/",
            "app/components/scheduler/",
            "app/entrypoints/webserver.py",
            "app/entrypoints/scheduler.py",
            "docker-compose.yml",
        ],
        expected_docker_services=[
            "webserver",
            "redis",
            "scheduler",
            "worker-system",
            "worker-load-test",
        ],
        expected_pyproject_deps=["fastapi", "flet", "arq", "apscheduler", "redis"],
    ),
    # ``database`` stack dropped from the matrix — every service-with-database
    # row (auth_org, ai_service, insights, payment, blog) already exercises the
    # database component end-to-end. The ``base_with_database`` cache entry
    # in conftest.py is still used by 6 other test files, so it stays.
    #
    # NOTE: the matrix build step runs each generated project's ``make check``,
    # and postgres-engine projects (plain ``database[postgres]`` or
    # ``database[neon]``) cannot run their full test suite without a live
    # database server — app-startup/health tests connect to postgres, which is
    # not running in CI. That is why every matrix row uses the sqlite engine.
    # Neon generation/config/compose is covered by ``TestNeonConfiguration`` in
    # tests/cli/test_database_config.py; lint+typecheck of the generated Neon
    # code is verified separately (it needs no database).
    StackCombination(
        name="auth_basic",
        components=[],
        services=["auth"],
        description="Auth service only (smallest auth slice)",
        expected_files=[
            "app/services/auth/",
            "app/components/backend/api/auth/",
        ],
        expected_docker_services=["webserver"],
        expected_pyproject_deps=["fastapi", "flet"],
    ),
    StackCombination(
        name="auth_org",
        components=["database"],
        services=["auth[org]"],
        description="Auth with org/RBAC level + database",
        expected_files=[
            "app/services/auth/",
            "app/core/db.py",
            "app/models/org.py",
            "app/services/auth/org_service.py",
        ],
        expected_docker_services=["webserver"],
        expected_pyproject_deps=["fastapi", "flet", "sqlmodel"],
    ),
    StackCombination(
        name="ai_service",
        components=["database"],
        services=["ai[sqlite]"],
        description="AI service with sqlite backend + database",
        expected_files=[
            "app/services/ai/",
            "app/core/db.py",
        ],
        expected_docker_services=["webserver"],
        expected_pyproject_deps=["fastapi", "flet", "pydantic-ai"],
    ),
    StackCombination(
        name="insights",
        components=["database", "scheduler"],
        services=["insights"],
        description="Insights service + database + scheduler",
        expected_files=[
            "app/services/insights/",
            "app/core/db.py",
            "app/components/scheduler/",
        ],
        expected_docker_services=["webserver", "scheduler"],
        expected_pyproject_deps=["fastapi", "flet", "apscheduler"],
    ),
    StackCombination(
        name="insights_per_user",
        components=["database", "scheduler"],
        services=["auth[org]", "insights[per_user]"],
        description="Per-user insights: auth[org] + Project model + project_id FKs",
        expected_files=[
            "app/services/insights/",
            "app/services/insights/project_service.py",
            "app/services/auth/",
            "app/core/db.py",
            "app/core/encryption.py",
            "app/components/scheduler/",
        ],
        expected_docker_services=["webserver", "scheduler"],
        expected_pyproject_deps=["fastapi", "flet", "apscheduler"],
    ),
    StackCombination(
        name="payment",
        components=["database"],
        services=["payment"],
        description="Payment service (Stripe) + database",
        expected_files=[
            "app/services/payment/",
            "app/core/db.py",
        ],
        expected_docker_services=["webserver"],
        expected_pyproject_deps=["fastapi", "flet", "stripe"],
    ),
    StackCombination(
        name="blog",
        components=["database"],
        services=["blog"],
        description="Blog service + database",
        expected_files=[
            "app/services/blog/",
            "app/components/backend/api/blog/",
            "app/core/db.py",
        ],
        expected_docker_services=["webserver"],
        expected_pyproject_deps=["fastapi", "flet", "sqlmodel"],
    ),
    StackCombination(
        name="documents",
        components=["database"],
        services=["documents"],
        description="Document store service + database",
        expected_files=[
            "app/services/documents/",
            "app/components/backend/api/documents/",
            "app/core/storage.py",
            "app/core/db.py",
        ],
        expected_docker_services=["webserver"],
        expected_pyproject_deps=["fastapi", "flet", "sqlmodel", "alembic"],
    ),
    StackCombination(
        name="finance",
        # Finance requires database + scheduler; auth is optional (owner FK
        # via finance_auth_link when present). This row proves standalone.
        components=["database", "scheduler"],
        services=["finance"],
        description="Finance service + database + scheduler (standalone)",
        expected_files=[
            "app/services/finance/",
            "app/core/db.py",
            "app/components/scheduler/",
        ],
        expected_docker_services=["webserver", "scheduler"],
        expected_pyproject_deps=["fastapi", "flet", "sqlmodel"],
    ),
    StackCombination(
        name="finance_auth",
        # The owner-scoped half of finance. With auth present the finance
        # router's ``get_owner_user_id`` resolves through
        # ``get_current_active_user``, so every route both authenticates and
        # filters rows by owner — a path the standalone ``finance`` row above
        # (owner is always ``None``) cannot reach. This row exists because the
        # generated finance endpoint tests once 401'd in every auth stack
        # while the matrix stayed green.
        components=["database", "scheduler"],
        services=["auth", "finance"],
        description="Finance service + auth (owner-scoped) + database + scheduler",
        expected_files=[
            "app/services/finance/",
            "app/services/auth/",
            "app/core/db.py",
            "app/components/scheduler/",
        ],
        expected_docker_services=["webserver", "scheduler"],
        expected_pyproject_deps=["fastapi", "flet", "sqlmodel"],
    ),
    StackCombination(
        name="comms",
        components=[],
        services=["comms"],
        description="Communications service (Twilio/SendGrid) only",
        expected_files=[
            "app/services/comms/",
        ],
        expected_docker_services=["webserver"],
        expected_pyproject_deps=["fastapi", "flet"],
    ),
    # htmx rows. Every one asserts BOTH frontends and BOTH of their deps: the
    # htmx frontend is additive, so a stack that ships it and loses the Flet
    # dashboard is the failure these rows exist to catch.
    StackCombination(
        name="base_htmx",
        components=["htmx"],
        description="htmx web frontend alongside the core Flet dashboard",
        expected_files=[
            "app/components/web_frontend/main.py",
            "app/components/web_frontend/templates/pages/landing.html",
            "app/components/frontend/main.py",
            "package.json",
            "tailwind.config.js",
        ],
        expected_docker_services=["webserver"],
        expected_pyproject_deps=["fastapi", "flet", "jinja2"],
    ),
    StackCombination(
        name="htmx_auth",
        components=["htmx", "database"],
        services=["auth"],
        description="htmx web frontend with the auth service (auth pages)",
        expected_files=[
            "app/components/web_frontend/templates/pages/auth/login.html",
            "app/components/web_frontend/static/js/auth.js",
            "app/components/frontend/main.py",
            "app/services/auth/",
        ],
        expected_docker_services=["webserver"],
        expected_pyproject_deps=["fastapi", "flet", "jinja2", "sqlmodel"],
    ),
    StackCombination(
        name="htmx_with_components",
        components=["htmx", "database", "worker", "redis"],
        description="htmx web frontend beside background processing infra",
        expected_files=[
            "app/components/web_frontend/main.py",
            "app/components/frontend/main.py",
            "app/components/worker/",
            "app/core/db.py",
        ],
        expected_docker_services=["webserver", "redis", "worker-system"],
        expected_pyproject_deps=["fastapi", "flet", "jinja2", "redis"],
    ),
    StackCombination(
        name="everything",
        components=["database", "scheduler", "worker", "redis"],
        services=["auth[org]", "ai[sqlite]", "insights", "payment", "blog", "comms"],
        description="Kitchen sink: all services + all processing infra",
        expected_files=[
            "app/services/auth/",
            "app/services/ai/",
            "app/services/insights/",
            "app/services/payment/",
            "app/services/blog/",
            "app/services/comms/",
            "app/core/db.py",
            "app/components/scheduler/",
            "app/components/worker/",
        ],
        expected_docker_services=[
            "webserver",
            "redis",
            "scheduler",
            "worker-system",
        ],
        expected_pyproject_deps=[
            "fastapi",
            "flet",
            "sqlmodel",
            "stripe",
            "apscheduler",
            "arq",
            "redis",
        ],
    ),
]


@pytest.mark.parametrize("combination", STACK_COMBINATIONS, ids=lambda x: x.name)
def test_stack_generation_matrix(
    combination: StackCombination,
    get_generated_stack: Any,
) -> None:
    """Test generation of each valid stack combination."""
    # Get the pre-generated stack
    _, result = get_generated_stack(combination.name)

    # Assert generation succeeded (this was already validated during session setup)
    assert result.success, (
        f"Failed to generate {combination.description}\n"
        f"Return code: {result.returncode}\n"
        f"STDOUT: {result.stdout}\n"
        f"STDERR: {result.stderr}"
    )

    # Assert project directory was created
    assert result.project_path.exists(), (
        f"Project directory not created: {result.project_path}"
    )
    assert result.project_path.is_dir(), (
        f"Project path is not a directory: {result.project_path}"
    )


@pytest.mark.parametrize("combination", STACK_COMBINATIONS, ids=lambda x: x.name)
def test_stack_file_structure(
    combination: StackCombination,
    get_generated_stack: Any,
) -> None:
    """Test that each stack has the correct file structure."""
    # Get the pre-generated stack
    _, result = get_generated_stack(combination.name)

    assert result.success, f"Failed to generate {combination.description}"

    # Validate file structure
    missing_files = validate_project_structure(
        result.project_path, combination.expected_files
    )
    assert not missing_files, (
        f"Missing expected files in {combination.description}:\n"
        + "\n".join(f"  - {file}" for file in missing_files)
    )


@pytest.mark.parametrize("combination", STACK_COMBINATIONS, ids=lambda x: x.name)
def test_stack_docker_configuration(
    combination: StackCombination,
    get_generated_stack: Any,
) -> None:
    """Test that each stack has correct Docker Compose configuration."""
    # Get the pre-generated stack
    _, result = get_generated_stack(combination.name)

    assert result.success, f"Failed to generate {combination.description}"

    # Validate Docker Compose services
    missing_services = validate_docker_compose(
        result.project_path, combination.expected_docker_services
    )
    assert not missing_services, (
        f"Docker Compose issues in {combination.description}:\n"
        + "\n".join(f"  - {issue}" for issue in missing_services)
    )


@pytest.mark.parametrize("combination", STACK_COMBINATIONS, ids=lambda x: x.name)
def test_stack_dependencies(
    combination: StackCombination,
    get_generated_stack: Any,
) -> None:
    """Test that each stack has correct Python dependencies."""
    # Get the pre-generated stack
    _, result = get_generated_stack(combination.name)

    assert result.success, f"Failed to generate {combination.description}"

    # Validate dependencies
    missing_deps = validate_pyproject_dependencies(
        result.project_path, combination.expected_pyproject_deps
    )
    assert not missing_deps, (
        f"Missing dependencies in {combination.description}:\n"
        + "\n".join(f"  - {dep}" for dep in missing_deps)
    )


def test_stack_combinations_comprehensive() -> None:
    """Test that we're covering all expected component combinations."""
    # Verify we have tests for basic patterns
    combination_names = {combo.name for combo in STACK_COMBINATIONS}

    # ``must_have`` pins the minimum matrix (component stacks + per-service
    # slices + kitchen sink). New combos can be added without breaking the
    # assertion, but removing any of these is a deliberate regression.
    # ``redis`` and ``database`` were intentionally dropped — both are
    # exercised transitively by larger rows (worker pulls redis; every
    # service-with-database row pulls database), so dedicated rows for
    # them only added pipeline-execution cost without unique coverage.
    must_have = {
        "base",
        "scheduler",
        "worker",
        "full",
        "auth_basic",
        "auth_org",
        "ai_service",
        "insights",
        "payment",
        "blog",
        "finance",
        "finance_auth",
        "comms",
        # The two htmx slices worth localizing: the frontend on its own, and
        # the frontend with auth (which is what pulls in the auth pages and
        # the auth JS). ``everything`` covers both transitively, but a focused
        # row says which half broke.
        "base_htmx",
        "htmx_auth",
        "everything",
    }
    missing = must_have - combination_names
    assert not missing, (
        f"Matrix missing required combinations: {missing}. Got: {combination_names}"
    )


def test_component_dependency_resolution() -> None:
    """Test that component dependencies are properly resolved."""
    # Worker should automatically include Redis
    worker_combo = next(c for c in STACK_COMBINATIONS if c.name == "worker")
    assert "redis" in worker_combo.expected_docker_services
    assert "redis" in worker_combo.expected_pyproject_deps

    # Scheduler should run standalone
    scheduler_combo = next(c for c in STACK_COMBINATIONS if c.name == "scheduler")
    assert "redis" not in scheduler_combo.expected_docker_services
    assert "redis" not in scheduler_combo.expected_pyproject_deps
    assert "apscheduler" in scheduler_combo.expected_pyproject_deps

    # Full stack should have both worker and scheduler capabilities
    full_combo = next(c for c in STACK_COMBINATIONS if c.name == "full")
    assert "worker-system" in full_combo.expected_docker_services
    assert "scheduler" in full_combo.expected_docker_services
    assert "arq" in full_combo.expected_pyproject_deps
    assert "apscheduler" in full_combo.expected_pyproject_deps


@pytest.mark.integration
def test_stack_generation_output_messages(get_generated_stack: Any) -> None:
    """Test that CLI provides helpful output messages during generation."""
    # Get the worker stack to check output messages
    _, result = get_generated_stack("worker")

    assert result.success

    # Should mention component inclusion
    assert "worker" in result.stdout.lower() or "worker" in result.stderr.lower()

    # Should indicate success
    success_indicators = ["✅", "success", "complete", "created"]
    output_text = (result.stdout + result.stderr).lower()
    assert any(indicator in output_text for indicator in success_indicators)
