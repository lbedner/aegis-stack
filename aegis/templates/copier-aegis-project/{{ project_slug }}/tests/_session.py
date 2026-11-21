"""The one way a test hands the app's session openers its own session, and
reads back what landed in it, and flushes a row in a process of its own."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
import subprocess
import sys
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


def flushes_alone(
    module: str, model: str, **fields: Any
) -> subprocess.CompletedProcess[str]:
    """Flush one ``model`` row in a fresh interpreter that imported only
    ``module`` and the app's database layer, the way a CLI command or a
    worker does. The suite imports every model, so a foreign key to a
    table nothing else loaded shows up only here."""
    code = (
        "import app.core.db\n"
        "from sqlalchemy import create_engine\n"
        "from sqlmodel import Session\n"
        f"from {module} import {model}\n"
        f"row = {model}(**{fields!r})\n"
        "engine = create_engine('sqlite://')\n"
        f"{model}.__table__.create(engine)\n"
        "with Session(engine) as session:\n"
        "    session.add(row)\n"
        "    session.flush()\n"
    )
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
