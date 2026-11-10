"""An ``alembic`` import sorts the same with or without ``alembic/``.

Ruff counts a top-level directory as first-party, and ``alembic/`` only
appears with a project's first migration. So ``aegis add scheduler`` on a
``database`` project re-sorted every module importing the alembic library
(``app/cli/migrate_*.py``, two tests) and left them failing I001: files
the add never wrote (aegis-stack#1424). The template's isort settings
must place ``alembic`` one way whether the directory exists or not.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from aegis.core.component_files import PROJECT_SLUG_PLACEHOLDER, get_template_path

# A module as the template writes one, and as a project with migrations
# (``alembic/`` present) has always had it sorted.
MODULE = """\
import re

from sqlalchemy import Column

from alembic import command
from app.cli.migrate_gen import _config

__all__ = ["Column", "_config", "command", "re"]
"""


def _isort_settings() -> str:
    """The template pyproject's isort table, which carries no Jinja."""
    text = (
        get_template_path() / PROJECT_SLUG_PLACEHOLDER / "pyproject.toml.jinja"
    ).read_text()
    start = text.index("[tool.ruff.lint.isort]")
    table = text[start : text.index("\n[", start + 1)]
    assert "{" not in table
    return table


def _sorted(project: Path) -> bool:
    ruff = Path(sys.executable).parent / "ruff"
    done = subprocess.run(
        [str(ruff), "check", "--select", "I", "--no-cache", "mod.py"],
        cwd=project,
        capture_output=True,
        text=True,
    )
    return done.returncode == 0


def test_alembic_sorts_the_same_before_and_after_the_first_migration(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(_isort_settings())
    (tmp_path / "mod.py").write_text(MODULE)
    before = _sorted(tmp_path)
    (tmp_path / "alembic").mkdir()
    (tmp_path / "alembic" / "env.py").write_text("")

    assert before and _sorted(tmp_path)
