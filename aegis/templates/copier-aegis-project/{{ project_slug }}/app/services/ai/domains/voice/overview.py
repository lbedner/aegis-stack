"""The stack's voice at a glance, as both Overseers show it: what the
active profile uses (speaking, listening, calls), then every speech,
hearing and live model, then every voice, each with a voice and model to
hear it on (one that speaks it) and the change a Use would make.

``use_voice`` puts a row on the active profile, the rest made to fit;
``switch_voice`` makes another profile the active one. A stack keeping no
profiles (no database) shows what its settings use, and nothing to change.
"""

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict

from app.core import secrets
from app.core.config import settings
from app.core.discovery import optional
from app.core.model_picker import format_price

from .catalog import (
    get_current_voice_config,
    get_stt_models,
    get_stt_providers,
    get_tts_model,
    get_tts_models,
    get_tts_providers,
    get_tts_voices,
    get_voice,
    speaking_model,
)
from .library import gemini_library
from .models import DEFAULT_TTS_VOICES, TTS_KEYS, TTSProvider

if TYPE_CHECKING:
    # Only a stack with a database has it; a voice-only one does not.
    from sqlmodel.ext.asyncio.session import AsyncSession

Kind = Literal["use", "tts", "stt", "live", "voice"]
# Each row's kind, as a filter says it.
KINDS: dict[str, str] = {
    "use": "In use",
    "tts": "Speech",
    "stt": "Hearing",
    "live": "Live",
    "voice": "Voice",
}
# The catalog's kind (``LargeLanguageModel.mode``) for each model row's.
MODES = {"tts": "audio_speech", "stt": "audio_transcription", "live": "realtime"}
PROFILES = "app.services.ai.domains.voice.profiles"
LIVE = "app.services.ai.domains.voice.live_engines"
CATALOG = "app.services.ai.domains.llm.catalog"


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class VoiceRow(Frozen):
    """One row, in the page's columns: its kind (``label`` as shown: the
    role for what is in use), its provider, its name, what it is
    (``detail``), the model a voice plays on, its price per million; then
    the models it is spoken on (a filter's), the voice and model to hear it
    on, the change a Use makes, and whether the profile uses it."""

    kind: Kind
    label: str
    provider: str
    provider_name: str
    name: str
    detail: str = ""
    plays_on: str | None = None
    price: str | None = None
    models: list[str] = []
    sample: tuple[str, str] | None = None
    use: dict[str, str] | None = None
    used: bool = False
    # What it cannot speak or hear without (its provider's key, missing):
    # no sample and no Use then, as either would only fail.
    blocked: str | None = None


class ProfileRef(Frozen):
    id: int
    name: str


class VoiceOverview(Frozen):
    rows: list[VoiceRow]
    profiles: list[ProfileRef]
    active: int | None
    kinds: dict[str, str] = KINDS


async def read_keys(*keys: str | None) -> dict[str, str | None]:
    """Each key's value, read through ``app.core.secrets`` (``.env``, then
    the secrets store) in one store read; None where it is not set."""
    return await secrets.get_many(*{key for key in keys if key})


def missing_from(key: str | None, found: dict[str, str | None]) -> str | None:
    """``key`` named when ``found`` (``read_keys``) lacks it; None when set
    or none is needed."""
    return f"{key} missing" if key and not found.get(key) else None


def provider_key(provider: Any) -> str | None:
    """The key a speech or hearing provider needs; None for a local one."""
    return provider.api_key_env_var if provider.requires_api_key else None


def _vendor_key(slug: str) -> str | None:
    """The key a live engine's vendor (a catalog org's slug) is reached with."""
    from app.services.ai.models.providers import PROVIDERS, AIProvider

    try:
        return PROVIDERS[AIProvider(slug)].env_var
    except (ValueError, KeyError):
        return None


async def _prices() -> dict[str, Any]:
    """Each voice model's catalog row, by its id as the provider names it:
    one read per kind, none where the catalog is not kept."""
    catalog = optional(CATALOG)
    if catalog is None:
        return {}
    # One after another: on SQLite each session takes the write lock (BEGIN
    # IMMEDIATE), so reads at once fail as "database is locked".
    found = [
        m
        for mode in MODES.values()
        for m in await catalog.list_models(mode=mode, limit=500)
    ]
    return {m.model_id.rpartition("/")[2]: m for m in found}


