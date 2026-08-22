"""Tests for voice API endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.integrations.main import create_integrated_app
from app.services.ai.domains.voice import (
    AudioFormat,
    OpenAIVoice,
    SpeechResult,
    STTProvider,
    TTSProvider,
)
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    """Create test client."""
    app = create_integrated_app()
    return TestClient(app)


class TestTtsCatalogProviders:
    """Tests for TTS provider catalog endpoints."""

    def test_list_tts_providers_success(self, client: TestClient) -> None:
        """Test successful retrieval of TTS providers."""
        response = client.get("/api/v1/voice/catalog/tts/providers")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_list_tts_providers_schema(self, client: TestClient) -> None:
        """Test TTS providers response schema."""
        response = client.get("/api/v1/voice/catalog/tts/providers")

        assert response.status_code == 200
        data = response.json()
        provider = data[0]

        required_fields = [
            "id",
            "name",
            "type",
            "requires_api_key",
            "is_local",
            "description",
        ]
        for field in required_fields:
            assert field in provider

    def test_list_tts_providers_contains_openai(self, client: TestClient) -> None:
        """Test that OpenAI provider is included."""
        response = client.get("/api/v1/voice/catalog/tts/providers")

        assert response.status_code == 200
        data = response.json()
        provider_ids = [p["id"] for p in data]
        assert TTSProvider.OPENAI.value in provider_ids

    def test_list_tts_providers_openai_requires_key(self, client: TestClient) -> None:
        """Test that OpenAI provider requires API key."""
        response = client.get("/api/v1/voice/catalog/tts/providers")

        assert response.status_code == 200
        data = response.json()
        openai = next(p for p in data if p["id"] == TTSProvider.OPENAI.value)
        assert openai["requires_api_key"] is True
        assert openai["api_key_env_var"] == "OPENAI_API_KEY"


class TestTtsCatalogModels:
    """Tests for TTS model catalog endpoints."""

    def test_list_tts_models_for_provider(self, client: TestClient) -> None:
        """Test retrieving models for a specific TTS provider."""
        response = client.get(
            f"/api/v1/voice/catalog/tts/{TTSProvider.OPENAI.value}/models"
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_list_tts_models_schema(self, client: TestClient) -> None:
        """Test TTS models response schema."""
        response = client.get(
            f"/api/v1/voice/catalog/tts/{TTSProvider.OPENAI.value}/models"
        )

        assert response.status_code == 200
        data = response.json()
        model = data[0]

        required_fields = [
            "id",
            "name",
            "provider_id",
            "quality",
            "supports_streaming",
        ]
        for field in required_fields:
            assert field in model

    def test_list_tts_models_filtered_by_provider(self, client: TestClient) -> None:
        """Test that models are filtered by provider."""
        response = client.get(
            f"/api/v1/voice/catalog/tts/{TTSProvider.OPENAI.value}/models"
        )

        assert response.status_code == 200
        data = response.json()
        for model in data:
            assert model["provider_id"] == TTSProvider.OPENAI.value

    def test_list_tts_models_invalid_provider(self, client: TestClient) -> None:
        """Test error handling for invalid provider."""
        response = client.get("/api/v1/voice/catalog/tts/invalid_provider/models")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_list_tts_models_invalid_provider_message(self, client: TestClient) -> None:
        """Test error message for invalid provider."""
        response = client.get("/api/v1/voice/catalog/tts/invalid_provider/models")

        assert response.status_code == 404
        detail = response.json()["detail"]
        assert "invalid_provider" in detail
        assert "Available" in detail


class TestTtsCatalogVoices:
    """Tests for TTS voice catalog endpoints."""

    def test_list_tts_voices_for_provider(self, client: TestClient) -> None:
        """Test retrieving voices for a specific TTS provider."""
        response = client.get(
            f"/api/v1/voice/catalog/tts/{TTSProvider.OPENAI.value}/voices"
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_list_tts_voices_schema(self, client: TestClient) -> None:
        """Test TTS voices response schema."""
        response = client.get(
            f"/api/v1/voice/catalog/tts/{TTSProvider.OPENAI.value}/voices"
        )

        assert response.status_code == 200
        data = response.json()
        voice = data[0]

        required_fields = [
            "id",
            "name",
            "provider_id",
            "model_ids",
            "description",
            "preview_text",
        ]
        for field in required_fields:
            assert field in voice

    def test_list_tts_voices_filtered_by_provider(self, client: TestClient) -> None:
        """Test that voices are filtered by provider."""
        response = client.get(
            f"/api/v1/voice/catalog/tts/{TTSProvider.OPENAI.value}/voices"
        )

        assert response.status_code == 200
        data = response.json()
        for voice in data:
            assert voice["provider_id"] == TTSProvider.OPENAI.value

    def test_list_tts_voices_contains_alloy(self, client: TestClient) -> None:
        """Test that Alloy voice is included."""
        response = client.get(
            f"/api/v1/voice/catalog/tts/{TTSProvider.OPENAI.value}/voices"
        )

        assert response.status_code == 200
        data = response.json()
        voice_ids = [v["id"] for v in data]
        assert OpenAIVoice.ALLOY.value in voice_ids

    def test_list_tts_voices_alloy_details(self, client: TestClient) -> None:
        """Test Alloy voice details."""
        response = client.get(
            f"/api/v1/voice/catalog/tts/{TTSProvider.OPENAI.value}/voices"
        )

        assert response.status_code == 200
        data = response.json()
        alloy = next(v for v in data if v["id"] == OpenAIVoice.ALLOY.value)
        assert alloy["name"] == "Alloy"
        assert alloy["provider_id"] == TTSProvider.OPENAI.value
        assert "tts-1" in alloy["model_ids"]

    def test_list_tts_voices_invalid_provider(self, client: TestClient) -> None:
        """Test error handling for invalid provider."""
        response = client.get("/api/v1/voice/catalog/tts/invalid_provider/voices")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestSttCatalogProviders:
    """Tests for STT provider catalog endpoints."""

    def test_list_stt_providers_success(self, client: TestClient) -> None:
        """Test successful retrieval of STT providers."""
        response = client.get("/api/v1/voice/catalog/stt/providers")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_list_stt_providers_schema(self, client: TestClient) -> None:
        """Test STT providers response schema."""
        response = client.get("/api/v1/voice/catalog/stt/providers")

        assert response.status_code == 200
        data = response.json()
        provider = data[0]

        required_fields = [
            "id",
            "name",
            "type",
            "requires_api_key",
            "is_local",
            "description",
        ]
        for field in required_fields:
            assert field in provider

    def test_list_stt_providers_contains_openai(self, client: TestClient) -> None:
        """Test that OpenAI Whisper is included."""
        response = client.get("/api/v1/voice/catalog/stt/providers")

        assert response.status_code == 200
        data = response.json()
        provider_ids = [p["id"] for p in data]
        assert STTProvider.OPENAI_WHISPER.value in provider_ids

    def test_list_stt_providers_contains_groq(self, client: TestClient) -> None:
        """Test that Groq Whisper is included."""
        response = client.get("/api/v1/voice/catalog/stt/providers")

        assert response.status_code == 200
        data = response.json()
        provider_ids = [p["id"] for p in data]
        assert STTProvider.GROQ_WHISPER.value in provider_ids

    def test_list_stt_providers_contains_faster_whisper(
        self, client: TestClient
    ) -> None:
        """Test that Faster Whisper is included."""
        response = client.get("/api/v1/voice/catalog/stt/providers")

        assert response.status_code == 200
        data = response.json()
        provider_ids = [p["id"] for p in data]
        assert STTProvider.FASTER_WHISPER.value in provider_ids


class TestSttCatalogModels:
    """Tests for STT model catalog endpoints."""

    def test_list_stt_models_for_provider(self, client: TestClient) -> None:
        """Test retrieving models for a specific STT provider."""
        response = client.get(
            f"/api/v1/voice/catalog/stt/{STTProvider.OPENAI_WHISPER.value}/models"
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_list_stt_models_schema(self, client: TestClient) -> None:
        """Test STT models response schema."""
        response = client.get(
            f"/api/v1/voice/catalog/stt/{STTProvider.OPENAI_WHISPER.value}/models"
        )

        assert response.status_code == 200
        data = response.json()
        model = data[0]

        required_fields = [
            "id",
            "name",
            "provider_id",
            "quality",
            "supports_streaming",
        ]
        for field in required_fields:
            assert field in model

    def test_list_stt_models_filtered_by_provider(self, client: TestClient) -> None:
        """Test that models are filtered by provider."""
        response = client.get(
            f"/api/v1/voice/catalog/stt/{STTProvider.OPENAI_WHISPER.value}/models"
        )

        assert response.status_code == 200
        data = response.json()
        for model in data:
            assert model["provider_id"] == STTProvider.OPENAI_WHISPER.value

    def test_list_stt_models_groq_provider(self, client: TestClient) -> None:
        """Test retrieving models for Groq provider."""
        response = client.get(
            f"/api/v1/voice/catalog/stt/{STTProvider.GROQ_WHISPER.value}/models"
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        for model in data:
            assert model["provider_id"] == STTProvider.GROQ_WHISPER.value

    def test_list_stt_models_faster_whisper_provider(self, client: TestClient) -> None:
        """Test retrieving models for Faster Whisper provider."""
        response = client.get(
            f"/api/v1/voice/catalog/stt/{STTProvider.FASTER_WHISPER.value}/models"
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        for model in data:
            assert model["provider_id"] == STTProvider.FASTER_WHISPER.value

    def test_list_stt_models_invalid_provider(self, client: TestClient) -> None:
        """Test error handling for invalid provider."""
        response = client.get("/api/v1/voice/catalog/stt/invalid_provider/models")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestVoiceSettings:
    """Tests for voice settings endpoints."""

    def test_get_voice_settings_success(self, client: TestClient) -> None:
        """Test successful retrieval of voice settings."""
        response = client.get("/api/v1/voice/settings")

        assert response.status_code == 200
        data = response.json()
        assert "tts_provider" in data
        assert "tts_model" in data
        assert "tts_voice" in data
        assert "tts_speed" in data
        assert "stt_provider" in data
        assert "stt_model" in data
        assert "stt_language" in data

    def test_get_voice_settings_defaults(self, client: TestClient) -> None:
        """Test that voice settings have default values."""
        response = client.get("/api/v1/voice/settings")

        assert response.status_code == 200
        data = response.json()
        assert data["tts_provider"] == TTSProvider.OPENAI.value or data["tts_provider"]
        assert data["tts_model"]
        assert data["tts_voice"]
        assert data["stt_provider"]
        assert data["stt_model"]

    def test_update_voice_settings_partial_tts(self, client: TestClient) -> None:
        """Test updating only TTS settings."""
        response = client.post(
            "/api/v1/voice/settings",
            json={
                "tts_provider": TTSProvider.OPENAI.value,
                "tts_model": "tts-1-hd",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["tts_provider"] == TTSProvider.OPENAI.value
        assert data["tts_model"] == "tts-1-hd"
        # Other settings should remain unchanged
        assert "stt_provider" in data

    def test_update_voice_settings_partial_stt(self, client: TestClient) -> None:
        """Test updating only STT settings."""
        response = client.post(
            "/api/v1/voice/settings",
            json={
                "stt_provider": STTProvider.GROQ_WHISPER.value,
                "stt_model": "whisper-large-v3-turbo",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["stt_provider"] == STTProvider.GROQ_WHISPER.value
        assert data["stt_model"] == "whisper-large-v3-turbo"
        # TTS settings should remain unchanged
        assert "tts_provider" in data

    def test_update_voice_settings_tts_speed(self, client: TestClient) -> None:
        """Test updating TTS speed."""
        response = client.post(
            "/api/v1/voice/settings",
            json={"tts_speed": 0.8},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["tts_speed"] == 0.8

    def test_update_voice_settings_stt_language(self, client: TestClient) -> None:
        """Test updating STT language."""
        response = client.post(
            "/api/v1/voice/settings",
            json={"stt_language": "es"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["stt_language"] == "es"

    def test_update_voice_settings_multiple_fields(self, client: TestClient) -> None:
        """Test updating multiple settings at once."""
        response = client.post(
            "/api/v1/voice/settings",
            json={
                "tts_voice": OpenAIVoice.ECHO.value,
                "tts_speed": 1.2,
                "stt_language": "fr",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["tts_voice"] == OpenAIVoice.ECHO.value
        assert data["tts_speed"] == 1.2
        assert data["stt_language"] == "fr"

    def test_update_voice_settings_empty_request(self, client: TestClient) -> None:
        """Test update with empty request body."""
        response = client.post(
            "/api/v1/voice/settings",
            json={},
        )

        assert response.status_code == 200
        data = response.json()
        # Should return current settings unchanged
        assert "tts_provider" in data


class TestVoicePreview:
    """Tests for voice preview endpoints."""

    @patch("app.components.backend.api.voice.router.AIService")
    def test_get_voice_preview_success(
        self, mock_ai_service_class: MagicMock, client: TestClient
    ) -> None:
        """Test successful voice preview generation."""
        # Setup mock
        mock_service = MagicMock()
        mock_tts = AsyncMock()
        mock_tts.synthesize = AsyncMock(
            return_value=SpeechResult(
                audio=b"mock_audio",
                format=AudioFormat.MP3,
                duration_seconds=2.0,
                provider=TTSProvider.OPENAI,
            )
        )
        mock_service.tts = mock_tts
        mock_ai_service_class.return_value = mock_service

        response = client.get(
            f"/api/v1/voice/preview/{OpenAIVoice.ALLOY.value}",
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/mpeg"

    @patch("app.components.backend.api.voice.router.AIService")
    def test_get_voice_preview_with_custom_text(
        self, mock_ai_service_class: MagicMock, client: TestClient
    ) -> None:
        """Test voice preview with custom text."""
        # Setup mock
        mock_service = MagicMock()
        mock_tts = AsyncMock()
        mock_tts.synthesize = AsyncMock(
            return_value=SpeechResult(
                audio=b"mock_audio",
                format=AudioFormat.MP3,
                duration_seconds=2.0,
                provider=TTSProvider.OPENAI,
            )
        )
        mock_service.tts = mock_tts
        mock_ai_service_class.return_value = mock_service

        response = client.get(
            f"/api/v1/voice/preview/{OpenAIVoice.ALLOY.value}",
            params={"text": "Custom preview text"},
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/mpeg"

    def test_get_voice_preview_invalid_voice(self, client: TestClient) -> None:
        """Test preview with invalid voice ID."""
        response = client.get("/api/v1/voice/preview/invalid_voice_id")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @patch("app.components.backend.api.voice.router.AIService")
    def test_post_voice_preview_success(
        self, mock_ai_service_class: MagicMock, client: TestClient
    ) -> None:
        """Test successful voice preview via POST."""
        # Setup mock
        mock_service = MagicMock()
        mock_tts = AsyncMock()
        mock_tts.synthesize = AsyncMock(
            return_value=SpeechResult(
                audio=b"mock_audio",
                format=AudioFormat.MP3,
                duration_seconds=2.0,
                provider=TTSProvider.OPENAI,
            )
        )
        mock_service.tts = mock_tts
        mock_ai_service_class.return_value = mock_service

        response = client.post(
            "/api/v1/voice/preview",
            json={"voice_id": OpenAIVoice.ECHO.value},
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/mpeg"

    @patch("app.components.backend.api.voice.router.AIService")
    def test_post_voice_preview_with_text(
        self, mock_ai_service_class: MagicMock, client: TestClient
    ) -> None:
        """Test POST voice preview with custom text."""
        # Setup mock
        mock_service = MagicMock()
        mock_tts = AsyncMock()
        mock_tts.synthesize = AsyncMock(
            return_value=SpeechResult(
                audio=b"mock_audio",
                format=AudioFormat.MP3,
                duration_seconds=2.0,
                provider=TTSProvider.OPENAI,
            )
        )
        mock_service.tts = mock_tts
        mock_ai_service_class.return_value = mock_service

        response = client.post(
            "/api/v1/voice/preview",
            json={
                "voice_id": OpenAIVoice.ECHO.value,
                "text": "Custom preview text",
            },
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/mpeg"


class TestCatalogSummary:
    """Tests for catalog summary endpoint."""

    def test_get_catalog_summary_success(self, client: TestClient) -> None:
        """Test successful retrieval of catalog summary."""
        response = client.get("/api/v1/voice/catalog/summary")

        assert response.status_code == 200
        assert response.json() is not None

    def test_get_catalog_summary_schema(self, client: TestClient) -> None:
        """Test catalog summary response schema."""
        response = client.get("/api/v1/voice/catalog/summary")

        assert response.status_code == 200
        data = response.json()

        # Check top-level fields
        assert "tts" in data
        assert "stt" in data
        assert "current_config" in data

        # Check TTS summary
        tts = data["tts"]
        assert "provider_count" in tts
        assert "model_count" in tts
        assert "voice_count" in tts
        assert "providers" in tts

        # Check STT summary
        stt = data["stt"]
        assert "provider_count" in stt
        assert "model_count" in stt
        assert "providers" in stt

    def test_get_catalog_summary_tts_counts(self, client: TestClient) -> None:
        """Test TTS counts in summary."""
        response = client.get("/api/v1/voice/catalog/summary")

        assert response.status_code == 200
        data = response.json()
        tts = data["tts"]

        assert tts["provider_count"] > 0
        assert tts["model_count"] > 0
        assert tts["voice_count"] > 0
        assert len(tts["providers"]) == tts["provider_count"]

    def test_get_catalog_summary_stt_counts(self, client: TestClient) -> None:
        """Test STT counts in summary."""
        response = client.get("/api/v1/voice/catalog/summary")

        assert response.status_code == 200
        data = response.json()
        stt = data["stt"]

        assert stt["provider_count"] > 0
        assert stt["model_count"] > 0
        assert len(stt["providers"]) == stt["provider_count"]

    def test_get_catalog_summary_current_config(self, client: TestClient) -> None:
        """Test current config in summary."""
        response = client.get("/api/v1/voice/catalog/summary")

        assert response.status_code == 200
        data = response.json()
        config = data["current_config"]

        required_fields = [
            "tts_provider",
            "tts_model",
            "tts_voice",
            "tts_speed",
            "stt_provider",
            "stt_model",
            "stt_language",
        ]
        for field in required_fields:
            assert field in config
