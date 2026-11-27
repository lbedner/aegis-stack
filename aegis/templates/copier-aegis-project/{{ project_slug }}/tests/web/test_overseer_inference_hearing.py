"""The hearing server's page under Overseer > Inference (speaches, or any
at HEARING_BASE_URL): what it holds and has in memory, each model loaded
or unloaded through the inference API, and its charts, live over SSE.
It reads its sampler's last reading, as the speech server's page does."""

import asyncio
from collections.abc import Generator

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.inference import sampler
from app.components.web_frontend import overseer_inference_hearing as hearing_page
from app.core import hearing_server
from app.services.system.models import ComponentStatus, ComponentStatusType
from tests._fake_ollama import (
    HEARING_READY,
    HEARING_URL,
    PARAKEET,
    SERVING,
    FakeClient,
    hearing,
    serve,
)
from tests._speech_server import WHISPER
from tests.web.dom import chart_json, one, select, stat, table_text, text
from tests.web.overseer import sent_events, sign_in, status_with

PAGE = f"/overseer/components/inference/{hearing_server.SLUG}"
HOLDING_TWO = HEARING_READY.model_copy(update={"models": [PARAKEET, WHISPER]})


@pytest.fixture
def signed_in(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    inference = ComponentStatus(
        name="inference",
        status=ComponentStatusType.HEALTHY,
        message="warm",
        response_time_ms=None,
    )
    sign_in(app, monkeypatch, status_with(inference))
    monkeypatch.setattr(FakeClient, "status", SERVING)
    serve(monkeypatch)
    with TestClient(app) as client:
        yield client


def _get(client: TestClient) -> str:
    response = client.get(PAGE)
    assert response.status_code == 200
    return response.text


def test_the_nav_has_it_under_hearing(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    hearing(monkeypatch)

    html = _get(signed_in)

    assert "Hearing" in [text(h) for h in select(html, "#overseer-subnav h3")]
    assert hearing_server.NAME in [text(a) for a in select(html, "#overseer-subnav a")]


def test_it_says_what_it_holds_and_what_is_in_memory(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    hearing(monkeypatch, HOLDING_TWO)

    html = _get(signed_in)

    assert (stat(html, "Models"), stat(html, "In memory")) == ("2", "1")
    assert HEARING_URL in text(one(html, "#card-server"))
    rows = {r["Model"]: r["State"] for r in table_text(html, "#hearing-models table")}
    assert rows == {PARAKEET: "In memory", WHISPER: "On disk"}


def test_each_model_moves_through_the_inference_api(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In memory, it offers Unload; on disk, Load."""
    hearing(monkeypatch, HOLDING_TWO)

    html = _get(signed_in)

    unload = one(html, f"[data-hearing-action=unload][data-model='{PARAKEET}']")
    assert unload.get("hx-post") == hearing_page.MOVE.format(
        action="unload", model=PARAKEET
    )
    load = one(html, f"[data-hearing-action=load][data-model='{WHISPER}']")
    assert load.get("hx-post") == hearing_page.MOVE.format(action="load", model=WHISPER)


def test_a_server_that_does_not_say_what_is_in_memory_offers_no_buttons(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    hearing(monkeypatch, HEARING_READY.model_copy(update={"loaded": None}))

    assert not select(_get(signed_in), "[data-hearing-action]")


def test_it_charts_whats_in_memory_and_each_transcription(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core import series

    hearing(monkeypatch)
    asyncio.run(series.sample(sampler.HEARING))
    asyncio.run(series.record({hearing_server.LATENCY: 0.7}))

    html = _get(signed_in)

    loaded = chart_json(html, "chart-hearing-loaded-data")
    assert loaded["series"][0]["values"] == [1.0]
    latency = chart_json(html, "chart-hearing-latency-data")
    assert latency["series"][0]["values"] == [0.7]
    live = one(html, "#hearing")
    assert live.get("sse-connect", "").startswith(hearing_page.HEARING_EVENTS)


@pytest.mark.asyncio
async def test_the_stream_sends_the_live_part(monkeypatch: pytest.MonkeyPatch) -> None:
    hearing(monkeypatch)

    events = await sent_events(hearing_page.hearing_events(max_frames=1))

    sent = [e.split("\n", 1)[0] for e in events]
    assert f"event: {hearing_page.HEARING_EVENT}" in sent


def test_one_that_does_not_answer_says_where_it_looked(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    down = HEARING_READY.model_copy(update={"available": False, "loaded": None})
    hearing(monkeypatch, down)

    assert HEARING_URL in text(one(_get(signed_in), "[role=alert]"))


def test_without_a_hearing_server_it_says_how_to_add_one(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "HEARING_BASE_URL", None)

    said = text(one(_get(signed_in), "[data-empty]"))
    assert "HEARING_BASE_URL" in said
    assert hearing_server.ADD in said
