"""Fragments for the Overseer's chat surface: the surface for the drawer,
conversation history and loading one, a turn's bubbles, a settled message,
what one tool run did, a stored image, the model chip and its picker, and
the two ends of a spoken turn (the microphone's recording transcribed, a
sentence or a stored answer said aloud). Mounted under the AI page's
partials by ``routes/partials/overseer_ai.py``.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response

from app.components.web_frontend import overseer_ai_chat as chat
from app.components.web_frontend.rendering import (
    close_dialog,
    dialog,
    templates,
    with_toast,
)
from app.models.user import User
from app.services.auth.deps import get_optional_user

from .overseer_auth import signed_in

router = APIRouter(prefix="/chat")

NOTHING_HEARD = "Didn't catch anything. Try again, a little closer."
MODELS_TEMPLATE = "partials/chat/models.html"


def _fragment(request: Request, name: str, **context: Any) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name=name, context=context)


async def _owned(conversation_id: str) -> Any:
    found = await chat.find_conversation(conversation_id)
    if found is None:
        raise HTTPException(status_code=404)
    return found


async def _message(conversation_id: str, message_id: str) -> Any:
    found = chat.find_message(await _owned(conversation_id), message_id)
    if found is None:
        raise HTTPException(status_code=404)
    return found


@router.get("/drawer", response_class=HTMLResponse)
async def drawer(
    request: Request, user: User | None = Depends(get_optional_user)
) -> Response:
    """The surface for the drawer: the partial the Chat section includes."""
    signed_in(user)
    context = await chat.surface_context()
    return _fragment(request, "partials/chat/surface.html", **context)


@router.get("/conversations", response_class=HTMLResponse)
async def history(
    request: Request, user: User | None = Depends(get_optional_user)
) -> Response:
    signed_in(user)
    conversations = (await chat.conversations())[: chat.HISTORY_LIMIT]
    return dialog(
        request,
        "partials/chat/history.html",
        conversations=conversations,
        chat_path=chat.PATH,
    )


@router.get("/conversations/new", response_class=HTMLResponse)
async def new_conversation(
    request: Request, user: User | None = Depends(get_optional_user)
) -> Response:
    """An empty thread; the id arrives on the first turn's first frame."""
    signed_in(user)
    context = await chat.transcript(None)
    return _fragment(request, "partials/chat/transcript.html", oob=True, **context)


@router.get("/conversations/{conversation_id}", response_class=HTMLResponse)
async def load_conversation(
    request: Request,
    conversation_id: str,
    user: User | None = Depends(get_optional_user),
) -> Response:
    """A conversation picked from history, replacing the thread in place;
    the dialog closes on the way."""
    signed_in(user)
    context = await chat.transcript(await _owned(conversation_id))
    response = _fragment(request, "partials/chat/transcript.html", oob=True, **context)
    return close_dialog(response)


@router.get("/conversations/{conversation_id}/earlier", response_class=HTMLResponse)
async def earlier(
    request: Request,
    conversation_id: str,
    before: str,
    user: User | None = Depends(get_optional_user),
) -> Response:
    """The page before ``before``, in place of the row that asked for it."""
    signed_in(user)
    context = await chat.transcript(await _owned(conversation_id), before)
    return _fragment(request, "partials/chat/transcript.html", page=True, **context)


@router.post("/turns", response_class=HTMLResponse)
async def start_turn(
    request: Request,
    message: Annotated[str, Form()] = "",
    conversation_id: Annotated[str, Form()] = "",
    attachment_names: Annotated[list[str] | None, Form()] = None,
    user: User | None = Depends(get_optional_user),
) -> Response:
    """The question and the bubble its answer streams into; nothing reaches
    the model until the script posts the bubble's text to the stream."""
    signed_in(user)
    context = await chat.turn_context(message, conversation_id, attachment_names or [])
    if context is None:
        return Response(status_code=422)
    return _fragment(request, "partials/chat/turn.html", **context)


@router.get("/messages/{conversation_id}/{message_id}", response_class=HTMLResponse)
async def message(
    request: Request,
    conversation_id: str,
    message_id: str,
    user: User | None = Depends(get_optional_user),
) -> Response:
    """The settled bubble, swapped over the streaming one when the turn
    completes (the message is stored before the stream's final frame)."""
    signed_in(user)
    found = await _message(conversation_id, message_id)
    context = await chat.message_context(conversation_id, found)
    return _fragment(request, "partials/chat/message.html", **context)


