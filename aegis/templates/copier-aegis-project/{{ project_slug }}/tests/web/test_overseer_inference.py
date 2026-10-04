"""The Overseer Inference page: what Ollama is serving (Overview), every
installed model with load and unload (Models), and the models moving in
and out of memory (Activity). Everything reads the server live, so a load
shows on the next render rather than the next health poll."""

import asyncio
from collections.abc import Generator

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.inference import activity, sampler
from app.components.inference.ollama import OllamaServerStatus
from app.components.web_frontend import overseer_inference
from app.services.system.models import ComponentStatus, ComponentStatusType
from tests._fake_ollama import SERVING, FakeClient, serve
from tests.web.dom import chart_json, one, select, text
from tests.web.overseer import sign_in, status_with

PAGE = "/overseer/components/ollama"
OLLAMA = ComponentStatus(
    name="ollama",
    status=ComponentStatusType.HEALTHY,
    message="qwen2.5:7b warm",
    metadata={"base_url": "http://host.docker.internal:11434"},
)


@pytest.fixture
def signed_in(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    sign_in(app, monkeypatch, status_with(OLLAMA))
    FakeClient.status, FakeClient.loaded, FakeClient.calls = SERVING, True, []
    monkeypatch.setattr(overseer_inference, "OllamaClient", FakeClient)
    serve(monkeypatch)
    monkeypatch.setattr(overseer_inference, "_moving", {})
    monkeypatch.setattr(overseer_inference, "_failed", {})
    with TestClient(app) as client:
        yield client


def _get(client: TestClient, section: str = "") -> str:
    response = client.get(PAGE + (f"/{section}" if section else ""))
    assert response.status_code == 200
    return response.text


def _figures(html: str) -> dict[str, str]:
    return {
        text(one(cell, "dt")): text(one(cell, "dd"))
        for cell in select(html, "#inference-figures > div")
    }


def test_sections_are_overview_models_and_activity(signed_in: TestClient) -> None:
    assert [text(a) for a in select(_get(signed_in), "#overseer-subnav nav a")] == [
        "Overview",
        "Models",
        "Activity",
        "Container",
        "Logs",
    ]


def test_overview_says_what_is_loaded(signed_in: TestClient) -> None:
    figures = _figures(_get(signed_in))
    assert figures["Loaded"] == "1 / 2"
    assert figures["VRAM"] == "4.2 GB"
    assert figures["Version"] == "0.12.3"


def test_overview_names_the_server(signed_in: TestClient) -> None:
    assert "host.docker.internal:11434" in text(one(_get(signed_in), "#card-server"))


def test_an_unreachable_server_says_where_it_looked(signed_in: TestClient) -> None:
    FakeClient.status = OllamaServerStatus(available=False)
    alert = text(one(_get(signed_in), "[role=alert]"))
    assert "host.docker.internal:11434" in alert


def _rows(html: str) -> dict[str, str]:
    return {
        text(select(row, "td")[0]): text(row)
        for row in select(html, "#inference-models tbody tr")
    }


def test_models_lists_every_installed_model(signed_in: TestClient) -> None:
    rows = _rows(_get(signed_in, "models"))
    assert set(rows) == {"qwen2.5:7b", "llama3.1:8b"}
    assert "4-bit" in rows["llama3.1:8b"] and "32k" in rows["llama3.1:8b"]


def test_a_loaded_model_offers_unload_and_an_idle_one_load(
    signed_in: TestClient,
) -> None:
    rows = _rows(_get(signed_in, "models"))
    assert "Unload" in rows["qwen2.5:7b"]
    assert "Load" in rows["llama3.1:8b"] and "Unload" not in rows["llama3.1:8b"]


def test_the_row_buttons_post_to_the_actions(signed_in: TestClient) -> None:
    """A mangled attribute leaves htmx posting to the page itself (a 404)."""
    buttons = select(_get(signed_in, "models"), "#inference-models button[hx-post]")
    assert {b.get("hx-post") for b in buttons} == {
        f"{overseer_inference.PARTIALS}/load",
        f"{overseer_inference.PARTIALS}/unload",
    }


def test_the_table_fits_without_the_digest(signed_in: TestClient) -> None:
    rows = _rows(_get(signed_in, "models"))
    assert "7.6B, 4-bit" in rows["llama3.1:8b"]
    assert "0123456789ab" not in rows["llama3.1:8b"]


def test_load_answers_at_once(signed_in: TestClient) -> None:
    """A 27B model takes a while to load; the click returns straight away and
    the table's stream shows it arriving."""
    response = signed_in.post(
        f"{overseer_inference.PARTIALS}/load", data={"model": "llama3.1:8b"}
    )
    assert response.status_code == 200


def test_a_model_already_moving_is_not_asked_twice(signed_in: TestClient) -> None:
    overseer_inference._moving["llama3.1:8b"] = "load"
    response = signed_in.post(
        f"{overseer_inference.PARTIALS}/load", data={"model": "llama3.1:8b"}
    )
    assert response.status_code == 409
    assert FakeClient.calls == []


@pytest.mark.asyncio
async def test_a_row_shows_the_load_in_flight_then_its_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeClient.calls = []
    monkeypatch.setattr(overseer_inference, "OllamaClient", FakeClient)
    monkeypatch.setattr(overseer_inference, "_moving", {})
    monkeypatch.setattr(overseer_inference, "_failed", {})

    task = overseer_inference.start("load", "llama3.1:8b")
    during = {r["model"]: r for r in overseer_inference.model_rows(SERVING)}
    assert during["llama3.1:8b"]["state"]["label"] == "Loading..."
    assert during["llama3.1:8b"]["moving"]

    await task
    assert FakeClient.calls == [("load", "llama3.1:8b")]
    after = {r["model"]: r for r in overseer_inference.model_rows(SERVING)}
    assert not after["llama3.1:8b"]["moving"]


@pytest.mark.asyncio
async def test_a_refused_load_stays_on_the_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(overseer_inference, "OllamaClient", FakeClient)
    monkeypatch.setattr(overseer_inference, "_moving", {})
    monkeypatch.setattr(overseer_inference, "_failed", {})
    monkeypatch.setattr(FakeClient, "loaded", False)

    await overseer_inference.start("load", "llama3.1:8b")
    rows = {r["model"]: r for r in overseer_inference.model_rows(SERVING)}
    assert rows["llama3.1:8b"]["state"] == {"label": "Load failed", "tone": "error"}


def test_a_failure_the_server_contradicts_gives_way(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A timed-out load that finished anyway shows Loaded, not Load failed."""
    monkeypatch.setattr(overseer_inference, "_moving", {})
    monkeypatch.setattr(
        overseer_inference, "_failed", {"qwen2.5:7b": "load", "llama3.1:8b": "unload"}
    )
    rows = {r["model"]: r for r in overseer_inference.model_rows(SERVING)}
    assert rows["qwen2.5:7b"]["state"]["label"].startswith("Loaded")
    assert rows["llama3.1:8b"]["state"]["label"] == "Idle"
    assert overseer_inference._failed == {}


def test_the_table_streams_while_the_page_is_open(signed_in: TestClient) -> None:
    card = one(_get(signed_in, "models"), "#inference-models-live")
    assert card.get("sse-connect") == overseer_inference.MODELS_EVENTS


@pytest.mark.asyncio
async def test_the_stream_sends_the_table_only_when_it_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(overseer_inference, "OllamaClient", FakeClient)
    monkeypatch.setattr(overseer_inference, "MODELS_INTERVAL_SECONDS", 0)
    frames = [f async for f in overseer_inference.models_events(max_frames=3)]
    events = [f for f in frames if f.startswith("event:")]
    assert len(events) == 1
    assert events[0].startswith(f"event: {overseer_inference.MODELS_EVENT}\n")


def test_the_stream_needs_a_signed_in_user(client: TestClient) -> None:
    assert client.get(overseer_inference.MODELS_EVENTS).status_code == 401


def test_only_load_and_unload_are_actions(signed_in: TestClient) -> None:
    response = signed_in.post(
        f"{overseer_inference.PARTIALS}/delete", data={"model": "llama3.1:8b"}
    )
    assert response.status_code == 404
    assert FakeClient.calls == []


def test_activity_starts_empty(signed_in: TestClient) -> None:
    assert select(_get(signed_in, "activity"), "[data-empty]")


def test_activity_lists_what_moved(signed_in: TestClient) -> None:
    activity.get_ollama_activity().record_loaded("llama3.1:8b")
    rows = select(_get(signed_in, "activity"), "#inference-activity tbody tr")
    assert "llama3.1:8b" in text(rows[0])


def test_models_are_served_from_the_one_shared_reading(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sampler reads Ollama once a tick for every viewer; a page reads
    that, not the server."""
    from app.core import series

    asyncio.run(series.sample(sampler.SAMPLER))
    FakeClient.status = OllamaServerStatus(available=False)  # a live read
    html = _get(signed_in, "models")
    loaded, _idle = select(html, "#inference-models tbody tr")
    assert "Loaded" in text(loaded)


def test_a_server_outside_docker_shows_its_own_numbers_in_place_of_a_container(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ollama on the host has no container to read: the Container section
    says so and charts what Ollama and the app's own calls report."""
    from app.core import series
    from tests._fake_runtime import REDIS, FakeRuntime, use_runtime

    use_runtime(monkeypatch, FakeRuntime(REDIS))  # no Ollama container
    asyncio.run(series.sample(sampler.SAMPLER))
    asyncio.run(
        series.record({f"{series.LLM}:qwen2.5:7b:{series.TOKENS_PER_SECOND}": 25.0})
    )
    html = _get(signed_in, "container")
    assert "outside Docker" in text(one(html, "#container"))
    memory = chart_json(html, "chart-container-model-memory-data")
    assert memory["series"][0]["label"] == "qwen2.5:7b"
    tokens = chart_json(html, "chart-container-tokens-data")
    assert tokens["series"] == [{"label": "qwen2.5:7b", "values": [25.0]}]
    # A call is a moment, not a level: dots, never a line between two calls.
    assert tokens["style"] == "events" and "style" not in memory
    # No call has been timed yet: the chart says so rather than draw nothing.
    assert "No calls" in text(one(html, "#chart-container-latency [data-chart-empty]"))


def test_the_host_section_keeps_its_own_sampler_watched(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What the section charts (the inference sampler) runs at full pace while
    it is open; Docker, which has nothing to show here, does not."""
    from app.core import series
    from app.services.system import ui_runtime
    from tests._fake_runtime import REDIS, FakeRuntime, use_runtime

    use_runtime(monkeypatch, FakeRuntime(REDIS))  # no Ollama container
    asyncio.run(series.sample(sampler.SAMPLER))
    _get(signed_in, "container")
    assert asyncio.run(series.watched(series.INFERENCE))
    assert not asyncio.run(series.watched(ui_runtime.SAMPLER))
