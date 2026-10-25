"""Gemini's voice library: its voices beyond the 30 prebuilt ones (regional
accents among them), listed with its key (``client.voices.list``) and kept
for the process, so the catalog finds them by id (``KEPT``). Gemini's 3.8
speech models speak them; Gemini Live keeps to the prebuilt 30.
"""

import asyncio
from typing import Any

from app.core.log import logger

from .models import TTSProvider, VoiceInfo

# The library's voices by id, once listed; and whether it has been tried
# this process (an empty or unreadable library is not asked again).
KEPT: dict[str, VoiceInfo] = {}
TRIED: set[str] = set()
PAGE = 200
# How long a page's draw waits for the library before going on without it.
WAIT_SECONDS = 5.0


def _client(key: str) -> Any:
    from google import genai

    return genai.Client(api_key=key)


async def gemini_library(key: str) -> list[VoiceInfo]:
    """The library's voices beyond the prebuilt ones, asked for once per
    process (within ``WAIT_SECONDS``); none (and why, in the log) where it
    cannot be read."""
    from .catalog import GEMINI_PREBUILT, gemini_models

    if "gemini" in TRIED:
        return list(KEPT.values())
    TRIED.add("gemini")
    try:
        listed = await asyncio.wait_for(
            _client(key).aio.voices.list(page_size=PAGE), WAIT_SECONDS
        )
    except Exception:  # the provider's own (the key, the network) or the wait
        logger.exception("Gemini's voice library could not be read")
        return []
    for found in listed.voices or []:
        if not found.id or found.id in GEMINI_PREBUILT:
            continue
        KEPT[found.id] = VoiceInfo(
            id=found.id,
            name=found.display_name or found.id,
            provider_id=TTSProvider.GEMINI.value,
            model_ids=gemini_models(),
            description=found.description or found.persona or "Gemini voice library",
            gender=(found.gender or "neutral").lower(),
            tone=found.persona,
            accent=found.accent,
        )
    return list(KEPT.values())
