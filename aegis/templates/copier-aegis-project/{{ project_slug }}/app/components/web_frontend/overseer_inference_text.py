"""The app's text engine's page under Overseer > Inference (Ollama, or
llama.cpp): its Overview (what it holds in memory and how much, where the
app reaches it), Models (every model it has, with load and unload) and
Activity (models moving in and out of memory). Each render reads the
inference sampler's last reading (``app.core.series``), taken once a second
for every viewer while one looks, rather than the last health poll.

A load or unload runs in the background (a large model takes a while to
load) and the Models table streams over SSE while the page is open, so a
row goes Idle, Loading..., Loaded, or says the load failed.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from app.components.inference import (
    get_inference_engine,
    inference_engine_class,
    sampler,
)
from app.components.inference import overview as engines
from app.components.inference.activity import get_inference_activity
from app.components.inference.engine import InferenceServerStatus
from app.components.inference.formatting import format_quantization
from app.core import series
from app.core.concurrency import background
from app.core.formatting import format_relative_time
from app.core.log import logger
from app.core.model_picker import format_context_window

from .overseer_live import fragment_events
from .overseer_nav import SectionRequest
from .rendering import fragment, status_cell

TABS = {"overview": "Overview", "models": "Models", "activity": "Activity"}
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


def where(url: str, available: bool) -> list[tuple[str, str]]:
    """A server's address and whether it answered, as facts."""
    return [("URL", url), ("Status", engines.STATES[available])]


def _overview(server: InferenceServerStatus, base_url: str) -> dict[str, Any]:
    """What it holds and the memory it takes (``inference.overview``'s row,
    as the engines overview shows it), and where the app reaches it."""
    row = engines.text_row(server, base_url)
    return {
        "figures": [
            {"label": "Memory", "value": engines.memory_said(row)},
            {"label": "Version", "value": server.version or "-"},
        ],
        "loaded": [engines.loaded_said(m) for m in row.loaded],
        "server": where(base_url, server.available),
    }


def _state(name: str, warm: dict[str, float]) -> dict[str, str]:
    if name in _moving:
        return status_cell(IN_FLIGHT[_moving[name]], "accent")
    if name in _failed:
        return status_cell(FAILED[_failed[name]], "error")
    if name in warm:
        gb = warm[name]  # 0 where the engine does not report its VRAM
        return status_cell(f"Loaded, {gb:.1f} GB" if gb else "Loaded", "ok")
    return status_cell("Idle", "muted")


def _settle_failures(warm: dict[str, float]) -> None:
    """Drop a failure the server now contradicts: a timed-out load that
    finished anyway, or an unload another process completed."""
    for name, action in list(_failed.items()):
        if (action == "load") == (name in warm):
            del _failed[name]


def _build(details: Any) -> str:
    """What a model is: its size and quantization, else its format (an MLX
    model reports neither)."""
    parts = (details.parameter_size, format_quantization(details.quantization_level))
    return ", ".join(p for p in parts if p and p != "—") or details.format or "-"


def model_rows(server: InferenceServerStatus) -> list[dict[str, Any]]:
    warm = {m.name: m.size_vram_gb for m in server.running_models}
    _settle_failures(warm)
    return [
        {
            "model": m.name,
            "build": _build(m.details),
            "context": format_context_window(m.details.context_length) or "-",
            "can": ", ".join(c for c in CAPABILITIES if c in (m.capabilities or ())) or "-",
            "size": f"{m.size_gb:.1f} GB" if m.size else "-",
            "modified": format_relative_time(m.modified_at),
            "state": _state(m.name, warm),
            "loaded": m.name in warm,
            "moving": m.name in _moving,
        }
        for m in server.installed_models
    ]


def _reach(server: InferenceServerStatus, base_url: str) -> dict[str, Any]:
    """Where nothing answered, and which engine, for ``_unreachable.html``."""
    return {
        "unreachable": None if server.available else base_url,
        "engine": inference_engine_class(),
    }


async def models_view() -> dict[str, Any]:
    """The Models table's context: the server as it is now, plus what this
    process has in flight."""
    server, base_url = await series.reading(sampler.SAMPLER)
    return _reach(server, base_url) | {
        "partials": PARTIALS,
        "models": model_rows(server),
        "can_move": server.can_load_unload,
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


async def context(tab: str, req: SectionRequest) -> dict[str, Any]:
    """What the named tab's template needs."""
    if tab == "activity":
        return {"events": _activity_rows()}
    if tab == "models":
        return await models_view()
    server, base_url = await series.reading(sampler.SAMPLER)
    return _reach(server, base_url) | _overview(server, base_url)