def _price(row: Any) -> str | None:
    """A catalog price as per million in and out, as every model's is shown."""
    if row is None:
        return None
    return format_price(row.input_price, row.output_price) or None


def detail(*parts: Any) -> str:
    """What a row is, its set parts joined."""
    return " · ".join(str(p) for p in parts if p not in (None, ""))


class _Rows:
    """The rows as they are built: each named for its provider, its Use
    dropped where nothing can be changed (no profiles) or it is in use."""

    def __init__(
        self, missing: dict[str, str | None], prices: dict[str, Any], keeps: bool
    ) -> None:
        self.providers = {p.id: p for p in [*get_tts_providers(), *get_stt_providers()]}
        self.missing, self.prices, self.keeps = missing, prices, keeps
        self.rows: list[VoiceRow] = []

    def add(self, kind: Kind, provider: str, label: str, name: str, **row: Any) -> None:
        named = self.providers.get(provider)
        change = row.pop("use", None)
        shown = row.pop("provider_name", None) or (named.name if named else provider)
        blocked = self.missing.get(provider)
        if blocked:
            row["sample"] = None
        self.rows.append(
            VoiceRow(
                kind=kind,
                label=label,
                provider=provider,
                provider_name=shown,
                name=name,
                use=change
                if self.keeps and not row.get("used") and not blocked
                else None,
                blocked=blocked,
                **row,
            )
        )


def _in_use(
    rows: _Rows, config: dict[str, Any], used: Any, live: Any, engine: Any
) -> None:
    """Speaking, listening and, where a live engine is set up, calls."""
    tts, voice = config["tts_model"], config["tts_voice"]
    speaker, listener = config["tts_provider"], config["stt_provider"]
    rows.add(
        "use",
        speaker,
        "Speaking",
        tts,
        sample=(voice, tts),
        detail=detail(
            voice,
            f"speed {config['tts_speed']}",
            "delivery set" if used.TTS_INSTRUCTIONS else None,
        ),
    )
    rows.add(
        "use",
        listener,
        "Listening",
        config["stt_model"],
        detail=config.get("stt_language") or "language detected",
    )
    if engine is None:
        return
    from .realtime_calls import call_voice

    rows.add(
        "use",
        engine.llm.served_by.slug,
        "Calls",
        engine.key,
        provider_name=engine.llm.served_by.name,
        detail=detail(
            call_voice(live.realtime_model(engine), voice) or "its own voice",
            f"reply {used.VOICE_REPLY}",
            f"check in {used.VOICE_LIVE_IDLE_SECONDS}s",
        ),
    )


def _models(
    rows: _Rows, config: dict[str, Any], engines: list[Any], engine: Any
) -> None:
    """Every speech model (heard in the voice in use where it speaks it),
    hearing model and live engine."""
    tts, voice = config["tts_model"], config["tts_voice"]
    for m in get_tts_models():
        spoken = get_tts_voices(model_id=m.id)
        sample = voice if speaking_model(voice, m.id) == m.id else spoken[0].id
        rows.add(
            "tts",
            m.provider_id,
            KINDS["tts"],
            m.id,
            detail=detail(f"{len(spoken)} voices", m.quality),
            price=_price(rows.prices.get(m.id)),
            models=[m.id],
            sample=(sample, m.id),
            use={"tts_model": m.id},
            used=m.id == tts,
        )
    for m in get_stt_models():
        rows.add(
            "stt",
            m.provider_id,
            KINDS["stt"],
            m.id,
            detail=m.quality,
            price=_price(rows.prices.get(m.id)),
            models=[m.id],
            use={"stt_model": m.id},
            used=m.id == config["stt_model"],
        )
    for e in engines:
        rows.add(
            "live",
            e.llm.served_by.slug,
            KINDS["live"],
            e.key,
            provider_name=e.llm.served_by.name,
            detail=e.llm.model_id,
            price=_price(rows.prices.get(e.llm.model_id)),
            use={"live_engine": e.key},
            used=engine is not None and e.key == engine.key,
        )


