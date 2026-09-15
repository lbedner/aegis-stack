"""The generated revisions and the generated models describe one schema.

Revisions are derived from the models by ``app/cli/migrate_gen.py`` inside
the generated project. This replays them onto a real Postgres, the engine
whose reflection is faithful and where the finance schema exists, and
asserts alembic's ``compare_metadata`` finds nothing either way. The
generated project's own ``tests/test_model_registry.py`` runs the same
check against a scratch SQLite on every stack; this is the Postgres oracle.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from .test_utils import run_project_command

pytestmark = [
    pytest.mark.slow,
    pytest.mark.postgres,
    pytest.mark.xdist_group("generated_stacks"),
]

STACKS = {
    "everything": (
        ["database[postgres]", "scheduler", "worker", "redis"],
        ["auth[org]", "ai[sqlite]", "insights", "payment", "blog", "comms"],
    ),
    "finance_auth": (["database[postgres]", "scheduler"], ["auth", "finance"]),
}

CREATE_DB = """
import os
from sqlalchemy import create_engine, text
db = os.environ["ORACLE_DB"]
admin = os.environ["ORACLE_ADMIN_URL"]
with create_engine(admin, isolation_level="AUTOCOMMIT").connect() as conn:
    conn.execute(text(f'DROP DATABASE IF EXISTS "{db}"'))
    conn.execute(text(f'CREATE DATABASE "{db}"'))
"""


def _postgres_available() -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex(("localhost", 5432)) == 0


@pytest.mark.parametrize("stack", sorted(STACKS))
def test_generated_revisions_rebuild_the_models_schema(
    project_factory, stack: str
) -> None:
    if not _postgres_available():
        pytest.skip("PostgreSQL not available on localhost:5432")
    components, services = STACKS[stack]
    project: Path = project_factory(components=components, services=services)
    # The cache copy carries a venv whose interpreter links are only valid
    # at the cache's own path; sync a fresh one here (as the db fixtures do).
    shutil.rmtree(project / ".venv", ignore_errors=True)
    sync = run_project_command(["uv", "sync"], project, timeout=600, step_name="sync")
    assert sync.success, sync.stderr[-800:]

    password = os.environ.get("POSTGRES_TEST_PASSWORD", "postgres")
    db = f"aegis-oracle-{stack}"
    url = f"postgresql://postgres:{password}@localhost:5432/{db}"
    env = {
        "VIRTUAL_ENV": "",
        "LOGFIRE_TOKEN": "",
        "DATABASE_URL": url,
        "DATABASE_URL_LOCAL": url,
        "ORACLE_DB": db,
        "ORACLE_ADMIN_URL": f"postgresql://postgres:{password}@localhost:5432/postgres",
    }
    created = run_project_command(
        ["uv", "run", "python", "-c", CREATE_DB],
        project,
        timeout=120,
        step_name="createdb",
        env_overrides=env,
    )
    assert created.success, created.stderr[-800:]

    check = run_project_command(
        ["uv", "run", "python", "-m", "app.cli.migrate_gen", "--check", "--url", url],
        project,
        timeout=600,
        step_name="oracle",
        env_overrides=env,
    )
    assert check.success, (
        f"{stack}: revisions do not rebuild the models\n"
        + check.stdout[-2000:]
        + check.stderr[-1500:]
    )
    assert json.loads(check.stdout.strip().splitlines()[-1]) == []
