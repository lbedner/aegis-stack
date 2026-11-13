"""Context for the Overseer Inference page's sections.

The Flet Ollama modal's three tabs: Overview (what is loaded, how much
VRAM it holds, where the server is), Models (every installed model, with
load and unload) and Activity (models moving in and out of memory). Each
render reads the inference sampler's last reading (``app.core.series``),
taken once a second for every viewer while one looks, rather than the last
health poll. Speech is the speech server the component tracks
(``app.core.speech_server``), read by its own sampler the same way: what it
reports of itself, its voices to play, its model to unload or reload, and
its memory, requests and the app's calls to it charted.

A load or unload runs in the background (a large model takes a while to
load) and the Models table streams over SSE while the page is open, so a
row goes Idle, Loading..., Loaded, or says the load failed.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from app.components.inference import get_inference_engine, sampler
from app.components.inference.activity import get_inference_activity
from app.components.inference.engine import InferenceServerStatus
from app.components.inference.formatting import format_quantization
from app.core import discovery, series, speech_server
from app.core.concurrency import background
from app.core.constants import ComponentName
from app.core.formatting import format_relative_time
from app.core.log import logger
from app.core.model_picker import format_context_window
from app.core.speech_server import SpeechServerReading
from app.services.system import ui_runtime
from app.services.system.models import ComponentStatus

from .overseer_live import Drawn, chart_panel, fragment_events, live_events
from .overseer_nav import SectionRequest, page_url
from .rendering import fragment, status_cell

SECTIONS = (
    (
        None,
        {
            "overview": "Overview",
            "models": "Models",
            "activity": "Activity",
            "speech": "Speech",
        },
    ),
)

PARTIALS = "/partials/overseer/inference"
# Capabilities worth a word in the Models table; ``completion`` is on every
# generative model, so it separates nothing.
CAPABILITIES = ("tools", "vision", "thinking", "embedding")
EVENT_TONES = {"loaded": "ok", "unloaded": "warn", "evicted": "muted"}
IN_FLIGHT = {"load": "Loading...", "unload": "Unloading..."}
FAILED = {"load": "Load failed", "unload": "Unload failed"}

MODELS_EVENTS = f"{PARTIALS}/models/events"
MODELS_EVENT = "inference-models"
MODELS_TEMPLATE = "pages/overseer/inference/_models_table.html"
# The inference sampler's tick: every viewer reads its one reading.
MODELS_INTERVAL_SECONDS = series.TICK_SECONDS

# Speech: its live part and charts over SSE, a voice played and its model
# moved by the inference API (``api/inference.py``), and where ai[voice]
# offers its voices (AI > Voice links back to ``SPEECH_PAGE``).
SPEECH_PAGE = page_url("components", ComponentName.OLLAMA) + "/speech"
SPEECH_EVENTS = f"{PARTIALS}/speech/events"
SPEECH_EVENT = "speech"
SPEECH_BODY = "pages/overseer/inference/_speech_body.html"
SPEECH_WINDOWS = series.windows(speech_server.SAMPLER, speech_server.CALLS)
SPEECH_API = "/api/v1/inference/speech"
SAY = f"{SPEECH_API}/say"
MOVE = SPEECH_API + "/{action}"
VOICE_PAGE = (
    discovery.optional("app.components.web_frontend.overseer_ai_common", "section_url")(
        "voice"
    )
    if discovery.present("app.services.ai.domains.voice")
    else None
)

# ponytail: process-local, so a second web worker does not see another's
# in-flight load; move to Redis if the web tier runs more than one process.
# model -> the action running on it, and the action that last failed.
_moving: dict[str, str] = {}
_failed: dict[str, str] = {}


async def _finish(action: str, model: str) -> None:
    try:
        done = await get_inference_engine().move(action, model)
    except Exception as exc:  # noqa: BLE001 - shown on the row, logged here
        logger.warning(
            "inference.action_failed", action=action, model=model, error=str(exc)
        )
        done = False
    finally:
        _moving.pop(model, None)
    if not done:
        _failed[model] = action


def moving(model: str) -> bool:
    return model in _moving


def start(action: str, model: str) -> asyncio.Task[None]:
    """Run ``action`` on ``model`` in the background; the table shows it."""
    _moving[model] = action
    _failed.pop(model, None)
    return background(_finish(action, model))


def _where(url: str, available: bool) -> list[tuple[str, str]]:
    """A server's address and whether it answered, as facts."""
    return [("URL", url), ("Status", "Reachable" if available else "Unreachable")]


def _overview(server: InferenceServerStatus, base_url: str) -> dict[str, Any]:
    loaded = [m.name for m in server.running_models]
    return {
        "figures": [
            {
                "label": "Loaded",
                "value": f"{len(loaded)} / {server.installed_models_count}",
            },
            {"label": "VRAM", "value": f"{server.total_vram_gb:.1f} GB"},
            {"label": "Version", "value": server.version or "-"},
        ],
        "loaded": loaded,
        "server": _where(base_url, server.available),
    }


def _state(name: str, warm: dict[str, float]) -> dict[str, str]:
    if name in _moving:
        return status_cell(IN_FLIGHT[_moving[name]], "accent")
    if name in _failed:
        return status_cell(FAILED[_failed[name]], "error")
    if name in warm:
        return status_cell(f"Loaded, {warm[name]:.1f} GB", "ok")
    return status_cell("Idle", "muted")


