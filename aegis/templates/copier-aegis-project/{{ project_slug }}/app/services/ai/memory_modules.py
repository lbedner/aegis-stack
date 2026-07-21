"""Memory module CRUD (hybrid, column-driven).

Memory modules are reusable prompt-context blocks agents opt into via
``Agent.memory_modules``. A module carries static ``prompt_content``, a
dynamic ``fetch_function`` (a registered fetcher name), or both; the
renderer emits the static block first, then the live data. The one
invariant enforced here: a module must have at least one of the two,
since an empty module can never contribute context.
"""

from datetime import UTC, datetime
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.log import logger
from app.services.ai.models.agents import MemoryModule


class InvalidMemoryModuleError(ValueError):
    """Raised when a module create/update violates the module invariants."""


def _validate_content(
    prompt_content: str | None, fetch_function: str | None
) -> None:
    if not prompt_content and not fetch_function:
        raise InvalidMemoryModuleError(
            "A memory module needs prompt_content, fetch_function, or both"
        )


async def get_memory_module(
    session: AsyncSession, slug: str
) -> MemoryModule | None:
    """Fetch one module by slug, or None."""
    result = await session.exec(
        select(MemoryModule).where(MemoryModule.slug == slug)
    )
    return result.first()


async def list_memory_modules(
    session: AsyncSession, *, active_only: bool = True
) -> list[MemoryModule]:
    """List modules ordered by priority (lowest number renders first)."""
    stmt = select(MemoryModule).order_by(MemoryModule.priority)  # type: ignore[arg-type]
    if active_only:
        stmt = stmt.where(MemoryModule.is_active)
    result = await session.exec(stmt)
    return list(result.all())


async def create_memory_module(
    *,
    slug: str,
    name: str,
    description: str | None = None,
    category: str | None = None,
    prompt_content: str | None = None,
    fetch_function: str | None = None,
    context_key: str | None = None,
    supports_days_back: bool = False,
    default_days_back: int | None = None,
    priority: int = 100,
    token_estimate: int = 0,
    is_active: bool = True,
    session: AsyncSession,
) -> MemoryModule:
    """Create a module. ``context_key`` defaults to the slug."""
    _validate_content(prompt_content, fetch_function)
    if await get_memory_module(session, slug) is not None:
        raise InvalidMemoryModuleError(f"Memory module '{slug}' already exists")

    module = MemoryModule(
        slug=slug,
        name=name,
        description=description,
        category=category,
        prompt_content=prompt_content,
        fetch_function=fetch_function,
        context_key=context_key or slug,
        supports_days_back=supports_days_back,
        default_days_back=default_days_back,
        priority=priority,
        token_estimate=token_estimate,
        is_active=is_active,
    )
    session.add(module)
    await session.commit()
    await session.refresh(module)
    logger.info("Created memory module", module_slug=slug)
    return module


async def update_memory_module(
    slug: str,
    *,
    session: AsyncSession,
    **changes: Any,
) -> MemoryModule:
    """Apply field changes to a module, preserving the content invariant.

    Passing ``prompt_content=None`` / ``fetch_function=None`` clears that
    column; the update is rejected if it would leave the module with
    neither content source.
    """
    module = await get_memory_module(session, slug)
    if module is None:
        raise InvalidMemoryModuleError(f"Memory module '{slug}' not found")

    allowed = set(MemoryModule.model_fields) - {"id", "slug", "created_at"}
    unknown = set(changes) - allowed
    if unknown:
        raise InvalidMemoryModuleError(
            f"Unknown memory module fields: {sorted(unknown)}"
        )

    prompt_content = changes.get("prompt_content", module.prompt_content)
    fetch_function = changes.get("fetch_function", module.fetch_function)
    _validate_content(prompt_content, fetch_function)

    for field, value in changes.items():
        setattr(module, field, value)
    module.updated_at = datetime.now(UTC)
    session.add(module)
    await session.commit()
    await session.refresh(module)
    logger.info("Updated memory module", module_slug=slug)
    return module


async def delete_memory_module(slug: str, *, session: AsyncSession) -> None:
    """Delete a module by slug. Unknown slugs are an error, not a no-op."""
    module = await get_memory_module(session, slug)
    if module is None:
        raise InvalidMemoryModuleError(f"Memory module '{slug}' not found")
    await session.delete(module)
    await session.commit()
    logger.info("Deleted memory module", module_slug=slug)
