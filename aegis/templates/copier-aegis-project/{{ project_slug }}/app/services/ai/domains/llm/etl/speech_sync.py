"""The speech server's models in the catalog (``app.core.speech_server``):
what it serves, as speech models (``audio_speech``) under its own name,
beside the inference engine's chat models (``LLMSyncService.sync_local``),
so the catalog lists it with the cloud voices. OpenAI's model names it
answers to are aliases of its own, not models: the catalog keeps OpenAI's
under OpenAI. A server not set or not running is no failed sync: it is
optional, and it is read again on the next one."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core import speech_server
from app.core.config import settings
from app.core.log import logger
from app.services.ai.domains.llm.etl.results import SyncResult
from app.services.ai.models.llm import LargeLanguageModel

if TYPE_CHECKING:
    from app.services.ai.domains.llm.etl.llm_sync_service import LLMSyncService

MODE = "audio_speech"


async def sync_speech(service: LLMSyncService, dry_run: bool) -> SyncResult:
    """The server's own models into the catalog, the ones it stopped
    serving turned off (``_retire_unserved``, as the engine's are)."""
    result = SyncResult()
    url = speech_server.reach(settings)
    if not url:
        return result
    reading = await speech_server.read(url)
    if not reading.available:
        logger.info(f"{speech_server.NAME} not read at {url}: {reading.error}")
        return result
    own = [m for m in reading.models if m not in speech_server.OPENAI_MODELS]
    service._load_caches()
    vendor = service._upsert_vendor(speech_server.SLUG, result, dry_run)
    if vendor is None:
        return result
    for model_id in own:
        existing = service._model_cache.get(model_id)
        if existing is None:
            model = LargeLanguageModel(
                model_id=model_id,
                title=f"{speech_server.NAME} {model_id}",
                mode=MODE,
                streamable=True,
                enabled=True,
                served_by_org_id=vendor.id,
            )
            if not dry_run:
                service.session.add(model)
                service.session.flush()
            service._model_cache[model_id] = model
            result.models_added += 1
        elif not existing.enabled:
            existing.enabled = True
            if not dry_run:
                service.session.add(existing)
            result.models_updated += 1
    service._retire_unserved(vendor, set(own), result, dry_run)
    if not dry_run:
        service.session.commit()
    return result
