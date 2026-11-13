"""Gemini's voice library: its voices beyond the 30 prebuilt ones (about two
thousand, regional accents among them, over many pages), listed with its
key (``client.voices.list``) and kept for the process, so the catalog
finds them by id (``KEPT``). Gemini's 3.8 speech models speak them; Gemini
Live keeps to the prebuilt 30.

Its first answer takes seconds, so nothing waits on it: the first ask
starts the load in the background (``fill``) and every ask gets what is in
so far.
"""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from app.core.concurrency import background
from app.core.log import logger

from .models import TTSProvider, VoiceInfo

# The library's voices by id, as they come in; and whether its load has
# been started this process (an unreadable library is not asked again).
KEPT: dict[str, VoiceInfo] = {}
TRIED: set[str] = set()
# The load in flight, for whoever must see it through (a test).
LOADING: set[asyncio.Task[None]] = set()
PAGE = 200
# How long the whole library may take before the load gives up.
WAIT_SECONDS = 120.0


def _client(key: str) -> Any:
    from google import genai

    return genai.Client(api_key=key)


def _kept(found: Any, models: list[str]) -> VoiceInfo:
    """One of the library's voices, as the catalog lists a voice: its tone
    the one its description says (the library gives a persona there)."""
    from .traits import tone_in

    return VoiceInfo(
        id=found.id,
        name=found.display_name or found.id,
        provider_id=TTSProvider.GEMINI.value,
        model_ids=models,
        description=found.description or found.persona or "Gemini voice library",
        gender=(found.gender or "neutral").lower(),
        tone=tone_in(found.description or ""),
        accent=found.accent,
    )


async def fill(key: str) -> None:
    """Every page of the library into ``KEPT`` (the prebuilt left as they
    are); where it cannot be read, why, in the log."""
    from .catalog import GEMINI_PREBUILT, gemini_models

    # The library lists the prebuilt again, under lowercase ids.
    prebuilt = {name.lower() for name in GEMINI_PREBUILT}
    client, models, token = _client(key), gemini_models(), None
    try:
        async with asyncio.timeout(WAIT_SECONDS):
            while True:
                page = {"page_token": token} if token else {}
                listed = await client.aio.voices.list(page_size=PAGE, **page)
                for found in listed.voices or []:
                    if found.id and found.id.lower() not in prebuilt:
                        KEPT[found.id] = _kept(found, models)
                if not (token := listed.next_page_token):
                    return
    except Exception:  # the provider's own (the key, the network) or the wait
        logger.exception("Gemini's voice library could not be read")


def _looping() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:  # no loop: a sync caller
        return False
    return True


def load_once(name: str, load: Callable[[], Coroutine[object, object, None]]) -> None:
    """``load`` started in the background the first time ``name`` is asked
    for in this process (one that could not be read is not asked again,
    unless its load forgets it in ``TRIED``); none waits on it. Outside a
    running loop (a sync caller) nothing starts: the next ask in one does."""
    if name in TRIED or not _looping():
        return
    TRIED.add(name)
    task = background(load())
    LOADING.add(task)
    task.add_done_callback(LOADING.discard)


async def gemini_library(key: str) -> list[VoiceInfo]:
    """The library's voices in so far; the first ask (per process) starts
    the load (``load_once``)."""
    load_once("gemini", lambda: fill(key))
    return list(KEPT.values())
