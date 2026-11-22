"""What a live call is made of, as the voice dialog shows it.

A realtime model hears and speaks by itself. A local chat model is a chain
(``cascade``): the active voice's STT hears the caller, the model thinks,
and the voice's TTS speaks. This names each part, says where it runs, and
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


def _models(voice: VoiceProfile | None, settings: Any) -> dict[str, str]:
    """The voice's STT and TTS models and providers, the running defaults
    where it leaves one unset."""
    config = get_current_voice_config(settings)
    return {
        key: str(getattr(voice, key, None) or config[key])
        for key in ("stt_model", "stt_provider", "tts_model", "tts_provider")
    }


def _local(providers: list[Any], provider_id: str) -> bool:
    return any(p.id == provider_id and p.is_local for p in providers)


def hears(voice: VoiceProfile | None, settings: Any) -> Part:
    """What hears the caller: the voice's STT."""
    used = _models(voice, settings)
    found = get_stt_model(used["stt_model"])
    return Part(
        found.name if found else used["stt_model"],
        local=_local(get_stt_providers(), used["stt_provider"]),
        model=used["stt_model"],
    )


def speaks(voice: VoiceProfile | None, settings: Any) -> Part:
    """What speaks the answer: the voice's TTS, in the voice."""
    used = _models(voice, settings)
    found = get_tts_model(used["tts_model"])
    name = found.name if found else used["tts_model"]
    speed = getattr(voice, "tts_speed", 1.0) or 1.0
    return Part(
        f"{name} · {voice.name}" if voice else name,
        local=_local(get_tts_providers(), used["tts_provider"]),
        note=f"{speed:g}×" if speed != 1 else "",
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
    used = _models(voice, settings)
    heard, said = hears(voice, settings), speaks(voice, settings)
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
