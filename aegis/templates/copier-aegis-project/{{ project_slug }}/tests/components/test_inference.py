"""Tests for the ephemeral Ollama model activity tracker."""

from typing import Any

import httpx
import pytest

from app.components.inference import sampler
from app.components.inference.activity import (
    OllamaActivityTracker,
    get_ollama_activity,
)
from app.components.inference.ollama import OllamaClient, OllamaServerStatus
from app.core import series
from app.services.system.models import ComponentStatusType
from tests._fake_ollama import RUNNING, SERVING, FakeClient, serve


class TestOllamaActivityTracker:
    """Diff/record behavior of the in-memory activity tracker."""

    def test_first_observation_sets_baseline_without_events(self) -> None:
        tracker = OllamaActivityTracker()
        tracker.observe({"qwen2.5:7b": 4.2})

        assert tracker.events() == []

    def test_detected_load_records_event(self) -> None:
        tracker = OllamaActivityTracker()
        tracker.observe({})
        tracker.observe({"qwen2.5:7b": 4.2})

        events = tracker.events()
        assert len(events) == 1
        assert events[0].action == "loaded"
        assert events[0].model == "qwen2.5:7b"
        assert events[0].vram_gb == 4.2
        assert events[0].detected is True

    def test_eviction_records_event_with_last_known_vram(self) -> None:
        tracker = OllamaActivityTracker()
        tracker.observe({"qwen2.5:7b": 4.2})
        tracker.observe({})

        events = tracker.events()
        assert len(events) == 1
        assert events[0].action == "evicted"
        assert events[0].model == "qwen2.5:7b"
        assert events[0].vram_gb == 4.2
        assert events[0].detected is True

    def test_explicit_load_is_not_double_counted_and_backfills_vram(self) -> None:
        tracker = OllamaActivityTracker()
        tracker.observe({})
        tracker.record_loaded("qwen2.5:7b")
        tracker.observe({"qwen2.5:7b": 4.2})

        events = tracker.events()
        assert len(events) == 1
        assert events[0].action == "loaded"
        assert events[0].detected is False
        assert events[0].vram_gb == 4.2

    def test_explicit_unload_is_not_double_counted(self) -> None:
        tracker = OllamaActivityTracker()
        tracker.observe({"qwen2.5:7b": 4.2})
        tracker.record_unloaded("qwen2.5:7b")
        tracker.observe({})

        events = tracker.events()
        assert len(events) == 1
        assert events[0].action == "unloaded"
        assert events[0].detected is False
        assert events[0].vram_gb == 4.2

    def test_events_are_newest_first(self) -> None:
        tracker = OllamaActivityTracker()
        tracker.observe({})
        tracker.observe({"a:1b": 1.0})
        tracker.observe({"a:1b": 1.0, "b:2b": 2.0})

        events = tracker.events()
        assert [e.model for e in events] == ["b:2b", "a:1b"]

    def test_stale_listing_after_explicit_unload_is_not_a_load(self) -> None:
        # Ollama's /api/ps keeps listing a model for a few seconds after an
        # unload request; that stale listing must not read as a fresh load
        # (which would then produce a phantom eviction on the next poll).
        tracker = OllamaActivityTracker()
        tracker.observe({"qwen2.5:7b": 4.2})
        tracker.record_unloaded("qwen2.5:7b")
        tracker.observe({"qwen2.5:7b": 4.2})
        tracker.observe({})

        events = tracker.events()
        assert len(events) == 1
        assert events[0].action == "unloaded"

    def test_appearance_after_grace_expires_is_a_real_load(self) -> None:
        tracker = OllamaActivityTracker(stale_grace_seconds=0.0)
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
        tracker = OllamaActivityTracker()
        tracker.observe({})
        tracker.record_loaded("qwen2.5:7b")
        tracker.observe({})
        tracker.observe({"qwen2.5:7b": 4.2})

        events = tracker.events()
        assert len(events) == 1
        assert events[0].action == "loaded"
        assert events[0].vram_gb == 4.2

    def test_event_count_is_bounded(self) -> None:
        tracker = OllamaActivityTracker(max_events=3)
        tracker.observe({})
        for i in range(5):
            tracker.observe({f"m{i}:1b": 1.0})
            tracker.observe({})

        assert len(tracker.events()) == 3

    def test_singleton_accessor_returns_same_instance(self) -> None:
        assert get_ollama_activity() is get_ollama_activity()


class TestModelMoves:
    """Load and unload go through one door, whoever asks (dashboard, page)."""

    async def test_an_action_reaches_its_call(self) -> None:
        calls: list[tuple[str, str]] = []

        class Recording(OllamaClient):
            async def load_model(
                self, model_name: str, keep_alive: str = "30m"
            ) -> bool:
                calls.append(("load", model_name))
                return True

        assert await Recording(base_url="http://x").move("load", "m") is True
        assert calls == [("load", "m")]

    async def test_anything_else_is_refused(self) -> None:
        with pytest.raises(ValueError, match="delete"):
            await OllamaClient(base_url="http://x").move("delete", "m")


class TestServerStatusReads:
    """The status the inference sampler reads every tick while the page is
    watched: one connection and one ``/api/tags``, which also answers
    whether the server is there at all."""

    @staticmethod
    def _client(handle: Any) -> tuple[OllamaClient, list[str], list[int]]:
        asked: list[str] = []
        opened: list[int] = []

        def record(request: httpx.Request) -> httpx.Response:
            asked.append(request.url.path)
            return handle(request)

        client = OllamaClient(
            "http://ollama:11434", transport=httpx.MockTransport(record)
        )
        build = client._client

        def counted(timeout: float = OllamaClient.TIMEOUT) -> httpx.AsyncClient:
            opened.append(1)
            return build(timeout)

        client._client = counted  # type: ignore[method-assign]
        return client, asked, opened

    async def test_one_connection_and_one_tags_read(self) -> None:
        bodies = {
            "/api/tags": {"models": []},
            "/api/ps": {"models": []},
            "/api/version": {"version": "0.12.0"},
        }
        client, asked, opened = self._client(
            lambda r: httpx.Response(200, json=bodies[r.url.path])
        )
        status = await client.get_server_status()
        assert status.available and status.version == "0.12.0"
        assert sorted(asked) == ["/api/ps", "/api/tags", "/api/version"]
        assert len(opened) == 1

    async def test_a_failed_tags_read_is_unavailable(self) -> None:
        def down(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

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
            async def get_server_status(self) -> OllamaServerStatus:
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
        monkeypatch.setattr(FakeClient, "status", OllamaServerStatus(available=True))
        await sampler.read()
        monkeypatch.setattr(FakeClient, "status", SERVING)
        await sampler.read()
        (event,) = get_ollama_activity().events()
        assert (event.action, event.model) == ("loaded", RUNNING.name)

    async def test_the_modal_status_is_the_samplers_reading(
        self, fake_server: list[int]
    ) -> None:
        first = await sampler.current_status()
        second = await sampler.current_status()
        assert first.status == ComponentStatusType.HEALTHY
        assert RUNNING.name in first.message and first == second
        assert len(fake_server) == 1


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
