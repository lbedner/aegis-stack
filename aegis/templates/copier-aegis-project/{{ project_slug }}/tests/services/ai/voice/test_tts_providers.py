"""Tests for TTS providers."""

from types import SimpleNamespace
from typing import Any

import pytest

from app.services.ai.domains.voice.models import (
    DEFAULT_TTS_MODEL,
    AudioFormat,
    SpeechRequest,
    SpeechTokens,
    TTSProvider,
)
from app.services.ai.domains.voice.tts import (
    BaseTTSProvider,
    GeminiTTSProvider,
    OpenAITTSProvider,
    get_tts_provider,
)


class TestGetTTSProvider:
    """Test get_tts_provider factory function."""

    def test_get_openai_provider(self) -> None:
        """Test factory returns OpenAITTSProvider."""
        provider = get_tts_provider(TTSProvider.OPENAI)

        assert isinstance(provider, OpenAITTSProvider)
        assert provider.provider_type == TTSProvider.OPENAI

    def test_get_provider_with_api_key(self) -> None:
        """Test factory passes API key to provider."""
        provider = get_tts_provider(
            TTSProvider.OPENAI,
            api_key="sk-test-key",
        )

        assert isinstance(provider, OpenAITTSProvider)
        assert provider.api_key == "sk-test-key"

    def test_get_provider_with_model(self) -> None:
        """Test factory passes model to provider."""
        provider = get_tts_provider(
            TTSProvider.OPENAI,
            model="tts-1-hd",
        )

        assert isinstance(provider, OpenAITTSProvider)
        assert provider.model == "tts-1-hd"

    def test_get_provider_with_voice(self) -> None:
        """Test factory passes voice to provider."""
        provider = get_tts_provider(
            TTSProvider.OPENAI,
            voice="nova",
        )

        assert isinstance(provider, OpenAITTSProvider)
        assert provider.default_voice == "nova"

    def test_get_provider_with_kwargs(self) -> None:
        """Test factory passes kwargs to provider."""
        provider = get_tts_provider(
            TTSProvider.OPENAI,
            base_url="https://custom.api.com",
        )

        assert isinstance(provider, OpenAITTSProvider)
        assert provider.base_url == "https://custom.api.com"


class TestOpenAITTSProvider:
    """Test OpenAITTSProvider class."""

    def test_default_model(self) -> None:
        provider = OpenAITTSProvider()

        assert provider.model == DEFAULT_TTS_MODEL

    def test_custom_model(self) -> None:
        """Test custom model can be set."""
        provider = OpenAITTSProvider(model="tts-1-hd")

        assert provider.model == "tts-1-hd"

    def test_default_voice(self) -> None:
        """Test default voice is alloy."""
        provider = OpenAITTSProvider()

        assert provider.default_voice == "alloy"

    def test_custom_voice(self) -> None:
        """Test custom voice can be set."""
        provider = OpenAITTSProvider(voice="nova")

        assert provider.default_voice == "nova"

    def test_api_key_stored(self) -> None:
        """Test API key is stored."""
        provider = OpenAITTSProvider(api_key="sk-test")

        assert provider.api_key == "sk-test"

    def test_base_url_stored(self) -> None:
        """Test base URL is stored."""
        provider = OpenAITTSProvider(base_url="https://custom.com")

        assert provider.base_url == "https://custom.com"

    def test_client_lazy_loaded(self) -> None:
        """Test client is not created until needed."""
        provider = OpenAITTSProvider()

        # Client should be None until _get_client is called
        assert provider._client is None

    def test_provider_type_is_openai(self) -> None:
        """Test provider_type is OPENAI."""
        provider = OpenAITTSProvider()

        assert provider.provider_type == TTSProvider.OPENAI

    def test_is_base_tts_provider(self) -> None:
        """Test inherits from BaseTTSProvider."""
        provider = OpenAITTSProvider()

        assert isinstance(provider, BaseTTSProvider)


