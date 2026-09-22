"""sqlmodel stays below the release that rejects naive datetimes.

sqlmodel 0.0.45 made ``datetime`` columns refuse a value without tzinfo
("Datetime values must have timezone information"). Every timestamp this
template writes is naive UTC by design - ``app/core/time.py`` says why:
SQLite has no timezone type, and asyncpg rejects aware datetimes against
``timestamp without time zone``. With an open ``>=0.0.14`` a fresh
project resolved 0.0.46, and every write of a timestamp failed: a
generated auth stack's suite errored in all 3,617 tests, because the
conftest's own seed rows could not be inserted.

The spec was also written in three places. The generator now reads the
database spec; the Jinja template cannot import Python, so this holds it
to the spec instead.
"""

from __future__ import annotations

from pathlib import Path

from aegis.core.component_files import get_template_path
from aegis.core.components import COMPONENTS

BREAKING = "0.0.45"


def _sqlmodel_spec() -> str:
    [spec] = [
        d for d in COMPONENTS["database"].pyproject_deps if d.startswith("sqlmodel")
    ]
    return spec


def test_the_database_spec_stays_below_the_breaking_release() -> None:
    assert f"<{BREAKING}" in _sqlmodel_spec()


def test_the_template_asks_for_the_same_sqlmodel_as_the_spec() -> None:
    template = Path(get_template_path()) / "{{ project_slug }}" / "pyproject.toml.jinja"
    assert f'"{_sqlmodel_spec()}"' in template.read_text()


def test_the_generator_does_not_restate_it() -> None:
    source = Path(__file__).resolve().parents[2] / "aegis/core/template_generator.py"
    assert '"sqlmodel>=' not in source.read_text(), (
        "the generator writes its own sqlmodel spec instead of the database spec's"
    )
