"""Actions for the Overseer Inference page: load a model into the
inference server's memory, or unload it. Mounted by ``routes/pages.py`` at
``overseer_inference.PARTIALS``. The action runs in the background and
answers at once; the Models table's stream shows it arriving. Speech's
stream too; its actions are the inference API's (``api/inference.py``).
"""

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import Response, StreamingResponse

from app.components.inference.engine import MODEL_ACTIONS
from app.components.web_frontend import overseer_inference
from app.components.web_frontend.overseer_live import event_stream
from app.core import series

router = APIRouter(prefix=overseer_inference.PARTIALS)


@router.get("/models/events", include_in_schema=False)
async def models_events() -> StreamingResponse:
    """The Models table, while the page is open."""
    return event_stream(overseer_inference.models_events())


@router.get("/speech/events", include_in_schema=False)
async def speech_events(window: str | None = None) -> StreamingResponse:
    """Speech's live part and charts over the window its range chips chose,
    while the section is open."""
    seconds = series.window_of(window, overseer_inference.SPEECH_WINDOWS)
    return event_stream(overseer_inference.speech_events(seconds))


@router.post("/{action}")
async def move_model(
    action: str,
    model: Annotated[str, Form()],
) -> Response:
    """Start loading or unloading ``model``; one action per model at a time."""
    if action not in MODEL_ACTIONS:
        raise HTTPException(status_code=404)
    if overseer_inference.moving(model):
        raise HTTPException(status_code=409, detail=f"{model} is already busy.")
    overseer_inference.start(action, model)
    return Response(status_code=200)