def _voices(rows: _Rows, config: dict[str, Any]) -> None:
    """Every voice, heard on the model in use where it speaks it, else on
    one that does."""
    tts, voice = config["tts_model"], config["tts_voice"]
    for v in get_tts_voices():
        on = speaking_model(v.id, tts) or tts
        rows.add(
            "voice",
            v.provider_id,
            KINDS["voice"],
            v.name,
            detail=detail(v.description, v.gender),
            plays_on=on,
            models=v.model_ids,
            sample=(v.id, on),
            use={"tts_voice": v.id},
            used=v.id == voice,
        )


async def voice_overview(db: "AsyncSession | None") -> VoiceOverview:
    """Every row, as the saved profile has it (one applied in another
    worker is in use there too)."""
    # The catalog's prices first: it reads in a session of its own, and on
    # SQLite one waits for ``db``'s open transaction until it is done.
    prices = await _prices()
    profiles, live = optional(PROFILES), optional(LIVE)
    keeps = profiles is not None and db is not None
    every = await profiles.list_profiles(db) if keeps else []
    active = next((p for p in every if p.is_active), None)
    used = profiles.settings_for(active, settings) if active else settings
    engines = await live.enabled(db) if live is not None and db is not None else []
    engine = live.pick(engines, used.VOICE_LIVE_ENGINE) if engines else None
    config = get_current_voice_config(used)
    speech = [*get_tts_providers(), *get_stt_providers()]
    vendors = {e.llm.served_by.slug for e in engines}
    found = await read_keys(
        *(provider_key(p) for p in speech), *(_vendor_key(v) for v in vendors)
    )
    missing = {p.id: missing_from(provider_key(p), found) for p in speech}
    for vendor in vendors:
        missing.setdefault(vendor, missing_from(_vendor_key(vendor), found))
    if gemini := found.get(TTS_KEYS[TTSProvider.GEMINI]):
        await gemini_library(gemini)  # its voices are rows too
    rows = _Rows(missing, prices, keeps)
    _in_use(rows, config, used, live, engine)
    _models(rows, config, engines, engine)
    _voices(rows, config)
    return VoiceOverview(
        rows=rows.rows,
        profiles=[ProfileRef(id=p.id, name=p.name) for p in every],
        active=active.id if active else None,
    )


def _change(profile: Any, choice: dict[str, str]) -> dict[str, Any]:
    """A row's choice made to fit the profile: a voice brings its provider
    and a model that speaks it; a speech model keeps the voice when it
    speaks it, else takes its provider's; a hearing model brings its
    provider."""
    if voice := get_voice(choice.get("tts_voice", "")):
        return {
            "tts_voice": voice.id,
            "tts_provider": voice.provider_id,
            "tts_model": speaking_model(voice.id, profile.tts_model),
        }
    if model := get_tts_model(choice.get("tts_model", "")):
        provider = TTSProvider(model.provider_id)
        kept = speaking_model(profile.tts_voice or "", model.id) == model.id
        return {
            "tts_model": model.id,
            "tts_provider": provider.value,
            "tts_voice": profile.tts_voice if kept else DEFAULT_TTS_VOICES[provider],
        }
    heard = next((m for m in get_stt_models() if m.id == choice.get("stt_model")), None)
    if heard is not None:
        return {"stt_model": heard.id, "stt_provider": heard.provider_id}
    if engine := choice.get("live_engine"):
        return {"live_engine": engine}
    raise ValueError("Nothing in the voice catalog to use")


async def use_voice(db: "AsyncSession", choice: dict[str, str], service: Any) -> str:
    """``choice`` (a row's ``use``) on the active profile (seeded from
    ``.env`` when there is none yet), saved and applied at once (``service``
    drops the speech services built from the old values). What it uses now."""
    profiles = optional(PROFILES)
    profile = await profiles.seeded_active(db, settings)
    changes = _change(profile, choice)
    profile = await profiles.update(db, profile.id, **changes)
    profiles.apply(profile, settings, service)
    return ", ".join(str(v) for v in changes.values())


async def switch_voice(db: "AsyncSession", profile_id: int, service: Any) -> str:
    """The profile ``profile_id`` made the active one, applied at once."""
    profiles = optional(PROFILES)
    chosen = next(p for p in await profiles.activate(db, profile_id) if p.is_active)
    profiles.apply(chosen, settings, service)
    return chosen.name
