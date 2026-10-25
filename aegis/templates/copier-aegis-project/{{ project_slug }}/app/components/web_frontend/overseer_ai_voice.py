"""The Overseer AI page's Voice section: the voice overview's rows
(``voice_overview``, the one the Flet Overseer reads over the API) in one
tight table on the canvas, each provider in its own color, narrowed by the
page's filters with no request (``data-facets``), each heard on its own
voice and model through the voice API's preview route.

Use puts a row on the active profile and Profile switches it
(``use_voice``, ``switch_voice``), saved and applied at once; Edit opens
the profile's own editor, the chat surface's voice dialog. Transcription is
the speech API's ``transcribe_audio``. Offered wherever ``ai[...,voice]``
installed the voice domain.
"""

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from fastapi import UploadFile

from .overseer_ai_common import PARTIALS, section_url

if TYPE_CHECKING:
    # Only a stack with a database has it; a voice-only one does not.
    from sqlmodel.ext.asyncio.session import AsyncSession

API = "/api/v1/voice"
PREVIEW = f"{API}/preview/"


def _speak(voice: str, model: str) -> str:
    """Where ``voice`` is heard on ``model``: the voice API's preview."""
    return f"{PREVIEW}{voice}?{urlencode({'model': model})}"


def _row(row: Any, colors: dict[str, int]) -> dict[str, Any]:
    """A row as the page draws it: its provider's color, the models a
    filter matches, and where it is heard."""
    return row.model_dump() | {
        "color": colors[row.provider],
        "models": " ".join(row.models),
        "speak": _speak(*row.sample) if row.sample else None,
    }


def _options(name: str, labels: dict[str, str]) -> list[dict[str, Any]]:
    """A filter's choices (``checklist``), none ticked."""
    return [{"name": name, "value": v, "label": label} for v, label in labels.items()]


# The section's tabs: Profiles (its own address), then Models.
TABS = {"profiles": "Profiles", "models": "Models"}


def _ai() -> Any:
    import app.services.ai.service as ai

    return ai


def _designs() -> Any:
    """The voice designer, where the stack keeps voice profiles."""
    return getattr(_ai(), "design", None)


async def voice_context(db: "AsyncSession", query: Mapping[str, str]) -> dict[str, Any]:
    """The tab asked for (Models where nothing can be designed: no
    profiles kept), under the tab row; Profiles is the list, or one
    profile's editor when one is asked for."""
    tab = query.get("tab") if query.get("tab") in TABS else "profiles"
    if _designs() is None:
        tab = "models"
    frame = {
        "tab": tab,
        "tabs": [
            {
                "label": label,
                "url": section_url("voice", tab=None if key == "profiles" else key),
                "active": key == tab,
            }
            for key, label in TABS.items()
            if key == "models" or _designs() is not None
        ],
    }
    if tab == "models":
        return frame | await _models(db)
    if query.get("profile", "").isdigit():
        return frame | await _editor(db, query)
    return frame | await _profiles(db)


async def _profiles(db: "AsyncSession") -> dict[str, Any]:
    """Every profile at a glance, each to hear, edit or put in use."""
    summaries = await _designs().profile_summaries(db)
    return {
        "editing": False,
        "summaries": [
            s.model_dump()
            | {
                "edit": section_url("voice", profile=str(s.id)),
                "listen": f"{API}/design/profiles/{s.id}/preview",
            }
            for s in summaries
        ],
        "new_url": f"{PARTIALS}/voice/profiles",
        "profile_url": f"{PARTIALS}/voice/profile",
    }


async def _editor(db: "AsyncSession", query: Mapping[str, str]) -> dict[str, Any]:
    """One profile's editor at a step (``go``, a step button just pressed,
    over ``step``, the one it was on), drawn from the designer's view
    (``design_view``): the choices the form carries where it carries any,
    the Voice step narrowed by the filters it sends."""
    design = _designs()
    step = next(
        (s for s in (query.get("go"), query.get("step")) if s in design.STEPS), "voice"
    )
    picked = design.parse_design(query)[0] if "voice" in query else None
    view = await design.design_view(db, int(query["profile"]), picked, query)
    return {
        "editing": True,
        "view": view,
        "step": step,
        "chosen_listen": _speak(view.voice, view.model),
        # The accent checklist follows the other filters: a new id when its
        # options change, so the page draws them (a checklist is preserved).
        "accent_id": "ai-voice-accent-"
        + str(abs(hash(tuple(o.value for o in view.find.options["accent"])))),
        "sample_url": PREVIEW,
        "back_url": section_url("voice"),
        "save_url": f"{PARTIALS}/voice/design",
        "listen_url": f"{API}/design/preview",
        # Each style as it would be picked: its dials, the rest kept.
        "style_listen": {
            key: f"{API}/design/preview?"
            + urlencode(view.form | style.dials | {"style": key, "was_style": key})
            for key, style in view.styles.items()
            if key
        },
    }


async def _models(db: "AsyncSession") -> dict[str, Any]:
    """Every model and voice, as the voice overview has them."""
    from app.services.ai.service import voice_overview

    found = await voice_overview(db)
    providers = {r.provider: r.provider_name for r in found.rows}
    voices = [r for r in found.rows if r.kind == "voice" and r.sample]
    speaking = found.rows[0].sample
    colors = {p: i + 1 for i, p in enumerate(providers)}
    return {
        "rows": [_row(r, colors) for r in found.rows],
        "kinds": _options("kind", found.kinds),
        "providers": _options("provider", providers),
        "models": _options(
            "model", {m: m for r in found.rows if r.kind != "use" for m in r.models}
        ),
        "use_url": f"{PARTIALS}/voice/use",
        "voice_options": [{"id": r.sample[0], "name": r.name} for r in voices],
        "current_voice": speaking[0] if speaking else None,
        "preview_base": PREVIEW,
        "transcribe_url": f"{PARTIALS}/voice/transcribe",
    }


async def save(db: "AsyncSession", form: Mapping[str, str]) -> tuple[str, int | None]:
    """The designer's form saved onto its profile: what was said, and the
    profile (None when the form was refused, and why)."""
    from app.components.backend.api.ai.service import ai_service

    design = _designs()
    picked, errors = design.parse_design(form)
    if picked is None:
        return " ".join(errors), None
    profile = form.get("profile", "")
    saved = await design.save_design(
        db, int(profile) if profile.isdigit() else None, picked, ai_service
    )
    return f"Saved {saved.name}.", saved.id


async def make(db: "AsyncSession", name: str) -> tuple[str, int | None]:
    """A new profile from the active one: what was said, and the profile
    (None when the name was refused, and why)."""
    profiles = _ai().profiles
    try:
        made = await _designs().make_profile(db, name)
    except profiles.VoiceProfileError as exc:
        return str(exc), None
    return f"Made {made.name}.", made.id


async def use(db: "AsyncSession", choice: dict[str, str]) -> str:
    """A row's choice on the active profile; what it uses now."""
    from app.components.backend.api.ai.service import ai_service
    from app.services.ai.service import use_voice

    return await use_voice(db, choice, ai_service)


async def switch(db: "AsyncSession", profile_id: int) -> str:
    """Another profile made the active one; its name."""
    from app.components.backend.api.ai.service import ai_service
    from app.services.ai.service import switch_voice

    return await switch_voice(db, profile_id, ai_service)


async def transcribe(audio: UploadFile) -> Any:
    """The speech API's transcription, unchanged: its format checks and its
    errors (``HTTPException``) are the page's too."""
    from app.components.backend.api.ai.speech import transcribe_audio

    return await transcribe_audio(audio=audio, language=None)
