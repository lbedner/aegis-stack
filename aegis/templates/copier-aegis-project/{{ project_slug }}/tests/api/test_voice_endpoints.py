"""Tests for voice API endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
import pytest

from app.integrations.main import create_integrated_app
from app.services.ai.domains.voice import (
    AudioFormat,
    OpenAIVoice,
    SpeechResult,
    STTProvider,
    TTSProvider,
)


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


class TestVoicePreview:
    """Tests for voice preview endpoints."""

    @patch("app.components.backend.api.voice.router.TTSService")
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
        mock_ai_service_class.return_value = mock_tts

        response = client.get(
            f"/api/v1/voice/preview/{OpenAIVoice.ALLOY.value}",
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/mpeg"

    @patch("app.components.backend.api.voice.router.TTSService")
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
        mock_ai_service_class.return_value = mock_tts

        response = client.get(
            f"/api/v1/voice/preview/{OpenAIVoice.ALLOY.value}",
            params={"text": "Custom preview text"},
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/mpeg"

    @patch("app.components.backend.api.voice.router.TTSService")
    def test_a_voice_plays_on_a_model_that_speaks_it(
        self, tts_class: MagicMock, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Whatever model is in use: tts-1 knows nine of OpenAI's voices,
        and none of Gemini's. The audio is served as what it is."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "TTS_MODEL", "tts-1")
        tts = MagicMock()
        tts.synthesize = AsyncMock(
            return_value=SpeechResult(
                audio=b"RIFF", format=AudioFormat.WAV, provider=TTSProvider.GEMINI
            )
        )
        tts_class.return_value = tts

        for voice, model in (
            ("marin", "gpt-realtime-2.1-mini"),
            ("alloy", "tts-1"),
            ("Kore", "gemini-3.8-flash-tts"),
        ):
            response = client.get(f"/api/v1/voice/preview/{voice}")
            used = tts_class.call_args.args[0]
            assert (used.TTS_VOICE, used.TTS_MODEL) == (voice, model)

        assert response.headers["content-type"] == "audio/wav"

    def test_get_voice_preview_invalid_voice(self, client: TestClient) -> None:
        """Test preview with invalid voice ID."""
        response = client.get("/api/v1/voice/preview/invalid_voice_id")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @patch("app.components.backend.api.voice.router.TTSService")
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
        mock_ai_service_class.return_value = mock_tts

        response = client.post(
            "/api/v1/voice/preview",
            json={"voice_id": OpenAIVoice.ECHO.value},
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/mpeg"

    @patch("app.components.backend.api.voice.router.TTSService")
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
        mock_ai_service_class.return_value = mock_tts

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


SECRET = "secret internal detail"


class _Exploding:
    """Every attribute, and every call, raises with ``SECRET``."""

    def __getattr__(self, name: str) -> "_Exploding":
        return self

    def __call__(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError(SECRET)


class TestFailuresKeepTheirTextInTheLog:
    """A failing provider's text can carry keys, paths or SQL: it goes to
    the log, never to the client. ``/ai/synthesize`` takes form fields."""

    @pytest.mark.parametrize(
        ("method", "path", "kwargs"),
        [
            ("post", "/api/v1/ai/transcribe", {"files": {"audio": ("a.wav", b"x")}}),
            ("post", "/api/v1/ai/voice-chat", {"files": {"audio": ("a.wav", b"x")}}),
            ("post", "/api/v1/ai/synthesize", {"data": {"text": "hi"}}),
            ("post", "/api/v1/ai/synthesize/stream", {"data": {"text": "hi"}}),
            ("get", "/api/v1/ai/stt/status", {}),
            ("get", "/api/v1/ai/tts/status", {}),
        ],
    )
    def test_speech_routes(
        self, client: TestClient, method: str, path: str, kwargs: dict[str, object]
    ) -> None:
        with patch("app.components.backend.api.ai.speech.ai_service", _Exploding()):
            response = getattr(client, method)(path, **kwargs)
        assert SECRET not in response.text

    def test_voice_preview(self, client: TestClient) -> None:
        with patch(
            "app.components.backend.api.voice.router.TTSService",
            return_value=_Exploding().tts,
        ):
            response = client.get(f"/api/v1/voice/preview/{OpenAIVoice.ALLOY.value}")
        assert response.status_code == 503
        assert SECRET not in response.text


class TestVoiceChatCarriesTheTurn:
    """The route passes what a typed turn passes, so the caller - not the
    stack - decides which agent answers."""

    def test_agent_surface_user_conversation_and_hint(self, client: TestClient) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.services.ai.domains.voice.models import (
            STTProvider,
            TranscriptionResult,
            VoiceChatResponse,
        )

        service = MagicMock()
        service.voice_chat = AsyncMock(
            return_value=VoiceChatResponse(
                transcription=TranscriptionResult(
                    text="hi", provider=STTProvider.OPENAI_WHISPER
                ),
                full_response="hello",
                voice_response="hello",
                conversation_id="c-1",
            )
        )
        with patch("app.components.backend.api.ai.speech.ai_service", service):
            response = client.post(
                "/api/v1/ai/voice-chat",
                params={
                    "conversation_id": "c-1",
                    "user_id": "0",
                    "agent_slug": "helper",
                    "surface": "support",
                    "transcription_hint": "Illiana",
                },
                files={"audio": ("a.webm", b"x", "audio/webm")},
            )

        assert response.status_code == 200
        kwargs = service.voice_chat.call_args.kwargs
        assert kwargs["conversation_id"] == "c-1"
        assert kwargs["user_id"] == "0"
        assert kwargs["agent_slug"] == "helper"
        assert kwargs["surface"] == "support"
        assert kwargs["transcription_hint"] == "Illiana"


class TestOverview:
    """What the stack's voice uses and every model and voice there is, as
    both Overseers show it (``voice_overview``)."""

    def test_every_voice_and_model_is_a_row(self, client: TestClient) -> None:
        rows = client.get("/api/v1/voice/overview").json()["rows"]
        by_kind = {
            kind: {r["name"] for r in rows if r["kind"] == kind}
            for kind in ("voice", "tts", "use")
        }

        assert {"Marin", "Kore"} <= by_kind["voice"]
        assert "gemini-3.8-flash-tts" in by_kind["tts"]
        kore = next(r for r in rows if r["name"] == "Kore")
        assert kore["plays_on"] == "gemini-3.8-flash-tts"

    def test_changing_the_voice_is_an_admins(self, client: TestClient) -> None:
        response = client.post("/api/v1/voice/use", json={"tts_voice": "Kore"})

        assert response.status_code in (401, 403)


class TestDesign:
    """The voice designer over the API, as the Flet Overseer reads it."""

    def test_a_design_is_heard_unsaved(self, client: TestClient) -> None:
        pytest.importorskip("app.services.ai.domains.voice.design")
        heard: list[object] = []

        class _TTS:
            def __init__(self, voice_settings: object) -> None:
                heard.append(voice_settings)

            async def synthesize(self, request: object) -> SpeechResult:
                return SpeechResult(
                    audio=b"RIFF", format=AudioFormat.WAV, provider=TTSProvider.GEMINI
                )

        with patch("app.components.backend.api.voice.overview.TTSService", _TTS):
            response = client.get(
                "/api/v1/voice/design/preview",
                params={"voice": "Kore", "style": "newsreader"},
            )

        assert (
            response.status_code == 200
            and response.headers["content-type"] == "audio/wav"
        )
        assert heard[0].TTS_VOICE == "Kore"
        assert heard[0].TTS_INSTRUCTIONS.startswith("Voice Affect: Authoritative")

    def test_a_design_that_is_not_one_is_refused(self, client: TestClient) -> None:
        pytest.importorskip("app.services.ai.domains.voice.design")
        response = client.get(
            "/api/v1/voice/design/preview", params={"voice": "nobody"}
        )

        assert response.status_code == 422

    def test_saving_a_design_is_an_admins(self, client: TestClient) -> None:
        pytest.importorskip("app.services.ai.domains.voice.design")
        response = client.post(
            "/api/v1/voice/design",
            json={"voice": "alloy", "delivery": {}, "speed": 1.0},
        )

        assert response.status_code in (401, 403)


def test_every_profile_is_listed_at_a_glance(client: TestClient) -> None:
    pytest.importorskip("app.services.ai.domains.voice.design")
    response = client.get("/api/v1/voice/design/profiles")

    assert response.status_code == 200
    assert {"id", "name", "voice", "style", "speed", "active"} <= set(
        response.json()[0]
    )


def test_a_saved_profile_is_heard_in_its_own_voice(client: TestClient) -> None:
    """Both Overseers' profile lists play a profile over the API."""
    pytest.importorskip("app.services.ai.domains.voice.design")
    heard: list[object] = []

    class _TTS:
        def __init__(self, voice_settings: object) -> None:
            heard.append(voice_settings)

        async def synthesize(self, request: object) -> SpeechResult:
            return SpeechResult(
                audio=b"RIFF", format=AudioFormat.WAV, provider=TTSProvider.OPENAI
            )

    summary = client.get("/api/v1/voice/design/profiles").json()[0]
    with patch("app.components.backend.api.voice.overview.TTSService", _TTS):
        response = client.get(f"/api/v1/voice/design/profiles/{summary['id']}/preview")
        missing = client.get("/api/v1/voice/design/profiles/999999/preview")

    assert response.status_code == 200 and heard
    assert missing.status_code == 404


def test_the_models_table_leaves_out_the_library(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Thousands of library voices would bury the table: they are reached
    through the editor's accents instead."""
    from app.services.ai.domains.voice import library
    from app.services.ai.domains.voice.models import VoiceInfo

    amelia = VoiceInfo(
        id="voice_en_gb_amelia",
        name="Amelia",
        provider_id="gemini",
        model_ids=["gemini-3.8-flash-tts"],
        description="Bright",
        gender="female",
    )
    monkeypatch.setattr(library, "KEPT", {amelia.id: amelia})
    monkeypatch.setattr(library, "TRIED", {"gemini"})

    rows = client.get("/api/v1/voice/overview").json()["rows"]

    assert "Amelia" not in {r["name"] for r in rows}
    assert "Kore" in {r["name"] for r in rows}
