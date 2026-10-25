"""The voice designer: a profile's voice picked by who it sounds like
(gender, tone and accent filter the catalog's voices) and how it says
things (a premade style, then each dial and anything extra: ``delivery``),
heard unsaved (``design_settings``) and saved onto the profile
(``save_design``), the choices kept so it opens on them again.

``design_view`` is the one home of what an editor shows: both Overseers
draw it as it comes, the voices already narrowed and the design already
the form fields the server reads back (``parse_design``).

Needs a database, as voice profiles do.
"""

from collections.abc import Mapping
from typing import Any, Self

from pydantic import ValidationError, model_validator
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings as app_settings
from app.core.voice_settings import TTS_SPEED_MAX, TTS_SPEED_MIN
from app.services.ai.domains.voice import profiles
from app.services.ai.domains.voice.catalog import (
    get_tts_models,
    get_tts_providers,
    get_tts_voices,
    get_voice,
    speaking_model,
    speeds,
    steers,
)
from app.services.ai.domains.voice.delivery import (
    DIALS,
    STYLES,
    Delivery,
    compose,
    tuned,
)
from app.services.ai.domains.voice.library import gemini_library
from app.services.ai.domains.voice.models import (
    DEFAULT_TTS_VOICE,
    TTS_KEYS,
    TTSProvider,
)
from app.services.ai.domains.voice.overview import (
    Frozen,
    ProfileRef,
    detail,
    missing_from,
    provider_key,
    read_keys,
)
from app.services.ai.models.voice import VoiceProfile

SPEED_RANGE = (TTS_SPEED_MIN, TTS_SPEED_MAX)
# A profile's editor, in three steps: who it is, how it talks, a last look.
STEPS = {"voice": "Voice", "delivery": "Delivery", "review": "Review"}
# The Voice step's filters: each by the name it rides in the query as, and
# the voice's own field it narrows by.
FILTERS = {"gender": "gender", "family": "family", "accent_of": "accent"}
# One passage for every preview, so voices are compared on the same words:
# a figure, some bad news, and a question.
PREVIEW_TEXT = (
    "Here's where things stand. Three items came in since yesterday, and "
    "two of them are done. Heads up, though: one is already four days "
    "overdue. Want me to walk you through it?"
)


class Design(Frozen):
    """What the designer saves: the voice, the model it is spoken on (one
    that speaks it, else the voice's own default), how it says things, its
    speed. It checks itself, so a save over the API refuses what the form
    does."""

    voice: str
    model: str | None = None
    delivery: Delivery
    speed: float = 1.0

    @model_validator(mode="after")
    def _on_offer(self) -> Self:
        if get_voice(self.voice) is None:
            raise ValueError("Pick a voice from the list.")
        low, high = SPEED_RANGE
        if not low <= self.speed <= high:
            raise ValueError(f"Speed is a number from {low} to {high}.")
        return self


# The handful of tone families the designer narrows by, each the words
# providers use for it.
TONE_FAMILIES: dict[str, tuple[str, frozenset[str]]] = {
    "warm": (
        "Warm and soft",
        frozenset(
            {"Warm", "Soft", "Gentle", "Breathy", "Smooth", "Easy-going", "Friendly",
             "Casual", "Breezy"}
        ),
    ),
    "bright": (
        "Bright and upbeat",
        frozenset({"Bright", "Upbeat", "Lively", "Excitable", "Youthful", "Forward"}),
    ),
    "calm": ("Calm and even", frozenset({"Calm", "Even", "Clear", "Mature"})),
    "firm": (
        "Firm and authoritative",
        frozenset({"Firm", "Informative", "Knowledgeable", "Gravelly"}),
    ),
    "expressive": ("Expressive", frozenset({"Expressive"})),
}  # fmt: skip


def family_of(tone: str) -> str | None:
    """The family a provider's tone word falls in."""
    return next(
        (key for key, (_, tones) in TONE_FAMILIES.items() if tone in tones), None
    )