@router.get(
    "/messages/{conversation_id}/{message_id}/runs/{index}",
    response_class=HTMLResponse,
)
async def run_detail(
    request: Request,
    conversation_id: str,
    message_id: str,
    index: int,
    user: User | None = Depends(get_optional_user),
) -> Response:
    signed_in(user)
    found = await _message(conversation_id, message_id)
    entries = (found.metadata or {}).get("tool_trace") or []
    if not 0 <= index < len(entries):
        raise HTTPException(status_code=404)
    return dialog(request, "partials/chat/run.html", run=chat.run(entries[index]))


@router.get("/attachments/{key:path}")
async def attachment(
    key: str,
    type: str = "image/png",
    user: User | None = Depends(get_optional_user),
) -> Response:
    """A stored image by its content key. Content-addressed, so the browser
    may cache it for good."""
    signed_in(user)
    data = await chat.read_attachment(key) if type.startswith("image/") else None
    if data is None:
        raise HTTPException(status_code=404)
    return Response(
        content=data,
        media_type=type,
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


# --- The model chip and its picker --------------------------------------------


@router.get("/models/chip", response_class=HTMLResponse)
async def model_chip(
    request: Request, user: User | None = Depends(get_optional_user)
) -> Response:
    """The composer's chip; it loads itself, and a pick sends it back out of
    band."""
    signed_in(user)
    from app.components.web_frontend import overseer_ai_chat_models as models

    chip = models.chip(await models.running_model())
    return _fragment(
        request, MODELS_TEMPLATE, chip=chip, chip_only=True, path=models.MODELS
    )


@router.get("/models", response_class=HTMLResponse)
async def models_dialog(
    request: Request,
    q: str = "",
    user: User | None = Depends(get_optional_user),
) -> Response:
    """The picker, in the modal; the same route re-renders its list as the
    search changes."""
    signed_in(user)
    from app.components.web_frontend import overseer_ai_chat_models as models

    picker = await models.picker(q, await models.running_model())
    return dialog(request, MODELS_TEMPLATE, picker=picker)


@router.post("/models", response_class=HTMLResponse)
async def pick_model(
    request: Request,
    model_id: Annotated[str, Form()],
    q: Annotated[str, Form()] = "",
    user: User | None = Depends(get_optional_user),
) -> Response:
    """A pick switches the model and updates the dialog in place (compare
    and switch twice without reopening) and the chip out of band; a refused
    pick says why and changes nothing."""
    signed_in(user)
    from app.components.web_frontend import overseer_ai_chat_models as models

    refused = await models.switch(model_id)
    current = await models.running_model()
    picker = await models.picker(q, current)
    if refused:
        return with_toast(
            dialog(request, MODELS_TEMPLATE, picker=picker), refused, tone="error"
        )
    return _fragment(
        request,
        MODELS_TEMPLATE,
        picker=picker,
        chip=models.chip(current),
        chip_oob=True,
    )


# --- Speech -------------------------------------------------------------------


@router.post("/speech/transcripts")
async def transcribe(
    audio: UploadFile, user: User | None = Depends(get_optional_user)
) -> Response:
    """The microphone's recording as text, through the same transcription
    the Voice section uses. Audio is never kept."""
    signed_in(user)
    from app.components.web_frontend import overseer_ai_voice

    try:
        result = await overseer_ai_voice.transcribe(audio)
    except HTTPException as exc:
        return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)
    text = (result.text or "").strip()
    if not text:
        return JSONResponse({"error": NOTHING_HEARD}, status_code=422)
    return JSONResponse({"text": text})


def _audio(data: bytes) -> Response:
    return Response(content=data, media_type="audio/mpeg")


@router.get("/speech/say")
async def say(
    text: str = "", user: User | None = Depends(get_optional_user)
) -> Response:
    """One sentence said aloud, as a reply streams in."""
    signed_in(user)
    words = chat.spoken(text)
    if not words:
        raise HTTPException(status_code=422)
    return _audio(await chat.synthesize(words))


@router.get("/messages/{conversation_id}/{message_id}/speech")
async def speak(
    conversation_id: str,
    message_id: str,
    user: User | None = Depends(get_optional_user),
) -> Response:
    """A stored answer said aloud."""
    signed_in(user)
    found = await _message(conversation_id, message_id)
    return _audio(await chat.synthesize(chat.spoken(found.content)))
