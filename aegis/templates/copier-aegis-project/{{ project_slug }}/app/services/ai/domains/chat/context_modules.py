"""Context module CRUD (hybrid, column-driven).

Context modules are reusable prompt-context blocks agents opt into via
``Agent.context_modules``; what each content source is, and the order
they render in, is ``ContextModule``'s docstring. The one invariant
enforced here: a module must have at least one source, since an empty
module can never contribute context.
"""

from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.log import logger
from app.core.time import utcnow
from app.services.ai.domains.chat import queries
from app.services.ai.models.agents import ContextModule, ContextModuleEntry


class InvalidContextModuleError(ValueError):
    """Raised when a module create/update violates the module invariants."""


def _validate_content(
    prompt_content: str | None, fetch_function: str | None, per_subject: bool
) -> None:
    if not prompt_content and not fetch_function and not per_subject:
        raise InvalidContextModuleError(
            "A context module needs prompt_content, fetch_function or per_subject text"
        )


async def get_context_module(session: AsyncSession, slug: str) -> ContextModule | None:
    """Fetch one module by slug, or None."""
    return await queries.context_module_by_slug(session, slug)


async def _require_module(session: AsyncSession, slug: str) -> ContextModule:
    module = await get_context_module(session, slug)
    if module is None:
        raise InvalidContextModuleError(f"Context module '{slug}' not found")
    return module


async def list_context_modules(
    session: AsyncSession, *, active_only: bool = True
) -> list[ContextModule]:
    """List modules ordered by priority (lowest number renders first)."""
    return list(
        await queries.context_modules_by_priority(session, active_only=active_only)
    )


async def create_context_module(
    *,
    slug: str,
    name: str,
    description: str | None = None,
    category: str | None = None,
    prompt_content: str | None = None,
    fetch_function: str | None = None,
    per_subject: bool = False,
    context_key: str | None = None,
    supports_days_back: bool = False,
    default_days_back: int | None = None,
    priority: int = 100,
    token_estimate: int = 0,
    is_active: bool = True,
    session: AsyncSession,
) -> ContextModule:
    """Create a module. ``context_key`` defaults to the slug."""
    _validate_content(prompt_content, fetch_function, per_subject)
    if await get_context_module(session, slug) is not None:
        raise InvalidContextModuleError(f"Context module '{slug}' already exists")

    module = ContextModule(
        slug=slug,
        name=name,
        description=description,
        category=category,
        prompt_content=prompt_content,
        fetch_function=fetch_function,
        per_subject=per_subject,
        context_key=context_key or slug,
        supports_days_back=supports_days_back,
        default_days_back=default_days_back,
        priority=priority,
        token_estimate=token_estimate,
        is_active=is_active,
    )
    session.add(module)
    await session.commit()
    logger.info("Created context module", module_slug=slug)
    return module


async def update_context_module(
    slug: str,
    *,
    session: AsyncSession,
    **changes: Any,
) -> ContextModule:
    """Apply field changes to a module, preserving the content invariant.

    Passing ``prompt_content=None`` / ``fetch_function=None`` clears that
    column; the update is rejected if it would leave the module with
    neither content source.
    """
    module = await _require_module(session, slug)

    allowed = set(ContextModule.model_fields) - {"id", "slug", "created_at"}
    unknown = set(changes) - allowed
    if unknown:
        raise InvalidContextModuleError(
            f"Unknown context module fields: {sorted(unknown)}"
        )

    _validate_content(
        changes.get("prompt_content", module.prompt_content),
        changes.get("fetch_function", module.fetch_function),
        changes.get("per_subject", module.per_subject),
    )

    for field, value in changes.items():
        setattr(module, field, value)
    module.updated_at = utcnow()
    session.add(module)
    await session.commit()
    logger.info("Updated context module", module_slug=slug)
    return module


async def delete_context_module(slug: str, *, session: AsyncSession) -> None:
    """Delete a module by slug, and its entries with it: deleted here, not
    left to the key's cascade, which SQLite runs only with foreign keys on.
    Unknown slugs are an error, not a no-op."""
    module = await _require_module(session, slug)
    for entry in await queries.context_entries_of(session, module.id):
        await session.delete(entry)
    await session.delete(module)
    await session.commit()
    logger.info("Deleted context module", module_slug=slug)


async def _per_subject_module(session: AsyncSession, slug: str) -> ContextModule:
    module = await _require_module(session, slug)
    if not module.per_subject:
        raise InvalidContextModuleError(
            f"Context module '{slug}' holds no text per subject"
        )
    return module


async def get_context_entry(
    slug: str, subject: str, *, session: AsyncSession
) -> str | None:
    """Module ``slug``'s text for ``subject``, or None when it has none."""
    module = await _per_subject_module(session, slug)
    entry = await queries.context_entry(session, module.id, subject)
    return entry.content if entry else None


async def set_context_entry(
    slug: str,
    subject: str,
    content: str,
    *,
    user_id: int | None = None,
    session: AsyncSession,
) -> ContextModuleEntry | None:
    """Write module ``slug``'s text for ``subject``; blank text removes it.

    Who may write a subject's text is the app's to decide, as it decides
    who may talk about the subject: this only records who did.
    """
    module = await _per_subject_module(session, slug)
    entry = await queries.context_entry(session, module.id, subject)
    text = content.strip()
    if not text:
        if entry is not None:
            await session.delete(entry)
            await session.commit()
        return None
    if entry is None:
        try:
            async with session.begin_nested():
                entry = ContextModuleEntry(
                    module_id=module.id, subject=subject, content=text
                )
                session.add(entry)
                await session.flush()
        except IntegrityError:
            # Another write made this subject's entry between our read and
            # our insert: that one is replaced instead.
            entry = await queries.context_entry(session, module.id, subject)
            if entry is None:
                raise
    entry.content = text
    entry.updated_by_user_id = user_id
    entry.updated_at = utcnow()
    session.add(entry)
    await session.commit()
    logger.info("Set context entry", module_slug=slug, subject=subject)
    return entry


def module_sources(module: ContextModule) -> list[str]:
    """Where a module's content comes from, in render order: ``static``,
    ``subject``, ``fetcher``. Named rather than implied, because each fails
    differently (static text is wrong in the database, a subject's text is
    wrong for that subject, a fetcher is wrong in code); every surface that
    shows a module reads this one answer."""
    return [
        source
        for source, present in (
            ("static", bool(module.prompt_content)),
            ("subject", module.per_subject),
            ("fetcher", bool(module.fetch_function)),
        )
        if present
    ]


def serialize_context_module(module: ContextModule) -> dict[str, Any]:
    """API/UI shape for one module row.

    Mirrors ``agent_registry.serialize_agent``: the dashboard and the API read
    the same dict, so a field added here shows up in both.
    """
    return {
        "slug": module.slug,
        "name": module.name,
        "description": module.description,
        "category": module.category,
        "prompt_content": module.prompt_content,
        "fetch_function": module.fetch_function,
        "per_subject": module.per_subject,
        "sources": module_sources(module),
        "context_key": module.context_key,
        "supports_days_back": module.supports_days_back,
        "default_days_back": module.default_days_back,
        "priority": module.priority,
        "token_estimate": module.token_estimate,
        "is_active": module.is_active,
    }
