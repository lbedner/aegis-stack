"""
Voice Catalog and Settings API Router

Provides endpoints for querying TTS/STT providers, models, and voices,
as well as managing voice settings and generating voice previews.
"""

from app.core.config import settings
from app.core.log import logger
from app.services.ai.service import AIService
from app.services.ai.domains.voice import (
    ModelInfo,
    ProviderInfo,
    SpeechRequest,
    VoiceInfo,
    VoicePreviewRequest,
    VoiceSettingsResponse,
    VoiceSettingsUpdate,
    get_current_voice_config,
    get_stt_models,
    get_stt_providers,
    get_tts_models,
    get_tts_providers,
    get_tts_voices,
    get_voice,
)
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

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
            description=m.description,
            supports_streaming=m.supports_streaming,
        )


class VoiceResponse(BaseModel):
    """Voice information response."""

    id: str
    name: str
    provider_id: str
    model_ids: list[str]
    description: str
    category: str | None = None
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
            category=v.category.value if v.category else None,
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


@router.post("/settings", response_model=VoiceSettingsResponse)
async def update_voice_settings(
    update: VoiceSettingsUpdate,
) -> VoiceSettingsResponse:
    """
    Update voice settings.

    Note: This is a read-only endpoint that returns what the settings
    would look like if applied. Actual settings changes require
    environment variable updates.

    Args:
        update: Partial settings update

    Returns:
        The merged settings (current + updates)
    """
    # Get current config
    current = get_current_voice_config(settings)

    # Apply updates
    if update.tts_provider is not None:
        current["tts_provider"] = update.tts_provider
    if update.tts_model is not None:
        current["tts_model"] = update.tts_model
    if update.tts_voice is not None:
        current["tts_voice"] = update.tts_voice
    if update.tts_speed is not None:
        current["tts_speed"] = update.tts_speed
    if update.stt_provider is not None:
        current["stt_provider"] = update.stt_provider
    if update.stt_model is not None:
        current["stt_model"] = update.stt_model
    if update.stt_language is not None:
        current["stt_language"] = update.stt_language

    # Log the settings update (actual persistence would require env update)
    logger.info(
        f"Voice settings update requested: {update.model_dump(exclude_none=True)}"
    )

    return VoiceSettingsResponse(**current)


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
) -> Response:
    """
    Generate a voice preview audio clip (GET).

    Browser-friendly endpoint for audio playback via URL.

    Args:
        voice_id: Voice ID to preview
        text: Optional custom text
        speed: Optional speed multiplier (0.25 to 4.0, default 1.0)

    Returns:
        Audio file (audio/mpeg) with the synthesized preview
    """
    return await _generate_preview(voice_id, text, speed)


async def _generate_preview(
    voice_id: str,
    text: str | None = None,
    speed: float | None = None,
) -> Response:
    """Internal helper to generate voice preview."""
    # Look up voice
    voice = get_voice(voice_id)
    if not voice:
        raise HTTPException(status_code=404, detail=f"Voice not found: {voice_id}")

    # Determine preview text
    preview_text = text or voice.preview_text.format(voice_name=voice.name)

    try:
        # Initialize AI service to get TTS
        ai_service = AIService(settings)

        # Generate speech with optional speed
        speech_request = SpeechRequest(
            text=preview_text,
            voice=voice_id,
            speed=speed or 1.0,
        )
        result = await ai_service.tts.synthesize(speech_request)

        # Return audio response
        return Response(
            content=result.audio,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": f'inline; filename="{voice_id}_preview.mp3"',
                "Cache-Control": "no-cache",
            },
        )

    except Exception as e:
        logger.exception(f"Voice preview generation failed for {voice_id}")
        raise HTTPException(
            status_code=503, detail=f"Voice preview generation failed: {e}"
        )


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
