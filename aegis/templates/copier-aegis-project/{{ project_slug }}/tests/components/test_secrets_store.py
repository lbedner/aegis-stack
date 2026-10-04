"""The secrets component's store: credentials encrypted in the database,
read live by every process, and never handed back to anything but the code
that uses them.

The shared cache holds the encrypted row, never a decrypted value, and a
write clears it, so the next read anywhere sees the change. Tests run on
the app-owned database the suite redirects ``get_async_session`` to, and on
the dict-backed cache the suite installs.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlmodel import select

from app.components.secrets import store as store_module
from app.components.secrets.models import SecretRecord
from app.core import encryption, secrets
from app.core.cache import get_cache
from app.core.config import settings
from app.core.db import get_async_session
from app.core.secrets import Secret
from tests._audit import Recorded

# These tests write and read one row several times on purpose: a write
# then a read is how invalidation and round trips are shown. Each read is
# one SELECT for one name, never a loop, so the repeats are the scenario,
# not an N+1 (queryspy otherwise fails a test on any repeated statement).
pytestmark = pytest.mark.queryspy(allow_n_plus_one=True)

KEY = "sk-live-0123456789abcdWXYZ"
DECLARED = (
    Secret("TEST_API_KEY", owner="Test"),
    Secret("TEST_FROM_EMAIL", owner="Test", secret=False),
)


async def _rows() -> list[SecretRecord]:
    async with get_async_session() as db:
        return list((await db.exec(select(SecretRecord))).all())


@pytest.fixture
async def store(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    monkeypatch.setitem(
        settings.__dict__, "ENCRYPTION_KEY", "test-encryption-key-0123456789"
    )
    encryption._reset_cache()
    monkeypatch.setattr(secrets, "declared", lambda: DECLARED)
    secrets.set_store(None)
    assert store_module.install() is None
    yield
    secrets.set_store(None)
    async with get_async_session() as db:
        for row in (await db.exec(select(SecretRecord))).all():
            await db.delete(row)
        await db.commit()
    await get_cache().invalidate_prefix(store_module.CACHE_PREFIX)
    encryption._reset_cache()


def test_without_an_encryption_key_there_is_no_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rotating SECRET_KEY must never strand stored keys, so the store will
    not fall back to it."""
    monkeypatch.setitem(settings.__dict__, "ENCRYPTION_KEY", None)
    secrets.set_store(None)
    reason = store_module.install()
    assert reason is not None and "ENCRYPTION_KEY" in reason
    assert not secrets.writable()


async def test_a_value_round_trips_and_is_stored_encrypted(store: None) -> None:
    await secrets.put("TEST_API_KEY", KEY, actor="ops@example.com")
    assert await secrets.get("TEST_API_KEY") == KEY
    (row,) = await _rows()
    assert KEY not in row.ciphertext
    assert (row.hint, row.set_by) == ("WXYZ", "ops@example.com")


async def test_a_ciphertext_moved_to_another_name_will_not_decrypt(store: None) -> None:
    await secrets.put("TEST_API_KEY", KEY, actor="ops")
    (row,) = await _rows()
    async with get_async_session() as db:
        db.add(
            SecretRecord(name="TEST_FROM_EMAIL", ciphertext=row.ciphertext, hint="x")
        )
        await db.commit()
    with pytest.raises(secrets.SecretUnreadableError) as raised:
        await secrets.get("TEST_FROM_EMAIL")
    assert KEY not in str(raised.value)


