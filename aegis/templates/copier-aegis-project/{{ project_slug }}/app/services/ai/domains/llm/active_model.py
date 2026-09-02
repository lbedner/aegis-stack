"""Runtime active-model override.

The model the app is actually using, stored in the database rather than in
``.env``. Switching writes here and mutates the live settings object, so a
change from the Cloud Catalog tab or from ``llm use`` takes effect on the next
request instead of on the next restart.

Why settings mutation rather than a lookup at read time: ``get_ai_config`` is
synchronous and constructed in half a dozen places, including
``AIService.__init__``. Making it await a database read would push async up
through every one of those call sites. Applying the override *to* settings
keeps the resolution path untouched, and the startup hook replays the stored
choice into each process as it boots.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.log import logger
from app.services.ai.models.llm import LLMActiveSelection

# The .env-sourced model/provider, captured before the first override mutates
# the live settings object. Without this, "back to .env" is impossible inside
# a running process - the original values are gone the moment an override
# applies - and a stored row shadows every later .env edit forever.
_env_defaults: dict[str, str] | None = None


def remember_env_defaults(settings: Any) -> None:
    """Capture the .env model/provider once, before any override overwrites it.

    Idempotent: the first call in a process wins, and both apply paths call it
    first, so what is remembered is always what the environment provided.
    """
    global _env_defaults
    if _env_defaults is None:
        _env_defaults = {
            "model": settings.AI_MODEL,
            "provider": settings.AI_PROVIDER,
        }


def env_default_model() -> str | None:
    """The .env model captured at startup, when this process recorded one."""
    return None if _env_defaults is None else _env_defaults["model"]


def _owner_clause(owner_user_id: int | None):
    """Match one owner's row; a NULL owner is the install-wide default."""
    column = LLMActiveSelection.owner_user_id
    return column.is_(None) if owner_user_id is None else column == owner_user_id


async def get_active_override(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> LLMActiveSelection | None:
    """This owner's stored selection, without falling back.

    Pass no owner for the install-wide default. Use ``resolve_override`` when
    you want the fallback chain rather than one exact row.
    """
    query = select(LLMActiveSelection).where(_owner_clause(owner_user_id))
    return (await db.exec(query)).first()


async def resolve_override(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> LLMActiveSelection | None:
    """The selection that applies to ``owner_user_id``.

    Resolution order: the user's own row, then the install-wide default. A
    stack without the auth service only ever has the latter.
    """
    if owner_user_id is not None:
        owned = await get_active_override(db, owner_user_id=owner_user_id)
        if owned is not None:
            return owned
    return await get_active_override(db)


async def list_overrides(db: AsyncSession) -> list[LLMActiveSelection]:
    """Every stored selection, across owners."""
    return list((await db.exec(select(LLMActiveSelection))).all())


async def set_active_override(
    db: AsyncSession,
    *,
    model_id: str,
    provider: str | None,
    owner_user_id: int | None = None,
) -> LLMActiveSelection:
    """Record ``model_id`` as active for one owner, replacing their prior row.

    Writes; the caller commits. Updates in place rather than inserting, so
    "active model" stays a single fact per owner, and never touches another
    owner's choice.
    """
    selection = await get_active_override(db, owner_user_id=owner_user_id)
    if selection is None:
        selection = LLMActiveSelection(
            owner_user_id=owner_user_id, model_id=model_id, provider=provider
        )
    else:
        selection.model_id = model_id
        selection.provider = provider
        selection.updated_at = datetime.now(UTC).replace(tzinfo=None)
    db.add(selection)
    await db.flush()
    return selection


def apply_to_settings(settings: Any, *, model_id: str, provider: str | None) -> None:
    """Point the live settings at ``model_id``.

    ``provider`` is left alone when unknown: a model resolved from Ollama or
    set with ``--force`` has no catalog vendor, and blanking the provider
    would break the next request rather than switch it.
    """
    remember_env_defaults(settings)
    settings.AI_MODEL = model_id
    if provider:
        settings.AI_PROVIDER = provider


async def clear_active_override(
    db: AsyncSession, settings: Any, *, owner_user_id: int | None = None
) -> bool:
    """Delete the stored selection and point live settings back at .env.

    The inverse of ``set_active_override`` + ``apply_to_settings``, and the
    reason it must exist: a row written once otherwise shadows every later
    .env edit, so a rebuild that "should have" changed the model silently
    changes nothing. Writes; the caller commits. True when a row was removed.
    """
    remember_env_defaults(settings)
    selection = await get_active_override(db, owner_user_id=owner_user_id)
    if selection is None:
        return False
    await db.delete(selection)
    await db.flush()
    if _env_defaults is not None:
        settings.AI_MODEL = _env_defaults["model"]
        settings.AI_PROVIDER = _env_defaults["provider"]
    return True


async def load_into_settings(
    db: AsyncSession, settings: Any, *, owner_user_id: int | None = None
) -> bool:
    """Apply the resolved override to ``settings``. True when one applied.

    Called at startup so every process (webserver, scheduler, worker) boots on
    the model that was last selected. Startup has no user, so it resolves the
    install-wide default.
    """
    remember_env_defaults(settings)
    selection = await resolve_override(db, owner_user_id=owner_user_id)
    if selection is None:
        return False
    apply_to_settings(
        settings, model_id=selection.model_id, provider=selection.provider
    )
    return True


async def sync_from_db(settings: Any) -> bool:
    """Adopt the stored selection into ``settings``. True when one applied.

    Opens its own session, so a caller with no request and no session of its
    own can still ask. A database without the catalog table yet (a fresh
    install, a test) leaves the bootstrap defaults in place.
    """
    from app.core.db import get_async_session

    try:
        async with get_async_session() as session:
            return await load_into_settings(session, settings)
    except SQLAlchemyError as exc:
        logger.debug(f"Active-model selection unavailable, using .env: {exc}")
        return False


async def model_for_active(settings: Any) -> tuple[Any, str]:
    """A model instance for the selection actually in force, and its name.

    The selection is a database row, and only the webserver re-reads it per
    request. Anything headless - a worker task, a scheduled job - resolves
    through here, or it runs on the .env bootstrap model while the dashboard
    shows the model the user picked.
    """
    from app.services.ai.config import AIServiceConfig
    from app.services.ai.domains.llm import providers

    await sync_from_db(settings)
    return providers.model_for(AIServiceConfig.from_settings(settings), settings)

