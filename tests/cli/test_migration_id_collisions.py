"""A project that writes its own migration still takes template revisions.

#1023: sector-7g authored ``003_schema_fix`` and the template shipped its
own ``003``; two revisions claimed the id, the chain forked, and the
startup runner gave up with "Requested revision 003 overlaps with other
requested revisions". Revisions are derived inside the project now, so
this asserts the property the ticket asked for: after an add, every id is
unique, every parent resolves, and the history is one line with one head.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from .conftest import ProjectFactory
from .test_utils import run_aegis_command

pytestmark = pytest.mark.slow

PROJECT_AUTHORED = '''"""project-authored schema fix

Revision ID: {rev}
Revises: {down}

"""

from alembic import op  # noqa: F401

revision = "{rev}"
down_revision = "{down}"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
'''


def _chain(versions: Path) -> dict[str, str | None]:
    """revision -> down_revision for every file, ids asserted unique."""
    chain: dict[str, str | None] = {}
    for path in sorted(versions.glob("*.py")):
        if path.name.startswith("__"):
            continue
        module = ast.parse(path.read_text())
        found: dict[str, str | None] = {}
        for node in module.body:
            if not isinstance(node, ast.Assign):
                continue
            name = node.targets[0]
            if isinstance(name, ast.Name) and name.id in ("revision", "down_revision"):
                found[name.id] = ast.literal_eval(node.value)
        revision = found.get("revision")
        assert isinstance(revision, str), f"{path.name} declares no revision"
        assert revision not in chain, (
            f"{path.name} reuses revision id {revision!r} - the chain forks here"
        )
        chain[revision] = found.get("down_revision")
    return chain


def _head(chain: dict[str, str | None]) -> str:
    parents = {down for down in chain.values() if down is not None}
    heads = sorted(set(chain) - parents)
    assert len(heads) == 1, f"expected one head, found {heads}"
    return heads[0]


def test_the_template_ships_no_revision_files() -> None:
    """The other half of #1023: an update cannot deliver a colliding id if
    it delivers no revision files at all. Revisions are generated in the
    project, against its own history, so the template carries none."""
    versions = Path(
        "aegis/templates/copier-aegis-project/{{ project_slug }}/alembic/versions"
    )
    assert versions.is_dir()
    assert [p.name for p in versions.iterdir()] == [".gitkeep"]


def test_add_chains_onto_a_project_authored_revision(
    project_factory: ProjectFactory,
) -> None:
    project_path = project_factory("base_with_ai_sqlite_service")
    versions = project_path / "alembic" / "versions"

    before = _chain(versions)
    project_head = _head(before)
    # What `make migrate-fix` writes, and what sector-7g had: the next
    # sequence number, authored by the project rather than the template.
    own_id = f"{max(int(r) for r in before if r.isdigit()) + 1:03d}"
    (versions / f"{own_id}_schema_fix.py").write_text(
        PROJECT_AUTHORED.format(rev=own_id, down=project_head)
    )

    result = run_aegis_command(
        "add-service", "auth", "--project-path", str(project_path), "--yes"
    )
    assert result.returncode == 0, f"add-service failed: {result.stderr}"

    after = _chain(versions)
    assert len(after) > len(before) + 1, "no revision was delivered"
    # Every parent resolves, and the project's own revision is still in the
    # line rather than orphaned beside a template revision of the same id.
    for revision, down in after.items():
        assert down is None or down in after, (
            f"{revision} points at {down!r}, which no revision declares"
        )
    assert own_id in after
    _head(after)
