"""
Pytest configuration for CLI integration tests.
"""

import hashlib
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Generator, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from filelock import FileLock

from aegis.core.copier_manager import generate_with_copier
from aegis.core.template_generator import TemplateGenerator

from .test_stack_generation import STACK_COMBINATIONS, StackCombination
from .test_utils import CLITestResult, run_aegis_init

# Type alias for project_factory fixture
ProjectFactory = Callable[..., Path]

# PostgreSQL test configuration (password can be overridden via environment)
POSTGRES_TEST_PASSWORD = os.environ.get("POSTGRES_TEST_PASSWORD", "postgres")


@pytest.fixture(scope="session")
def cli_test_timeout() -> int:
    """Default timeout for CLI commands."""
    return 60  # seconds


@pytest.fixture
def temp_output_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test project generation.

    ``ignore_cleanup_errors`` papers over a known CI race: copier
    shallow-clones aegis-stack into the tempdir, and git can still be
    holding handles in ``.git/objects/`` when pytest tries to rmtree.
    The OS reaps the dir eventually; we don't want the test to fail.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        yield Path(temp_dir)


@pytest.fixture(scope="session")
def session_temp_dir() -> Generator[Path, None, None]:
    """Create a session-scoped temporary directory for shared stack generation."""
    with tempfile.TemporaryDirectory(
        prefix="aegis-test-session-", ignore_cleanup_errors=True
    ) as temp_dir:
        yield Path(temp_dir)


@dataclass(frozen=True)
class ProjectTemplateSpec:
    """Normalized spec used for caching generated projects."""

    components: tuple[str, ...] = ()
    scheduler_backend: str = "memory"
    services: tuple[str, ...] = ()


NAMED_PROJECT_SPECS: dict[str, ProjectTemplateSpec] = {
    "base": ProjectTemplateSpec(),
    "base_with_database": ProjectTemplateSpec(components=("database",)),
    "base_with_database_postgres": ProjectTemplateSpec(
        components=("database[postgres]",)
    ),
    # Neon = postgres provider; dev uses the same local container, prod is cloud.
    "base_with_database_neon": ProjectTemplateSpec(components=("database[neon]",)),
    # Neon + auth (migration-needing, so alembic/ is generated) + ingress (the
    # .env.deploy.example production template is gated on ingress). Exercises the
    # full Neon production surface: direct migration URL and cloud deploy URLs.
    "neon_full": ProjectTemplateSpec(
        components=("database[neon]", "ingress"), services=("auth",)
    ),
    "base_with_scheduler": ProjectTemplateSpec(components=("scheduler",)),
    "base_with_scheduler_sqlite": ProjectTemplateSpec(
        components=("database", "scheduler"), scheduler_backend="sqlite"
    ),
    "base_with_worker": ProjectTemplateSpec(components=("worker",)),
    "base_with_worker_taskiq": ProjectTemplateSpec(components=("worker[taskiq]",)),
    "base_with_worker_dramatiq": ProjectTemplateSpec(components=("worker[dramatiq]",)),
    "base_with_redis": ProjectTemplateSpec(components=("redis",)),
    "scheduler_and_database": ProjectTemplateSpec(components=("database", "scheduler")),
    "base_with_auth_service": ProjectTemplateSpec(services=("auth",)),
    "base_with_ai_service": ProjectTemplateSpec(services=("ai",)),
    "base_with_ai_sqlite_service": ProjectTemplateSpec(services=("ai[sqlite]",)),
    # AI with the option-gated rag + voice extras enabled — used to verify
    # `aegis remove ai` deletes the full footprint, not just the add base.
    "ai_with_rag_voice": ProjectTemplateSpec(
        components=("database",), services=("ai[sqlite,rag,voice]",)
    ),
    "base_with_auth_and_ai_services": ProjectTemplateSpec(services=("auth", "ai")),
    # Full-stack matrix entries (mirror STACK_COMBINATIONS service rows so
    # ``make test-stacks-build`` doesn't pay a 30-40s regeneration cost
    # per slow test — per ``tests/CLAUDE.md``, every new stack MUST have
    # a cache entry or the matrix explodes past 10 minutes.
    "auth_basic": ProjectTemplateSpec(services=("auth",)),
    "auth_org_with_database": ProjectTemplateSpec(
        components=("database",), services=("auth[org]",)
    ),
    "ai_with_database": ProjectTemplateSpec(
        components=("database",), services=("ai[sqlite]",)
    ),
    "insights_full": ProjectTemplateSpec(
        components=("database", "scheduler"), services=("insights",)
    ),
    "insights_per_user": ProjectTemplateSpec(
        components=("database", "scheduler"),
        services=("auth[org]", "insights[per_user]"),
    ),
    "payment_with_database": ProjectTemplateSpec(
        components=("database",), services=("payment",)
    ),
    "blog_with_database": ProjectTemplateSpec(
        components=("database",), services=("blog",)
    ),
    "finance_with_database": ProjectTemplateSpec(
        components=("database", "scheduler"), services=("finance",)
    ),
    # Finance + auth: owner-scoped finance, where the router's
    # ``get_owner_user_id`` resolves through the authenticated user.
    "finance_auth": ProjectTemplateSpec(
        components=("database", "scheduler"), services=("auth", "finance")
    ),
    "comms_only": ProjectTemplateSpec(services=("comms",)),
    # htmx web frontend. The Flet frontend is CORE and still present in both:
    # htmx is additive, so these stacks have two frontends.
    "base_htmx": ProjectTemplateSpec(components=("htmx",)),
    "htmx_auth": ProjectTemplateSpec(
        components=("htmx", "database"), services=("auth",)
    ),
    "everything": ProjectTemplateSpec(
        components=("database", "scheduler", "worker", "redis", "htmx"),
        services=("auth[org]", "ai[sqlite]", "insights", "payment", "blog", "comms"),
    ),
}


