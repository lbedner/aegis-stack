"""A service's ``data_after`` body run as its revision runs it: the body of
an ``upgrade()`` with alembic's ``op`` and ``sa`` in scope, against ``conn``."""

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def run_data_after(conn: sa.Connection, body: str) -> None:
    namespace: dict[str, object] = {
        "op": Operations(MigrationContext.configure(conn)),
        "sa": sa,
    }
    exec(compile(f"def upgrade():\n{body}\n", "revision", "exec"), namespace)
    namespace["upgrade"]()  # type: ignore[operator]
