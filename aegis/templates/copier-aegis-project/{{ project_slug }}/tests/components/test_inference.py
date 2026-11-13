"""Tests for the ephemeral Ollama model activity tracker."""

from typing import Any

import httpx
import pytest

from app.components.inference import sampler
from app.components.inference.activity import (
    ActivityTracker,
    get_inference_activity,
)
from app.components.inference.engine import InferenceServerStatus
from app.components.inference.ollama import OllamaEngine
from app.core import series, speech_server
from app.core.config import settings
from app.core.speech_server import SpeechServerReading
from app.services.system.health_ollama import check_ollama_health
from app.services.system.models import ComponentStatusType
from tests._fake_ollama import (
    ROUTES,
    RUNNING,
    SERVING,
    SPEECH_DOWN,
    SPEECH_READY,
    SPEECH_URL,
    FakeClient,
    down,
    serve,
    serving,
)


class TestActivityTracker:
    """Diff/record behavior of the in-memory activity tracker."""

    def test_first_observation_sets_baseline_without_events(self) -> None:
        tracker = ActivityTracker()
        tracker.observe({"qwen2.5:7b": 4.2})

        assert tracker.events() == []

    def test_detected_load_records_event(self) -> None:
        tracker = ActivityTracker()
        tracker.observe({})
        tracker.observe({"qwen2.5:7b": 4.2})

        events = tracker.events()
        assert len(events) == 1
        assert events[0].action == "loaded"
        assert events[0].model == "qwen2.5:7b"
        assert events[0].vram_gb == 4.2
        assert events[0].detected is True

    def test_eviction_records_event_with_last_known_vram(self) -> None:
        tracker = ActivityTracker()
        tracker.observe({"qwen2.5:7b": 4.2})
        tracker.observe({})

        events = tracker.events()
        assert len(events) == 1
        assert events[0].action == "evicted"
        assert events[0].model == "qwen2.5:7b"
        assert events[0].vram_gb == 4.2
        assert events[0].detected is True

    def test_explicit_load_is_not_double_counted_and_backfills_vram(self) -> None:
        tracker = ActivityTracker()
        tracker.observe({})
        tracker.record_loaded("qwen2.5:7b")
        tracker.observe({"qwen2.5:7b": 4.2})

        events = tracker.events()
        assert len(events) == 1
        assert events[0].action == "loaded"
        assert events[0].detected is False
        assert events[0].vram_gb == 4.2

    def test_explicit_unload_is_not_double_counted(self) -> None:
        tracker = ActivityTracker()
        tracker.observe({"qwen2.5:7b": 4.2})
        tracker.record_unloaded("qwen2.5:7b")
        tracker.observe({})

        events = tracker.events()
        assert len(events) == 1
        assert events[0].action == "unloaded"
        assert events[0].detected is False
        assert events[0].vram_gb == 4.2

    def test_events_are_newest_first(self) -> None:
        tracker = ActivityTracker()
        tracker.observe({})
        tracker.observe({"a:1b": 1.0})
        tracker.observe({"a:1b": 1.0, "b:2b": 2.0})

        events = tracker.events()
        assert [e.model for e in events] == ["b:2b", "a:1b"]

    def test_stale_listing_after_explicit_unload_is_not_a_load(self) -> None:
        # Ollama's /api/ps keeps listing a model for a few seconds after an
        # unload request; that stale listing must not read as a fresh load
        # (which would then produce a phantom eviction on the next poll).
        tracker = ActivityTracker()
        tracker.observe({"qwen2.5:7b": 4.2})
        tracker.record_unloaded("qwen2.5:7b")
        tracker.observe({"qwen2.5:7b": 4.2})
        tracker.observe({})

        events = tracker.events()
        assert len(events) == 1
        assert events[0].action == "unloaded"

    def test_appearance_after_grace_expires_is_a_real_load(self) -> None:
        tracker = ActivityTracker(stale_grace_seconds=0.0)
        tracker.observe({"qwen2.5:7b": 4.2})
        tracker.record_unloaded("qwen2.5:7b")
        tracker.observe({"qwen2.5:7b": 4.2})

        events = tracker.events()
        assert len(events) == 2
        assert events[0].action == "loaded"
        assert events[0].detected is True

    def test_ps_lag_after_explicit_load_is_not_an_eviction(self) -> None:
        # The mirror race: right after an explicit load, a poll that does
        # not list the model yet must not read as an eviction.
        tracker = ActivityTracker()
        tracker.observe({})
        tracker.record_loaded("qwen2.5:7b")
        tracker.observe({})
        tracker.observe({"qwen2.5:7b": 4.2})

        events = tracker.events()
        assert len(events) == 1
        assert events[0].action == "loaded"
        assert events[0].vram_gb == 4.2

    def test_event_count_is_bounded(self) -> None:
        tracker = ActivityTracker(max_events=3)
        tracker.observe({})
        for i in range(5):
            tracker.observe({f"m{i}:1b": 1.0})
            tracker.observe({})

        assert len(tracker.events()) == 3

    def test_singleton_accessor_returns_same_instance(self) -> None:
        assert get_inference_activity() is get_inference_activity()


class TestModelMoves:
    """Load and unload go through one door, whoever asks (dashboard, page)."""

    async def test_an_action_reaches_its_call(self) -> None:
        calls: list[tuple[str, str]] = []

        class Recording(OllamaEngine):
            async def _move(self, action: str, model_name: str) -> bool:
                calls.append((action, model_name))
                return True

        assert await Recording(base_url="http://x").move("load", "m") is True
        assert calls == [("load", "m")]


