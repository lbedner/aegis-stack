"""Memory endpoints: the modules an agent opts into, and the facts saved
about a user.

Its own sub-router (the finance API's pattern) rather than more lines in
the ai router: paths and behavior are identical either way, and the
aggregator stays readable. Both halves of the dashboard's Memory tab are
served from here.
"""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.log import logger
from app.services.ai.domains.chat.user_memory import DEFAULT_MEMORY_USER_ID

router = APIRouter()


class MemoryModuleUpdateRequest(BaseModel):
    """Partial update of a memory module's editable fields."""

    name: str | None = None
    description: str | None = None
    category: str | None = None
    prompt_content: str | None = None
    fetch_function: str | None = None
    context_key: str | None = None
    priority: int | None = None
    token_estimate: int | None = None
    is_active: bool | None = None


@router.get("/memory-modules")
async def list_registry_memory_modules() -> list[dict[str, Any]]:
    """Every memory module, active or not, in render order."""
    from app.core.db import get_async_session
    from app.services.ai.domains.chat.memory_modules import (
        list_memory_modules,
        serialize_memory_module,
    )

    try:
        async with get_async_session() as session:
            modules = await list_memory_modules(session, active_only=False)
            return [serialize_memory_module(module) for module in modules]
    except Exception as e:
        logger.exception("Failed to list memory modules")
        raise HTTPException(
            status_code=500, detail="Failed to list memory modules"
        ) from e


@router.patch("/memory-modules/{slug}")
async def update_registry_memory_module(
    slug: str, request: MemoryModuleUpdateRequest
) -> dict[str, Any]:
    """Apply a partial memory-module update."""
    from app.core.db import get_async_session
    from app.services.ai.domains.chat.memory_modules import (
        InvalidMemoryModuleError,
        serialize_memory_module,
        update_memory_module,
    )

    changes = request.model_dump(exclude_unset=True)
    try:
        async with get_async_session() as session:
            module = await update_memory_module(slug, session=session, **changes)
            return serialize_memory_module(module)
    except InvalidMemoryModuleError as e:
        # The service raises one error type for "no such module" and for a
        # rejected change; a missing slug is the only 404-shaped one.
        status = 404 if "not found" in str(e) else 400
        raise HTTPException(status_code=status, detail=str(e)) from None
    except Exception as e:
        logger.exception("Failed to update memory module")
        raise HTTPException(
            status_code=500, detail="Failed to update memory module"
        ) from e


@router.get("/memory-modules/{slug}/preview")
async def preview_registry_memory_module(
    slug: str, user_id: str = DEFAULT_MEMORY_USER_ID
) -> dict[str, Any]:
    """Render a module exactly as an agent turn would see it.

    A module whose content comes from a fetcher has nothing to show in its
    row: the text is produced per request. This runs the real renderer so the
    dashboard can display what the model would actually be handed, which is
    the only way to tell a working module from a silently empty one.
    """
    from app.services.ai.domains.chat.module_context import render_memory_modules

    try:
        rendered = await render_memory_modules([slug], user_id=user_id)
    except Exception as e:
        logger.exception("Failed to render memory module")
        raise HTTPException(
            status_code=500, detail="Failed to render memory module"
        ) from e
    return {"slug": slug, "user_id": user_id, "rendered": rendered}


class UserFactUpdateRequest(BaseModel):
    """Partial edit of one saved fact."""

    fact: str | None = None
    category: str | None = None


@router.get("/user-memory")
async def list_saved_user_facts(user_id: str = DEFAULT_MEMORY_USER_ID) -> dict[str, Any]:
    """Durable facts the assistant saved about this user.

    The other half of what an agent is handed: memory modules are what the
    system assembles, these are what the user told it.
    """
    from app.core.db import get_async_session
    from app.services.ai.domains.chat import user_memory

    try:
        async with get_async_session() as session:
            facts = await user_memory.list_user_facts(user_id, session=session)
    except Exception as e:
        logger.exception("Failed to list saved facts")
        raise HTTPException(status_code=500, detail="Failed to list saved facts") from e
    return {"user_id": user_id, "facts": facts}


@router.patch("/user-memory/{index}")
async def update_saved_user_fact(
    index: int,
    request: UserFactUpdateRequest,
    user_id: str = DEFAULT_MEMORY_USER_ID,
) -> dict[str, Any]:
    """Correct one saved fact in place."""
    from app.core.db import get_async_session
    from app.services.ai.domains.chat import user_memory

    try:
        async with get_async_session() as session:
            return await user_memory.update_user_fact(
                user_id,
                index,
                fact=request.fact,
                category=request.category,
                session=session,
            )
    except IndexError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except Exception as e:
        logger.exception("Failed to update saved fact")
        raise HTTPException(
            status_code=500, detail="Failed to update saved fact"
        ) from e


@router.delete("/user-memory/{index}")
async def delete_saved_user_fact(
    index: int, user_id: str = DEFAULT_MEMORY_USER_ID
) -> dict[str, Any]:
    """Forget one saved fact."""
    from app.core.db import get_async_session
    from app.services.ai.domains.chat import user_memory

    try:
        async with get_async_session() as session:
            await user_memory.delete_user_fact(user_id, index, session=session)
    except IndexError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except Exception as e:
        logger.exception("Failed to delete saved fact")
        raise HTTPException(
            status_code=500, detail="Failed to delete saved fact"
        ) from e
    return {"deleted": True, "index": index}