def _settle_failures(warm: dict[str, float]) -> None:
    """Drop a failure the server now contradicts: a timed-out load that
    finished anyway, or an unload another process completed."""
    for name, action in list(_failed.items()):
        if (action == "load") == (name in warm):
            del _failed[name]


def model_rows(server: InferenceServerStatus) -> list[dict[str, Any]]:
    warm = {m.name: m.size_vram_gb for m in server.running_models}
    _settle_failures(warm)
    return [
        {
            "model": m.name,
            "build": ", ".join(
                part
                for part in (
                    m.details.parameter_size,
                    format_quantization(m.details.quantization_level),
                )
                if part and part != "—"
            )
            or "-",
            "context": format_context_window(m.details.context_length) or "-",
            "can": ", ".join(c for c in CAPABILITIES if c in m.capabilities) or "-",
            "size": f"{m.size_gb:.1f} GB",
            "modified": format_relative_time(m.modified_at),
            "state": _state(m.name, warm),
            "loaded": m.name in warm,
            "moving": m.name in _moving,
        }
        for m in server.installed_models
    ]


async def _read_server() -> tuple[InferenceServerStatus, str]:
    """The server as the inference sampler last read it (once a tick for
    every viewer, kept at full pace while one looks), and where it was
    looked for; read here only before the first sample."""
    return await series.reading(sampler.SAMPLER)


def _reach(server: InferenceServerStatus, base_url: str) -> dict[str, Any]:
    """Where nothing answered, for ``_unreachable.html``."""
    return {"unreachable": None if server.available else base_url}


async def models_view() -> dict[str, Any]:
    """The Models table's context: the server as it is now, plus what this
    process has in flight."""
    server, base_url = await _read_server()
    return _reach(server, base_url) | {
        "partials": PARTIALS,
        "models": model_rows(server),
        "models_events": MODELS_EVENTS,
        "models_event": MODELS_EVENT,
    }


def models_events(max_frames: int | None = None) -> AsyncIterator[str]:
    """The Models table over SSE, sent again only when it changes."""

    async def render() -> str:
        return fragment(MODELS_TEMPLATE, **await models_view())

    return fragment_events(MODELS_EVENT, render, MODELS_INTERVAL_SECONDS, max_frames)


def _activity_rows() -> list[dict[str, Any]]:
    return [
        {
            "model": e.model,
            "event": status_cell(e.action.capitalize(), EVENT_TONES[e.action]),
            "vram": f"{e.vram_gb:.1f} GB" if e.vram_gb else "-",
            "by": "Server" if e.detected else "This app",
            "when": format_relative_time(e.timestamp),
        }
        for e in get_inference_activity().events()
    ]


def speech_view(speech: SpeechServerReading) -> dict[str, Any]:
    """The Speech section's live part (``SPEECH_BODY``): what the server
    reports of itself, where the app reaches it, the flags it was started
    without, and its model's actions where it takes them."""
    loaded = speech.loaded
    server = [
        ("Server", speech_server.NAME),
        *_where(speech.base_url, speech.available),
        *speech_server.facts(speech),
    ]
    labels = {"unload": "Unload", "reload": "Reload" if loaded else "Load"}
    return {
        "figures": [
            {"label": label, "value": value}
            for label, value in speech_server.figures(speech)
        ],
        "server": server,
        "left_off": speech_server.left_off(speech.closed),
        "actions": []
        if loaded is None
        else [
            (action, labels[action], MOVE.format(action=action))
            for action in speech_server.ACTIONS
            if loaded or action == "reload"
        ],
        "errors": []
        if speech.available
        else [speech_server.unanswered(speech.base_url)],
    }


async def _speech(req: SectionRequest) -> dict[str, Any]:
    """The speech server as its sampler last read it (once a tick while the
    section is open), its voices by accent and gender and its charts;
    nothing where none is set, and the section says how to add one."""
    speech = await series.reading(sampler.SPEECH)
    if speech is None:
        return {"speech": None, "unset": speech_server.UNSET}
    window = series.window_of(req.query.get("window"), SPEECH_WINDOWS)
    charts = await ui_runtime.draw(sampler.SPEECH_CHARTS, window)
    return speech_view(speech) | {
        "speech": speech,
        "voices": speech_server.grouped(speech.voices),
        "say": SAY,
        "voice_page": VOICE_PAGE,
        "speech_event": SPEECH_EVENT,
        "speech_charts": chart_panel(
            SPEECH_EVENT, charts, window, SPEECH_EVENTS, SPEECH_WINDOWS
        ),
    }


def speech_events(  # noqa: ANN201 - async iterator
    window: int = series.DEFAULT_WINDOW, max_frames: int | None = None
):
    """The Speech section's live part and each chart over SSE
    (``overseer_live.live_events``)."""

    async def read(draw: bool) -> tuple[dict[str, str], Drawn]:
        speech = await series.reading(sampler.SPEECH)
        sent = (
            {}
            if speech is None
            else {SPEECH_EVENT: fragment(SPEECH_BODY, **speech_view(speech))}
        )
        drawn = await ui_runtime.draw(sampler.SPEECH_CHARTS, window) if draw else None
        return sent, drawn

    return live_events(SPEECH_EVENT, read, window, max_frames)


async def section_context(
    section: str, ollama: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    """What the named section's template needs."""
    if section == "activity":
        return {"events": _activity_rows()}
    if section == "speech":
        return await _speech(req)
    if section == "models":
        return await models_view()
    server, base_url = await _read_server()
    return _reach(server, base_url) | _overview(server, base_url)
