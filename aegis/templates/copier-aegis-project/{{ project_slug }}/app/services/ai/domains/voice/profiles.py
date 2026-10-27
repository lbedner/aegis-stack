"""Voice profiles: which one is active, and putting it to work.

The active profile is applied onto the running settings, the way the active
model is, so everything that already reads ``settings.TTS_*`` / ``STT_*`` /
``VOICE_*`` follows it unchanged. The speech services read their config once
when built, so applying a profile also drops them for the next call to
rebuild.
"""

from typing import Any, get_args

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.core.voice_settings import (
    LIVE_IDLE_MAX_SECONDS,
    Reply,
    WorkingSound,
)
from app.services.ai.domains.voice import pronunciations, queries
from app.services.ai.domains.voice.catalog import (
    get_stt_models,
)
from app.services.ai.domains.voice.models import STTProvider
from app.services.ai.models.voice import VoiceProfile

# The first profile, seeded from ``.env``.
SEEDED_NAME = "Default"

# Profile column -> the setting it drives. One table, read both ways: to
# seed a profile from .env and to put a profile onto the settings.
SETTINGS = {
    "stt_provider": "STT_PROVIDER",
    "stt_model": "STT_MODEL",
    "tts_provider": "TTS_PROVIDER",
    "tts_model": "TTS_MODEL",
    "tts_voice": "TTS_VOICE",
    "tts_speed": "TTS_SPEED",
    "tts_instructions": "TTS_INSTRUCTIONS",
    "reply": "VOICE_REPLY",
    "working_sound": "VOICE_WORKING_SOUND",
    "live_idle_seconds": "VOICE_LIVE_IDLE_SECONDS",
    "live_engine": "VOICE_LIVE_ENGINE",
}


# What the profile form may say (the voice itself, its model, speed and
# delivery, is put together in the voice designer: ``design``).
STT_MODELS = tuple(m.id for m in get_stt_models(STTProvider.OPENAI_WHISPER.value))
REPLIES = get_args(Reply)
WORKING_SOUNDS = get_args(WorkingSound)
# What each picked column of the form may be: what it checks, what it offers.
CHOICES = {
    "stt_model": STT_MODELS,
    "reply": REPLIES,
    "working_sound": WORKING_SOUNDS,
}
IDLE_RANGE = (0, LIVE_IDLE_MAX_SECONDS)


def form_choices() -> dict[str, list[dict[str, Any]]]:
    """The edit form's options, from the one list each (``CHOICES``)."""
    return {
        column: [{"id": v, "name": v} for v in allowed]
        for column, allowed in CHOICES.items()
    }


def parse_form(form: Any) -> tuple[dict[str, Any], list[str]]:
    """A profile's edit form as column values, and what is wrong with it.
    The live engine is not on the form: the voice dialog's Calls list picks
    it (``chat_models.use_for_calls``); nor is the voice: the designer puts
    it together."""
    errors: list[str] = []
    name = str(form.get("name") or "").strip()
    if not name:
        errors.append(NEEDS_NAME)
    values: dict[str, Any] = {"name": name}
    for column, allowed in CHOICES.items():
        value = str(form.get(column) or "")
        if value not in allowed:
            errors.append(f"{column.replace('_', ' ')}: pick one of the choices.")
        values[column] = value
    try:
        idle = int(str(form.get("live_idle_seconds") or ""))
        if not IDLE_RANGE[0] <= idle <= IDLE_RANGE[1]:
            raise ValueError
        values["live_idle_seconds"] = idle
    except ValueError:
        errors.append(
            f"Check in after is whole seconds from {IDLE_RANGE[0]} to {IDLE_RANGE[1]}."
        )
    return values, errors


def settings_for(profile: VoiceProfile, settings: Any) -> Any:
    """A copy of ``settings`` speaking as ``profile`` - for a preview, which
    must not change the voice in use."""
    return settings.model_copy(
        update={key: getattr(profile, column) for column, key in SETTINGS.items()}
    )


