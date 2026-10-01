"""Regression guard: a Postgres-backed scheduler must ship runnable migrations.

The stack matrix is all-SQLite (which uses ``SQLModel.metadata.create_all`` and
never calls the startup ``_run_migrations`` path), so it never exercises a
Postgres scheduler stack actually running its schema-qualified migration. These
tests assert the three pieces that path needs at runtime, each of which was
missing at some point because "needs migrations" was computed from services
only, never the scheduler:

1. ``alembic`` as a runtime dependency (otherwise ``from alembic import
   command`` resolves to the project's local ``alembic/`` directory and the
   migration runner crashes).
2. the alembic environment (``env.py`` + ``alembic.ini``) surviving the
   post-generation cleanup that removes ``alembic/`` when nothing needs it.
3. the generated, schema-qualified scheduler migration itself.
"""

from pathlib import Path

from .conftest import ProjectFactory
from .test_utils import run_aegis_command


def test_postgres_scheduler_ships_runnable_migrations(
    temp_output_dir: Path,
) -> None:
    result = run_aegis_command(
        "init",
        "schedpg",
        "--components",
        "scheduler[postgres]",
        "--output-dir",
        str(temp_output_dir),
        "--no-interactive",
        "--yes",
    )
    assert result.returncode == 0, f"init failed: {result.stderr}"

    project = temp_output_dir / "schedpg"
    answers = (project / ".copier-answers.yml").read_text()
    assert "scheduler_backend: postgres" in answers

    # 1. alembic must be a runtime dependency.
    assert "alembic==" in (project / "pyproject.toml").read_text(), (
        "Postgres scheduler stack must depend on alembic to run migrations"
    )

    # 2. the alembic environment must survive post-generation cleanup.
    assert (project / "alembic" / "env.py").exists(), "alembic/env.py missing"
    assert (project / "alembic" / "alembic.ini").exists(), "alembic.ini missing"

    # 3. the schema-qualified scheduler migration must be generated.
    migrations = list((project / "alembic" / "versions").glob("*_scheduler.py"))
    assert len(migrations) == 1, "expected exactly one scheduler migration"
    content = migrations[0].read_text()
    assert 'CREATE SCHEMA IF NOT EXISTS "scheduler"' in content
    # post-generation `ruff --fix` may normalise quote style
    assert ('schema="scheduler"' in content) or ("schema='scheduler'" in content)


def test_sqlite_scheduler_ships_an_unqualified_migration(
    temp_output_dir: Path,
) -> None:
    """A SQLite scheduler versions its tables like everything else.

    Revisions come from the models, and the models drop the ``scheduler``
    schema on SQLite, so there is nothing left that only Postgres can run.
    """
    result = run_aegis_command(
        "init",
        "schedlite",
        "--components",
        "scheduler[sqlite]",
        "--output-dir",
        str(temp_output_dir),
        "--no-interactive",
        "--yes",
    )
    assert result.returncode == 0, f"init failed: {result.stderr}"

    project = temp_output_dir / "schedlite"
    assert "alembic==" in (project / "pyproject.toml").read_text()
    migrations = list((project / "alembic" / "versions").glob("*_scheduler.py"))
    assert len(migrations) == 1, "expected exactly one scheduler migration"
    content = migrations[0].read_text()
    assert "job_execution" in content
    assert "CREATE SCHEMA" not in content
    assert "scheduler" not in content.split("def upgrade")[1].replace(
        "apscheduler_jobs", ""
    ).replace("ix_apscheduler", ""), "SQLite has no schemas to qualify with"


def test_adding_a_sqlite_scheduler_versions_it_like_init(
    project_factory: ProjectFactory,
) -> None:
    """``aegis add scheduler --backend sqlite`` wrote no revision (only
    Postgres got one), so a project that gained the scheduler later had
    tables no revision describes and failed its own drift check, where the
    same stack from ``init`` passed."""
    project = project_factory("base_with_database")

    result = run_aegis_command(
        "add",
        "scheduler",
        "--backend",
        "sqlite",
        "--project-path",
        str(project),
        "--yes",
    )
    assert result.returncode == 0, f"add failed: {result.stderr}"

    migrations = list((project / "alembic" / "versions").glob("*_scheduler.py"))
    assert len(migrations) == 1, "expected exactly one scheduler migration"
    assert "job_execution" in migrations[0].read_text()
