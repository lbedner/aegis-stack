"""What a live call is made of, as the voice dialog shows it.

A realtime model hears and speaks by itself. A local chat model is a chain
(``cascade``): the call setup's STT hears the caller, the model thinks,
and its TTS speaks in the active voice. This names each part, says where it runs, and
adds the call up a minute at a time, so the dialog says what was picked
rather than leaving it in fine print.
"""

from dataclasses import dataclass
from typing import Any

from app.core.model_picker import format_per_minute
from app.services.ai.domains.spend import calls
from app.services.ai.domains.spend.recording import speech_cost
from app.services.ai.domains.voice.catalog import (
    get_current_voice_config,
    get_stt_model,
    get_stt_providers,
    get_tts_model,
    get_tts_providers,
    voice_name,
)
from app.services.ai.models import AIProvider
from app.services.ai.models.provider_names import provider_label
from app.services.ai.models.voice import VoiceProfile

# ponytail: about 150 spoken words a minute; a voice priced by the
# character is costed at it. Measure it from calls if that drifts.
CHARS_PER_MINUTE = 900


@dataclass(frozen=True)
class Part:
    """One part of a call: what it is, whether it runs on this machine, a
    note (a voice's speed), and the model's id."""

    name: str
    local: bool
    note: str = ""
    model: str = ""


@dataclass(frozen=True)
class Summary:
    """The line under the parts: where the call runs, what it costs, how
    long a caller waits for the first word."""

    where: str
    local: bool
    cost: str
    wait: str


def _models(settings: Any) -> dict[str, str]:
    """The call setup's STT and TTS models and providers, as running."""
    config = get_current_voice_config(settings)
    return {
        key: str(config[key])
        for key in ("stt_model", "stt_provider", "tts_model", "tts_provider")
    }


def unvoiced(voice: VoiceProfile, provider_id: str) -> str:
    """What a voice with none of its own on ``provider_id`` says: the
    provider's default speaks instead, and that is not her."""
    found = next((p for p in get_tts_providers() if p.id == provider_id), None)
    return f"{voice.name} has no {found.name if found else provider_id} voice yet"


def speaking(
    voice: VoiceProfile, settings: Any, model: str | None = None
) -> dict[str, Any]:
    """What of her a call takes: her voice on what speaks it (a realtime
    ``model``, else the setup's TTS), a note where she has none there
    (``voiced`` False), and her style and speed where it takes them.
    Every engine takes her style; speed, OpenAI's realtime models (not
    GPT-Live) and a chain's TTS (``realtime_calls``)."""
    from app.services.ai.domains.voice import live_engines

    if model:
        provider = by.value if (by := live_engines.voiced_by(model)) else None
        said = live_engines.call_voice(model, voice.voices)
        paced = model.startswith("openai:") and not live_engines.is_gpt_live(model)
    else:
        provider = _models(settings)["tts_provider"]
        said = voice.voices.get(provider)
        paced = True
    takes = ["her style"] if voice.tts_instructions else []
    if paced:
        takes.append(f"{voice.tts_speed:g}×")
    if said or provider is None:
        return {
            "said": voice_name(said) if said else "its own voice",
            "voiced": True,
            "takes": takes,
        }
    return {"said": unvoiced(voice, provider), "voiced": False, "takes": takes}


def speaks_as(model: str, voice: VoiceProfile | None) -> str:
    """What a realtime ``model`` speaks in, as one line (``speaking``)."""
    if voice is None:
        return "speaks in its own voice"
    line = speaking(voice, None, model)
    return f"speaks as {line['said']}" if line["voiced"] else line["said"]


def _local(providers: list[Any], provider_id: str) -> bool:
    return any(p.id == provider_id and p.is_local for p in providers)


def hears(settings: Any) -> Part:
    """What hears the caller: the call setup's STT."""
    used = _models(settings)
    found = get_stt_model(used["stt_model"])
    return Part(
        found.name if found else used["stt_model"],
        local=_local(get_stt_providers(), used["stt_provider"]),
        model=used["stt_model"],
    )


def speaks(voice: VoiceProfile | None, settings: Any) -> Part:
    """What speaks the answer: the call setup's TTS, in the voice's own
    voice for it (a note when she has none there)."""
    used = _models(settings)
    found = get_tts_model(used["tts_model"])
    name = found.name if found else used["tts_model"]
    speed = getattr(voice, "tts_speed", 1.0) or 1.0
    provider = used["tts_provider"]
    note = f"{speed:g}×" if speed != 1 else ""
    if voice is not None and provider not in voice.voices:
        note = unvoiced(voice, provider)
    return Part(
        f"{name} · {voice.name}" if voice else name,
        local=_local(get_tts_providers(), provider),
        note=note,
        model=used["tts_model"],
    )


def waited(wait_ms: int | None) -> str:
    """How long a caller waits for the first word, as measured."""
    if wait_ms is None:
        return "no calls timed yet"
    return f"about {wait_ms / 1000:.1f}s to first word"


async def chain_summary(
    voice: VoiceProfile | None,
    settings: Any,
    *,
    thinks_local: bool,
    wait_ms: int | None,
) -> Summary:
    """A chain call's line: every part added up. A minute of call hears at
    most a minute and says at most a minute, so speech is costed at both
    (an upper bound); a cloud part the catalog does not price makes the
    whole unknown, not cheaper."""
    used = _models(settings)
    heard, said = hears(settings), speaks(voice, settings)
    cloud = [
        verb for verb, part in (("hears", heard), ("speaks", said)) if not part.local
    ]
    if not thinks_local:
        cloud.insert(1, "thinks")
    local = not cloud
    costs = [
        await speech_cost(used["stt_model"], input_seconds=60)
        if not heard.local
        else 0,
        await speech_cost(
            used["tts_model"], output_seconds=60, characters=CHARS_PER_MINUTE
        )
        if not said.local
        else 0,
    ]
    if local:
        cost = "free"
    elif not thinks_local or any(
        c == 0 for c, part in zip(costs, (heard, said), strict=True) if not part.local
    ):
        cost = "price unknown"
    else:
        cost = f"up to {format_per_minute(sum(costs))}"
    where = (
        "Runs entirely on this machine"
        if local
        else f"{' and '.join(cloud).capitalize()} in the cloud"
    )
    return Summary(where, local, cost, waited(wait_ms))


async def one_summary(model_id: str, vendor: str, *, wait_ms: int | None) -> Summary:
    """A realtime model's line: it is the whole call, at its own rate."""
    rate = calls.per_second(await calls.realtime_price(model_id))
    cost = format_per_minute(rate * 60) if rate else "priced by its tokens"
    where = f"Runs in the cloud ({provider_label(AIProvider(vendor))})"
    return Summary(where, False, cost, waited(wait_ms))
