"""Tests for the ephemeral Ollama model activity tracker."""

import pytest

from app.components.inference.activity import (
    OllamaActivityTracker,
    get_ollama_activity,
)
from app.components.inference.ollama import OllamaClient


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
