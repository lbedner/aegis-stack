"""The voice, switched and tuned from the chat surface, on any mount.

A voice chip sits in the composer beside the model chip. It opens the one
dialog, which lists the voice profiles (each with a preview), switches the
active one, makes a new one from the active, and edits one. The active
profile is applied onto the running settings (``profiles.apply``), so the
next thing said uses it - no ``.env`` edit, no restart.

``add_voice_routes(router, mount)`` adds them to a mount's router; the
chat router does, where voice and a database are both installed.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.backend.api.ai.service import ai_service
from app.components.web_frontend import chat_surface as chat
from app.components.web_frontend.chat_surface import ChatSurface
from app.components.web_frontend.rendering import dialog, templates, with_toast
from app.core.config import settings
from app.core.db import get_async_db
from app.services.ai.domains.voice import profiles
from app.services.ai.domains.voice.tts import TTSService
from app.services.ai.models.voice import VoiceProfile

TEMPLATE = "partials/chat/voices.html"

# One passage for every preview, so voices are compared on the same words:
# a figure, some bad news, and a question.
PREVIEW_TEXT = (
    "Here's where things stand. Three items came in since yesterday, and "
    "two of them are done. Heads up, though: one is already four days "
    "overdue. Want me to walk you through it?"
)


def _choices() -> dict[str, list[dict[str, str]]]:
    """The edit form's options, from the one list each (``profiles``)."""
    return {
        column: [{"id": v, "name": v} for v in allowed]
        for column, allowed in profiles.CHOICES.items()
    }


def add_voice_routes(router: APIRouter, mount: ChatSurface) -> None:
    """The voice chip and dialog, under ``mount.path``/voices."""
    voices_path = f"{mount.path}/voices"

    async def listing_response(
        request: Request,
        db: AsyncSession,
        *,
        chip: bool = False,
        errors: list[str] | None = None,
        new_name: str = "",
        rows: list[VoiceProfile] | None = None,
    ) -> Response:
        if rows is None:
            rows = await profiles.list_profiles(db)
        return dialog(
            request,
            TEMPLATE,
            status_code=422 if errors else 200,
            view="list",
            voices=rows,
            path=voices_path,
            assistant=await chat.assistant_name(mount),
            active=next((p for p in rows if p.is_active), None),
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
            choices=_choices(),
            speed=profiles.SPEED_RANGE,
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
                "path": voices_path,
            },
        )

    @router.get("/voices", response_class=HTMLResponse)
    async def voices(
        request: Request, db: AsyncSession = Depends(get_async_db)
    ) -> Response:
        return await listing_response(request, db)

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
        request: Request, profile_id: int, db: AsyncSession = Depends(get_async_db)
    ) -> Response:
        """The preview passage in THIS profile's voice, whichever one is
        active - or, from the edit form, in the values the form holds,
        unsaved (the query carries them, checked as a save would be)."""
        profile = await owned(db, profile_id)
        if "tts_voice" in request.query_params:
            values, errors = profiles.parse_form(request.query_params)
            if errors:
                return Response(status_code=422)
            profile = VoiceProfile(**values)
        tts = TTSService(profiles.settings_for(profile, settings))
        audio = await chat.synthesize(PREVIEW_TEXT, tts=tts)
        return Response(content=audio, media_type="audio/mpeg")
