"""The Overseer Inference page: every engine on its Overview (a row each,
the memory they report, who runs on each, how to add one), the nav grouped
by job, and a page per engine with its own tabs: the text engine's Overview,
Models (load and unload) and Activity, the speech server's Overview and
Voices. Everything reads the samplers' last readings, so a load shows on the
next render rather than the next health poll."""

import asyncio
from collections.abc import Generator

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.inference import activity, overview, sampler
from app.components.inference.engine import (
    InferenceModel,
    InferenceServerStatus,
    ModelDetails,
)
from app.components.inference.llamacpp import LlamaCppEngine
from app.components.web_frontend import overseer_inference_speech as speech_page
from app.components.web_frontend import overseer_inference_text as text_page
from app.core import speech_server
from app.services.system.models import ComponentStatus, ComponentStatusType
from tests._fake_ollama import (
    SERVING,
    SPEECH_DOWN,
    SPEECH_READY,
    SPEECH_URL,
    FakeClient,
    serve,
    speaking,
)
from tests.web.dom import chart_json, one, select, stat, table_text, text
from tests.web.overseer import sent_events, sign_in, status_with

PAGE = "/overseer/components/inference"
TEXT = f"{PAGE}/ollama"
SPEECH = f"{PAGE}/{speech_server.SLUG}"
OLLAMA = ComponentStatus(
    name="inference",
    status=ComponentStatusType.HEALTHY,
    message="qwen2.5:7b warm",
    metadata={"base_url": "http://host.docker.internal:11434"},
)