class VoiceChoice(Frozen):
    """A voice as the designer offers it: who it sounds like (``detail``,
    as a line), and the tone family it falls in."""

    id: str
    name: str
    provider_name: str
    gender: str
    tone: str
    family: str | None
    accent: str | None = None
    detail: str


class ModelChoice(Frozen):
    """A model the chosen voice is spoken on, and whether it follows
    delivery instructions (the style and fine-tuning do nothing without)."""

    id: str
    note: str
    instructions: bool


class LockedProvider(Frozen):
    """A provider whose voices cannot be heard: its key is missing."""

    provider_name: str
    voices: int
    key: str


class StyleChoice(Frozen):
    """A style as offered (Plain, no style, among them): its name, what it
    sounds like, and where it sets the dials."""

    label: str
    sounds: str
    dials: dict[str, str] = {}


# No style: the dials alone.
PLAIN = StyleChoice(label="Plain", sounds="No style; just the dials")


class ProfileSummary(Frozen):
    """A profile at a glance: its voice, its style, its speed, in use."""

    id: int
    name: str
    voice: str
    style: str
    speed: float
    active: bool


class DesignView(Frozen):
    """An editor as it is drawn: the profile; the Voice step's filters,
    their choices and the voices they keep (``cards``, the chosen one
    first), with the providers locked out; the styles and the dials the
    model takes; what is picked, what it makes, and the design as the form
    fields the server reads back (``form``)."""

    profile: ProfileRef
    active: bool
    steps: dict[str, str]
    chosen: VoiceChoice | None
    cards: list[VoiceChoice]
    locked: list[LockedProvider]
    # Each filter's choices, by value and as labeled.
    genders: dict[str, str]
    families: dict[str, str]
    accents: dict[str, str]
    filters: dict[str, str]
    styles: dict[str, StyleChoice]
    # Each dial's choices, by value and as labeled; accent only where the
    # model steers it (else it comes with the voice: ``steers_accent``).
    dials: dict[str, dict[str, str]]
    steers_accent: bool
    voice: str
    model: str
    models: list[ModelChoice]
    # Whether the model follows delivery instructions at all.
    follows: bool
    delivery: Delivery
    speed: float
    # The speeds the model takes; None when it has no speed (Gemini).
    speed_range: tuple[float, float] | None
    # Whether Fine-tune holds a pick, so the editor opens it.
    tuned: bool
    instructions: str
    form: dict[str, str]


async def _voices(chosen: str) -> tuple[list[VoiceChoice], list[LockedProvider]]:
    """The voices that can be heard (and the chosen one, whatever), and
    each provider locked out by its missing key."""
    providers = get_tts_providers()
    found = await read_keys(*(provider_key(p) for p in providers))
    if gemini := found.get(TTS_KEYS[TTSProvider.GEMINI]):
        await gemini_library(gemini)
    voices: list[VoiceChoice] = []
    locked: list[LockedProvider] = []
    for provider in providers:
        theirs = get_tts_voices(provider.id)
        key = provider_key(provider)
        if key and missing_from(key, found):
            locked.append(
                LockedProvider(provider_name=provider.name, voices=len(theirs), key=key)
            )
            theirs = [v for v in theirs if v.id == chosen]
        voices += [
            VoiceChoice(
                id=v.id,
                name=v.name,
                provider_name=provider.name,
                gender=v.gender or "neutral",
                tone=v.tone or "",
                family=family_of(v.tone or ""),
                accent=v.accent,
                detail=detail(v.tone, v.gender, v.accent, provider.name),
            )
            for v in theirs
        ]
    return voices, locked


def _fit(speed: float, model: str) -> float:
    """``speed`` within what ``model`` takes (as it would be spoken)."""
    span = speeds(model)
    return min(max(speed, span[0]), span[1]) if span else speed


