"""Every engine the inference component tracks, in one read
(``inference.overview``): what each does, whether it answers, what it holds
and the memory it reports, who runs on it, and how to add one it lacks. The
Overseer page, the ``inference status`` command and its API all show it."""

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

import pytest

from app.components.inference import overview, sampler
from app.components.inference.engine import InferenceServerStatus
from app.components.inference.llamacpp import LlamaCppEngine
from app.components.inference.ollama import OllamaEngine
from app.core import speech_server
from app.core.config import settings
from tests._fake_ollama import (
    RUNNING,
    SERVING,
    SPEECH_READY,
    FakeClient,
    serve,
    speaking,
)


class Used:
    """The AI service's answer (``chat/engine_users``), as its shape."""

    def __init__(self, uses: list[tuple[str, str]], in_app: Sequence[Any] = ()) -> None:
        self.uses = [type("Use", (), {"engine": e, "by": b})() for e, b in uses]
        self.in_app = list(in_app)


def _answers(monkeypatch: pytest.MonkeyPatch, used: Used | None) -> list[Any]:
    asked: list[Any] = []

    async def engine_users(session: Any, served: Any) -> Used | None:
        asked.append(served)
        return used

    monkeypatch.setattr(overview, "_engine_users", lambda: engine_users)
    return asked


@pytest.fixture(autouse=True)
def _serving(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(FakeClient, "status", SERVING)
    serve(monkeypatch)
    monkeypatch.setattr(settings, "SPEECH_BASE_URL", None)
    _answers(monkeypatch, None)


def _row(found: overview.InferenceOverview, engine: str) -> overview.EngineRow:
    return next(r for r in found.engines if r.id == engine)


async def test_the_text_engine_says_what_it_holds_and_its_memory() -> None:
    found = await overview.read_overview(None)

    row = _row(found, OllamaEngine.NAME)
    assert (row.name, row.job, row.available) == ("Ollama", overview.TEXT, True)
    assert [(m.name, m.memory_bytes) for m in row.loaded] == [
        (RUNNING.name, RUNNING.size_vram)
    ]
    assert row.memory_bytes == RUNNING.size_vram
    assert found.reported_bytes == RUNNING.size_vram


async def test_an_engine_that_reports_no_memory_says_so_rather_than_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Quiet(FakeClient):
        NAME, LABEL = LlamaCppEngine.NAME, LlamaCppEngine.LABEL
        REPORTS_MEMORY = LlamaCppEngine.REPORTS_MEMORY

    serve(monkeypatch, Quiet)

    row = (await overview.read_overview(None)).engines[0]

    assert row.memory_bytes is None
    assert row.memory_note == overview.UNREPORTED
    assert "memory_bytes" not in row.model_dump(mode="json")

    monkeypatch.setattr(FakeClient, "status", InferenceServerStatus(available=False))
    down = (await overview.read_overview(None, serving=False)).engines[0]

    assert down.memory_note == overview.DOWN


async def test_with_nothing_reported_the_total_says_so_rather_than_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(FakeClient, "status", InferenceServerStatus(available=False))

    found = await overview.read_overview(None)

    assert overview.total_said(found) == overview.NOTHING_REPORTED


async def test_the_speech_server_is_a_row_with_the_memory_it_reports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    held = {"memory_bytes": 812 * 2**20, "loaded": True}
    speaking(monkeypatch, SPEECH_READY.model_copy(update=held))

    found = await overview.read_overview(None)

    row = _row(found, speech_server.SLUG)
    assert (row.name, row.job) == (speech_server.NAME, overview.SPEECH)
    assert row.memory_bytes == 812 * 2**20
    # ``tts-1`` is OpenAI's name for the model it holds, not a second one.
    assert [m.name for m in row.loaded] == ["kokoro"]
    assert found.reported_bytes == RUNNING.size_vram + 812 * 2**20


async def test_with_no_speech_server_set_none_is_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def read() -> None:
        raise AssertionError("read with no SPEECH_BASE_URL")

    monkeypatch.setattr(sampler, "SPEECH", replace(sampler.SPEECH, read=read))

    found = await overview.read_overview(None)

    assert speech_server.SLUG not in [r.id for r in found.engines]


async def test_a_speech_server_keeping_its_memory_shut_names_the_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    speaking(
        monkeypatch, SPEECH_READY.model_copy(update={"closed": [speech_server.DEBUG]})
    )

    row = _row(await overview.read_overview(None), speech_server.SLUG)

    assert row.memory_bytes is None
    assert f"{speech_server.DEBUG}=true" in (row.memory_note or "")


async def test_an_engine_it_lacks_says_how_to_add_it_never_a_button() -> None:
    found = await overview.read_overview(None)

    to_add = {a.name: a for a in found.to_add}
    assert to_add[speech_server.NAME].command == "aegis add inference[kokoro_fastapi]"
    assert "SPEECH_BASE_URL" in to_add[speech_server.NAME].how
    # One text engine per app: the other is a switch.
    assert to_add[LlamaCppEngine.LABEL].command == "aegis add inference[llamacpp]"
    assert "Switch" in to_add[LlamaCppEngine.LABEL].how
    assert OllamaEngine.LABEL not in to_add


async def test_each_engine_says_who_runs_on_it(monkeypatch: pytest.MonkeyPatch) -> None:
    speaking(monkeypatch)
    asked = _answers(
        monkeypatch,
        Used([("ollama", "Assistant"), (speech_server.SLUG, "Voice, speaking")]),
    )

    found = await overview.read_overview(object())

    assert _row(found, "ollama").used_by == ["Assistant"]
    assert _row(found, speech_server.SLUG).used_by == ["Voice, speaking"]
    assert asked == [{"ollama": ["qwen2.5:7b", "llama3.1:8b"]}]


async def test_without_a_database_no_one_is_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked = _answers(monkeypatch, Used([("ollama", "Assistant")]))

    found = await overview.read_overview(None)

    assert asked == [] and _row(found, "ollama").used_by == []


async def test_in_app_engines_are_one_row_with_this_process_s_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parakeet = type("InApp", (), {"name": "Parakeet", "loaded": True})()
    _answers(
        monkeypatch, Used([(speech_server.IN_APP, "Voice, listening")], [parakeet])
    )
    monkeypatch.setattr(overview, "_process_memory", lambda: 900 * 2**20)

    row = _row(await overview.read_overview(object()), speech_server.IN_APP)

    assert row.name == "In the app"
    assert [m.name for m in row.loaded] == ["Parakeet"]
    assert row.memory_bytes == 900 * 2**20
    assert row.used_by == ["Voice, listening"]


async def test_another_process_does_not_claim_the_webservers_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kokoro = type("InApp", (), {"name": "Kokoro", "loaded": False})()
    _answers(monkeypatch, Used([], [kokoro]))

    row = _row(
        await overview.read_overview(object(), serving=False), speech_server.IN_APP
    )

    assert row.memory_bytes is None and row.loaded == []
    assert row.memory_note
