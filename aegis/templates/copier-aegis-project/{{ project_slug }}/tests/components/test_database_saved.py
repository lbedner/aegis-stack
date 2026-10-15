"""Saved queries (``app.components.database.saved``): the statements Query
keeps in the app's database, by name, shared by every admin. Tests run on
the app-owned database the suite redirects ``get_async_session`` to."""

from collections.abc import AsyncIterator

import pytest
from sqlmodel import select

from app.components.database import saved
from app.components.database.models import SavedQuery
from app.core.db import get_async_session

# Each test saves and reads back more than once; the repeats are the scenario.
pytestmark = pytest.mark.queryspy(allow_n_plus_one=True)


@pytest.fixture(autouse=True)
async def _none_kept() -> AsyncIterator[None]:
    """The suite's database outlives a test; each one starts with none."""
    yield
    async with get_async_session() as db:
        for row in (await db.exec(select(SavedQuery))).all():
            await db.delete(row)
        await db.commit()


async def test_a_query_is_kept_by_name_and_listed_by_name() -> None:
    """Saved again under its name, it is the same one, changed."""
    await saved.keep("orgs", "SELECT * FROM org", by="ops@example.com")
    await saved.keep("active", "SELECT 1", by=None)
    await saved.keep("orgs", "SELECT id FROM org", by="dev@example.com")
    kept = await saved.kept()
    assert [(q.name, q.sql, q.saved_by) for q in kept] == [
        ("active", "SELECT 1", None),
        ("orgs", "SELECT id FROM org", "dev@example.com"),
    ]


async def test_a_query_is_forgotten() -> None:
    query = await saved.keep("orgs", "SELECT * FROM org", by=None)
    assert query.id is not None
    assert await saved.forget(query.id) == "orgs"
    assert await saved.forget(query.id) is None  # already gone
    assert await saved.kept() == []


@pytest.mark.parametrize(
    ("name", "sql"),
    [("", "SELECT 1"), ("x" * 121, "SELECT 1"), ("orgs", "  "), ("orgs", "x" * 20_001)],
)
async def test_what_cannot_be_kept_says_why(name: str, sql: str) -> None:
    """A name to find it by and a statement, each within its size."""
    with pytest.raises(saved.SavedError):
        await saved.keep(name, sql, by=None)
