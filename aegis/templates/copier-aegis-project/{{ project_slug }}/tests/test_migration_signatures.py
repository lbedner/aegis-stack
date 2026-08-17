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


def test_every_migration_file_has_a_stamp_signature() -> None:
    signatures = signatures_module.SERVICE_MIGRATION_SIGNATURES
    missing = [s for s in _service_suffixes() if s not in signatures]
    assert not missing, (
        f"migrations without a stamp signature: {missing} - add an entry to "
        "_SERVICE_MIGRATION_SIGNATURES naming the table or column whose "
        "existence proves the migration ran"
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
