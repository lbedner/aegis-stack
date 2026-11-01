"""The model kept whole for every process. Built, it imports the whole app
(every route, job and tool, to read them), so a worker that built its own
held all that code for a map of a few hundred nodes. The webserver, where
every part registers, keeps the model it builds in Redis (``keep``); a
process where nothing registered reads that one (``twin``) and builds its
own only when none is kept. Without Redis nothing is kept: each process
builds its own, as ever."""

import asyncio

from pydantic import ValidationError

from app.core.cache import CACHE_ERRORS, get_cache
from app.core.key_family import KeyFamily
from app.core.log import logger
from app.core.ontology import system
from app.core.ontology.model import SystemModel

KEY = "ontology:model"
KEEP_SECONDS = 30 * 86_400  # written again each time the webserver starts

REDIS_KEYS = (
    KeyFamily(
        KEY,
        "string",
        "System model",
        "The model of the app the webserver built, for every other process",
        "Ontology",
        db="CACHE_REDIS_DB",
    ),
)


async def keep(model: SystemModel) -> None:
    """Keep ``model`` for the other processes: a whole one, in Redis."""
    cache = get_cache()
    if model.partial or cache.backend_name != "redis":
        return
    whole = await asyncio.to_thread(model.model_dump_json)
    try:
        await cache.set(KEY, whole, KEEP_SECONDS)
    except CACHE_ERRORS as exc:
        logger.warning(
            "System model not kept: the cache did not answer", error=str(exc)
        )


async def kept() -> SystemModel | None:
    """The model the webserver kept; None for none, or one another build
    wrote."""
    try:
        stored = await get_cache().get(KEY)
    except CACHE_ERRORS as exc:
        logger.warning("System model unread: the cache did not answer", error=str(exc))
        return None
    if not isinstance(stored, str):
        return None
    try:
        return await asyncio.to_thread(SystemModel.model_validate_json, stored)
    except ValidationError:
        return None


async def twin() -> SystemModel:
    """The model, for an async reader: this process's (``system.current``);
    the one kept, read once, where none is built yet and nothing registered."""
    unbuilt = system._kept is None and not system._registered()
    stored = await kept() if unbuilt else None
    return await asyncio.to_thread(system.current, stored)
