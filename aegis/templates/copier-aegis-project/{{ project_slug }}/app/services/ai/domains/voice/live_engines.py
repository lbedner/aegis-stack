"""Live engines, as table data.

A live call runs on an engine (``models/voice/live_engine.py``): a catalog
model and how the assistant uses it on a call. Every engine is a Pydantic
AI realtime model that IS the brain - the voice agent's prompt, tools and
code mode - and every call takes the one path (``realtime_calls``): the
app's server holds the provider session and carries the audio over its
own WebSocket. The defaults below are seeded when missing; a seeded row is
the app's, and an edit is never overwritten.
"""

from __future__ import annotations

import hashlib
import statistics
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.log import logger
from app.core.voice_settings import setting_default
from app.services.ai.domains.llm.queries import price_for_model
from app.services.ai.domains.spend import calls
from app.services.ai.domains.voice import queries
from app.services.ai.domains.voice.catalog import GEMINI_PREBUILT
from app.services.ai.domains.voice.models import TTS_ORGS, TTSProvider
from app.services.ai.models.provider_names import LOCAL_PROVIDERS
from app.services.ai.models.voice import LiveEngine

DEFAULT = setting_default("VOICE_LIVE_ENGINE")
# The vendors whose realtime models a call can reach through Pydantic AI.
CALL_VENDORS = frozenset({"openai", "google"})
# The speaking provider whose voices each realtime vendor speaks.
VOICED_BY = {org: provider for provider, org in TTS_ORGS.items()}

# How a call talks: the section that leads the voice agent's prompt on a
# call. Everything else in that prompt still applies.
LIVE_CALL_INSTRUCTIONS = """\
## THIS IS A LIVE VOICE CALL

You are talking with them out loud, in real time. Everything below still \
applies - your role, your tools, how you work - except how you answer, \
which this section decides:

- They can see the screen, and you can draw on it: draw_card shows a \
chart, a flow or how a part is wired under the call while you talk. When a \
typed answer would get a card, call it here too, in the same script as the \
lookup it draws, before you speak, so it is up as you start to explain; \
then say what it means, naming its parts as the card titles them, never \
what the card looks like. Never say you cannot show a chart.
- Lead with the answer, then give as much as the question needs. A quick \
question gets a sentence or two. A question about how or why something \
works gets a real explanation, the way you would explain it to a colleague: \
walk it through end to end in one reply, with the reasons, not one step a \
turn waiting to be asked for the next. Never offer to tell them more or ask \
whether they want the details: if more would help, look it up and say it.
- Never read out a list, a table or markdown. Round figures the way a \
person would say them, and say dates the way a person would.
- When they ask about anything your tools can answer - their numbers, a \
breakdown by country or source, how a part works, what depends on what - \
call your tools before answering, and when the first answer raises the next \
question, look that up too. Never fill it in from general knowledge.
- Do not announce that you are looking something up: they hear you \
working while your tools run.
- They are calling about this app and their own data. A word that does \
not fit is most likely a part of it misheard: take the nearest one, or ask. \
If you did not catch what they said, ask them to say it again. Never agree \
with something you did not hear.
- When they are done - a goodbye, "that's all", thanks with nothing more \
to ask - say a short goodbye, then call end_call and say nothing more."""

# A realtime reply's hard cap. Output tokens include the speech's audio
# (about 1,200 a minute) and any script the assistant writes, so this is a
# backstop against a runaway monologue - about two minutes - not the
# length itself: the instructions are that, and a walk-through runs long.
REPLY_CAP = 2_400

# GPT-Live's voice speaks for itself and hands the work to its backend: the
# manners replace its default, which is what says when to.
LIVE_HANDS_OFF = (
    "When they ask for something you cannot answer from this conversation "
    "alone, or for anything to be shown, drawn or changed (a table, a "
    "chart, a category), delegate it: you can only talk. Never say you "
    "will do something you have not delegated."
)

# Every default LIVE_CALL_INSTRUCTIONS has had, by digest: an engine still
# holding one was never edited, so it takes the current default. Add the
# old one here whenever the default changes.
FORMER_DEFAULTS = frozenset(
    {
        "0cd96842a556cdcdad725d0aaa26f15789dafea55931f1d325c03a9d3bc8f9a5",
        "a146cd9f48ccb02cc3511d8fdb24b256d9a5af71832746796d6661b2edbc9a8c",
        "6e99d34920873a2119da1b68e28435ab47bea1770ae7319b897b41bdd8b01014",
    }
)