class VoiceProfileError(ValueError):
    """A profile change that cannot be made (a duplicate name, a missing row)."""


NEEDS_NAME = "A voice needs a name."
GONE = "That voice no longer exists."


async def _refuse_taken(session: AsyncSession, name: str) -> None:
    if await queries.profile_named(session, name) is not None:
        raise VoiceProfileError(f'There is already a voice called "{name}".')


list_profiles = queries.all_profiles
active_profile = queries.active_profile


async def seed_from_settings(
    session: AsyncSession, settings: Any
) -> VoiceProfile | None:
    """The first profile, from .env, made active - only when there is none.
    Returns it, or None when profiles already exist (they are the app's)."""
    if await queries.any_profile(session):
        return None
    seeded = VoiceProfile(
        name=SEEDED_NAME,
        is_active=True,
        **{column: getattr(settings, key) for column, key in SETTINGS.items()},
    )
    session.add(seeded)
    await session.commit()
    return seeded


async def create(session: AsyncSession, *, name: str, **changes: Any) -> VoiceProfile:
    """A new, inactive profile: the active one's values, with ``changes``."""
    name = name.strip()
    if not name:
        raise VoiceProfileError(NEEDS_NAME)
    await _refuse_taken(session, name)
    base = await active_profile(session)
    values = {column: getattr(base, column) for column in SETTINGS} if base else {}
    values.update(changes)
    made = VoiceProfile(name=name, is_active=False, **values)
    session.add(made)
    await session.commit()
    return made


async def update(
    session: AsyncSession, profile_id: int, **changes: Any
) -> VoiceProfile:
    profile = await session.get(VoiceProfile, profile_id)
    if profile is None:
        raise VoiceProfileError(GONE)
    name = changes.get("name")
    if name and name != profile.name:
        await _refuse_taken(session, name)
    for column, value in changes.items():
        setattr(profile, column, value)
    profile.updated_at = utcnow()
    session.add(profile)
    await session.commit()
    return profile


async def activate(session: AsyncSession, profile_id: int) -> list[VoiceProfile]:
    """Make ``profile_id`` the one active profile. Returns every profile, so
    a caller showing the list does not read it again. (Sessions keep objects
    loaded after a commit: no refresh round trips here.)"""
    profiles = await list_profiles(session)
    chosen = next((p for p in profiles if p.id == profile_id), None)
    if chosen is None:
        raise VoiceProfileError(GONE)
    for profile in profiles:
        if profile.is_active != (profile is chosen):
            profile.is_active = profile is chosen
            session.add(profile)
    await session.commit()
    return profiles


def apply(profile: VoiceProfile, settings: Any, service: Any) -> None:
    """Put ``profile`` onto the running ``settings``, and drop the speech
    services ``service`` built from the old values."""
    for column, key in SETTINGS.items():
        setattr(settings, key, getattr(profile, column))
    service._stt_service = None
    service._tts_service = None


async def active_settings(session: AsyncSession, settings: Any) -> Any:
    """``settings`` in the active profile's voice: what anything headless (a
    worker, the CLI) speaks and hears with, as only the webserver applies
    the profile at startup (``load_active``). The saved pronunciations come
    with the voice, as they do there."""
    await pronunciations.load(session)
    active = await active_profile(session)
    return settings if active is None else settings_for(active, settings)


async def seeded_active(session: AsyncSession, settings: Any) -> VoiceProfile:
    """The active profile, a first one seeded from ``settings`` (``.env``)
    when there is none yet."""
    await seed_from_settings(session, settings)
    return await active_profile(session)  # type: ignore[return-value]


async def load_active(
    session: AsyncSession, settings: Any, service: Any
) -> VoiceProfile | None:
    """At startup: seed a first profile from .env if there is none, then run
    on the active one, saying terms the saved way. After the first boot the
    table wins over .env."""
    await pronunciations.load(session)
    active = await seeded_active(session, settings)
    if active is not None:
        apply(active, settings, service)
    return active