@pytest.fixture(scope="session")
def project_template_cache(
    tmp_path_factory: pytest.TempPathFactory,
) -> Callable[[ProjectTemplateSpec], Path]:
    """
    Generate reusable project skeletons once per test session, shared across xdist workers.

    Cache root selection:
      - Under xdist, ``tmp_path_factory.getbasetemp()`` is per-worker
        (``.../pytest-N/popen-gw0``), so we climb to its parent
        (``.../pytest-N``) which is per-session and shared across workers.
        Result: 16 workers, 1 cache build per spec instead of 16.
      - Without xdist, ``getbasetemp()`` is already per-session and not
        shared with anyone, so we use it directly. We DO NOT use
        ``getbasetemp().parent`` outside xdist — that's
        ``/tmp/pytest-of-<user>/``, persisted across runs and branch
        checkouts, which would serve stale projects after template edits.

    Atomic generation: write to a sibling temp dir, then rename onto the
    final target only on success. A partial directory after a crash will
    never be mistaken for a valid cache entry.
    """
    if os.environ.get("PYTEST_XDIST_WORKER"):
        shared_root = tmp_path_factory.getbasetemp().parent / "aegis-shared-cache"
    else:
        shared_root = tmp_path_factory.getbasetemp() / "aegis-shared-cache"
    shared_root.mkdir(exist_ok=True)
    in_memory: dict[ProjectTemplateSpec, Path] = {}

    def get_project(spec: ProjectTemplateSpec) -> Path:
        if spec in in_memory:
            return in_memory[spec]
        spec_hash = hashlib.sha1(repr(spec).encode("utf-8")).hexdigest()[:10]
        project_name = f"cached-{spec_hash}"
        target = shared_root / project_name
        # Lock per-spec so concurrent workers don't both build the same project;
        # workers wanting different specs proceed in parallel.
        with FileLock(str(shared_root / f"{project_name}.lock")):
            if not target.exists():
                staging_parent = Path(
                    tempfile.mkdtemp(prefix=f"{project_name}.staging-", dir=shared_root)
                )
                try:
                    template_gen = TemplateGenerator(
                        project_name=project_name,
                        selected_components=list(spec.components),
                        scheduler_backend=spec.scheduler_backend,
                        selected_services=list(spec.services),
                    )
                    generate_with_copier(template_gen, staging_parent, dev_mode=True)
                    staged = staging_parent / project_name
                    if not staged.exists():
                        raise FileNotFoundError(
                            f"Generated project not found at expected staging path: {staged}"
                        )
                    # Pack the repo BEFORE publish: generation's git commit
                    # can leave (or detach) a ``git gc`` that deletes loose
                    # .git/objects/* dirs after the cache goes live, racing
                    # every concurrent copytree reader. A synchronous gc
                    # here leaves a stable, packed object store (and makes
                    # the per-test copies faster: fewer files).
                    subprocess.run(
                        ["git", "-c", "gc.autoDetach=false", "gc", "--quiet"],
                        cwd=staged,
                        capture_output=True,
                    )
                    # Atomic publish: rename only succeeds whole or not at all,
                    # so a partial project is never visible to other workers.
                    staged.rename(target)
                finally:
                    shutil.rmtree(staging_parent, ignore_errors=True)
        in_memory[spec] = target
        return target

    return get_project


