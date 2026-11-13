"""Every inference engine answers the same questions in the same shapes
(``app.components.inference.engine``): what the server is running, what it
has, and whether it is there. A second engine is a fake server added to
``SERVERS``, not a second set of tests."""

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.components.inference import ENGINES, activity, get_inference_engine
from app.components.inference.engine import (
    BaseInferenceEngine,
    InferenceModel,
    InferenceServerStatus,
    RunningModel,
)
from tests import _fake_ollama
from tests._fake_ollama import down, serving

# Each engine's fake server: its name in ``ENGINES`` and the JSON it answers
# per path, serving the same two installed models with one loaded.
SERVERS = [("ollama", _fake_ollama.ROUTES)]
INSTALLED = {"qwen2.5:7b", "llama3.1:8b"}
LOADED = ["qwen2.5:7b"]


def _engine(
    name: str, answer: Callable[[httpx.Request], httpx.Response]
) -> BaseInferenceEngine:
    return ENGINES[name]("http://engine:1", transport=httpx.MockTransport(answer))


@pytest.mark.parametrize(("name", "routes"), SERVERS)
class TestTheContract:
    async def test_the_status_carries_the_models_in_neutral_shapes(
        self, name: str, routes: dict[str, Any]
    ) -> None:
        status = await _engine(name, serving(routes)).get_server_status()

        assert isinstance(status, InferenceServerStatus)
        assert status.available and status.version
        assert {m.name for m in status.installed_models} == INSTALLED
        assert [m.name for m in status.running_models] == LOADED
        assert all(isinstance(m, InferenceModel) for m in status.installed_models)
        assert all(isinstance(m, RunningModel) for m in status.running_models)

    async def test_the_models_are_the_installed_ones(
        self, name: str, routes: dict[str, Any]
    ) -> None:
        models = await _engine(name, serving(routes)).fetch_models()

        assert {m.model_id for m in models} == INSTALLED

    async def test_a_server_that_is_down_is_unavailable_not_an_error(
        self, name: str, routes: dict[str, Any]
    ) -> None:
        assert not (await _engine(name, down).get_server_status()).available

    async def test_a_move_lands_on_the_activity_tab(
        self, name: str, routes: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _engine(name, serving(routes))

        async def moved(action: str, model: str) -> bool:
            return True

        monkeypatch.setattr(engine, "_move", moved)
        monkeypatch.setattr(activity, "_tracker", activity.ActivityTracker())

        assert await engine.move("load", "qwen2.5:7b")
        assert [e.action for e in activity.get_inference_activity().events()] == [
            "loaded"
        ]

    async def test_only_load_and_unload_are_moves(
        self, name: str, routes: dict[str, Any]
    ) -> None:
        with pytest.raises(ValueError, match="delete"):
            await _engine(name, serving(routes)).move("delete", "m")


def test_callers_get_the_engine_without_naming_its_class() -> None:
    assert isinstance(get_inference_engine(), BaseInferenceEngine)
