"""A generated revision declares the object that proves it ran.

The startup hook re-adopts a persisted database by asking, per pending
revision, whether its proof object already exists - and stamping instead
of replaying DDL that would fail. That mapping used to live in a
hand-kept table keyed by service name, which the generator could silently
outgrow: revision bodies come from the models now, so the table a
revision creates first is no longer fixed by hand. A revision that
carries its own signature cannot drift from itself.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from .conftest import ProjectFactory
from .test_utils import run_aegis_command

pytestmark = pytest.mark.slow


def _signature(path: Path) -> tuple[str, ...] | None:
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign):
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == "aegis_stamp_signature":
                value = ast.literal_eval(node.value)
                return tuple(value) if value is not None else None
    return None


def test_a_generated_revision_carries_its_own_signature(
    project_factory: ProjectFactory,
) -> None:
    project_path = project_factory("base")
    result = run_aegis_command(
        "add-service", "auth", "--project-path", str(project_path), "--yes"
    )
    assert result.returncode == 0, f"add-service failed: {result.stderr}"

    revisions = sorted((project_path / "alembic" / "versions").glob("*_auth.py"))
    assert revisions, "no auth revision was written"
    signature = _signature(revisions[0])
    assert signature is not None, (
        f"{revisions[0].name} declares no aegis_stamp_signature; the startup "
        "hook would fall back to a hand-kept table to recover this revision"
    )
    # auth's revision creates the user table, so that is what proves it ran.
    assert signature[0] == "table"
    assert signature[1].split(".")[-1] == "user"
