"""Revisions written under sqlmodel 0.0.45+ must still load below it.

sqlmodel 0.0.45 added ``UTCDateTime`` and autogenerate names it in every
revision it renders for a ``datetime`` column. The template then pinned
sqlmodel below 0.0.45 (0.0.45 rejects the naive UTC timestamps the template
writes), so a project generated in that window updates onto a sqlmodel that
no longer has the type its own revisions call, and every migration fails.
``env.py`` runs before any revision, so it keeps the name resolvable.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import alembic
import pytest
import sqlalchemy as sa
from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path

PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"


def _env_py() -> str:
    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    context = {
        **get_copier_defaults(),
        "project_slug": "demo",
        "include_database": True,
    }
    return env.get_template(f"{PROJECT_SLUG_PLACEHOLDER}/alembic/env.py.jinja").render(
        context
    )


def _module(name: str, **attrs: object) -> ModuleType:
    module = ModuleType(name)
    module.__dict__.update(attrs)
    return module


def _load_env(monkeypatch: pytest.MonkeyPatch, sqltypes: ModuleType) -> None:
    """Execute env.py against stubs for everything but the sqltypes module."""
    sql = _module("sqlmodel.sql", sqltypes=sqltypes)
    stubs = {
        "sqlmodel": _module(
            "sqlmodel", SQLModel=SimpleNamespace(metadata=None), sql=sql
        ),
        "sqlmodel.sql": sql,
        "sqlmodel.sql.sqltypes": sqltypes,
        "app": _module("app"),
        "app.core": _module("app.core"),
        "app.core.config": _module(
            "app.core.config", settings=SimpleNamespace(DATABASE_URL="sqlite://")
        ),
        "app.core.model_registry": _module(
            "app.core.model_registry", import_all_models=lambda: None
        ),
    }
    for name, module in stubs.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(alembic, "context", MagicMock(), raising=False)
    exec(compile(_env_py(), "env.py", "exec"), {"__file__": "/demo/alembic/env.py"})  # noqa: S102


def test_a_revision_naming_utc_datetime_loads_below_0_0_45(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sqltypes = _module("sqlmodel.sql.sqltypes")
    _load_env(monkeypatch, sqltypes)

    column_type = sqltypes.UTCDateTime()

    assert isinstance(column_type, sa.DateTime)
    assert column_type.timezone is True


def test_a_real_utc_datetime_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    real = object()
    sqltypes = _module("sqlmodel.sql.sqltypes", UTCDateTime=real)
    _load_env(monkeypatch, sqltypes)

    assert sqltypes.UTCDateTime is real
