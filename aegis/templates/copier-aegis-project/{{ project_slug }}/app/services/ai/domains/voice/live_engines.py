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

from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.log import logger
from app.core.voice_settings import setting_default
from app.services.ai.domains.voice import queries
from app.services.ai.models.voice import LiveEngine

DEFAULT = setting_default("VOICE_LIVE_ENGINE")
# The vendors whose realtime models a call can reach through Pydantic AI.
CALL_VENDORS = frozenset({"openai", "google"})

# How a call talks: the section that leads the voice agent's prompt on a
# call. Everything else in that prompt still applies.
LIVE_CALL_INSTRUCTIONS = """\
## THIS IS A LIVE VOICE CALL

You are talking with them out loud, in real time. Everything below still \
applies - your role, your tools, how you work - except how you answer, \
which this section decides:

- One or two short sentences a reply. Lead with the answer.
- Never read out a list, a table or markdown. Round figures the way a \
person would say them, and say dates the way a person would.
- If there is more, say you can tell them more and let them ask.
- Before you look something up, say a few words ("Let me check") so there \
is no silence.
- When they are done - a goodbye, "that's all", thanks with nothing more \
to ask - say a short goodbye, then call end_call and say nothing more."""

# A realtime reply's hard cap. Output tokens include the speech's audio
# (about 1,200 a minute) and any script the assistant writes, so this is a
# backstop against a monologue, not the brevity itself - the instructions
# are that.
REPLY_CAP = 1_200

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


def is_gpt_live(model: str) -> bool:
    """GPT-Live, by its id bare ("gpt-live-1") or as Pydantic AI names it
    ("openai:gpt-live-1"): its own session settings."""
    return model.rpartition(":")[2].startswith("gpt-live")


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


async def choose(session: AsyncSession, model_id: str) -> LiveEngine | None:
    """The engine for a catalog model picked for calls, offered again if it
    was turned off, or made on the spot with the seeded call instructions
    and reply cap, to be tuned on its row afterwards. None when the
    catalog lacks the model or no call can reach its vendor."""
    engine = await queries.engine_for_model(session, model_id)
    if engine is None:
        found = await queries.model_vendor(session, model_id)
        if found is None or found[1] not in CALL_VENDORS:
            return None
        engine = LiveEngine(
            key=model_id,
            llm_id=found[0],
            instructions=LIVE_CALL_INSTRUCTIONS,
            max_output_tokens=None if is_gpt_live(model_id) else REPLY_CAP,
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