class TestServerStatusReads:
    """The status the inference sampler reads every tick while the page is
    watched: one connection and one ``/api/tags``, which also answers
    whether the server is there at all."""

    @staticmethod
    def _client(handle: Any) -> tuple[OllamaEngine, list[str], list[int]]:
        asked: list[str] = []
        opened: list[int] = []

        def record(request: httpx.Request) -> httpx.Response:
            asked.append(request.url.path)
            return handle(request)

        client = OllamaEngine(
            "http://ollama:11434", transport=httpx.MockTransport(record)
        )
        build = client._client

        def counted(timeout: float = OllamaEngine.TIMEOUT) -> httpx.AsyncClient:
            opened.append(1)
            return build(timeout)

        client._client = counted  # type: ignore[method-assign]
        return client, asked, opened

    async def test_one_connection_and_one_tags_read(self) -> None:
        client, asked, opened = self._client(serving(ROUTES))
        status = await client.get_server_status()
        assert status.available
        assert sorted(asked) == ["/api/ps", "/api/tags", "/api/version"]
        assert len(opened) == 1

    async def test_a_failed_tags_read_is_unavailable(self) -> None:
        client, asked, _ = self._client(down)
        assert not (await client.get_server_status()).available
        assert asked == ["/api/tags"]


class TestSampler:
    """The inference sampler is the one reader of Ollama: it notices model
    loads and evictions as it reads, and the Flet modal shows its last
    reading rather than polling the server itself."""

    @pytest.fixture(autouse=True)
    def fake_server(self, monkeypatch: pytest.MonkeyPatch) -> list[int]:
        reads: list[int] = []

        class Counted(FakeClient):
            async def get_server_status(self) -> InferenceServerStatus:
                reads.append(1)
                return self.status

        serve(monkeypatch, Counted)
        return reads

    async def test_it_reads_each_loaded_models_memory(self) -> None:
        reading = await sampler.read()
        assert reading.values == {
            f"qwen2.5:7b:{series.MEMORY}": RUNNING.size,
            f"qwen2.5:7b:{series.VRAM}": RUNNING.size_vram,
        }
        assert reading.latest == (SERVING, "http://host.docker.internal:11434")

    async def test_a_model_that_appears_between_readings_is_a_load(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(FakeClient, "status", InferenceServerStatus(available=True))
        await sampler.read()
        monkeypatch.setattr(FakeClient, "status", SERVING)
        await sampler.read()
        (event,) = get_inference_activity().events()
        assert (event.action, event.model) == ("loaded", RUNNING.name)

    async def test_the_modal_status_is_the_samplers_reading(
        self, fake_server: list[int]
    ) -> None:
        first = await sampler.current_status()
        second = await sampler.current_status()
        assert first.status == ComponentStatusType.HEALTHY
        assert RUNNING.name in first.message and first == second
        assert len(fake_server) == 1


class TestSpeechServer:
    """The speech server's status in the inference health check."""

    @pytest.fixture(autouse=True)
    def ollama(self, monkeypatch: pytest.MonkeyPatch) -> None:
        serve(monkeypatch)
        monkeypatch.setattr(settings, "SPEECH_BASE_URL", SPEECH_URL)

    def _answers(
        self, monkeypatch: pytest.MonkeyPatch, reading: SpeechServerReading
    ) -> None:
        async def read(url: str) -> SpeechServerReading:
            return reading

        monkeypatch.setattr(speech_server, "read", read)

    async def test_its_voices_are_in_the_inference_check(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._answers(monkeypatch, SPEECH_READY)

        status = await check_ollama_health()

        speech = status.sub_components["speech"]
        assert status.message.startswith(RUNNING.name)
        assert speech.status == ComponentStatusType.HEALTHY
        assert "2 voices" in speech.message
        assert speech.metadata["base_url"] == SPEECH_URL

    async def test_one_that_does_not_answer_is_unhealthy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._answers(monkeypatch, SPEECH_DOWN)

        speech = (await check_ollama_health()).sub_components["speech"]

        assert speech.status == ComponentStatusType.UNHEALTHY

    async def test_it_is_carried_while_ollama_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class Failing(FakeClient):
            async def get_server_status(self) -> InferenceServerStatus:
                raise httpx.ReadError("/api/ps failed")

        serve(monkeypatch, Failing)
        self._answers(monkeypatch, SPEECH_READY)

        status = await check_ollama_health()

        assert status.status == ComponentStatusType.UNHEALTHY
        assert status.sub_components["speech"].status == ComponentStatusType.HEALTHY

    async def test_without_an_address_there_is_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "SPEECH_BASE_URL", None)

        assert (await check_ollama_health()).sub_components == {}


def test_the_inference_page_charts_come_with_the_component() -> None:
    """Ollama's host note and charts ship with the inference component and
    reach ``ui_runtime`` through the sampler registry, so a stack without
    inference carries none of them."""
    from app.services.system import ui_runtime

    assert ui_runtime.host_of("inference") is sampler.HOST
    assert [c.key for c in sampler.HOST.charts] == ["model-memory", "tokens", "latency"]
    assert ui_runtime.host_of("redis") is None

    async def test_after_its_own_action_the_modal_reads_now(
        self, fake_server: list[int]
    ) -> None:
        await sampler.current_status()
        await sampler.current_status(fresh=True)
        assert len(fake_server) == 2
