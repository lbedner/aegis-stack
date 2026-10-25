"""
Voice Catalog and Settings API Router

Provides endpoints for querying TTS/STT providers, models, and voices,
as well as managing voice settings and generating voice previews.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.components.backend.api.voice.overview import router as overview_router
from app.core.config import settings
from app.core.log import logger
from app.services.ai.domains.voice import (
    ModelInfo,
    ProviderInfo,
    SpeechRequest,
    VoiceInfo,
    VoicePreviewRequest,
    VoiceSettingsResponse,
    get_current_voice_config,
    get_stt_models,
    get_stt_providers,
    get_tts_models,
    get_tts_providers,
    get_tts_voices,
    get_voice,
    speaking_model,
)
from app.services.ai.service import TTSService

router = APIRouter(prefix="/voice", tags=["voice"])


# =============================================================================
# API Response Models (for OpenAPI schema)
# =============================================================================


class ProviderResponse(BaseModel):
    """Provider information response."""

    id: str
    name: str
    type: str
    requires_api_key: bool
    api_key_env_var: str | None = None
    is_local: bool
    description: str | None = None

    @classmethod
    def from_provider_info(cls, p: ProviderInfo) -> "ProviderResponse":
        """Create from ProviderInfo."""
        return cls(
            id=p.id,
            name=p.name,
            type=p.type,
            requires_api_key=p.requires_api_key,
            api_key_env_var=p.api_key_env_var,
            is_local=p.is_local,
            description=p.description,
        )


class ModelResponse(BaseModel):
    """Model information response."""

    id: str
    name: str
    provider_id: str
    quality: str
    description: str | None = None
    supports_streaming: bool

    @classmethod
    def from_model_info(cls, m: ModelInfo) -> "ModelResponse":
        """Create from ModelInfo."""
        return cls(
            id=m.id,
            name=m.name,
            provider_id=m.provider_id,
            quality=m.quality,
            description=m.note,
            supports_streaming=m.supports_streaming,
        )


class VoiceResponse(BaseModel):
    """Voice information response."""

    id: str
    name: str
    provider_id: str
    model_ids: list[str]
    description: str
    tone: str | None = None
    gender: str | None = None
    preview_text: str

    @classmethod
    def from_voice_info(cls, v: VoiceInfo) -> "VoiceResponse":
        """Create from VoiceInfo."""
        return cls(
            id=v.id,
            name=v.name,
            provider_id=v.provider_id,
            model_ids=v.model_ids,
            description=v.description,
            tone=v.tone,
            gender=v.gender,
            preview_text=v.preview_text,
        )


class CatalogSummaryResponse(BaseModel):
    """Catalog summary response."""

    class TTSSummary(BaseModel):
        provider_count: int
        model_count: int
        voice_count: int
        providers: list[str]

    class STTSummary(BaseModel):
        provider_count: int
        model_count: int
        providers: list[str]

    tts: TTSSummary
    stt: STTSummary
    current_config: VoiceSettingsResponse


# =============================================================================
# TTS Catalog Endpoints
# =============================================================================


@router.get("/catalog/tts/providers", response_model=list[ProviderResponse])
async def list_tts_providers() -> list[ProviderResponse]:
    """
    List all available TTS providers.

    Returns information about each TTS provider including whether
    it requires an API key and if it runs locally.
    """
    providers = get_tts_providers()
    return [ProviderResponse.from_provider_info(p) for p in providers]


@router.get("/catalog/tts/{provider_id}/models", response_model=list[ModelResponse])
async def list_tts_models(provider_id: str) -> list[ModelResponse]:
    """
    List TTS models for a specific provider.

    Args:
        provider_id: Provider identifier (e.g., 'openai')

    Returns:
        List of models available for this provider
    """
    models = get_tts_models(provider_id)
    if not models:
        # Check if provider exists
        providers = get_tts_providers()
        provider_ids = [p.id for p in providers]
        if provider_id not in provider_ids:
            raise HTTPException(
                status_code=404,
                detail=f"TTS provider not found: {provider_id}. "
                f"Available: {', '.join(provider_ids)}",
            )
    return [ModelResponse.from_model_info(m) for m in models]


@router.get("/catalog/tts/{provider_id}/voices", response_model=list[VoiceResponse])
async def list_tts_voices(provider_id: str) -> list[VoiceResponse]:
    """
    List TTS voices for a specific provider.

    Args:
        provider_id: Provider identifier (e.g., 'openai')

    Returns:
        List of voices available for this provider
    """
    voices = get_tts_voices(provider_id=provider_id)
    if not voices:
        # Check if provider exists
        providers = get_tts_providers()
        provider_ids = [p.id for p in providers]
        if provider_id not in provider_ids:
            raise HTTPException(
                status_code=404,
                detail=f"TTS provider not found: {provider_id}. "
                f"Available: {', '.join(provider_ids)}",
            )
    return [VoiceResponse.from_voice_info(v) for v in voices]


# =============================================================================
# STT Catalog Endpoints
# =============================================================================


@router.get("/catalog/stt/providers", response_model=list[ProviderResponse])
async def list_stt_providers() -> list[ProviderResponse]:
    """
    List all available STT providers.

    Returns information about each STT provider including whether
    it requires an API key and if it runs locally.
    """
    providers = get_stt_providers()
    return [ProviderResponse.from_provider_info(p) for p in providers]


@router.get("/catalog/stt/{provider_id}/models", response_model=list[ModelResponse])
async def list_stt_models(provider_id: str) -> list[ModelResponse]:
    """
    List STT models for a specific provider.

    Args:
        provider_id: Provider identifier (e.g., 'openai_whisper', 'groq_whisper')

    Returns:
        List of models available for this provider
    """
    models = get_stt_models(provider_id)
    if not models:
        # Check if provider exists
        providers = get_stt_providers()
        provider_ids = [p.id for p in providers]
        if provider_id not in provider_ids:
            raise HTTPException(
                status_code=404,
                detail=f"STT provider not found: {provider_id}. "
                f"Available: {', '.join(provider_ids)}",
            )
    return [ModelResponse.from_model_info(m) for m in models]


# =============================================================================
# Settings Endpoints
# =============================================================================


@router.get("/settings", response_model=VoiceSettingsResponse)
async def get_voice_settings() -> VoiceSettingsResponse:
    """
    Get current voice settings.

    Returns the current TTS and STT configuration from application settings.
    """
    config = get_current_voice_config(settings)
    return VoiceSettingsResponse(**config)


# =============================================================================
# Preview Endpoint
# =============================================================================


@router.post("/preview")
async def generate_voice_preview(request: VoicePreviewRequest) -> Response:
    """
    Generate a voice preview audio clip (POST).

    Creates a short audio sample demonstrating the selected voice.

    Args:
        request: Voice ID and optional custom text

    Returns:
        Audio file (audio/mpeg) with the synthesized preview

    Raises:
        HTTPException: 404 if voice not found
        HTTPException: 503 if TTS service error
    """
    return await _generate_preview(request.voice_id, request.text, None)


@router.get("/preview/{voice_id}")
async def get_voice_preview(
    voice_id: str,
    text: str | None = None,
    speed: float | None = None,
    model: str | None = None,
) -> Response:
    """
    Generate a voice preview audio clip (GET).

    Browser-friendly endpoint for audio playback via URL.

    Args:
        voice_id: Voice ID to preview
        text: Optional custom text
        speed: Optional speed multiplier (0.25 to 4.0, default 1.0)
        model: The model to say it on, when it speaks the voice

    Returns:
        The synthesized preview, as its provider makes it (MP3 or WAV)
    """
    return await _generate_preview(voice_id, text, speed, model)


async def _generate_preview(
    voice_id: str,
    text: str | None = None,
    speed: float | None = None,
    model: str | None = None,
) -> Response:
    """The voice saying ``text`` (else its preview line), in the delivery in
    use, on ``model`` or the model in use where either speaks it, else on
    one that does (``speaking_model``): a voice listed always plays."""
    voice = get_voice(voice_id)
    if not voice:
        raise HTTPException(status_code=404, detail=f"Voice not found: {voice_id}")

    preview_text = text or voice.preview_text.format(voice_name=voice.name)
    spoken = settings.model_copy(
        update={
            "TTS_PROVIDER": voice.provider_id,
            "TTS_MODEL": speaking_model(voice_id, model or settings.TTS_MODEL),
            "TTS_VOICE": voice_id,
        }
    )

    try:
        speech_request = SpeechRequest(
            text=preview_text,
            voice=voice_id,
            speed=speed or 1.0,
        )
        result = await TTSService(spoken).synthesize(speech_request)

        return Response(
            content=result.audio,
            media_type=result.media_type,
            headers={
                "Content-Disposition": (
                    f'inline; filename="{voice_id}_preview.{result.format.value}"'
                ),
                "Cache-Control": "no-cache",
            },
        )

    except Exception:
        # Logged, not returned: a provider's text can carry keys or URLs.
        logger.exception(f"Voice preview generation failed for {voice_id}")
        raise HTTPException(
            status_code=503, detail="Voice preview generation failed"
        ) from None


# =============================================================================
# Summary Endpoint
# =============================================================================


@router.get("/catalog/summary", response_model=CatalogSummaryResponse)
async def get_catalog_summary() -> CatalogSummaryResponse:
    """
    Get a summary of the voice catalog.

    Returns counts and overview of available providers, models, and voices.
    """
    tts_providers = get_tts_providers()
    tts_models = get_tts_models()
    tts_voices = get_tts_voices()
    stt_providers = get_stt_providers()
    stt_models = get_stt_models()
    current_config = get_current_voice_config(settings)

    return CatalogSummaryResponse(
        tts=CatalogSummaryResponse.TTSSummary(
            provider_count=len(tts_providers),
            model_count=len(tts_models),
            voice_count=len(tts_voices),
            providers=[p.id for p in tts_providers],
        ),
        stt=CatalogSummaryResponse.STTSummary(
            provider_count=len(stt_providers),
            model_count=len(stt_models),
            providers=[p.id for p in stt_providers],
        ),
        current_config=VoiceSettingsResponse(**current_config),
    )


# What the voice uses and every model and voice, and the changes to it.
router.include_router(overview_router)