def _narrowed(
    voices: list[VoiceChoice], chosen: VoiceChoice | None, asked: Mapping[str, str]
) -> tuple[dict[str, str], list[VoiceChoice]]:
    """The filters (each the query's where it has one, Any among them, else
    the chosen voice's own) and the voices they keep, the chosen one always,
    and first."""
    filters = {
        name: asked[name] if name in asked else (getattr(chosen, field) or "")
        for name, field in FILTERS.items()
    }
    kept = [
        v
        for v in voices
        if v.id == (chosen.id if chosen else None)
        or all(
            filters[name] in ("", getattr(v, field) or "")
            for name, field in FILTERS.items()
        )
    ]
    return filters, sorted(kept, key=lambda v: chosen is None or v.id != chosen.id)


def _form(shown: Design, model: str, speed: float) -> dict[str, str]:
    """The design as the form fields ``parse_design`` reads back; the style
    it is drawn with also as ``was_style``, so a style just picked moves the
    dials and one kept leaves them as picked."""
    style = shown.delivery.style or ""
    fields = {
        "voice": shown.voice,
        "model": model,
        "speed": str(speed),
        "style": style,
        **{dial: getattr(shown.delivery, dial) for dial in DIALS},
        "extra": shown.delivery.extra or "",
        "was_style": style,
    }
    return {name: value for name, value in fields.items() if value}


async def design_view(
    db: AsyncSession,
    profile_id: int | None,
    picked: Design | None,
    filters: Mapping[str, str] | None = None,
) -> DesignView:
    """The designer on a profile, on ``picked`` (choices not yet saved)
    where given, else on what the profile has; the Voice step narrowed by
    the ``filters`` the query holds (``FILTERS``)."""
    profile = await _profile(db, profile_id)
    shown = picked or Design(
        voice=profile.tts_voice or DEFAULT_TTS_VOICE,
        model=profile.tts_model,
        delivery=Delivery(**(profile.tts_delivery or {})),
        speed=profile.tts_speed,
    )
    model = speaking_model(shown.voice, shown.model or profile.tts_model) or ""
    spoken, accent = get_voice(shown.voice), "accent" in steers(model)
    voices, locked = await _voices(shown.voice)
    chosen = next((v for v in voices if v.id == shown.voice), None)
    narrowed, cards = _narrowed(voices, chosen, filters or {})
    speed = _fit(shown.speed, model)
    return DesignView(
        profile=ProfileRef(id=profile.id, name=profile.name),  # type: ignore[arg-type]
        active=profile.is_active,
        steps=STEPS,
        chosen=chosen,
        cards=cards,
        locked=locked,
        genders={g: g.title() for g in sorted({v.gender for v in voices})},
        families={key: label for key, (label, _) in TONE_FAMILIES.items()},
        accents={a: a for a in sorted({v.accent for v in voices if v.accent})},
        filters=narrowed,
        styles={"": PLAIN}
        | {
            key: StyleChoice(
                label=s.label, sounds=f"{s.affect}; {s.tone.lower()}", dials=s.dials
            )
            for key, s in STYLES.items()
        },
        dials={
            dial: {choice: choice.title() for choice in choices}
            for dial, choices in DIALS.items()
            if dial != "accent" or accent
        },
        steers_accent=accent,
        voice=shown.voice,
        model=model,
        models=[
            ModelChoice(id=m.id, note=m.note, instructions=bool(m.steers))
            for m in get_tts_models()
            if spoken and m.id in spoken.model_ids
        ],
        follows=bool(steers(model)),
        delivery=shown.delivery,
        speed=speed,
        speed_range=speeds(model),
        tuned=tuned(shown.delivery),
        instructions=compose(shown.delivery, accent=accent),
        form=_form(shown, model, speed),
    )