# The engines a fresh app offers, by catalog model id.
ENGINE_SEEDS: tuple[dict[str, Any], ...] = (
    {
        "key": "gemini-live",
        "model": "gemini-3.8-live",
        "note": "turn-taking, the agent's own brain; billed by its tokens",
        "instructions": LIVE_CALL_INSTRUCTIONS,
        "max_output_tokens": REPLY_CAP,
        "sort_order": 0,
    },
    {
        "key": "gpt-realtime-2.1",
        "model": "gpt-realtime-2.1",
        "note": "turn-taking, the agent's own brain; billed by its tokens",
        "instructions": LIVE_CALL_INSTRUCTIONS,
        "max_output_tokens": REPLY_CAP,
        "sort_order": 1,
    },
    {
        "key": "gpt-realtime-2.1-mini",
        "model": "gpt-realtime-2.1-mini",
        "note": "turn-taking, cheapest",
        "instructions": LIVE_CALL_INSTRUCTIONS,
        "max_output_tokens": REPLY_CAP,
        "sort_order": 2,
    },
    {
        "key": "gpt-live",
        "model": "gpt-live-1",
        "note": "full duplex; billed by the minute",
        "instructions": LIVE_CALL_INSTRUCTIONS,
        "sort_order": 3,
    },
)

enabled = queries.enabled_engines


def split_model(model: str) -> tuple[str, str]:
    """A Pydantic AI model string's provider prefix and the model's own id
    (``realtime_model`` joins them). The prefix ends at the first colon: a
    local model's id has its own ("llamacpp:qwen3.8:27b"). No prefix, ""."""
    provider, colon, bare = model.partition(":")
    return (provider, bare) if colon else ("", model)


def reachable(vendor: str, mode: str, model_id: str, tools: bool | None = None) -> bool:
    """Whether a call can run on this catalog model: a realtime model of a
    vendor the call path serves, by the vendor's own id (the catalog's
    routed copies, "gemini/...", are not reachable), or any chat model,
    local or cloud, that can call the agent's tools, which a call runs as
    a chain (``chained``). Unknown is let through on a local engine, which
    may not say; the cloud catalog says."""
    if mode == "realtime":
        return vendor in CALL_VENDORS and "/" not in model_id
    said = tools if tools is not None else vendor in LOCAL_PROVIDERS
    return mode == "chat" and said


def reply_cap(engine: LiveEngine) -> int | None:
    """One reply's token cap. A realtime model's is its engine's: a
    backstop sized for its speech's audio tokens. A chain's reply is text
    and its model's thinking, so its cap is what the catalog says the
    model can write (its serving org's deployment); none where the
    catalog does not say. A realtime seed's 1200 left GPT-6 Luna no room
    to think, and it said nothing (2026-11-22)."""
    if not chained(engine):
        return engine.max_output_tokens
    deployment = engine.llm.serving_deployment
    return deployment.output_max_tokens if deployment else None


def chained(engine: LiveEngine) -> bool:
    """Whether a call on ``engine`` runs as the app's own chain (hear,
    think, speak: ``cascade``): its model is a chat model, with no
    realtime API of its own."""
    return engine.llm.mode != "realtime"


def voiced_by(model: str) -> TTSProvider | None:
    """The speaking provider whose voices a realtime ``model`` speaks;
    None for a vendor with none to pick."""
    return VOICED_BY.get(model.partition(":")[0])


def call_voice(model: str, voices: dict[str, str]) -> str | None:
    """The voice a call on realtime ``model`` speaks: the voice's own for
    the vendor's provider (``voices``, ``VoiceProfile.voices``), else None:
    the model's own default. Gemini Live speaks only its 30 prebuilt
    voices, not its library's others."""
    by = voiced_by(model)
    voice = voices.get(by.value) if by else None
    if by == TTSProvider.GEMINI and voice not in GEMINI_PREBUILT:
        return None
    return voice


