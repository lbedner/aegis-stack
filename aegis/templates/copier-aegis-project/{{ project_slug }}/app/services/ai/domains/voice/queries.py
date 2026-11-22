"""Reads for the voice domain: which profiles exist, which is active, and
how terms are said."""

from sqlalchemy.orm import selectinload
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.conversation import ConversationMessage
from app.services.ai.models.llm import LargeLanguageModel, LLMOrg
from app.services.ai.models.voice import (
    LiveEngine,
    VoiceProfile,
    VoicePronunciation,
)


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


async def pronunciations(session: AsyncSession) -> list[VoicePronunciation]:
    """Every saved pronunciation, by term."""
    return list(
        (
            await session.exec(
                select(VoicePronunciation).order_by(col(VoicePronunciation.key))
            )
        ).all()
    )


async def pronunciation_of(
    session: AsyncSession, key: str
) -> VoicePronunciation | None:
    return (
        await session.exec(
            select(VoicePronunciation).where(VoicePronunciation.key == key)
        )
    ).first()


async def engine_keys(session: AsyncSession) -> set[str]:
    return set((await session.exec(select(LiveEngine.key))).all())


async def all_engines(session: AsyncSession) -> list[LiveEngine]:
    return list((await session.exec(select(LiveEngine))).all())


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


async def model_vendor(
    session: AsyncSession, model_id: str
) -> tuple[int, str, str, bool | None] | None:
    """A catalog model's id, the slug of the org that serves it, its mode
    ("realtime", "chat", ...) and whether it can call tools."""
    row = (
        await session.exec(
            select(
                LargeLanguageModel.id,
                LLMOrg.slug,
                LargeLanguageModel.mode,
                LargeLanguageModel.supports_tools,
            )
            .join(LLMOrg, col(LargeLanguageModel.served_by_org_id) == LLMOrg.id)
            .where(LargeLanguageModel.model_id == model_id)
        )
    ).first()
    return (row[0], row[1], row[2], row[3]) if row and row[0] is not None else None


async def catalog_ids(session: AsyncSession, model_ids: list[str]) -> dict[str, int]:
    """Catalog row ids for these model ids; a model it lacks is absent."""
    rows = await session.exec(
        select(LargeLanguageModel.model_id, LargeLanguageModel.id).where(
            col(LargeLanguageModel.model_id).in_(model_ids)
        )
    )
    return {model_id: llm_id for model_id, llm_id in rows.all() if llm_id is not None}


async def first_word_waits(
    session: AsyncSession, model_id: str, limit: int
) -> list[int]:
    """How long callers waited for the first word back (ms), on the last
    ``limit`` timed call turns on ``model_id``, newest first."""
    meta = ConversationMessage.meta_data
    waited = meta["first_word_ms"].as_integer()  # type: ignore[index]
    rows = await session.exec(
        select(waited)
        .where(
            meta["model"].as_string() == model_id,  # type: ignore[index]
            waited.is_not(None),
        )
        .order_by(col(ConversationMessage.timestamp).desc())
        .limit(limit)
    )
    return [int(ms) for ms in rows.all()]
