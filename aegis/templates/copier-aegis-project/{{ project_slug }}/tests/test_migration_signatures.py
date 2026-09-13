"""Every migration must carry a stamp signature.

The startup hook re-adopts a persisted database by checking, per pending
migration, whether its signature object already exists - and stamping
instead of replaying the DDL. A migration that ships without a signature
opts out of that recovery: the day a volume outlives its version row, the
upgrade replays, and the database logs an "already exists" error on every
boot until someone stamps by hand. That is not hypothetical - 004..007
shipped unsigned and did exactly this.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

signatures_module = pytest.importorskip(
    "app.components.backend.startup.migration_signatures",
    reason="no database component in this stack",
)

VERSIONS = Path(__file__).parent.parent / "alembic" / "versions"


def _service_suffixes() -> list[str]:
    names = []
    for p in sorted(VERSIONS.glob("*.py")):
        m = re.match(r"\d+_(.+)", p.stem)
        if m:
            names.append(m.group(1))
    return names


def _revision_files() -> list[Path]:
    return [p for p in sorted(VERSIONS.glob("*.py")) if not p.name.startswith("__")]


PROVABLE = ("create_table(", "add_column(", "create_foreign_key(", "INSERT INTO")


def _has_something_to_prove(path: Path) -> bool:
    """Whether the revision makes something whose existence proves it ran.

    A created table, an added column, a new foreign key, an inserted row.
    A revision that only drops or re-indexes leaves nothing to check for,
    so the re-adoption hook has nothing to do with it either.
    """
    body = path.read_text()
    return any(marker in body for marker in PROVABLE)


def _carried_signature(path: Path) -> tuple[str, ...] | None:
    """The signature a generated revision declares about itself."""
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign):
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == "aegis_stamp_signature":
                value = ast.literal_eval(node.value)
                return tuple(value) if value is not None else None
    return None


def test_every_migration_file_has_a_stamp_signature() -> None:
    """Either the revision declares its own, or the legacy table names it.

    Revisions are derived from the models now, so a generated one carries
    the signature of the object it creates. The table stays for revisions
    written before that, which a long-lived project still has on disk.
    """
    signatures = signatures_module.SERVICE_MIGRATION_SIGNATURES
    missing = [
        path.name
        for path in _revision_files()
        if _has_something_to_prove(path)
        and _carried_signature(path) is None
        and (re.match(r"\d+_(.+)", path.stem) or [None, ""])[1] not in signatures
    ]
    assert not missing, (
        f"migrations without a stamp signature: {missing} - a generated "
        "revision declares `aegis_stamp_signature`; a hand-written one needs "
        "an entry in SERVICE_MIGRATION_SIGNATURES naming the table or column "
        "whose existence proves the migration ran"
    )


def test_a_carried_signature_names_something_the_revision_creates() -> None:
    """A signature that points outside its own revision can never fire."""
    for path in _revision_files():
        signature = _carried_signature(path)
        if signature is None:
            continue
        body = path.read_text()
        name = signature[1].split(".")[-1]
        assert f'"{name}"' in body or f"'{name}'" in body, (
            f"{path.name} claims {signature!r}, but never mentions {name}"
        )


def test_signatures_name_real_model_objects() -> None:
    """A signature pointing at a table nobody declares can never fire."""
    sqlmodel = pytest.importorskip(
        "sqlmodel", reason="stack has migrations dir but no ORM (e.g. worker-only)"
    )

    import importlib
    import pkgutil

    import app.models  # noqa: F401  (registers core tables)
    import app.services

    # Service-owned tables register only when their models module imports -
    # exactly how alembic's env.py loads them. Walk every installed service;
    # a service without a models module is fine.
    for info in pkgutil.iter_modules(app.services.__path__):
        try:
            importlib.import_module(f"app.services.{info.name}.models")
        except ModuleNotFoundError:
            continue

    tables = set(sqlmodel.SQLModel.metadata.tables)
    bare = {t.split(".")[-1] for t in tables}
    installed = set(_service_suffixes())
    for service, sig in signatures_module.SERVICE_MIGRATION_SIGNATURES.items():
        if service not in installed:
            continue  # signature for a service this stack doesn't ship
        name = sig[1]
        assert name in tables or name in bare or name.split(".")[-1] in bare, (
            f"signature for '{service}' names '{name}', which no model declares"
        )


def test_row_signature_checks_the_live_database() -> None:
    """``("row", table, where)``: the hook must replay a data-only revision
    whose row is missing and stamp it when the row is there."""
    database_init = pytest.importorskip(
        "app.components.backend.startup.database_init",
        reason="no database component in this stack",
    )
    row_exists = getattr(database_init, "_row_exists", None)
    if row_exists is None:
        pytest.skip("re-adoption hook is Postgres-only in this stack")
    import sqlalchemy as sa

    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            sa.text('CREATE TABLE "user" (id INTEGER PRIMARY KEY, email TEXT)')
        )
        assert row_exists(conn, "user", "id = 0") is False
        conn.execute(
            sa.text("INSERT INTO \"user\" VALUES (0, 'standalone@finance.local')")
        )
        assert row_exists(conn, "user", "id = 0") is True
        # A table that does not exist is "not applied", never an exception.
        assert row_exists(conn, "nope", "id = 0") is False


def test_data_only_revisions_use_the_row_form() -> None:
    """A data-only revision cannot be proven by a schema object."""
    sig = signatures_module.SERVICE_MIGRATION_SIGNATURES.get("finance_auth_link")
    if sig is None:
        pytest.skip("finance_auth_link not in this stack")
    assert sig[0] == "row" and sig[1] == "user" and "id = 0" in sig[2]


@pytest.mark.skipif(
    not (VERSIONS.parent / "alembic.ini").exists(),
    reason="this stack ships no migrations",
)
def test_the_startup_hook_can_read_a_carried_signature() -> None:
    """Alembic hands the hook the revision module; the constant rides on it.

    The hook reads ``rev.module.aegis_stamp_signature`` inside a broad
    try/except, so a broken mechanism would go unnoticed at boot: this is
    what fails instead.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config("alembic/alembic.ini"))
    carried = {
        rev.revision: getattr(rev.module, "aegis_stamp_signature", None)
        for rev in script.walk_revisions()
    }
    on_disk = {
        path.stem: _carried_signature(path)
        for path in _revision_files()
        if _carried_signature(path) is not None
    }
    if not on_disk:
        pytest.skip("no generated revisions in this project")
    assert any(carried.values()), (
        "revisions declare aegis_stamp_signature on disk, but alembic exposes "
        f"none of them to the startup hook: {sorted(on_disk)}"
    )
