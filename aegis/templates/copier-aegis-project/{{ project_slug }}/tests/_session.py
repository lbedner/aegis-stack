"""The one way a test hands the app's session openers its own session, and
reads back what landed in it."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession


def opens(
    session: AsyncSession,
) -> Callable[[], AbstractAsyncContextManager[AsyncSession]]:
    """A stand-in for ``get_async_session`` that yields ``session``:
    ``monkeypatch.setattr(module, "get_async_session", opens(session))``."""

    @asynccontextmanager
    async def opener() -> AsyncIterator[AsyncSession]:
        yield session

    return opener


async def rows_of(db: AsyncSession, model: Any) -> list[Any]:
    """Every row of ``model`` the session can see."""
    return list((await db.exec(select(model))).all())
