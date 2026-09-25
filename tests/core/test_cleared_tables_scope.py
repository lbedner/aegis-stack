"""An AI migration empties the LLM catalog only when it changes it.

``AI_MIGRATION.cleared_tables`` exists for the one revision that added a
required column the old catalog rows could not supply. It was prepended to
EVERY generated ``NNN_ai.py``, so adding voice (new tables only) wiped the
synced deployments and prices, and usage costs read zero (#1259, found in
aegis-steward).
"""

from __future__ import annotations

from pathlib import Path

from aegis.core.migration_generator import _place_data_statements

HEADER = '''"""ai

Revision ID: 041
Revises: 040
"""
from alembic import op
import sqlalchemy as sa

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
'''
FOOTER = """

def downgrade() -> None:
    pass
"""


def _place(tmp_path: Path, body: str) -> str:
    revision = tmp_path / "041_ai.py"
    revision.write_text(HEADER + body + FOOTER)
    _place_data_statements(tmp_path, ["ai"], [revision])
    return revision.read_text()


def test_a_revision_that_only_adds_tables_keeps_the_catalog(tmp_path: Path) -> None:
    out = _place(
        tmp_path,
        """    op.create_table(
        "voice_usage",
        sa.Column("id", sa.Integer(), nullable=False),
    )
""",
    )

    assert "DELETE FROM" not in out


def test_a_revision_that_alters_a_catalog_table_clears_that_table(
    tmp_path: Path,
) -> None:
    out = _place(
        tmp_path,
        """    with op.batch_alter_table("llm_price", schema=None) as batch_op:
        batch_op.add_column(sa.Column("org_id", sa.Integer(), nullable=False))
""",
    )

    assert "DELETE FROM llm_price" in out
    assert "DELETE FROM llm_deployment" not in out
    assert out.index("DELETE FROM llm_price") < out.index("batch_alter_table")
