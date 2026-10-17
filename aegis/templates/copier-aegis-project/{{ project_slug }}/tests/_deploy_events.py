"""The deploy events table emptied after a test (the suite's database
outlives one)."""

from collections.abc import AsyncIterator

import pytest
from sqlmodel import select

from app.components.deploy.models import DeployEvent
from app.core.db import get_async_session


@pytest.fixture
async def no_deploy_events() -> AsyncIterator[None]:
    yield
    async with get_async_session() as db:
        for row in (await db.exec(select(DeployEvent))).all():
            await db.delete(row)
        await db.commit()
