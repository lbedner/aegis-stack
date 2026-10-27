"""The voice, switched and tuned from the chat surface, on any mount.

A voice chip sits in the composer beside the model chip, naming what a
live call runs on where the mount takes calls (else the voice). It opens
the one dialog, which picks what calls run on (the realtime models a call
can reach: ``chat_models.call_rows``), lists the voice profiles (each with
a preview), switches the active one, makes a new one from the active, and
edits one; and keeps the one list of how terms are said (``spoken``), for
every voice. The active profile is applied onto the running settings
(``profiles.apply``), so the next thing said uses it - no ``.env`` edit,
no restart.

``add_voice_routes(router, mount)`` adds them to a mount's router; the
chat router does, where voice and a database are both installed.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.backend.api.ai.service import ai_service
from app.components.web_frontend import chat_models as models
from app.components.web_frontend import chat_surface as chat
from app.components.web_frontend.chat_surface import ChatSurface
from app.components.web_frontend.rendering import dialog, templates, with_toast
from app.core.config import settings
from app.core.db import get_async_db
from app.services.ai.service import (
    TTSService,
    VoiceProfile,
    design,
    profiles,
    pronunciation_list,
    pronunciations,
    saved_keys,
)

TEMPLATE = "partials/chat/voices.html"


def add_voice_routes(router: APIRouter, mount: ChatSurface) -> None:
    """The voice chip and dialog, under ``mount.path``/voices."""
    voices_path = f"{mount.path}/voices"
    calls = chat.offers_calls(mount)

    async def calling(db: AsyncSession) -> Any | None:
        """What a live call runs on, where this mount takes calls."""
        return await models.calling_model(db) if calls else None

    async def listing_response(
        request: Request,
        db: AsyncSession,
        *,
        chip: bool = False,
        errors: list[str] | None = None,
        new_name: str = "",
        rows: list[VoiceProfile] | None = None,
        on: Any | None = None,
    ) -> Response:
        """The dialog's list, ``on`` what calls run on where the caller
        has read it already."""
        if rows is None:
            rows = await profiles.list_profiles(db)
        on = on or await calling(db)
        return dialog(
            request,
            TEMPLATE,
            status_code=422 if errors else 200,
            view="list",
            voices=rows,
            path=voices_path,
            assistant=await chat.assistant_name(mount, db),
            active=next((p for p in rows if p.is_active), None),
            call_rows=await models.call_rows(getattr(on, "model_id", None))
            if calls
            else None,
            calling=on,
            chip_oob=chip,
            errors=errors or [],
            new_name=new_name,
        )

    def form_response(
        request: Request,
        profile: VoiceProfile,
        *,
        values: dict[str, Any] | None = None,
        errors: list[str] | None = None,
        status_code: int = 200,
    ) -> Response:
        return dialog(
            request,
            TEMPLATE,
            status_code=status_code,
            view="form",
            voice=profile,
            values=values or profile.model_dump(),
            errors=errors or [],
            choices=profiles.form_choices(),
            idle=profiles.IDLE_RANGE,
            path=voices_path,
        )

    async def owned(db: AsyncSession, profile_id: int) -> VoiceProfile:
        profile = await db.get(VoiceProfile, profile_id)
        if profile is None:
            raise HTTPException(status_code=404)
        return profile

    @router.get("/voices/chip", response_class=HTMLResponse)
    async def voice_chip(
        request: Request, db: AsyncSession = Depends(get_async_db)
    ) -> Response:
        """The composer's voice chip: it loads itself, so the surface needs
        nothing new in its own context."""
        return templates.TemplateResponse(
            request=request,
            name=TEMPLATE,
            context={
                "view": "chip",
                "active": await profiles.active_profile(db),
                "calling": await calling(db),
                "path": voices_path,
            },
        )

    @router.get("/voices", response_class=HTMLResponse)
    async def voices(
        request: Request, db: AsyncSession = Depends(get_async_db)
    ) -> Response:
        return await listing_response(request, db)

    # Before the per-voice routes: "pronunciation" is no voice id.
    def said_response(
        request: Request,
        *,
        values: dict[str, str] | None = None,
        errors: list[str] | None = None,
    ) -> Response:
        """The whole list as every voice says it; a saved row can go."""
        return dialog(
            request,
            TEMPLATE,
            status_code=422 if errors else 200,
            view="said",
            said=pronunciation_list(),
            saved=saved_keys(),
            values=values or {},
            errors=errors or [],
            path=voices_path,
        )

    @router.get("/voices/pronunciation", response_class=HTMLResponse)
    async def pronunciation(request: Request) -> Response:
        return said_response(request)

    @router.post("/voices/pronunciation", response_class=HTMLResponse)
    async def save_pronunciation(
        request: Request, db: AsyncSession = Depends(get_async_db)
    ) -> Response:
        form = await request.form()
        values = {key: str(form.get(key) or "") for key in ("term", "say", "ipa")}
        try:
            await pronunciations.save(db, **values)
        except pronunciations.PronunciationError as error:
            return said_response(request, values=values, errors=[str(error)])
        return with_toast(
            said_response(request), f"Saved how {values['term'].strip()} is said."
        )

    @router.post("/voices/pronunciation/delete", response_class=HTMLResponse)
    async def remove_pronunciation(
        request: Request, db: AsyncSession = Depends(get_async_db)
    ) -> Response:
        await pronunciations.remove(db, str((await request.form()).get("term") or ""))
        return said_response(request)

    @router.post("/voices/calls", response_class=HTMLResponse)
    async def pick_for_calls(
        request: Request,
        model_id: Annotated[str, Form()],
        db: AsyncSession = Depends(get_async_db),
    ) -> Response:
        """What a live call runs on, the active voice's engine; a refused
        pick says why and changes nothing."""
        if not calls:
            raise HTTPException(status_code=404)
        if refused := await models.use_for_calls(model_id):
            return with_toast(
                await listing_response(request, db), refused, tone="error"
            )
        chosen = await calling(db)
        return with_toast(
            await listing_response(request, db, chip=True, on=chosen),
            f"Calls now run on {chosen.title if chosen else model_id}.",
        )

    @router.post("/voices/{profile_id}/active", response_class=HTMLResponse)
    async def use_voice(
        request: Request, profile_id: int, db: AsyncSession = Depends(get_async_db)
    ) -> Response:
        try:
            rows = await profiles.activate(db, profile_id)
        except profiles.VoiceProfileError:
            raise HTTPException(status_code=404) from None
        chosen = next(p for p in rows if p.is_active)
        profiles.apply(chosen, settings, ai_service)
        return with_toast(
            await listing_response(request, db, chip=True, rows=rows),
            f"Now speaking as {chosen.name}.",
        )

    @router.post("/voices", response_class=HTMLResponse)
    async def make_voice(
        request: Request, db: AsyncSession = Depends(get_async_db)
    ) -> Response:
        """A new voice from the active one, opened straight into its form."""
        name = str((await request.form()).get("name") or "")
        try:
            made = await profiles.create(db, name=name)
        except profiles.VoiceProfileError as error:
            return await listing_response(
                request, db, errors=[str(error)], new_name=name
            )
        return form_response(request, made)

    @router.get("/voices/{profile_id}/edit", response_class=HTMLResponse)
    async def edit_voice(
        request: Request, profile_id: int, db: AsyncSession = Depends(get_async_db)
    ) -> Response:
        return form_response(request, await owned(db, profile_id))

    @router.post("/voices/{profile_id}", response_class=HTMLResponse)
    async def save_voice(
        request: Request, profile_id: int, db: AsyncSession = Depends(get_async_db)
    ) -> Response:
        profile = await owned(db, profile_id)
        values, errors = profiles.parse_form(await request.form())
        if not errors:
            try:
                profile = await profiles.update(db, profile_id, **values)
            except profiles.VoiceProfileError as error:
                errors = [str(error)]
        if errors:
            return form_response(
                request, profile, values=values, errors=errors, status_code=422
            )
        if profile.is_active:
            profiles.apply(profile, settings, ai_service)
        return with_toast(
            await listing_response(request, db, chip=profile.is_active),
            f"Saved {profile.name}.",
        )

    @router.get("/voices/{profile_id}/preview")
    async def preview_voice(
        profile_id: int, db: AsyncSession = Depends(get_async_db)
    ) -> Response:
        """The preview passage in THIS profile's voice, whichever one is
        active."""
        tts = TTSService(profiles.settings_for(await owned(db, profile_id), settings))
        said = await chat.synthesize(design.PREVIEW_TEXT, tts=tts)
        return Response(content=said.audio, media_type=said.media_type)