@pytest.fixture
def project_factory(
    project_template_cache: Callable[[ProjectTemplateSpec], Path],
    temp_output_dir: Path,
) -> Callable[..., Path]:
    """
    Provide a helper that copies cached skeletons into the per-test temp directory.

    Supports either named specs (e.g., "base") or explicit component lists.
    """

    def _factory(
        name: str | None = None,
        *,
        components: Iterable[str] | None = None,
        scheduler_backend: str = "memory",
        services: Iterable[str] | None = None,
    ) -> Path:
        if name is not None:
            if name not in NAMED_PROJECT_SPECS:
                raise KeyError(
                    f"Project template '{name}' is not cached. "
                    f"Available templates: {list(NAMED_PROJECT_SPECS.keys())}"
                )
            spec = NAMED_PROJECT_SPECS[name]
        else:
            spec = ProjectTemplateSpec(
                components=tuple(components or ()),
                scheduler_backend=scheduler_backend,
                services=tuple(services or ()),
            )

        source = project_template_cache(spec)
        destination = temp_output_dir / source.name
        try:
            shutil.copytree(source, destination)
        except shutil.Error:
            # Residual safety net for source churn mid-copy (a lingering
            # git gc in the cached repo): the churn settles in seconds,
            # so one clean retry is enough.
            shutil.rmtree(destination, ignore_errors=True)
            time.sleep(2)
            shutil.copytree(source, destination)
        return destination

    return _factory


@pytest.fixture(scope="session")
def generated_stacks(
    session_temp_dir: Path,
) -> Callable[[str], tuple[StackCombination, CLITestResult]]:
    """
    Lazily generate stack combinations, memoized for the session.

    Each combination is a full ``aegis init`` (render + uv sync + make fix +
    migrations), 10-40s apiece — the single most expensive fixture in the
    suite, and it grows with every matrix row (htmx, finance, ...). The old
    eager version built ALL combinations the moment any test touched the
    fixture, so a one-test run paid for the whole matrix. Now a stack is
    generated on first request and reused for the rest of the session; a full
    matrix run costs the same as before, a scoped run only pays for the
    stacks its tests actually use.

    Runs serially — ``run_aegis_init`` invokes the aegis CLI in-process via
    Typer's ``CliRunner``, so it shares module state, cwd, and copier caches
    (the ``generated_stacks`` xdist group pins all consumers to one worker).
    """
    stacks: dict[str, tuple[StackCombination, CLITestResult]] = {}
    combinations = {c.name: c for c in STACK_COMBINATIONS}

    def _get_or_generate(name: str) -> tuple[StackCombination, CLITestResult]:
        if name in stacks:
            return stacks[name]
        combination = combinations.get(name)
        if combination is None:
            raise KeyError(
                f"Stack '{name}' not found. Available: {sorted(combinations)}"
            )

        print(f"\n   - Generating {name} stack for session...")
        result = run_aegis_init(
            combination.project_name,
            combination.components,
            session_temp_dir,
            services=combination.services or None,
            dev=True,
        )
        if not result.success:
            raise RuntimeError(
                f"Failed to generate {name} stack for test session:\n"
                f"STDOUT: {result.stdout}\n"
                f"STDERR: {result.stderr}"
            )
        stacks[name] = (combination, result)
        return stacks[name]

    return _get_or_generate


@pytest.fixture
def get_generated_stack(
    generated_stacks: Callable[[str], tuple[StackCombination, CLITestResult]],
) -> Any:
    """Helper to get (lazily generating on first use) a stack by name."""
    return generated_stacks


# Database Runtime Testing Fixtures
# Following ee-toolset pattern for proper fixture-based testing


# PostgreSQL Runtime Testing Fixtures