def is_gpt_live(model: str) -> bool:
    """GPT-Live, by its id bare ("gpt-live-1") or as Pydantic AI names it
    ("openai:gpt-live-1"): its own session settings."""
    return split_model(model)[1].startswith("gpt-live")


def pick(engines: list[LiveEngine], key: str | None) -> LiveEngine | None:
    """The engine ``key`` names among ``engines``, else the default."""
    keyed = {engine.key: engine for engine in engines}
    return keyed.get(key or DEFAULT) or keyed.get(DEFAULT)


async def resolve(session: AsyncSession, key: str | None) -> LiveEngine | None:
    """The enabled engine ``key`` names, or the default when it is gone or
    off."""
    return pick(await enabled(session), key)


def realtime_model(engine: LiveEngine) -> str:
    """The Pydantic AI model string: the serving org, then the model."""
    # ponytail: the catalog org slug doubles as Pydantic AI's provider
    # prefix ("openai"); a provider whose names differ needs a mapping.
    return f"{engine.llm.served_by.slug}:{engine.llm.model_id}"


async def per_second(session: AsyncSession, engine: LiveEngine) -> float | None:
    """USD a second when the engine's model bills its call by time (the
    catalog's per-minute price); None when its tokens price it."""
    return calls.per_second(await price_for_model(session, engine.llm.model_id))


async def choose(session: AsyncSession, model_id: str) -> LiveEngine | None:
    """The engine for a catalog model picked for calls, offered again if it
    was turned off, or made on the spot with the seeded call instructions
    and reply cap, to be tuned on its row afterwards. None when the
    catalog lacks the model or no call can reach it (``reachable``)."""
    engine = await queries.engine_for_model(session, model_id)
    if engine is None:
        found = await queries.model_vendor(session, model_id)
        if found is None:
            return None
        llm_id, vendor, mode, tools = found
        if not reachable(vendor, mode, model_id, tools):
            return None
        engine = LiveEngine(
            key=model_id,
            llm_id=llm_id,
            instructions=LIVE_CALL_INSTRUCTIONS,
            # A chain's reply cap is its model's (``reply_cap``).
            max_output_tokens=REPLY_CAP
            if mode == "realtime" and not is_gpt_live(model_id)
            else None,
            sort_order=len(ENGINE_SEEDS),
        )
    engine.is_enabled = True
    session.add(engine)
    await session.commit()
    return engine


async def seed_missing(
    session: AsyncSession, seeds: tuple[dict[str, Any], ...] = ENGINE_SEEDS
) -> int:
    """Insert the engines not yet in the table; never touch one that is.
    A seed names its model by catalog id; one the catalog lacks is skipped
    until a sync brings it. Returns how many were added."""
    have = await queries.engine_keys(session)
    wanted = [seed for seed in seeds if seed["key"] not in have]
    if not wanted:
        return 0
    ids = await queries.catalog_ids(session, [seed["model"] for seed in wanted])
    added = []
    for seed in wanted:
        if seed["model"] not in ids:
            logger.warning(
                "Live engine's model is not in the catalog yet",
                engine=seed["key"],
                model=seed["model"],
            )
            continue
        values = {k: v for k, v in seed.items() if k != "model"}
        added.append(LiveEngine(llm_id=ids[seed["model"]], **values))
    session.add_all(added)
    if added:
        await session.commit()
    return len(added)


def digest(instructions: str) -> str:
    return hashlib.sha256(instructions.encode()).hexdigest()


async def refresh_defaults(session: AsyncSession) -> int:
    """Hand the current instructions to each engine still holding a former
    default; an edited engine keeps its own. Returns how many changed."""
    stale = [
        engine
        for engine in await queries.all_engines(session)
        if engine.instructions and digest(engine.instructions) in FORMER_DEFAULTS
    ]
    for engine in stale:
        engine.instructions = LIVE_CALL_INSTRUCTIONS
    session.add_all(stale)
    if stale:
        await session.commit()
    return len(stale)


# How many recent turns a model's wait is the median of.
WAITS = 20


async def first_word_ms(session: AsyncSession, model_id: str) -> int | None:
    """The median wait for the first word back on a call on ``model_id``,
    over its last timed turns (``WAITS``); None before any."""
    waits = await queries.first_word_waits(session, model_id, WAITS)
    return round(statistics.median(waits)) if waits else None
