"""The Overseer AI page's Voice section: what speaks and what listens, as
settings configure them (``TTS_*``/``STT_*`` in ``.env``), each provider's
key state; every voice of the speaking provider with a play button; a
sentence spoken in a chosen voice; and an audio file transcribed.

Playback is the voice API's preview route (an ``<audio>`` points at it);
transcription is the speech API's own ``transcribe_audio``. Nothing here
synthesizes or transcribes on its own. Offered wherever ``ai[...,voice]``
installed the voice domain.
"""

from typing import Any

from fastapi import UploadFile

from app.core.config import settings

from .overseer_ai_common import PARTIALS

PREVIEW = "/api/v1/voice/preview/"


def _provider(providers: list[Any], provider_id: str) -> dict[str, Any]:
    """A provider's name and whether its key is set (named when missing)."""
    info = next((p for p in providers if p.id == provider_id), None)
    if info is None:
        return {"name": provider_id, "key": None}
    if not info.requires_api_key:
        return {"name": info.name, "key": "Not needed"}
    key = info.api_key_env_var
    return {
        "name": info.name,
        "key": "Set" if key and getattr(settings, key, None) else f"{key} missing",
    }


def voice_context() -> dict[str, Any]:
    from app.services.ai.domains.voice import (
        get_current_voice_config,
        get_stt_providers,
        get_tts_providers,
        get_tts_voices,
    )

    config = get_current_voice_config(settings)
    speaker = _provider(get_tts_providers(), config["tts_provider"])
    listener = _provider(get_stt_providers(), config["stt_provider"])
    voices = get_tts_voices(config["tts_provider"])
    return {
        "speaking": [
            ("Provider", speaker["name"]),
            ("Key", speaker["key"]),
            ("Model", config["tts_model"]),
            ("Voice", config["tts_voice"]),
            ("Speed", config["tts_speed"]),
        ],
        "listening": [
            ("Provider", listener["name"]),
            ("Key", listener["key"]),
            ("Model", config["stt_model"]),
            ("Language", config.get("stt_language") or "Detected"),
        ],
        "voices": [
            {
                "name": v.name,
                "description": v.description,
                "gender": (v.gender or "").title() or None,
                "tone": v.category.value.title() if v.category else None,
                "preview": f"{PREVIEW}{v.id}",
            }
            for v in voices
        ],
        "voice_options": [{"id": v.id, "name": v.name} for v in voices],
        "current_voice": config["tts_voice"],
        "preview_base": PREVIEW,
        "transcribe_url": f"{PARTIALS}/voice/transcribe",
    }


async def transcribe(audio: UploadFile) -> Any:
    """The speech API's transcription, unchanged: its format checks and its
    errors (``HTTPException``) are the page's too."""
    from app.components.backend.api.ai.speech import transcribe_audio

    return await transcribe_audio(audio=audio, language=None)