@pytest.fixture(scope="session")
def generated_db_project_postgres(
    project_template_cache: Callable[[ProjectTemplateSpec], Path],
    session_temp_dir: Path,
) -> CLITestResult | None:
    """
    Get a cached PostgreSQL database project for runtime testing.

    Uses the project_template_cache for fast project generation.
    Returns None if PostgreSQL is not available.
    """
    import os
    import socket
    import subprocess
    import sys

    from .test_utils import CLITestResult, run_project_command

    # Check if PostgreSQL is available
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(("localhost", 5432))
        sock.close()
        if result != 0:
            print("PostgreSQL not available on localhost:5432, skipping setup")
            return None
    except Exception:
        print("Could not check PostgreSQL availability, skipping setup")
        return None

    # Create the test database in PostgreSQL
    db_name = "test-database-postgres-runtime"
    print(f"Creating PostgreSQL database: {db_name}")
    try:
        subprocess.run(
            [
                "psql",
                "-h",
                "localhost",
                "-U",
                "postgres",
                "-c",
                f'DROP DATABASE IF EXISTS "{db_name}"',
            ],
            capture_output=True,
            env={**dict(os.environ), "PGPASSWORD": POSTGRES_TEST_PASSWORD},
        )
        create_result = subprocess.run(
            [
                "psql",
                "-h",
                "localhost",
                "-U",
                "postgres",
                "-c",
                f'CREATE DATABASE "{db_name}"',
            ],
            capture_output=True,
            env={**dict(os.environ), "PGPASSWORD": POSTGRES_TEST_PASSWORD},
        )
        if create_result.returncode != 0:
            print(f"Failed to create database: {create_result.stderr.decode()}")
            return None
    except Exception as e:
        print(f"Could not create PostgreSQL database: {e}")
        return None

    # Get cached project and copy to session temp dir (exclude .venv - wrong Python version)
    print("Using cached PostgreSQL project template...")
    spec = NAMED_PROJECT_SPECS["base_with_database_postgres"]
    cached_project = project_template_cache(spec)
    project_path = session_temp_dir / "db-postgres-runtime"
    shutil.copytree(
        cached_project, project_path, ignore=shutil.ignore_patterns(".venv")
    )

    # Patch pyproject.toml to use current Python version (cached may have different version)
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    pyproject_path = project_path / "pyproject.toml"
    content = pyproject_path.read_text()
    import re

    content = re.sub(
        r'requires-python\s*=\s*"[^"]+"',
        f'requires-python = ">={python_version}"',
        content,
    )
    pyproject_path.write_text(content)

    # Update .python-version to match current Python (cached may have different version)
    python_version_file = project_path / ".python-version"
    python_version_file.write_text(f"{python_version}\n")

    # Install dependencies
    print("Installing dependencies in PostgreSQL project...")
    install_result = run_project_command(
        ["uv", "sync", "--extra", "dev", "--python", python_version],
        project_path,
        step_name="Install Dependencies",
        env_overrides={"VIRTUAL_ENV": ""},
    )

    if not install_result.success:
        raise RuntimeError(f"Failed to install dependencies: {install_result.stderr}")

    print("PostgreSQL database project ready for runtime testing!")
    return CLITestResult(
        returncode=0,
        stdout="",
        stderr="",
        project_path=project_path,
    )


# SQLite Runtime Testing Fixtures


@pytest.fixture(scope="session")
def generated_db_project(
    project_template_cache: Callable[[ProjectTemplateSpec], Path],
    session_temp_dir: Path,
) -> CLITestResult:
    """
    Get a cached SQLite database project for runtime testing.

    Uses the project_template_cache for fast project generation.
    """
    from .test_utils import CLITestResult, run_project_command

    # Get cached project and copy to session temp dir (exclude .venv - wrong Python version)
    print("Using cached SQLite project template...")
    spec = NAMED_PROJECT_SPECS["base_with_database"]
    cached_project = project_template_cache(spec)
    project_path = session_temp_dir / "db-sqlite-runtime"
    shutil.copytree(
        cached_project, project_path, ignore=shutil.ignore_patterns(".venv")
    )

    # Patch pyproject.toml to use current Python version (cached may have different version)
    import re
    import sys

    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    pyproject_path = project_path / "pyproject.toml"
    content = pyproject_path.read_text()
    content = re.sub(
        r'requires-python\s*=\s*"[^"]+"',
        f'requires-python = ">={python_version}"',
        content,
    )
    pyproject_path.write_text(content)

    # Update .python-version to match current Python (cached may have different version)
    python_version_file = project_path / ".python-version"
    python_version_file.write_text(f"{python_version}\n")

    # Install dependencies
    print("Installing dependencies in SQLite project...")
    install_result = run_project_command(
        ["uv", "sync", "--extra", "dev"],
        project_path,
        step_name="Install Dependencies",
        env_overrides={"VIRTUAL_ENV": ""},
    )

    if not install_result.success:
        raise RuntimeError(f"Failed to install dependencies: {install_result.stderr}")

    print("SQLite database project ready for runtime testing!")
    return CLITestResult(
        returncode=0,
        stdout="",
        stderr="",
        project_path=project_path,
    )
