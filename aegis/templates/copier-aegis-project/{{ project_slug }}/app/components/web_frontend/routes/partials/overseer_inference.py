"""Actions for the Overseer Inference page: load a model into the
inference server's memory, or unload it. Mounted by ``routes/pages.py`` at
``overseer_inference_text.PARTIALS``. The action runs in the background and
answers at once; the Models table's stream shows it arriving. The speech
server's stream too; its actions are the inference API's
(``api/inference.py``).
"""

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import Response, StreamingResponse

from app.components.inference.engine import MODEL_ACTIONS
from app.components.web_frontend import overseer_inference_speech as speech_page
from app.components.web_frontend import overseer_inference_text as text_page
from app.components.web_frontend.overseer_live import event_stream
from app.core import series

router = APIRouter(prefix=text_page.PARTIALS)


@router.get("/models/events", include_in_schema=False)
async def models_events() -> StreamingResponse:
    """The Models table, while the page is open."""
    return event_stream(text_page.models_events())


@router.get("/speech/events", include_in_schema=False)
async def speech_events(window: str | None = None) -> StreamingResponse:
    """The speech server's live part and charts over the window its range
    chips chose, while its page is open."""
    seconds = series.window_of(window, speech_page.SPEECH_WINDOWS)
    return event_stream(speech_page.speech_events(seconds))


@router.post("/{action}")
async def move_model(
    action: str,
    model: Annotated[str, Form()],
) -> Response:
    """Start loading or unloading ``model``; one action per model at a time."""
    if action not in MODEL_ACTIONS:
        raise HTTPException(status_code=404)
    if text_page.moving(model):
        raise HTTPException(status_code=409, detail=f"{model} is already busy.")
    text_page.start(action, model)
    return Response(status_code=200)
