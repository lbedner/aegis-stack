"""Reads for the voice domain: which profiles exist, and which is active."""

from sqlalchemy.orm import selectinload
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.ai.models.llm import LargeLanguageModel, LLMOrg
from app.services.ai.models.voice import LiveEngine, VoiceProfile


async def all_profiles(session: AsyncSession) -> list[VoiceProfile]:
    """Every voice profile, by name."""
    return list(
        (
            await session.exec(select(VoiceProfile).order_by(col(VoiceProfile.name)))
        ).all()
    )


async def active_profile(session: AsyncSession) -> VoiceProfile | None:
    return (
        await session.exec(select(VoiceProfile).where(col(VoiceProfile.is_active)))
    ).first()


async def profile_named(session: AsyncSession, name: str) -> VoiceProfile | None:
    return (
        await session.exec(select(VoiceProfile).where(VoiceProfile.name == name))
    ).first()


async def any_profile(session: AsyncSession) -> bool:
    return (await session.exec(select(VoiceProfile.id))).first() is not None


async def engine_keys(session: AsyncSession) -> set[str]:
    return set((await session.exec(select(LiveEngine.key))).all())


async def enabled_engines(session: AsyncSession) -> list[LiveEngine]:
    """The engines on offer, in their order, each with its catalog model
    and the org that serves it."""
    return list(
        (
            await session.exec(
                select(LiveEngine)
                .where(col(LiveEngine.is_enabled))
                .order_by(col(LiveEngine.sort_order))
                .options(
                    selectinload(LiveEngine.llm).selectinload(  # type: ignore[arg-type]
                        LargeLanguageModel.served_by  # type: ignore[arg-type]
                    )
                )
            )
        ).all()
    )


async def engine_for_model(session: AsyncSession, model_id: str) -> LiveEngine | None:
    """The engine on this catalog model, offered or not."""
    return (
        await session.exec(
            select(LiveEngine)
            .join(LargeLanguageModel, col(LiveEngine.llm_id) == LargeLanguageModel.id)
            .where(LargeLanguageModel.model_id == model_id)
        )
    ).first()


async def model_vendor(session: AsyncSession, model_id: str) -> tuple[int, str] | None:
    """A catalog model's id and the slug of the org that serves it."""
    row = (
        await session.exec(
            select(LargeLanguageModel.id, LLMOrg.slug)
            .join(LLMOrg, col(LargeLanguageModel.served_by_org_id) == LLMOrg.id)
            .where(LargeLanguageModel.model_id == model_id)
        )
    ).first()
    return (row[0], row[1]) if row and row[0] is not None else None


async def catalog_ids(session: AsyncSession, model_ids: list[str]) -> dict[str, int]:
    """Catalog row ids for these model ids; a model it lacks is absent."""
    rows = await session.exec(
        select(LargeLanguageModel.model_id, LargeLanguageModel.id).where(
            col(LargeLanguageModel.model_id).in_(model_ids)
        )
    )
    return {model_id: llm_id for model_id, llm_id in rows.all() if llm_id is not None}
