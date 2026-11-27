"""The speech server's page under Overseer > Inference (Kokoro-FastAPI, or
any at SPEECH_BASE_URL, ``app.core.speech_server``), read by its own
sampler once a tick while one looks: its Overview (what it reports of
itself, where the app reaches it, its model to unload or reload, and its
memory, requests and the app's calls to it charted) and its Voices, each
played by the server itself through the inference API.
"""

from typing import Any

from app.components.inference import sampler
from app.core import discovery, series, speech_server
from app.core.constants import ComponentName
from app.core.speech_server import SpeechServerReading

from .overseer_inference_text import PARTIALS, where
from .overseer_live import ServerPage
from .overseer_nav import SectionRequest, page_url

TABS = {"overview": "Overview", "voices": "Voices"}
# Its live part and charts over SSE, a voice played and its model moved by
# the inference API (``api/inference.py``), and where ai[voice] offers its
# voices (AI > Voice links back to ``SPEECH_PAGE``).
SPEECH_PAGE = page_url("components", ComponentName.INFERENCE, speech_server.SLUG)
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


def speech_view(speech: SpeechServerReading) -> dict[str, Any]:
    """The Overview's live part (``SPEECH_BODY``): what the server reports
    of itself, where the app reaches it, the flags it was started without,
    and its model's actions where it takes them."""
    loaded = speech.loaded
    server = [
        ("Server", speech_server.NAME),
        *where(speech.base_url, speech.available),
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


SPEECH_OVERVIEW = ServerPage(
    sampler.SPEECH,
    sampler.SPEECH_CHARTS,
    SPEECH_EVENT,
    SPEECH_BODY,
    SPEECH_EVENTS,
    SPEECH_WINDOWS,
    speech_view,
)


async def context(tab: str, req: SectionRequest) -> dict[str, Any]:
    """The speech server as its sampler last read it (once a tick while the
    page is open): its Overview with its charts, or its voices by accent
    and gender; nothing where none is set, and the page says how to add
    one."""
    speech = await series.reading(sampler.SPEECH)
    if speech is None:
        return {"speech": None, "unset": speech_server.UNSET}
    if tab == "voices":
        return {
            "speech": speech,
            "voices": speech_server.grouped(speech.voices),
            "say": SAY,
            "voice_page": VOICE_PAGE,
        }
    overview = await SPEECH_OVERVIEW.overview(speech, req.query.get("window"))
    return overview | {"speech": speech}


speech_events = SPEECH_OVERVIEW.stream