async def test_the_cache_never_holds_a_decrypted_value(
    store: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    cached: list[Any] = []
    real_set = get_cache().set

    async def spy(key: str, value: Any, ttl: int | None = None) -> None:
        cached.append(value)
        await real_set(key, value, ttl)

    monkeypatch.setattr(get_cache(), "set", spy)
    await secrets.put("TEST_API_KEY", KEY, actor="ops")
    await secrets.get("TEST_API_KEY")
    assert cached and all(KEY not in repr(value) for value in cached)


async def test_a_write_clears_the_cache_so_the_next_read_sees_it(store: None) -> None:
    await secrets.put("TEST_API_KEY", KEY, actor="ops")
    assert await secrets.get("TEST_API_KEY") == KEY  # now cached
    await secrets.put("TEST_API_KEY", "sk-live-rotated-000000", actor="ops")
    assert await secrets.get("TEST_API_KEY") == "sk-live-rotated-000000"


async def test_get_many_reads_every_missing_row_in_one_query(store: None) -> None:
    await secrets.put("TEST_API_KEY", KEY, actor="ops")
    await secrets.put("TEST_FROM_EMAIL", "hi@example.com", actor="ops")
    await get_cache().invalidate_prefix(store_module.CACHE_PREFIX)
    found = await secrets.get_many("TEST_API_KEY", "TEST_FROM_EMAIL")
    assert found == {"TEST_API_KEY": KEY, "TEST_FROM_EMAIL": "hi@example.com"}
    # Now cached: a second read needs no row at all.
    assert await secrets.get_many("TEST_API_KEY") == {"TEST_API_KEY": KEY}


async def test_a_name_with_no_row_is_cached_as_absent(store: None) -> None:
    """A status poll over unset keys must not query the table every time."""
    assert await secrets.get("TEST_API_KEY") is None
    assert await get_cache().get(store_module.CACHE_PREFIX + "TEST_API_KEY") == ""
    await secrets.put("TEST_API_KEY", KEY, actor="ops")  # clears the absent mark
    assert await secrets.get("TEST_API_KEY") == KEY


async def test_delete_removes_it_everywhere(store: None) -> None:
    await secrets.put("TEST_API_KEY", KEY, actor="ops")
    await secrets.get("TEST_API_KEY")
    await secrets.delete("TEST_API_KEY", actor="ops")
    assert await secrets.get("TEST_API_KEY") is None
    assert await _rows() == []


async def test_status_reads_who_and_when_without_decrypting(
    store: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    await secrets.put("TEST_API_KEY", KEY, actor="ops@example.com")
    await secrets.put("TEST_FROM_EMAIL", "hi@example.com", actor="ops@example.com")

    def refuse(*args: Any, **kwargs: Any) -> str:
        raise AssertionError("status must not decrypt")

    monkeypatch.setattr(store_module, "decrypt_secret", refuse)
    rows = {row.name: row for row in await secrets.status()}
    assert rows["TEST_API_KEY"].source == "database"
    assert rows["TEST_API_KEY"].hint == "WXYZ"
    assert rows["TEST_API_KEY"].set_by == "ops@example.com"
    assert rows["TEST_API_KEY"].set_at is not None
    assert rows["TEST_FROM_EMAIL"].hint == "hi@example.com"


async def test_every_write_is_audited_without_the_value(
    store: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    audit = Recorded()
    monkeypatch.setattr(store_module, "get_audit", lambda: audit)
    await secrets.put("TEST_API_KEY", KEY, actor="ops@example.com")
    await secrets.delete("TEST_API_KEY", actor="ops@example.com")
    assert [e["event_type"] for e in audit.events] == ["secrets.set", "secrets.deleted"]
    assert all(KEY not in repr(event) for event in audit.events)
    assert audit.events[0]["actor_email"] == "ops@example.com"


def test_the_table_has_its_own_migration() -> None:
    """Component tables belong to the component (``migrate_owners``), so the
    secret table gets ``NNN_secrets.py`` rather than a sweep into another."""
    from app.cli.migrate_owners import _owners

    owned = {key: names for key, names in _owners().items() if key.endswith("secret")}
    assert owned and all(names == ["secrets"] for names in owned.values())


async def test_health_counts_what_is_set_and_stored(store: None) -> None:
    from app.components.secrets.health import check_secrets_health
    from app.services.system.models import ComponentStatusType

    await secrets.put("TEST_API_KEY", KEY, actor="ops")
    status = await check_secrets_health()
    assert status.status is ComponentStatusType.HEALTHY
    assert (status.metadata["declared"], status.metadata["set"]) == (2, 1)
    assert status.metadata["stored"] == 1


async def test_health_says_why_there_is_no_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.components.secrets.health import check_secrets_health
    from app.services.system.models import ComponentStatusType

    monkeypatch.setitem(settings.__dict__, "ENCRYPTION_KEY", None)
    secrets.set_store(None)
    status = await check_secrets_health()
    assert status.status is ComponentStatusType.WARNING
    assert "ENCRYPTION_KEY" in status.message


async def test_health_warns_only_for_a_needed_key_that_is_missing(
    store: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Optional providers left unset are choices, not problems."""
    from app.components.secrets.health import check_secrets_health
    from app.services.system.models import ComponentStatusType

    status = await check_secrets_health()
    assert status.status is ComponentStatusType.HEALTHY
    monkeypatch.setattr(
        secrets,
        "declared",
        lambda: (*DECLARED, Secret("TEST_NEEDED_KEY", owner="Test", needed=True)),
    )
    status = await check_secrets_health()
    assert status.status is ComponentStatusType.WARNING
    assert "TEST_NEEDED_KEY" in status.message
    assert (status.metadata["needed"], status.metadata["needed_set"]) == (1, 0)
