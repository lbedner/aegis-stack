"""A model in the catalog, for a test that pins one on an agent."""

from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.ai.models.llm.large_language_model import LargeLanguageModel
from app.services.ai.models.llm.llm_org import LLMOrg


async def listed(
    session: AsyncSession, model_id: str, served_by: str = "openai", **fields: Any
) -> LargeLanguageModel:
    """``model_id`` as a catalog row (``fields`` over the defaults: its
    ``mode``, ``supports_tools``), served by the org ``served_by`` (made
    the first time it is named)."""
    org = (await session.exec(select(LLMOrg).where(LLMOrg.slug == served_by))).first()
    if org is None:
        org = LLMOrg(slug=served_by, name=served_by, color="#000", icon_path="")
        session.add(org)
        await session.flush()
    model = LargeLanguageModel(
        **{"title": model_id, **fields}, model_id=model_id, served_by_org_id=org.id
    )
    session.add(model)
    await session.commit()
    return model
