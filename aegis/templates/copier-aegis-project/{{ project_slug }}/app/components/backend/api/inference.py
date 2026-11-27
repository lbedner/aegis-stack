"""The inference component's API: every engine it tracks (``overview``, as
Overseer > Inference and ``inference status`` show them), the speech server
(``app.core.speech_server``) as it answers, a line said in one of its
voices, and its model unloaded or loaded again; the hearing server
(``app.core.hearing_server``) as it answers, and a model of its loaded or
unloaded. Their Overseer pages play and move here; the ``inference`` CLI
calls the same clients.
"""

from types import ModuleType

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response

from app.components.inference import overview
from app.components.inference.overview import InferenceOverview
from app.core import hearing_server, speech_server
from app.core.config import settings
from app.core.hearing_server import HearingServerReading
from app.core.speech_server import SpeechServerReading
from app.services.shared.deps import get_admin_actor, get_admin_reader

router = APIRouter(prefix="/inference", tags=["inference"])


def _url(server: ModuleType = speech_server) -> str:
    """Where the speech server (or ``hearing_server``) is; 404 saying how to
    set one where none is."""
    if url := server.reach(settings):
        return url
    raise HTTPException(status.HTTP_404_NOT_FOUND, server.UNSET)


def _refused(exc: speech_server.SpeechServerError) -> HTTPException:
    """A flag left off is the caller's to turn on (409), the rest the
    server's (502)."""
    code = status.HTTP_409_CONFLICT if exc.flag else status.HTTP_502_BAD_GATEWAY
    return HTTPException(code, str(exc))


@router.get(
    "",
    response_model=InferenceOverview,
    dependencies=[Depends(get_admin_reader)],
)
async def engines() -> InferenceOverview:
    """Every engine: its job, whether it answers, what it holds, the memory
    it reports and who runs on it, and how to add one the app lacks."""
    return await overview.current_overview()


@router.get(
    "/speech",
    response_model=SpeechServerReading,
    dependencies=[Depends(get_admin_reader)],
)
async def speech() -> SpeechServerReading:
    """The speech server as it answers now: its models and voices, what it
    reports of itself and the flags it was started without."""
    return await speech_server.read(_url())


@router.get(
    "/speech/say",
    response_class=Response,
    dependencies=[Depends(get_admin_reader)],
)
async def say(voice: str, text: str = speech_server.LINE) -> Response:
    """``text`` (a sample line, left out) said in ``voice``, as an MP3."""
    return Response(await _said(text, voice), media_type="audio/mpeg")


async def _said(text: str, voice: str) -> bytes:
    try:
        return await speech_server.say(_url(), text, voice)
    except speech_server.SpeechServerError as exc:
        raise _refused(exc) from None


@router.post(
    "/speech/{action}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(get_admin_actor)],
)
async def move(action: str) -> None:
    """Unload the server's model, or load it again (``ACTIONS``)."""
    try:
        await speech_server.move(_url(), action)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except speech_server.SpeechServerError as exc:
        raise _refused(exc) from None


@router.get(
    "/hearing",
    response_model=HearingServerReading,
    dependencies=[Depends(get_admin_reader)],
)
async def hearing() -> HearingServerReading:
    """The hearing server as it answers now: the hearing models it holds,
    and those in memory where it says."""
    return await hearing_server.read(_url(hearing_server))


@router.post(
    "/hearing/{action}/{model:path}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(get_admin_actor)],
)
async def move_hearing(action: str, model: str) -> None:
    """Load ``model`` into the hearing server's memory, or unload it
    (``hearing_server.ACTIONS``)."""
    try:
        await hearing_server.move(_url(hearing_server), action, model)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except speech_server.SpeechServerError as exc:
        raise _refused(exc) from None
