"""Table registration goes through ``app/core/model_registry.py``, nowhere else.

Autogenerate (``migrate-fix`` today, migration generation tomorrow), the
startup re-adoption check and the test suite all need every table in
``SQLModel.metadata``. Each used to keep its own hand-written import list;
the AI service's 22 tables, payment, rag, the voice usage tables and the org
tables were missing from at least one of them. One registry, one rule
(tables live under ``app/models/`` or ``app/services/<svc>/models``), and
the generated ``tests/test_model_registry.py`` proves the rule covers reality.

This pins the repo side: the four consumers call the registry, and none of
them has grown a private import list again.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aegis.core.component_files import get_template_path

PROJECT = Path(get_template_path()) / "{{ project_slug }}"
CONSUMERS = (
    "alembic/env.py.jinja",
    "tests/conftest.py.jinja",
    "app/components/backend/startup/database_init.py.jinja",
    "app/cli/migrate_fix.py.jinja",
)
MODEL_IMPORT = re.compile(
    r"^(from|import) app\.(models|services\.[a-z_]+\.models)", re.M
)
TABLE_RE = re.compile(r"^class \w+\([^)]*\btable=True", re.M)


@pytest.mark.parametrize("rel", CONSUMERS)
def test_consumer_registers_through_the_registry(rel: str) -> None:
    text = (PROJECT / rel).read_text()
    assert "import_all_models()" in text, f"{rel} does not call the model registry"
    stray = MODEL_IMPORT.findall(text)
    assert not stray, f"{rel} imports model modules by hand again: {stray}"


def test_every_table_lives_where_the_registry_looks() -> None:
    """The registry's rule is a convention; this is where it is enforced."""
    off_path = sorted(
        p.relative_to(PROJECT).as_posix()
        for p in (PROJECT / "app").rglob("*.py*")
        if p.suffix in (".py", ".jinja")
        and TABLE_RE.search(p.read_text())
        and not re.match(
            r"app/(models/|(services|components)/[a-z_]+/models(/|\.py))",
            p.relative_to(PROJECT).as_posix(),
        )
    )
    assert not off_path, "tables the registry cannot find:\n  " + "\n  ".join(off_path)
