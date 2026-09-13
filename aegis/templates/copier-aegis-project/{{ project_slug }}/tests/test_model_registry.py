"""The model registry finds every table this project defines.

``import_all_models()`` walks ``app/models/`` and ``app/services/*/models``.
A table defined anywhere else never reaches ``SQLModel.metadata``, so alembic
autogenerate, ``migrate-fix`` and the startup re-adoption check are blind to
it. This test walks the source tree the slow way and compares.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("sqlmodel", reason="no database in this stack")

from app.core.model_registry import import_all_models  # noqa: E402

APP = Path(__file__).resolve().parents[1] / "app"
TABLE_RE = re.compile(r"^class \w+\([^)]*\btable=True", re.M)


def _table_modules() -> set[str]:
    found = set()
    for path in APP.rglob("*.py"):
        if TABLE_RE.search(path.read_text()):
            rel = path.relative_to(APP.parent).with_suffix("").as_posix()
            found.add(rel.replace("/", ".").removesuffix(".__init__"))
    return found


def test_registry_imports_every_table_module() -> None:
    import_all_models()
    missing = sorted(m for m in _table_modules() if m not in sys.modules)
    assert not missing, "tables the registry never imported:\n  " + "\n  ".join(missing)


@pytest.mark.skipif(
    not (APP.parent / "alembic" / "alembic.ini").exists(),
    reason="this stack ships no migrations",
)
def test_generated_revisions_rebuild_the_models(tmp_path: Path) -> None:
    """Applying every revision to an empty database yields the models, exactly.

    This is the property the revision generator exists to hold: the files
    under ``alembic/versions`` are derived from the models, so replaying
    them must reproduce ``SQLModel.metadata`` with no drift either way.
    """
    from app.cli.migrate_drift import drift

    assert drift(scratch_dir=tmp_path) == []
