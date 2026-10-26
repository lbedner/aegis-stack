"""The stack's voice at a glance (``voice_overview``), as both Overseers
show it, and the two changes they make: a row put on the active voice
profile, another profile made the active one (an admin's, each answered
with the overview as it now is). Where the stack keeps no profiles (no
database) the overview is what its settings use. Beside it, how every
voice says terms (``pronunciation_list``): read on every stack, changed
where there is a database to keep the change."""

from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.components.backend.api.ai.service import ai_service
from app.core.log import logger
import app.services.ai.service as ai
from app.services.ai.service import (
    Pronunciation,
    VoiceOverview,
    pronunciation_list,
    switch_voice,
    use_voice,
    voice_overview,
)
from app.services.shared.deps import get_admin_actor

router = APIRouter()
CHANGE = [Depends(get_admin_actor)]
# The voice designer is on the facade where the stack keeps voice profiles
# (a database).
KEEPS_PROFILES = hasattr(ai, "design")


async def _session() -> AsyncIterator[Any]:
    """The database, where the stack keeps voice profiles; else None."""
    if not KEEPS_PROFILES:
        yield None
        return
    from app.core.db import get_async_db

    async for session in get_async_db():
        yield session


@router.get("/overview", response_model=VoiceOverview)
async def overview(db: Any = Depends(_session)) -> VoiceOverview:
    """What the active profile uses, then every model and voice."""
    return await voice_overview(db)


@router.post("/use", response_model=VoiceOverview, dependencies=CHANGE)
async def use(choice: dict[str, str], db: Any = Depends(_session)) -> VoiceOverview:
    """A row's ``use`` on the active profile, the rest made to fit."""
    if db is None:
        raise HTTPException(409, "This stack keeps no voice profiles")
    try:
        await use_voice(db, choice, ai_service)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return await voice_overview(db)


@router.post(
    "/profiles/{profile_id}/active", response_model=VoiceOverview, dependencies=CHANGE
)
async def activate(profile_id: int, db: Any = Depends(_session)) -> VoiceOverview:
    """Another voice profile made the active one."""
    if db is None:
        raise HTTPException(409, "This stack keeps no voice profiles")
    try:
        await switch_voice(db, profile_id, ai_service)
    except StopIteration:
        raise HTTPException(404, f"No voice profile {profile_id}") from None
    return await voice_overview(db)



@router.get("/pronunciation", response_model=list[Pronunciation])
async def pronunciation() -> list[Pronunciation]:
    """How every voice says terms: the defaults, an app's own, the saved."""
    return pronunciation_list()

if KEEPS_PROFILES:
    # The voice designer (``design``): a profile's voice put together, heard
    # unsaved and saved. Only where profiles are kept.
    from fastapi import Request
    from fastapi.responses import Response

    from app.core.config import settings
    from app.services.ai.service import SpeechRequest, TTSService, design

    async def _heard(voice_settings: Any, missing: str = "") -> Response:
        """The preview passage said with ``voice_settings`` (404 ``missing``
        where there are none)."""
        if voice_settings is None:
            raise HTTPException(404, missing)
        try:
            said = await TTSService(voice_settings).synthesize(
                SpeechRequest(text=design.PREVIEW_TEXT)
            )
        except Exception:  # the provider's own: a key, the network, a format
            logger.exception("Voice preview failed")
            raise HTTPException(503, "The voice could not be heard") from None
        return Response(content=said.audio, media_type=said.media_type)

    def _picked(query: Any) -> Any:
        picked, errors = design.parse_design(query)
        if picked is None:
            raise HTTPException(422, " ".join(errors))
        return picked

    def _asked(query: Any) -> Any:
        """The choices the query holds, where it holds a voice; else None."""
        return _picked(query) if "voice" in query else None

    @router.get("/design", response_model=design.DesignView)
    async def design_view(
        request: Request, profile: int | None = None, db: Any = Depends(_session)
    ) -> Any:
        """A profile's voice as the designer opens on it (else the active
        one's), or on the choices the query holds."""
        return await design.design_view(
            db, profile, _asked(request.query_params), request.query_params
        )

    @router.post("/design", response_model=design.DesignView, dependencies=CHANGE)
    async def design_save(
        picked: design.Design, profile: int | None = None, db: Any = Depends(_session)
    ) -> Any:
        """``picked`` saved onto the profile (else the active one)."""
        saved = await design.save_design(db, profile, picked, ai_service)
        return await design.design_view(db, saved.id, None)

    @router.get("/design/preview")
    async def design_preview(request: Request) -> Response:
        """The choices in the query heard unsaved, as they would be said."""
        return await _heard(
            design.design_settings(_picked(request.query_params), settings)
        )

    @router.get("/design/profiles/{profile_id}/preview")
    async def profile_preview(profile_id: int, db: Any = Depends(_session)) -> Response:
        """A saved profile's voice, whichever one is in use."""
        return await _heard(
            await design.profile_voice(db, profile_id, settings),
            missing=f"No voice profile {profile_id}",
        )

    @router.get("/design/profiles", response_model=list[design.ProfileSummary])
    async def design_profiles(db: Any = Depends(_session)) -> Any:
        """Every voice profile at a glance, the active one first."""
        return await design.profile_summaries(db)

    @router.post(
        "/design/profiles",
        response_model=design.ProfileSummary,
        dependencies=CHANGE,
        status_code=201,
    )
    async def design_make(made: dict[str, str], db: Any = Depends(_session)) -> Any:
        """A new voice profile (``{"name": ...}``), from the active one."""
        try:
            profile = await design.make_profile(db, made.get("name", ""))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        return next(s for s in await design.profile_summaries(db) if s.id == profile.id)

    from app.services.ai.service import pronunciations

    @router.post(
        "/pronunciation", response_model=list[Pronunciation], dependencies=CHANGE
    )
    async def pronunciation_save(
        said: Pronunciation, db: Any = Depends(_session)
    ) -> list[Pronunciation]:
        """Say ``said.term`` its way from the next thing said."""
        try:
            await pronunciations.save(db, said.term, said.say, said.ipa)
        except pronunciations.PronunciationError as exc:
            raise HTTPException(422, str(exc)) from None
        return pronunciation_list()

    @router.delete(
        "/pronunciation/{term}",
        response_model=list[Pronunciation],
        dependencies=CHANGE,
    )
    async def pronunciation_remove(
        term: str, db: Any = Depends(_session)
    ) -> list[Pronunciation]:
        """Drop ``term``'s saved row: it is said the default way again."""
        await pronunciations.remove(db, term)
        return pronunciation_list()