class TestBaseTTSProviderInterface:
    """Test BaseTTSProvider abstract interface."""

    def test_all_providers_have_synthesize_method(self) -> None:
        """Test all provider classes have synthesize method."""
        providers = [
            OpenAITTSProvider,
        ]

        for provider_class in providers:
            assert hasattr(provider_class, "synthesize")
            # Method should be callable
            provider = provider_class()
            assert callable(provider.synthesize)

    def test_all_providers_have_synthesize_stream_method(self) -> None:
        """Test all provider classes have synthesize_stream method."""
        providers = [
            OpenAITTSProvider,
        ]

        for provider_class in providers:
            assert hasattr(provider_class, "synthesize_stream")
            # Method should be callable
            provider = provider_class()
            assert callable(provider.synthesize_stream)

    def test_all_providers_have_provider_type(self) -> None:
        """Test all provider classes have provider_type class attribute."""
        providers = [
            (OpenAITTSProvider, TTSProvider.OPENAI),
        ]

        for provider_class, expected_type in providers:
            assert hasattr(provider_class, "provider_type")
            assert provider_class.provider_type == expected_type


class TestGeminiTTSProvider:
    """Gemini says a line in one of its voices through the Interactions
    API: the line is the transcript, the delivery its ``speech_metadata``
    style, the voice in ``speech_config``; it answers with a WAV."""

    async def test_a_line_comes_back_as_wav_in_the_voice_asked(self) -> None:
        pytest.importorskip("google.genai")
        import base64
        import io
        import wave

        asked: dict[str, Any] = {}
        out = io.BytesIO()
        with wave.open(out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24_000)
            w.writeframes(b"\x01\x00" * 2400)  # a tenth of a second
        wav = out.getvalue()

        async def create(**kwargs: Any) -> Any:
            asked.update(kwargs)
            return SimpleNamespace(
                output_audio=SimpleNamespace(data=base64.b64encode(wav))
            )

        provider = get_tts_provider(TTSProvider.GEMINI, api_key="k", voice="Kore")
        assert isinstance(provider, GeminiTTSProvider)
        provider._client = SimpleNamespace(
            aio=SimpleNamespace(interactions=SimpleNamespace(create=create))
        )

        result = await provider.synthesize(
            SpeechRequest(text="Hello there.", voice="Puck", instructions="Warmly")
        )

        assert result.format == AudioFormat.WAV and result.audio == wav
        assert result.duration_seconds == 0.1
        assert asked["model"] == "gemini-3.8-flash-tts"
        assert asked["generation_config"] == {"speech_config": [{"voice": "Puck"}]}
        [content] = asked["input"][0]["content"]
        assert content["text"] == "Hello there."
        assert content["annotations"] == [
            {"type": "speech_metadata", "style": "Warmly"}
        ]


class _Realtime:
    """OpenAI's Realtime API, faked at the connection: what was sent, and
    the events it answers with."""

    def __init__(self, events: list[Any]) -> None:
        self.sent: dict[str, Any] = {}
        self.audio_sent = False
        self._events = events
        self.session = SimpleNamespace(update=self._keep("session"))
        self.response = SimpleNamespace(create=self._keep("response"))
        self.input_audio_buffer = SimpleNamespace(append=self._heard)

    def _keep(self, name: str) -> Any:
        async def keep(**kwargs: Any) -> None:
            self.sent[name] = kwargs[name]

        return keep

    async def _heard(self, **kwargs: Any) -> None:
        self.audio_sent = True

    async def __aenter__(self) -> "_Realtime":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def __aiter__(self) -> Any:
        for event in self._events:
            yield event

    def client(self) -> Any:
        return SimpleNamespace(realtime=SimpleNamespace(connect=lambda **kwargs: self))


def _done(status: str = "completed") -> Any:
    usage = SimpleNamespace(
        input_tokens=40,
        output_tokens=120,
        input_token_details=SimpleNamespace(
            audio_tokens=0, cached_tokens=0, cached_tokens_details=None
        ),
        output_token_details=SimpleNamespace(audio_tokens=100, text_tokens=20),
    )
    return SimpleNamespace(
        type="response.done",
        response=SimpleNamespace(status=status, status_details=None, usage=usage),
    )


