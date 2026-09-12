"""The async URL converter in ``app/core/db.py`` must accept a SQLite URL
whatever engine the project chose.

The generated test suite points ``DATABASE_URL`` at a throwaway SQLite file
at import time, before ``app.core.db`` builds its engines, so the suite of
a Postgres project runs on SQLite like every other. A converter that only
knows ``postgresql://`` hands ``create_async_engine`` a sync ``sqlite://``
URL and the whole suite fails to collect. The CI matrix never generates a
Postgres project (it would need a server), so nothing else catches this.
"""

from __future__ import annotations

import ast
from typing import Any

import pytest
from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path


def _converter(engine: str) -> Any:
    env = Environment(
        loader=FileSystemLoader(str(get_template_path())), keep_trailing_newline=True
    )
    ctx = {**get_copier_defaults(), "include_database": True, "database_engine": engine}
    source = env.get_template("{{ project_slug }}/app/core/db.py.jinja").render(ctx)
    tree = ast.parse(source)
    fn = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "_get_async_database_url"
    )
    ns: dict[str, Any] = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "db.py", "exec"), ns)
    return ns["_get_async_database_url"]


@pytest.mark.parametrize("engine", ["sqlite", "postgres"])
def test_sqlite_url_becomes_aiosqlite_for_every_engine(engine: str) -> None:
    convert = _converter(engine)
    assert convert("sqlite:////tmp/x/app.db") == "sqlite+aiosqlite:////tmp/x/app.db"


def test_postgres_url_becomes_asyncpg_for_a_postgres_project() -> None:
    convert = _converter("postgres")
    assert convert("postgresql://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"
