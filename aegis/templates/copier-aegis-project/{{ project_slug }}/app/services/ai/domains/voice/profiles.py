"""Voice profiles and the call setup: which voice is active, and putting
both to work.

Two rows meet on the running settings, the way the active model does: the
call setup (``CallSetup``: what a call runs on, how it behaves) and the
active voice (``VoiceProfile``: how she sounds, with a voice per speaking
provider). Everything that already reads ``settings.TTS_*`` / ``STT_*`` /
``VOICE_*`` follows them unchanged; ``TTS_VOICE`` is the voice's for the
setup's speaking provider. Picking a model changes the setup, never the
voice. The speech services read their config once when built, so applying
either also drops them for the next call to rebuild.
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
    get_stt_model,
    get_stt_models,
    get_tts_model,
    get_tts_voices,
    get_voice,
    speaking_model,
)
from app.services.ai.models.voice import CallSetup, VoiceProfile

# The first profile, seeded from ``.env``.
SEEDED_NAME = "Default"

# Column -> the setting it drives, one table per row: read both ways, to
# seed from .env and to put the row onto the settings.
SETUP = {
    "stt_provider": "STT_PROVIDER",
    "stt_model": "STT_MODEL",
    "tts_provider": "TTS_PROVIDER",
    "tts_model": "TTS_MODEL",
    "reply": "VOICE_REPLY",
    "working_sound": "VOICE_WORKING_SOUND",
    "live_idle_seconds": "VOICE_LIVE_IDLE_SECONDS",
    "live_engine": "VOICE_LIVE_ENGINE",
}
VOICE = {
    "voices": "TTS_VOICES",
    "tts_speed": "TTS_SPEED",
    "tts_instructions": "TTS_INSTRUCTIONS",
}
# What a new voice copies from the active one: how it sounds, the
# designer's choices included.
COPIED = (*VOICE, "tts_delivery")


def setting_values(
    profile: VoiceProfile | None = None, setup: CallSetup | None = None
) -> dict[str, Any]:
    """The settings ``profile`` and ``setup`` drive, by setting name."""
    values: dict[str, Any] = {}
    if setup is not None:
        values |= {key: getattr(setup, column) for column, key in SETUP.items()}
    if profile is not None:
        values |= {key: getattr(profile, column) for column, key in VOICE.items()}
    return values


def _speaking(settings: Any) -> Any:
    """``settings`` with ``TTS_VOICE`` the voice's for its provider, else
    None (the provider's own default)."""
    settings.TTS_VOICE = settings.TTS_VOICES.get(settings.TTS_PROVIDER)
    return settings


# What the call setup's form may say (what a call runs on is picked from
# the voice dialog's lists: ``chat_models.use_for_calls``, Hears, Speaks).
# What each picked column of the form may be: what it checks, what it offers.
CHOICES = {
    "stt_model": tuple(m.id for m in get_stt_models()),
    "reply": get_args(Reply),
    "working_sound": get_args(WorkingSound),
}
IDLE_RANGE = (0, LIVE_IDLE_MAX_SECONDS)


def form_choices() -> dict[str, list[dict[str, Any]]]:
    """The setup form's options, from the one list each (``CHOICES``)."""
    return {
        column: [{"id": v, "name": v} for v in allowed]
        for column, allowed in CHOICES.items()
    }


def parse_name(form: Any) -> tuple[dict[str, Any], list[str]]:
    """A voice's edit form (its name: how it sounds is put together in the
    voice designer, ``design``), and what is wrong with it."""
    name = str(form.get("name") or "").strip()
    return {"name": name}, [] if name else [NEEDS_NAME]


def parse_form(form: Any) -> tuple[dict[str, Any], list[str]]:
    """The call setup's form as column values, and what is wrong with it."""
    errors: list[str] = []
    values: dict[str, Any] = {}
    for column, allowed in CHOICES.items():
        value = str(form.get(column) or "")
        if value not in allowed:
            errors.append(f"{column.replace('_', ' ')}: pick one of the choices.")
        values[column] = value
    values.update(hearing(values["stt_model"]))
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


def hearing(model_id: str) -> dict[str, str]:
    """The columns a hearing model sets: it, and its own provider (an
    OpenAI model kept beside Parakeet would be asked of Parakeet); none for
    a model the catalog does not know."""
    heard = get_stt_model(model_id)
    return {"stt_model": model_id, "stt_provider": heard.provider_id} if heard else {}


def speaking(model_id: str) -> dict[str, str]:
    """The columns a speaking model sets: it and its own provider; none for
    a model the catalog does not know or one with no voices. The voice it
    speaks in stays the voice's."""
    found = get_tts_model(model_id)
    if not (found and get_tts_voices(model_id=model_id)):
        return {}
    return {"tts_model": model_id, "tts_provider": found.provider_id}


async def hear_with(session: AsyncSession, settings: Any, model_id: str) -> CallSetup:
    """The call setup hearing with ``model_id`` (its Hears)."""
    columns = hearing(model_id)
    if not columns:
        raise VoiceProfileError(f"{model_id} is not a hearing model.")
    return await set_up(session, settings, **columns)


async def speak_with(session: AsyncSession, settings: Any, model_id: str) -> CallSetup:
    """The call setup speaking with ``model_id`` (its Speaks)."""
    columns = speaking(model_id)
    if not columns:
        raise VoiceProfileError(f"{model_id} is not a speaking model.")
    return await set_up(session, settings, **columns)


def settings_for(
    profile: VoiceProfile,
    settings: Any,
    setup: CallSetup | None = None,
    engine: str | None = None,
) -> Any:
    """A copy of ``settings`` sounding as ``profile`` (on ``setup`` where
    given; on ``engine``, her voice there, where she has one) - for a
    preview, which must not change the voice in use."""
    update = setting_values(profile, setup)
    if engine and (voice := profile.voices.get(engine)):
        model = speaking_model(voice, update.get("TTS_MODEL", settings.TTS_MODEL))
        update |= {"TTS_PROVIDER": engine, "TTS_MODEL": model}
    return _speaking(settings.model_copy(update=update))


class VoiceProfileError(ValueError):
    """A profile change that cannot be made (a duplicate name, a missing row)."""


NEEDS_NAME = "A voice needs a name."
GONE = "That voice no longer exists."


async def _refuse_taken(session: AsyncSession, name: str) -> None:
    if await queries.profile_named(session, name) is not None:
        raise VoiceProfileError(f'There is already a voice called "{name}".')


list_profiles = queries.all_profiles
active_profile = queries.active_profile
call_setup = queries.call_setup


def _from_settings(settings: Any) -> dict[str, Any]:
    """A first voice's columns, from .env: its voice on its provider."""
    voice = settings.TTS_VOICE
    return {column: getattr(settings, key) for column, key in VOICE.items()} | {
        "voices": {settings.TTS_PROVIDER: voice} if voice else {}
    }


async def seed_from_settings(
    session: AsyncSession, settings: Any
) -> VoiceProfile | None:
    """The call setup and a first profile, from .env, made active - each
    only when there is none. Returns the profile, or None when profiles
    already exist (they are the app's)."""
    await seeded_setup(session, settings)
    return await _seeded_profile(session, settings)


async def _seeded_profile(session: AsyncSession, settings: Any) -> VoiceProfile | None:
    """A first profile from .env, made active, when there is none."""
    if await queries.any_profile(session):
        return None
    seeded = VoiceProfile(name=SEEDED_NAME, is_active=True, **_from_settings(settings))
    session.add(seeded)
    await session.commit()
    return seeded


async def seeded_setup(session: AsyncSession, settings: Any) -> CallSetup:
    """The call setup, seeded from ``settings`` (``.env``) when there is
    none yet. One read."""
    setup = await queries.call_setup(session)
    if setup is None:
        setup = CallSetup(
            **{column: getattr(settings, key) for column, key in SETUP.items()}
        )
        session.add(setup)
        await session.commit()
    return setup


async def set_up(session: AsyncSession, settings: Any, **changes: Any) -> CallSetup:
    """``changes`` on the call setup (seeded from ``settings`` first when
    there is none)."""
    return await _change(session, await seeded_setup(session, settings), changes)


async def _change(
    session: AsyncSession, setup: CallSetup, changes: dict[str, Any]
) -> CallSetup:
    for column, value in changes.items():
        setattr(setup, column, value)
    setup.updated_at = utcnow()
    session.add(setup)
    await session.commit()
    return setup


async def create(session: AsyncSession, *, name: str, **changes: Any) -> VoiceProfile:
    """A new, inactive profile: how the active one sounds, with ``changes``."""
    name = name.strip()
    if not name:
        raise VoiceProfileError(NEEDS_NAME)
    await _refuse_taken(session, name)
    base = await active_profile(session)
    values = {column: getattr(base, column) for column in COPIED} if base else {}
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


async def give_voice(
    session: AsyncSession,
    setup: CallSetup,
    profile: VoiceProfile,
    voice_id: str,
    model: str | None = None,
    **columns: Any,
) -> tuple[VoiceProfile, CallSetup]:
    """``voice_id`` made ``profile``'s on its provider, the others kept,
    with ``columns`` (a design's speed and delivery), in one write. Where
    the call setup speaks that provider it moves to a model that speaks the
    voice (``model`` where it does, else its own where it does, else one
    that does): a voice picked for the engine in use is heard. A voice for
    another engine leaves the setup be."""
    voice = get_voice(voice_id)
    if voice is None:
        raise VoiceProfileError(f"{voice_id} is not in the voice catalog.")
    for column, value in columns.items():
        setattr(profile, column, value)
    profile.voices = {**profile.voices, voice.provider_id: voice.id}
    profile.updated_at = utcnow()
    session.add(profile)
    if voice.provider_id == setup.tts_provider:
        on = speaking_model(voice.id, model or setup.tts_model)
        if on and on != setup.tts_model:
            setup.tts_model, setup.updated_at = on, utcnow()
            session.add(setup)
    await session.commit()
    return profile, setup


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


def apply(
    profile: VoiceProfile | None,
    settings: Any,
    service: Any,
    setup: CallSetup | None = None,
) -> None:
    """Put ``profile`` (and ``setup``, where given) onto the running
    ``settings``, and drop the speech services ``service`` built from the
    old values."""
    for key, value in setting_values(profile, setup).items():
        setattr(settings, key, value)
    _speaking(settings)
    service._stt_service = None
    service._tts_service = None


async def active_settings(session: AsyncSession, settings: Any) -> Any:
    """``settings`` in the active voice, on the call setup: what anything
    headless (a worker, the CLI) speaks and hears with, as only the
    webserver applies them at startup (``load_active``). The saved
    pronunciations come with the voice, as they do there."""
    await pronunciations.load(session)
    active = await active_profile(session)
    if active is None:
        return settings
    return settings_for(active, settings, await queries.call_setup(session))


async def seeded_active(session: AsyncSession, settings: Any) -> VoiceProfile:
    """The active profile, a first one seeded from ``settings`` (``.env``)
    when there is none yet."""
    if (active := await active_profile(session)) is not None:
        return active
    await _seeded_profile(session, settings)
    return await active_profile(session)  # type: ignore[return-value]


async def load_active(
    session: AsyncSession, settings: Any, service: Any
) -> VoiceProfile | None:
    """At startup: seed the call setup and a first profile from .env where
    there are none, then run on them, saying terms the saved way. After the
    first boot the tables win over .env."""
    await pronunciations.load(session)
    setup = await seeded_setup(session, settings)
    active = await seeded_active(session, settings)
    apply(active, settings, service, setup)
    return active