def parse_design(form: Any) -> tuple[Design | None, list[str]]:
    """The designer's form as a design, and what is wrong with it. A style
    just picked (not the one the form was drawn with, ``was_style``) sets
    the dials to where it puts them; after that they are the form's."""
    form = dict(form)
    style = str(form.get("style") or "")
    if style in STYLES and style != form.get("was_style"):
        form |= STYLES[style].dials
    errors: list[str] = []
    try:
        delivery = Delivery(
            style=style or None,
            **{
                dial: str(form.get(dial) or Delivery.model_fields[dial].default)
                for dial in DIALS
            },
            extra=str(form.get("extra") or "").strip() or None,
        )
    except ValidationError as exc:
        errors += _said(exc)
        delivery = None
    try:
        speed = float(str(form.get("speed") or 1.0))
    except ValueError:
        speed = -1.0  # refused below, as any speed out of range is
    try:
        picked = Design(
            voice=str(form.get("voice") or ""),
            model=str(form.get("model") or "") or None,
            delivery=delivery or Delivery(),
            speed=speed,
        )
    except ValidationError as exc:
        errors += _said(exc)
    return (None, errors) if errors else (picked, [])


def _said(exc: ValidationError) -> list[str]:
    """A refusal's messages, as the form shows them."""
    return [e["msg"].removeprefix("Value error, ") for e in exc.errors()]


def _columns(picked: Design, model: str | None) -> dict[str, Any]:
    """The profile's columns a design sets: the voice, its provider and a
    model that speaks it, the speed it takes, the choices and the text they
    make."""
    voice = get_voice(picked.voice)
    spoken_on = speaking_model(picked.voice, picked.model or model) or ""
    return {
        "tts_voice": picked.voice,
        "tts_provider": voice.provider_id if voice else None,
        "tts_model": spoken_on or None,
        "tts_speed": _fit(picked.speed, spoken_on),
        "tts_delivery": picked.delivery.model_dump(),
        "tts_instructions": compose(
            picked.delivery, accent="accent" in steers(spoken_on)
        ),
    }


async def _profile(db: AsyncSession, profile_id: int | None) -> VoiceProfile:
    """The profile asked for, else the active one (seeded from ``.env``
    when there is none yet)."""
    if profile_id is not None and (found := await db.get(VoiceProfile, profile_id)):
        return found
    return await profiles.seeded_active(db, app_settings)


async def save_design(
    db: AsyncSession, profile_id: int | None, picked: Design, service: Any
) -> VoiceProfile:
    """``picked`` on the profile, in use at once when it is the active one
    (``service`` drops the speech services built from the old values)."""
    profile = await _profile(db, profile_id)
    saved = await profiles.update(db, profile.id, **_columns(picked, profile.tts_model))  # type: ignore[arg-type]
    if saved.is_active:
        profiles.apply(saved, app_settings, service)
    return saved


def design_settings(picked: Design, settings: Any) -> Any:
    """``settings`` speaking as ``picked`` would, for hearing it unsaved."""
    columns = _columns(picked, settings.TTS_MODEL)
    return settings.model_copy(
        update={
            profiles.SETTINGS[column]: value
            for column, value in columns.items()
            if column in profiles.SETTINGS
        }
    )


async def profile_summaries(db: AsyncSession) -> list[ProfileSummary]:
    """Every profile at a glance, the active one first (the first seeded
    from ``.env`` when there is none yet)."""
    await profiles.seeded_active(db, app_settings)
    every = await profiles.list_profiles(db)
    return [
        ProfileSummary(
            id=p.id,  # type: ignore[arg-type]
            name=p.name,
            voice=(
                found.name
                if (found := get_voice(p.tts_voice or ""))
                else DEFAULT_TTS_VOICE.title()
            ),
            style=(
                STYLES[style].label
                if (style := (p.tts_delivery or {}).get("style")) in STYLES
                else PLAIN.label
            ),
            speed=p.tts_speed,
            active=p.is_active,
        )
        for p in sorted(every, key=lambda p: not p.is_active)
    ]


async def profile_voice(db: AsyncSession, profile_id: int, settings: Any) -> Any:
    """``settings`` in a saved profile's voice, whichever is in use; None
    for a profile there is not."""
    profile = await db.get(VoiceProfile, profile_id)
    return profiles.settings_for(profile, settings) if profile else None


async def make_profile(db: AsyncSession, name: str) -> VoiceProfile:
    """A new profile, from the active one (``VoiceProfileError`` for a
    name taken or missing)."""
    return await profiles.create(db, name=name)