class TestOpenAIRealtimeSpeech:
    """OpenAI's replacement for its retiring speech models,
    gpt-realtime-2.1-mini, speaks only over the Realtime API. A line is
    the response's only message, and the instructions say to read it, so
    a line that reads as a command is read, not obeyed. It is one way:
    nothing is ever heard, only said."""

    async def test_a_line_is_read_word_for_word_as_wav(self) -> None:
        import base64
        import io
        import wave

        pcm = b"\x01\x00" * 2400  # a tenth of a second at 24kHz
        realtime = _Realtime(
            [
                SimpleNamespace(
                    type="response.output_audio.delta",
                    delta=base64.b64encode(pcm[:2400]).decode(),
                ),
                SimpleNamespace(
                    type="response.output_audio.delta",
                    delta=base64.b64encode(pcm[2400:]).decode(),
                ),
                _done(),
            ]
        )
        provider = get_tts_provider(
            TTSProvider.OPENAI, api_key="k", model="gpt-realtime-2.1-mini"
        )
        provider._client = realtime.client()

        result = await provider.synthesize(
            SpeechRequest(
                text="Hello there.", voice="marin", instructions="Warmly.", speed=1.2
            )
        )

        assert result.format == AudioFormat.WAV and result.duration_seconds == 0.1
        with wave.open(io.BytesIO(result.audio)) as w:
            assert w.getframerate() == 24_000 and w.readframes(w.getnframes()) == pcm
        session = realtime.sent["session"]
        assert session["output_modalities"] == ["audio"]
        assert session["audio"]["input"]["turn_detection"] is None
        assert session["audio"]["output"]["voice"] == "marin"
        assert session["audio"]["output"]["speed"] == 1.2
        response = realtime.sent["response"]
        [message] = response["input"]
        assert message["role"] == "user"
        assert message["content"] == [{"type": "input_text", "text": "Hello there."}]
        assert response["instructions"].startswith("Warmly.")
        assert "Hello there." not in response["instructions"]  # data, not orders
        assert realtime.audio_sent is False
        assert result.tokens == SpeechTokens(
            input_tokens=40, output_tokens=120, output_audio_tokens=100
        )

    async def test_speed_past_what_realtime_takes_is_held_at_its_most(
        self,
    ) -> None:
        realtime = _Realtime([_done()])
        provider = get_tts_provider(
            TTSProvider.OPENAI, api_key="k", model="gpt-realtime-2.1-mini"
        )
        provider._client = realtime.client()

        await provider.synthesize(SpeechRequest(text="Hi.", speed=3.0))

        assert realtime.sent["session"]["audio"]["output"]["speed"] == 1.5

    async def test_an_error_or_unfinished_response_fails_the_line(self) -> None:
        for events in (
            [SimpleNamespace(type="error", error=SimpleNamespace(message="bad voice"))],
            [_done("incomplete")],
        ):
            provider = get_tts_provider(
                TTSProvider.OPENAI, api_key="k", model="gpt-realtime-2.1-mini"
            )
            provider._client = _Realtime(events).client()

            with pytest.raises(RuntimeError, match="Speech synthesis failed"):
                await provider.synthesize(SpeechRequest(text="Hi."))


# An MPEG-2 Layer III frame as OpenAI sends them: 128kbps at 24kHz, 384
# bytes, 576 samples (0.024s).
MP3_FRAME = b"\xff\xf3\xc4\xc4" + b"\x00" * 380


class TestOpenAISpeechLength:
    """gpt-4o-mini-tts is billed by the second of speech: its MP3's length
    is read from its frames, or the ledger prices it at nothing."""

    async def test_a_line_says_how_long_it_is(self) -> None:
        async def create(**kwargs: Any) -> Any:
            return SimpleNamespace(
                content=b"ID3\x04\x00\x00\x00\x00\x00\x00" + MP3_FRAME * 50
            )

        provider = get_tts_provider(
            TTSProvider.OPENAI, api_key="k", model="gpt-4o-mini-tts"
        )
        provider._client = SimpleNamespace(
            audio=SimpleNamespace(speech=SimpleNamespace(create=create))
        )

        result = await provider.synthesize(SpeechRequest(text="Hello there."))

        assert result.format == AudioFormat.MP3
        assert result.duration_seconds == pytest.approx(1.2)
