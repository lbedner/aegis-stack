"""The chat surface's routes, for any mount (``ChatSurface``): the surface
itself, conversation history and loading one, a turn's bubbles, a settled
message, what one tool run did, a stored image, the model chip and its
picker, and the two ends of a spoken turn (the microphone's recording
transcribed, a sentence or a stored answer said aloud).

``chat_router(mount, guard)`` builds them under the mount's path; ``guard``
is the dependency every route runs first (who may use this mount). The live
call's socket is its own router (``chat_live.live_router``): a socket has no
HTTP request for a page guard to read. The Overseer mounts both once
(``overseer_ai_chat``, which adds the reply's agent drawer); an app's own
chat page mounts them again with its own agent and user.
"""

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response

from app.components.web_frontend import chat_surface as chat
from app.components.web_frontend.chat_surface import ChatSurface
from app.components.web_frontend.rendering import (
    close_dialog,
    dialog,
    templates,
    with_toast,
)

NOTHING_HEARD = "Didn't catch anything. Try again, a little closer."
MODELS_TEMPLATE = "partials/chat/models.html"


def _fragment(request: Request, name: str, **context: Any) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name=name, context=context)


def _audio(data: bytes) -> Response:
    return Response(content=data, media_type="audio/mpeg")


def chat_router(mount: ChatSurface, guard: Callable[..., Any]) -> APIRouter:
    """Every page route of the surface, under ``mount.path``, behind
    ``guard``."""
    router = APIRouter(prefix=mount.path, dependencies=[Depends(guard)])
    models_path = f"{mount.path}/models"
    # Live calls are picked with the models where calls are on offer.
    calls = chat.HAS_VOICE and chat.PERSISTED

    async def owned(conversation_id: str) -> Any:
        found = await chat.find_conversation(mount, conversation_id)
        if found is None:
            raise HTTPException(status_code=404)
        return found

    async def stored(conversation_id: str, message_id: str) -> Any:
        found = chat.find_message(await owned(conversation_id), message_id)
        if found is None:
            raise HTTPException(status_code=404)
        return found

    @router.get("/drawer", response_class=HTMLResponse)
    async def drawer(request: Request) -> Response:
        """The surface for a drawer: the partial a page includes."""
        context = await chat.surface_context(mount)
        return _fragment(request, "partials/chat/surface.html", **context)

    @router.get("/conversations", response_class=HTMLResponse)
    async def history(request: Request) -> Response:
        conversations = (await chat.conversations(mount))[: chat.HISTORY_LIMIT]
        return dialog(
            request,
            "partials/chat/history.html",
            conversations=conversations,
            chat_path=mount.path,
        )

    @router.get("/conversations/new", response_class=HTMLResponse)
    async def new_conversation(request: Request) -> Response:
        """An empty thread; the id arrives on the first turn's first frame."""
        context = await chat.transcript(mount, None)
        return _fragment(request, "partials/chat/transcript.html", oob=True, **context)

    @router.get("/conversations/{conversation_id}", response_class=HTMLResponse)
    async def load_conversation(request: Request, conversation_id: str) -> Response:
        """A conversation picked from history, replacing the thread in place;
        the dialog closes on the way."""
        context = await chat.transcript(mount, await owned(conversation_id))
        response = _fragment(
            request, "partials/chat/transcript.html", oob=True, **context
        )
        return close_dialog(response)

    @router.get("/conversations/{conversation_id}/earlier", response_class=HTMLResponse)
    async def earlier(request: Request, conversation_id: str, before: str) -> Response:
        """The page before ``before``, in place of the row that asked for it."""
        context = await chat.transcript(mount, await owned(conversation_id), before)
        return _fragment(request, "partials/chat/transcript.html", page=True, **context)

    @router.post("/turns", response_class=HTMLResponse)
    async def start_turn(
        request: Request,
        message: Annotated[str, Form()] = "",
        conversation_id: Annotated[str, Form()] = "",
        attachment_names: Annotated[list[str] | None, Form()] = None,
    ) -> Response:
        """The question and the bubble its answer streams into; nothing
        reaches the model until the script posts the bubble's text to the
        stream."""
        context = await chat.turn_context(
            mount, message, conversation_id, attachment_names or []
        )
        if context is None:
            return Response(status_code=422)
        return _fragment(request, "partials/chat/turn.html", **context)

    @router.get("/messages/{conversation_id}/{message_id}", response_class=HTMLResponse)
    async def message(
        request: Request, conversation_id: str, message_id: str
    ) -> Response:
        """The settled bubble, swapped over the streaming one when the turn
        completes (the message is stored before the stream's final frame)."""
        found = await stored(conversation_id, message_id)
        context = await chat.message_context(mount, conversation_id, found)
        return _fragment(request, "partials/chat/message.html", **context)

    @router.get(
        "/messages/{conversation_id}/{message_id}/runs/{index}",
        response_class=HTMLResponse,
    )
    async def run_detail(
        request: Request, conversation_id: str, message_id: str, index: int
    ) -> Response:
        found = await stored(conversation_id, message_id)
        entries = (found.metadata or {}).get("tool_trace") or []
        if not 0 <= index < len(entries):
            raise HTTPException(status_code=404)
        return dialog(request, "partials/chat/run.html", run=chat.run(entries[index]))

    @router.get("/attachments/{key:path}")
    async def attachment(key: str, type: str = "image/png") -> Response:
        """A stored image by its content key. Content-addressed, so the
        browser may cache it for good."""
        data = await chat.read_attachment(key) if type.startswith("image/") else None
        if data is None:
            raise HTTPException(status_code=404)
        return Response(
            content=data,
            media_type=type,
            headers={"Cache-Control": "private, max-age=31536000, immutable"},
        )

    # --- The model chip and its picker ----------------------------------------

    @router.get("/models/chip", response_class=HTMLResponse)
    async def model_chip(request: Request) -> Response:
        """The composer's chip; it loads itself, and a pick sends it back out
        of band."""
        from app.components.web_frontend import chat_models as models

        chip = models.chip(await models.running_model())
        return _fragment(
            request, MODELS_TEMPLATE, chip=chip, chip_only=True, path=models_path
        )

    @router.get("/models", response_class=HTMLResponse)
    async def models_dialog(request: Request, q: str = "") -> Response:
        """The picker, in the modal; the same route re-renders its list as
        the search changes."""
        from app.components.web_frontend import chat_models as models

        current = await models.running_model()
        picker = await models.picker(q, current, models_path, calls)
        return dialog(request, MODELS_TEMPLATE, picker=picker)

    @router.post("/models", response_class=HTMLResponse)
    async def pick_model(
        request: Request,
        model_id: Annotated[str, Form()],
        q: Annotated[str, Form()] = "",
        kind: Annotated[str, Form()] = "chat",
    ) -> Response:
        """A pick sets its role - the chat model, or what a live call runs
        on - and updates the dialog in place (compare and switch twice
        without reopening) and the chip out of band; a refused pick says
        why and changes nothing."""
        from app.components.web_frontend import chat_models as models

        if calls and kind == "realtime":
            refused = await models.use_for_calls(model_id)
        else:
            refused = await models.switch(model_id)
        current = await models.running_model()
        picker = await models.picker(q, current, models_path, calls)
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

    # --- Speech ---------------------------------------------------------------

    @router.post("/speech/transcripts")
    async def transcribe(audio: UploadFile) -> Response:
        """The microphone's recording as text, through the same transcription
        the Voice section uses. Audio is never kept."""
        from app.components.backend.api.ai.speech import transcribe_audio

        try:
            result = await transcribe_audio(audio=audio, language=None)
        except HTTPException as exc:
            return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)
        text = (result.text or "").strip()
        if not text:
            return JSONResponse({"error": NOTHING_HEARD}, status_code=422)
        return JSONResponse({"text": text})

    @router.get("/speech/say")
    async def say(text: str = "") -> Response:
        """One sentence said aloud, as a reply streams in."""
        words = chat.spoken(text)
        if not words:
            raise HTTPException(status_code=422)
        return _audio(await chat.synthesize(words))

    @router.get("/messages/{conversation_id}/{message_id}/speech")
    async def speak(conversation_id: str, message_id: str) -> Response:
        """A stored answer said aloud."""
        found = await stored(conversation_id, message_id)
        return _audio(await chat.synthesize(chat.spoken(found.content)))

    # A drawn card is a row: no card route without a database.
    if chat.PERSISTED:
        from .chat_cards import add_card_routes

        add_card_routes(router, mount)
    # Voice profiles are rows: the chip and its dialog need a database too.
    if chat.HAS_VOICE and chat.PERSISTED:
        from .chat_voices import add_voice_routes

        add_voice_routes(router, mount)
    return router
