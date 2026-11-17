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
from tests import _fake_llamacpp, _fake_ollama
from tests._fake_ollama import down, serving

# Each engine's fake server: its name in ``ENGINES`` and the JSON it
# answers per path.
SERVERS = [
    pytest.param("ollama", _fake_ollama.ROUTES, id="ollama"),
    pytest.param("llamacpp", _fake_llamacpp.ROUTES, id="llamacpp"),
    pytest.param("llamacpp", _fake_llamacpp.ROUTER, id="llamacpp-router"),
]
TWO = {"qwen2.5:7b", "llama3.1:8b"}
# What each serves: the models installed, and those loaded. Ollama and a
# llama-server router have two with one loaded; a single-model llama-server,
# its one.
SERVES = {
    id(_fake_ollama.ROUTES): (TWO, ["qwen2.5:7b"]),
    id(_fake_llamacpp.ROUTES): ({"qwen2.5:7b"}, ["qwen2.5:7b"]),
    id(_fake_llamacpp.ROUTER): (TWO, ["qwen2.5:7b"]),
}


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
        installed, loaded = SERVES[id(routes)]

        assert isinstance(status, InferenceServerStatus)
        assert status.available and status.version
        assert {m.name for m in status.installed_models} == installed
        assert [m.name for m in status.running_models] == loaded
        assert all(isinstance(m, InferenceModel) for m in status.installed_models)
        assert all(isinstance(m, RunningModel) for m in status.running_models)

    async def test_the_models_are_the_installed_ones(
        self, name: str, routes: dict[str, Any]
    ) -> None:
        models = await _engine(name, serving(routes)).fetch_models()

        assert {m.model_id for m in models} == SERVES[id(routes)][0]

    async def test_a_server_that_is_down_is_unavailable_not_an_error(
        self, name: str, routes: dict[str, Any]
    ) -> None:
        assert not (await _engine(name, down).get_server_status()).available

    async def test_a_quiet_turn_says_whether_its_model_is_loading(
        self, name: str, routes: dict[str, Any]
    ) -> None:
        """A turn's silence, explained: its model is in memory and working,
        or still being loaded. A single-model server answers on the model it
        serves, whatever the turn calls it."""
        engine = _engine(name, serving(routes))
        status = await engine.get_server_status()
        cold = "loading" if status.can_load_unload else "thinking"

        assert await engine.waiting_reason("qwen2.5:7b") == "thinking"
        assert await engine.waiting_reason("llama3.1:8b") == cold
        assert await _engine(name, down).waiting_reason("qwen2.5:7b") is None

    async def test_a_quiet_turn_costs_one_read(
        self, name: str, routes: dict[str, Any]
    ) -> None:
        """Asked every quiet stretch, it read the whole status (three reads
        on Ollama, two on llama.cpp): it asks one thing, what is loaded, or
        on a server that serves only its one model, whether it is up."""
        asked: list[str] = []
        answer = serving(routes)

        def counted(request: httpx.Request) -> httpx.Response:
            asked.append(request.url.path)
            return answer(request)

        await _engine(name, counted).waiting_reason("qwen2.5:7b")

        assert len(asked) == 1

    async def test_a_move_lands_on_the_activity_tab(
        self, name: str, routes: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _engine(name, serving(routes))

        async def moved(action: str, model: str) -> None:
            return None

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


def test_an_engine_is_had_by_its_name() -> None:
    """The AI service's local providers are named as the engines are."""
    assert get_inference_engine("llamacpp").NAME == "llamacpp"


async def test_a_single_model_llama_server_cannot_move_its_model() -> None:
    """Its one model is the one it was started with: there is no load or
    unload to offer, and asking for one does nothing."""
    engine = _engine("llamacpp", serving(_fake_llamacpp.ROUTES))

    assert not (await engine.get_server_status()).can_load_unload
    assert not await engine.move("unload", "qwen2.5:7b")


@pytest.mark.parametrize("action", ["load", "unload"])
async def test_a_llama_server_router_moves_a_model_by_name(action: str) -> None:
    """A router (``--models-dir``) loads and frees its models on request,
    as Ollama does: the pages offer the buttons."""
    asked: list[tuple[str, bytes]] = []
    answer = serving(_fake_llamacpp.ROUTER)

    def recorded(request: httpx.Request) -> httpx.Response:
        asked.append((request.url.path, request.content))
        return answer(request)

    engine = _engine("llamacpp", recorded)

    assert (await engine.get_server_status()).can_load_unload
    assert await engine.move(action, "llama3.1:8b")
    assert (f"/models/{action}", b'{"model":"llama3.1:8b"}') in asked


async def test_a_router_reports_the_context_a_model_was_trained_for() -> None:
    """A router knows each model's trained context, and where it found it;
    not its size until loaded, so the size stays the unknown 0."""
    status = await _engine(
        "llamacpp", serving(_fake_llamacpp.ROUTER)
    ).get_server_status()
    model = next(m for m in status.installed_models if m.name == "llama3.1:8b")

    assert status.version == "b12110-cd959bae9"
    assert model.details.context_length == 131072
    assert model.details.format == "gguf"
    assert model.size == 0


async def test_llama_server_reports_what_the_ollama_shaped_list_leaves_empty() -> None:
    """Size, context and quantization come from ``data[].meta``, not from
    the Ollama-shaped ``models`` list beside it, whose fields are empty."""
    status = await _engine("llamacpp", serving(_fake_llamacpp.ROUTES)).get_server_status()
    model = status.installed_models[0]

    assert status.version == "b6700-cd959bae9"
    assert model.size == 4683073952
    assert model.details.context_length == 131072
    assert model.details.quantization_level == "Q4_K - Medium"
    assert model.details.parameter_size == "7.6B"
    assert "tools" in model.capabilities
    assert status.running_models[0].context_length == 32768


def test_an_engine_is_titled_with_the_version_it_reports() -> None:
    """A release number reads ``v0.5.7``; llama.cpp's build is its own."""
    from app.components.inference import ENGINES

    assert ENGINES["ollama"].titled("0.5.7") == "Ollama v0.5.7"
    assert ENGINES["llamacpp"].titled("b6700-cd959bae9") == "llama.cpp b6700-cd959bae9"
    assert ENGINES["ollama"].titled(None) == "Ollama"
