"""The hearing server's page under Overseer > Inference (speaches, or any
at HEARING_BASE_URL, ``app.core.hearing_server``), read by its own sampler
once a tick while one looks: what it holds and has in memory, where the
app reaches it, each model loaded or unloaded through the inference API,
and what is in memory and the app's transcriptions charted.
"""

from typing import Any

from app.components.inference import sampler
from app.core import hearing_server, series
from app.core.hearing_server import HearingServerReading

from .overseer_inference_text import PARTIALS, where
from .overseer_live import ServerPage
from .overseer_nav import SectionRequest
from .rendering import status_cell

TABS = {"overview": "Overview"}
# Its live part and charts over SSE, and a model moved by the inference API
# (``api/inference.py``).
HEARING_EVENTS = f"{PARTIALS}/hearing/events"
HEARING_EVENT = "hearing"
HEARING_BODY = "pages/overseer/inference/_hearing_body.html"
HEARING_WINDOWS = series.windows(hearing_server.SAMPLER, hearing_server.CALLS)
HEARING_API = "/api/v1/inference/hearing"
MOVE = HEARING_API + "/{action}/{model}"
# A model's state (in memory, or not: None where the server does not say),
# and the action that moves it with its button's tone.
STATES = {
    True: ("In memory", "ok", "unload", "warn"),
    False: ("On disk", "muted", "load", "primary"),
    None: ("Held", "muted", None, None),
}


def _models(reading: HearingServerReading) -> list[dict[str, Any]]:
    """Each model it holds, its state and the action that moves it."""
    rows = []
    for model in reading.models:
        label, tone, action, button = STATES[reading.in_memory(model)]
        rows.append(
            {
                "model": model,
                "state": status_cell(label, tone),
                "action": action,
                "tone": button,
                "url": action and MOVE.format(action=action, model=model),
            }
        )
    return rows


def hearing_view(reading: HearingServerReading) -> dict[str, Any]:
    """The Overview's live part (``HEARING_BODY``)."""
    return {
        "figures": [
            {"label": label, "value": value}
            for label, value in hearing_server.figures(reading)
        ],
        "server": [
            ("Server", hearing_server.NAME),
            *where(reading.base_url, reading.available),
        ],
        "models": _models(reading),
        "errors": []
        if reading.available
        else [hearing_server.unanswered(reading.base_url)],
    }


HEARING_OVERVIEW = ServerPage(
    sampler.HEARING,
    sampler.HEARING_CHARTS,
    HEARING_EVENT,
    HEARING_BODY,
    HEARING_EVENTS,
    HEARING_WINDOWS,
    hearing_view,
)
hearing_events = HEARING_OVERVIEW.stream


async def context(tab: str, req: SectionRequest) -> dict[str, Any]:
    """The hearing server as its sampler last read it, with its charts;
    nothing where none is set, and the page says how to add one."""
    reading = await series.reading(sampler.HEARING)
    if reading is None:
        return {"hearing": None, "unset": hearing_server.UNSET}
    overview = await HEARING_OVERVIEW.overview(reading, req.query.get("window"))
    return overview | {"hearing": reading}
