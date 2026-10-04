"""The catalog's voice models, for tests that price or dial them.

Seeded from the catalog's own offline seed (``fixtures/llm_catalog``), so
a test prices at exactly the rates a fresh install would. Idempotent: the
seed skips what is already there.
"""

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.ai.fixtures.llm_fixtures import load_all_llm_fixtures


async def seed_voice_catalog(session: AsyncSession) -> None:
    """The offline catalog, voice models and their prices included."""
    await session.run_sync(load_all_llm_fixtures)
    await session.commit()