@pytest.fixture
def signed_in(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    sign_in(app, monkeypatch, status_with(OLLAMA))
    monkeypatch.setattr(FakeClient, "status", SERVING)
    monkeypatch.setattr(FakeClient, "loaded", True)
    monkeypatch.setattr(FakeClient, "calls", [])
    serve(monkeypatch)
    monkeypatch.setattr(text_page, "_moving", {})
    monkeypatch.setattr(text_page, "_failed", {})
    with TestClient(app) as client:
        yield client


def _get(client: TestClient, url: str = PAGE, tab: str | None = None) -> str:
    response = client.get(url, params={"tab": tab} if tab else None)
    assert response.status_code == 200
    return response.text


def _figures(html: str) -> dict[str, str]:
    return {
        text(one(cell, "dt")): text(one(cell, "dd"))
        for cell in select(html, "#inference-figures > div")
    }


def test_the_nav_groups_the_engines_by_job(signed_in: TestClient) -> None:
    """A page per engine, under its job; the containers behind them after."""
    html = _get(signed_in)
    assert [text(h) for h in select(html, "#overseer-subnav h3")] == ["Text", "Speech"]
    assert [text(a) for a in select(html, "#overseer-subnav nav a")] == [
        "Overview",
        "Ollama",
        speech_server.NAME,
        "Container",
        "Logs",
    ]


def test_an_engine_page_has_the_tabs_it_has(signed_in: TestClient) -> None:
    def tabs(url: str) -> list[str]:
        return [text(a) for a in select(_get(signed_in, url), "[role=tablist] a")]

    assert tabs(TEXT) == ["Overview", "Models", "Activity"]
    assert tabs(SPEECH) == ["Overview", "Voices"]


def _engines(html: str) -> dict[str, dict[str, str]]:
    return {r["Engine"]: r for r in table_text(html, "#inference-engines table")}


def test_the_overview_is_a_row_per_engine(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    speaking(monkeypatch, SPEECH_READY.model_copy(update={"memory_bytes": 812 * 2**20}))

    rows = _engines(_get(signed_in))

    assert set(rows) == {"Ollama", speech_server.NAME}
    assert rows["Ollama"]["Job"] == "Text"
    assert "qwen2.5:7b" in rows["Ollama"]["Loaded"]
    assert rows["Ollama"]["Memory"] == "4.2 GB"
    assert rows[speech_server.NAME]["Memory"] == "812.0 MB"
    links = select(_get(signed_in), "#inference-engines tbody a")
    assert {a.get("href") for a in links} >= {TEXT, SPEECH}


def test_a_row_that_reports_no_memory_says_so_never_zero(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    speaking(
        monkeypatch, SPEECH_READY.model_copy(update={"closed": [speech_server.DEBUG]})
    )

    row = _engines(_get(signed_in))[speech_server.NAME]

    assert f"{speech_server.DEBUG}=true" in row["Memory"]


def test_one_memory_bar_across_the_engines(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    speaking(monkeypatch, SPEECH_READY.model_copy(update={"memory_bytes": 812 * 2**20}))

    bar = one(_get(signed_in), "#inference-memory")

    segments = select(bar, "[data-segment]")
    assert [s.get("data-segment") for s in segments] == ["Ollama", speech_server.NAME]
    assert "5.0 GB" in text(bar)


def test_an_engine_the_app_lacks_says_how_to_add_it(signed_in: TestClient) -> None:
    """A command or an address, never an install button."""
    added = one(_get(signed_in), "#inference-add")

    assert "aegis add inference[kokoro_fastapi]" in text(added)
    assert "SPEECH_BASE_URL" in text(added)
    assert "aegis add inference[llamacpp]" in text(added)
    assert not select(added, "button[hx-post]")


def test_each_engine_says_who_runs_on_it(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Used:
        uses = [type("Use", (), {"engine": "ollama", "by": "Assistant"})()]
        in_app: list[object] = []

    async def users(session: object, server: object) -> Used:
        return Used()

    monkeypatch.setattr(overview, "_users", users)

    assert _engines(_get(signed_in))["Ollama"]["Used by"] == "Assistant"


# Kokoro-FastAPI with its flags on: what it reports past the listings.
SPEECH_REPORTING = SPEECH_READY.model_copy(
    update={
        "version": "0.10.1",
        "device": "mps",
        "loaded": True,
        "active_requests": 0,
        "memory_bytes": 812 * 2**20,
        "threads": 12,
    }
)


def test_speech_says_what_the_server_has(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    speaking(monkeypatch, SPEECH_READY)

    html = _get(signed_in, SPEECH)
    assert stat(html, "Voices") == "2"
    assert speech_server.NAME in text(one(html, "#card-server"))

    html = _get(signed_in, SPEECH, "voices")
    groups = select(html, "#card-voices [data-voice-group]")
    assert [text(one(g, "dt")) for g in groups] == [
        "General American, female",
        "British, male",
    ]
    heart = one(html, "#card-voices [data-voice=af_heart]")
    assert heart.get("data-say") == f"{speech_page.SAY}?voice=af_heart"


def test_speech_shows_what_the_server_reports_of_itself(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    speaking(monkeypatch, SPEECH_REPORTING)

    html = _get(signed_in, SPEECH)

    assert (stat(html, "Version"), stat(html, "Model")) == ("0.10.1", "Loaded")
    assert (stat(html, "Device"), stat(html, "Memory")) == ("mps", "812.0 MB")
    unload = one(html, "#card-server [data-speech-action=unload]")
    assert unload.get("hx-post") == speech_page.MOVE.format(action="unload")
    assert not select(html, "[data-speech-closed]")


def test_a_flag_left_off_says_what_to_turn_on(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plain OpenAI-compatible server reports nothing past its listings
    and has no flags to name; Kokoro-FastAPI names those it was started
    without."""
    closed = ["ALLOW_DEV_UNLOAD", "ENABLE_DEBUG_ENDPOINTS"]
    speaking(monkeypatch, SPEECH_READY.model_copy(update={"closed": closed}))

    html = _get(signed_in, SPEECH)

    said = text(one(html, "[data-speech-closed]"))
    assert "ALLOW_DEV_UNLOAD=true" in said and "ENABLE_DEBUG_ENDPOINTS=true" in said
    assert not select(html, "[data-speech-action]")


def test_speech_charts_the_server_and_the_apps_calls(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core import series

    speaking(monkeypatch, SPEECH_REPORTING)
    asyncio.run(series.sample(sampler.SPEECH))
    asyncio.run(series.record({speech_server.LATENCY["file"]: 0.4}))

    html = _get(signed_in, SPEECH)

    memory = chart_json(html, "chart-speech-memory-data")
    assert memory["series"][0]["values"] == [812.0 * 2**20]
    latency = chart_json(html, "chart-speech-latency-data")
    assert latency["series"] == [{"label": "file", "values": [0.4]}]
    live = one(html, "#speech")
    assert live.get("sse-connect", "").startswith(speech_page.SPEECH_EVENTS)


@pytest.mark.asyncio
async def test_the_speech_stream_sends_the_server_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    speaking(monkeypatch, SPEECH_REPORTING)

    events = await sent_events(speech_page.speech_events(max_frames=1))

    sent = [e.split("\n", 1)[0] for e in events]
    assert f"event: {speech_page.SPEECH_EVENT}" in sent


def test_a_speech_server_that_does_not_answer_says_where_it_looked(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    speaking(monkeypatch, SPEECH_DOWN)

    assert SPEECH_URL in text(one(_get(signed_in, SPEECH), "[role=alert]"))


def test_without_a_speech_server_it_says_how_to_add_one(
    signed_in: TestClient,
) -> None:
    assert "SPEECH_BASE_URL" in text(one(_get(signed_in, SPEECH), "[data-empty]"))


def test_the_engines_overview_says_what_it_holds_and_the_memory(
    signed_in: TestClient,
) -> None:
    """What is loaded and the memory it takes, not a count of loaded to
    installed."""
    html = _get(signed_in, TEXT)
    figures = _figures(html)
    assert figures["Memory"] == "4.2 GB"
    assert figures["Version"] == "0.12.3"
    assert "Loaded" not in figures
    assert "qwen2.5:7b (4.2 GB)" in text(one(html, "#card-in-memory"))


def test_the_engines_overview_names_the_server(signed_in: TestClient) -> None:
    assert "host.docker.internal:11434" in text(
        one(_get(signed_in, TEXT), "#card-server")
    )


def test_an_unreachable_server_says_where_it_looked(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(FakeClient, "status", InferenceServerStatus(available=False))
    alert = text(one(_get(signed_in, TEXT), "[role=alert]"))
    assert "host.docker.internal:11434" in alert


def test_an_engine_that_reports_no_memory_says_so(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(FakeClient, "REPORTS_MEMORY", LlamaCppEngine.REPORTS_MEMORY)
    figures = _figures(_get(signed_in, TEXT))
    assert figures["Memory"] == overview.UNREPORTED


def _rows(html: str) -> dict[str, str]:
    return {
        text(select(row, "td")[0]): text(row)
        for row in select(html, "#inference-models tbody tr")
    }


def test_models_lists_every_installed_model(signed_in: TestClient) -> None:
    rows = _rows(_get(signed_in, TEXT, "models"))
    assert set(rows) == {"qwen2.5:7b", "llama3.1:8b"}
    assert "4-bit" in rows["llama3.1:8b"] and "32k" in rows["llama3.1:8b"]


def test_a_loaded_model_offers_unload_and_an_idle_one_load(
    signed_in: TestClient,
) -> None:
    rows = _rows(_get(signed_in, TEXT, "models"))
    assert "Unload" in rows["qwen2.5:7b"]
    assert "Load" in rows["llama3.1:8b"] and "Unload" not in rows["llama3.1:8b"]


def test_the_row_buttons_post_to_the_actions(signed_in: TestClient) -> None:
    """A mangled attribute leaves htmx posting to the page itself (a 404)."""
    buttons = select(
        _get(signed_in, TEXT, "models"), "#inference-models button[hx-post]"
    )
    assert {b.get("hx-post") for b in buttons} == {
        f"{text_page.PARTIALS}/load",
        f"{text_page.PARTIALS}/unload",
    }


def test_an_engine_that_cannot_move_its_model_offers_no_buttons(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A single-model llama-server serves what it was started with; its
    reading says so (a router of the same engine moves its models)."""
    fixed = SERVING.model_copy(update={"can_load_unload": False})
    monkeypatch.setattr(FakeClient, "status", fixed)
    page = _get(signed_in, TEXT, "models")
    assert select(page, "#inference-models button[hx-post]") == []
    assert "Loaded" in _rows(page)["qwen2.5:7b"]


def test_an_empty_table_says_how_the_engine_takes_a_model(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each engine adds a model its own way (``engine.ADD_MODEL``)."""
    monkeypatch.setattr(FakeClient, "status", InferenceServerStatus(available=True))
    empty = text(one(_get(signed_in, TEXT, "models"), "#inference-models [data-empty]"))
    assert FakeClient.ADD_MODEL in empty


def test_the_table_fits_without_the_digest(signed_in: TestClient) -> None:
    rows = _rows(_get(signed_in, TEXT, "models"))
    assert "7.6B, 4-bit" in rows["llama3.1:8b"]
    assert "0123456789ab" not in rows["llama3.1:8b"]


def test_a_model_without_a_build_shows_its_format(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An MLX model reports no parameter size or quantization; its format
    says what it is where the build would read "-"."""
    mlx = InferenceModel(
        name="qwen3:mlx", model="qwen3:mlx", size=1, details=ModelDetails(format="mlx")
    )
    held = SERVING.model_copy(
        update={"installed_models": [*SERVING.installed_models, mlx]}
    )
    monkeypatch.setattr(FakeClient, "status", held)
    assert "mlx" in _rows(_get(signed_in, TEXT, "models"))["qwen3:mlx"]


def test_load_answers_at_once(signed_in: TestClient) -> None:
    """A 27B model takes a while to load; the click returns straight away and
    the table's stream shows it arriving."""
    response = signed_in.post(
        f"{text_page.PARTIALS}/load", data={"model": "llama3.1:8b"}
    )
    assert response.status_code == 200


def test_a_model_already_moving_is_not_asked_twice(signed_in: TestClient) -> None:
    text_page._moving["llama3.1:8b"] = "load"
    response = signed_in.post(
        f"{text_page.PARTIALS}/load", data={"model": "llama3.1:8b"}
    )
    assert response.status_code == 409
    assert FakeClient.calls == []


@pytest.mark.asyncio
async def test_a_row_shows_the_load_in_flight_then_its_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(FakeClient, "calls", [])
    serve(monkeypatch)
    monkeypatch.setattr(text_page, "_moving", {})
    monkeypatch.setattr(text_page, "_failed", {})

    task = text_page.start("load", "llama3.1:8b")
    during = {r["model"]: r for r in text_page.model_rows(SERVING)}
    assert during["llama3.1:8b"]["state"]["label"] == "Loading..."
    assert during["llama3.1:8b"]["moving"]

    await task
    assert FakeClient.calls == [("load", "llama3.1:8b")]
    after = {r["model"]: r for r in text_page.model_rows(SERVING)}
    assert not after["llama3.1:8b"]["moving"]


@pytest.mark.asyncio
async def test_a_refused_load_stays_on_the_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    serve(monkeypatch)
    monkeypatch.setattr(text_page, "_moving", {})
    monkeypatch.setattr(text_page, "_failed", {})
    monkeypatch.setattr(FakeClient, "loaded", False)

    await text_page.start("load", "llama3.1:8b")
    rows = {r["model"]: r for r in text_page.model_rows(SERVING)}
    assert rows["llama3.1:8b"]["state"] == {"label": "Load failed", "tone": "error"}


def test_a_failure_the_server_contradicts_gives_way(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A timed-out load that finished anyway shows Loaded, not Load failed."""
    monkeypatch.setattr(text_page, "_moving", {})
    monkeypatch.setattr(
        text_page, "_failed", {"qwen2.5:7b": "load", "llama3.1:8b": "unload"}
    )
    rows = {r["model"]: r for r in text_page.model_rows(SERVING)}
    assert rows["qwen2.5:7b"]["state"]["label"].startswith("Loaded")
    assert rows["llama3.1:8b"]["state"]["label"] == "Idle"
    assert text_page._failed == {}


def test_the_table_streams_while_the_page_is_open(signed_in: TestClient) -> None:
    card = one(_get(signed_in, TEXT, "models"), "#inference-models-live")
    assert card.get("sse-connect") == text_page.MODELS_EVENTS


@pytest.mark.asyncio
async def test_the_stream_sends_the_table_only_when_it_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    serve(monkeypatch)
    monkeypatch.setattr(text_page, "MODELS_INTERVAL_SECONDS", 0)
    events = await sent_events(text_page.models_events(max_frames=3))
    assert len(events) == 1
    assert events[0].startswith(f"event: {text_page.MODELS_EVENT}\n")


def test_only_load_and_unload_are_actions(signed_in: TestClient) -> None:
    response = signed_in.post(
        f"{text_page.PARTIALS}/delete", data={"model": "llama3.1:8b"}
    )
    assert response.status_code == 404
    assert FakeClient.calls == []


def test_activity_starts_empty(signed_in: TestClient) -> None:
    assert select(_get(signed_in, TEXT, "activity"), "[data-empty]")


def test_activity_lists_what_moved(signed_in: TestClient) -> None:
    activity.get_inference_activity().record_loaded("llama3.1:8b")
    rows = select(_get(signed_in, TEXT, "activity"), "#inference-activity tbody tr")
    assert "llama3.1:8b" in text(rows[0])


def test_models_are_served_from_the_one_shared_reading(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sampler reads Ollama once a tick for every viewer; a page reads
    that, not the server."""
    from app.core import series

    asyncio.run(series.sample(sampler.SAMPLER))
    # A live read would find it down.
    monkeypatch.setattr(FakeClient, "status", InferenceServerStatus(available=False))
    html = _get(signed_in, TEXT, "models")
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
    html = _get(signed_in, f"{PAGE}/container")
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
    _get(signed_in, f"{PAGE}/container")
    assert asyncio.run(series.watched(series.INFERENCE))
    assert not asyncio.run(series.watched(ui_runtime.SAMPLER))
