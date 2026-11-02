"""Context module CRUD (hybrid, column-driven).

Context modules are reusable prompt-context blocks agents opt into via
``Agent.context_modules``. A module carries static ``prompt_content``, a
dynamic ``fetch_function`` (a registered fetcher name), or both; the
renderer emits the static block first, then the live data. The one
invariant enforced here: a module must have at least one of the two,
since an empty module can never contribute context.
"""

from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.log import logger
from app.core.time import utcnow
from app.services.ai.domains.chat import queries
from app.services.ai.models.agents import ContextModule


class InvalidContextModuleError(ValueError):
    """Raised when a module create/update violates the module invariants."""


def _validate_content(prompt_content: str | None, fetch_function: str | None) -> None:
    if not prompt_content and not fetch_function:
        raise InvalidContextModuleError(
            "A context module needs prompt_content, fetch_function, or both"
        )


async def get_context_module(session: AsyncSession, slug: str) -> ContextModule | None:
    """Fetch one module by slug, or None."""
    return await queries.context_module_by_slug(session, slug)


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
    context_key: str | None = None,
    supports_days_back: bool = False,
    default_days_back: int | None = None,
    priority: int = 100,
    token_estimate: int = 0,
    is_active: bool = True,
    session: AsyncSession,
) -> ContextModule:
    """Create a module. ``context_key`` defaults to the slug."""
    _validate_content(prompt_content, fetch_function)
    if await get_context_module(session, slug) is not None:
        raise InvalidContextModuleError(f"Context module '{slug}' already exists")

    module = ContextModule(
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
    module = await get_context_module(session, slug)
    if module is None:
        raise InvalidContextModuleError(f"Context module '{slug}' not found")

    allowed = set(ContextModule.model_fields) - {"id", "slug", "created_at"}
    unknown = set(changes) - allowed
    if unknown:
        raise InvalidContextModuleError(
            f"Unknown context module fields: {sorted(unknown)}"
        )

    prompt_content = changes.get("prompt_content", module.prompt_content)
    fetch_function = changes.get("fetch_function", module.fetch_function)
    _validate_content(prompt_content, fetch_function)

    for field, value in changes.items():
        setattr(module, field, value)
    module.updated_at = utcnow()
    session.add(module)
    await session.commit()
    logger.info("Updated context module", module_slug=slug)
    return module


async def delete_context_module(slug: str, *, session: AsyncSession) -> None:
    """Delete a module by slug. Unknown slugs are an error, not a no-op."""
    module = await get_context_module(session, slug)
    if module is None:
        raise InvalidContextModuleError(f"Context module '{slug}' not found")
    await session.delete(module)
    await session.commit()
    logger.info("Deleted context module", module_slug=slug)


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
        "context_key": module.context_key,
        "supports_days_back": module.supports_days_back,
        "default_days_back": module.default_days_back,
        "priority": module.priority,
        "token_estimate": module.token_estimate,
        "is_active": module.is_active,
    }
