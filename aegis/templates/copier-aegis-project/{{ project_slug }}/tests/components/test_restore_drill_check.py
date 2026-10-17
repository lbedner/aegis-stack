"""A restore drill's checks, run by the app's own code against a restored
copy (``deploy drill-check``, aegis-stack#1482): the database whole, every
stored secret readable with this ``ENCRYPTION_KEY``, every stored file the
rows name present."""

from pathlib import Path
import sqlite3

import pytest

from app.components.deploy import drill
from app.core import encryption
from app.core.cache import get_cache
from app.core.config import settings
from app.core.storage import content_key

pytestmark = pytest.mark.queryspy(allow_n_plus_one=True)


def _database(path: Path) -> Path:
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE t (v TEXT)")
    db.commit()
    db.close()
    return path


@pytest.fixture(autouse=True)
async def _nothing_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Migrating is ``alembic upgrade`` on the settings' database, which the
    drill's container points at the copy: stood in here."""

    async def missing(session: object) -> list[str]:
        return []

    monkeypatch.setattr(drill, "missing_objects", missing)
    monkeypatch.setattr(
        drill, "_migrated", lambda db: {"name": "migrations", "ok": True, "said": ""}
    )
    await get_cache().clear()


def _by_name(checks: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(c["name"]): c for c in checks}


async def test_a_whole_copy_passes(tmp_path: Path) -> None:
    checks = _by_name(await drill.drill_check(_database(tmp_path / "app.db")))
    assert all(c["ok"] for c in checks.values()), checks
    assert set(checks) == {"migrations", "database", "secrets", "files"}


async def test_a_copy_that_will_not_migrate_is_checked_no_further(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    refused = {"name": "migrations", "ok": False, "said": "no such table: x"}
    monkeypatch.setattr(drill, "_migrated", lambda db: refused)
    assert await drill.drill_check(_database(tmp_path / "app.db")) == [refused]


async def test_a_damaged_database_fails(tmp_path: Path) -> None:
    broken = tmp_path / "app.db"
    broken.write_bytes(b"SQLite format 3\x00" + b"\xff" * 4096)
    checks = _by_name(await drill.drill_check(broken))
    assert checks["database"]["ok"] is False


async def test_a_secret_this_key_cannot_read_fails_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The copy is only as good as the key kept off the server: restored
    with the wrong one, the drill says so."""
    secrets_store = pytest.importorskip("app.components.secrets.store").DatabaseStore()
    await secrets_store.put("RESEND_API_KEY", "re_live_value", "alue", "test")
    try:
        monkeypatch.setitem(
            settings.__dict__, "ENCRYPTION_KEY", "a different key entirely"
        )
        encryption._reset_cache()
        await get_cache().clear()
        checks = _by_name(await drill.drill_check(_database(tmp_path / "app.db")))
        assert checks["secrets"]["ok"] is False
        assert "RESEND_API_KEY" in str(checks["secrets"]["said"])
    finally:
        await secrets_store.delete("RESEND_API_KEY", "test")
        encryption._reset_cache()


async def test_a_stored_file_missing_from_the_copy_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def missing(session: object) -> list[str]:
        return [content_key(b"gone")]

    monkeypatch.setattr(drill, "missing_objects", missing)
    checks = _by_name(await drill.drill_check(_database(tmp_path / "app.db")))
    assert checks["files"]["ok"] is False
    assert "1 stored file" in str(checks["files"]["said"])


def test_the_cli_says_each_check_and_fails_when_one_does(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``aegis deploy-restore-drill`` reads its last line, and its exit."""
    import json

    from tests._cli import invoke

    async def checks(database: Path) -> list[dict[str, object]]:
        return [
            {"name": "database", "ok": True, "said": "integrity: ok"},
            {"name": "files", "ok": False, "said": "1 stored file missing"},
        ]

    monkeypatch.setattr(drill, "drill_check", checks)
    result = invoke(["deploy", "drill-check", "--database", str(tmp_path / "a.db")])
    assert result.exit_code == 1
    said = json.loads(result.output.strip().splitlines()[-1])
    assert [c["name"] for c in said] == ["database", "files"]
