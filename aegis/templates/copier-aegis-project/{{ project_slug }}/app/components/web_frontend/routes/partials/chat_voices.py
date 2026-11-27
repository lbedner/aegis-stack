"""The voice, switched and tuned from the chat surface, on any mount.

A voice chip sits in the composer beside the model chip, naming what a
live call runs on where the mount takes calls (else the voice). It opens
the one dialog, in two panels: the call (what it runs on, as the parts a
call is made of - ``chat_calls``: one model, or hear, think, speak - and
who it speaks as, switched there) and the voice in use (her style, her
voice on each engine, each heard there). Behind them: how a call behaves
(the call setup's form), every voice (Manage: each with a preview, a new
one from the active, a rename), and the one list of how terms are said
(``spoken``), for every voice.
The setup and the active voice are applied onto the running settings
(``profiles.apply``), so the next thing said uses them - no ``.env`` edit,
no restart. Picking what a call runs on changes the setup, never the
voice.

``add_voice_routes(router, mount)`` adds them to a mount's router; the
chat router does, where voice and a database are both installed.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.backend.api.ai.service import ai_service
from app.components.web_frontend import chat_calls
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
        mode: str | None = None,
        slot: str | None = None,
        q: str = "",
        view: str = "list",
    ) -> Response:
        """The dialog's two panels (or, ``view`` "manage", every voice),
        ``on`` what calls run on where the caller has read it already;
        ``mode`` and ``slot`` what the call setup shows, ``q`` its search
        (``chat_calls.view``)."""
        if rows is None:
            rows = await profiles.list_profiles(db)
        on = on or await calling(db)
        active = next((p for p in rows if p.is_active), None)
        return dialog(
            request,
            TEMPLATE,
            status_code=422 if errors else 200,
            view=view,
            voices=rows,
            path=voices_path,
            active=active,
            engines=design.voice_engines(active) if active else [],
            terms=len(pronunciation_list()),
            setup=await chat_calls.view(
                db,
                voices_path,
                voice=active,
                calling=on,
                mode=mode,
                slot=slot,
                query=q,
            )
            if calls and view == "list"
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
            engines=design.voice_engines(profile),
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
        request: Request,
        mode: str | None = None,
        slot: str | None = None,
        q: str = "",
        db: AsyncSession = Depends(get_async_db),
    ) -> Response:
        return await listing_response(request, db, mode=mode, slot=slot, q=q)

    @router.get("/voices/manage", response_class=HTMLResponse)
    async def manage_voices(
        request: Request, db: AsyncSession = Depends(get_async_db)
    ) -> Response:
        """Every voice, each with a preview, Use and Edit; and a new one."""
        return await listing_response(request, db, view="manage")

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
        values = {key: str(form.get(key) or "") for key in ("term", "say")}
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

    async def voice_part(
        request: Request,
        db: AsyncSession,
        part: str,
        pick: Callable[..., Awaitable[Any]],
        model_id: str,
    ) -> Response:
        """What hears the caller, or speaks to them, on a chained call
        (``part``): the call setup's model, so spoken replies use it too.
        The voice stays as it is."""
        if not calls:
            raise HTTPException(status_code=404)
        try:
            setup = await pick(db, settings, model_id)
        except profiles.VoiceProfileError as error:
            return with_toast(
                await listing_response(request, db), str(error), tone="error"
            )
        profiles.apply(None, settings, ai_service, setup)
        return with_toast(
            await listing_response(request, db, mode=chat_calls.CHAIN, slot=part),
            f"Calls now {chat_calls.VERBS[part]} with {model_id}.",
        )

    @router.post("/voices/hears", response_class=HTMLResponse)
    async def hear_with(
        request: Request,
        model_id: Annotated[str, Form()],
        db: AsyncSession = Depends(get_async_db),
    ) -> Response:
        return await voice_part(
            request, db, chat_calls.HEARS, profiles.hear_with, model_id
        )

    @router.post("/voices/speaks", response_class=HTMLResponse)
    async def speak_with(
        request: Request,
        model_id: Annotated[str, Form()],
        db: AsyncSession = Depends(get_async_db),
    ) -> Response:
        return await voice_part(
            request, db, chat_calls.SPEAKS, profiles.speak_with, model_id
        )

    # Before the per-voice routes: "setup" is no voice id.
    def setup_response(
        request: Request,
        values: dict[str, Any],
        *,
        errors: list[str] | None = None,
    ) -> Response:
        return dialog(
            request,
            TEMPLATE,
            status_code=422 if errors else 200,
            view="setup",
            values=values,
            errors=errors or [],
            choices=profiles.form_choices(),
            idle=profiles.IDLE_RANGE,
            path=voices_path,
        )

    @router.get("/voices/setup", response_class=HTMLResponse)
    async def edit_setup(
        request: Request, db: AsyncSession = Depends(get_async_db)
    ) -> Response:
        """How a call behaves: what hears it, how a reply is heard, what
        plays while it works, when it checks in."""
        setup = await profiles.seeded_setup(db, settings)
        return setup_response(request, setup.model_dump())

    @router.post("/voices/setup", response_class=HTMLResponse)
    async def save_setup(
        request: Request, db: AsyncSession = Depends(get_async_db)
    ) -> Response:
        values, errors = profiles.parse_form(await request.form())
        if errors:
            return setup_response(request, values, errors=errors)
        setup = await profiles.set_up(db, settings, **values)
        profiles.apply(None, settings, ai_service, setup)
        return with_toast(await listing_response(request, db), "Saved the call setup.")

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
                request, db, errors=[str(error)], new_name=name, view="manage"
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
        values, errors = profiles.parse_name(await request.form())
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
        profile_id: int,
        engine: str | None = None,
        db: AsyncSession = Depends(get_async_db),
    ) -> Response:
        """The preview passage in THIS profile's voice, whichever one is
        active: on ``engine``, her voice there."""
        profile = await owned(db, profile_id)
        tts = TTSService(profiles.settings_for(profile, settings, engine=engine))
        said = await chat.synthesize(design.PREVIEW_TEXT, tts=tts)
        return Response(content=said.audio, media_type=said.media_type)
