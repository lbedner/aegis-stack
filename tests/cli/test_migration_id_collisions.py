"""A project that writes its own migration still takes template revisions.

#1023: sector-7g authored ``003_schema_fix`` and the template shipped its
own ``003``; two revisions claimed the id, the chain forked, and the
startup runner gave up with "Requested revision 003 overlaps with other
requested revisions". Revisions are derived inside the project now, so
this asserts the property the ticket asked for: after an add, every id is
unique, every parent resolves, and the history is one line with one head.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from .conftest import ProjectFactory
from .test_utils import revision_chain, revision_head, run_aegis_command

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

    before = revision_chain(versions)
    project_head = revision_head(before)
    # What `make migrate-fix` writes, and what sector-7g had: the next
    # sequence number, authored by the project rather than the template.
    own_id = f"{max(int(r) for r in before if r.isdigit()) + 1:03d}"
    (versions / f"{own_id}_schema_fix.py").write_text(
        PROJECT_AUTHORED.format(rev=own_id, down=project_head)
    )
    # Committed like a real one: add-service refuses a dirty tree, since it
    # resets to the last commit when an add fails.
    for git in (["add", "-A"], ["commit", "-qm", "project-authored schema fix"]):
        subprocess.run(["git", *git], cwd=project_path, check=True, capture_output=True)

    result = run_aegis_command(
        "add-service", "auth", "--project-path", str(project_path), "--yes"
    )
    assert result.returncode == 0, f"add-service failed: {result.stderr}"

    after = revision_chain(versions)
    assert len(after) > len(before) + 1, "no revision was delivered"
    # Every parent resolves, and the project's own revision is still in the
    # line rather than orphaned beside a template revision of the same id.
    for revision, down in after.items():
        assert down is None or down in after, (
            f"{revision} points at {down!r}, which no revision declares"
        )
    assert own_id in after
    revision_head(after)
