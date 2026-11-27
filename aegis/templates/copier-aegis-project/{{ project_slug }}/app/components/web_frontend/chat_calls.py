"""What a live call runs on, laid out as the parts it is made of, for the
voice dialog (``chat_voices``).

Two ways a call can run, picked first: one model that hears and speaks by
itself (a realtime model), or a chain, hear then think then speak (any
chat model that calls tools, local or cloud, between the call setup's
STT and TTS: ``cascade``). A chain
shows its three parts, each opening its own list below: Hears is the
setup's hearing model, Thinks the model calls run on, Speaks its speaking
model, in the active voice. Picking any of them changes the setup, never
the voice.
Each part is a card: its list opens from it (``slot``), and a pick closes
it again onto the card. Under them, what speaks her (``speaking``): on what
engine, in which of her voices, with what of her style and speed.
A line under them says where the call runs, what it costs and how long a
caller waits (``call_setup``). Every list is searched in one box: the
Thinks list holds every tool-calling model of every vendor with a key. The mode is the model's, not stored: picking
one of the other kind switches it.
"""

from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

from app.components.web_frontend import chat_models as models
from app.core.model_picker import (
    NO_MATCH,
    filter_models,
    is_local_model,
    newest_first,
    one_per_base,
)

ONE, CHAIN = "one", "chain"
MODES = {ONE: "One model", CHAIN: "Hear → think → speak"}
HEARS, THINKS, SPEAKS = "hears", "thinks", "speaks"
SLOTS = {HEARS: "Hears", THINKS: "Thinks", SPEAKS: "Speaks"}
# What a pick of each part does: its list's rows carry ``data-<verb>-model``
# and post to ``<verb>s`` (Thinks picks the model calls run on).
VERBS = {HEARS: "hear", THINKS: "call", SPEAKS: "speak"}
# What a row or a part shows of where it runs.
LOCAL = {"label": "Local", "tone": "ok"}
CLOUD = {"label": "Cloud", "tone": "warn"}
PICK = "Pick a model below"  # a part with no model yet
NO_LIVE = (
    "No live model can be reached: a call needs an OpenAI or Google key "
    "with a realtime model in the catalog."
)
NO_THINKER = (
    "No model here can call tools: add a cloud provider's key, or load a "
    "local model in the inference engine and sync the catalog "
    "(llm sync --source local)."
)
NO_RUNNABLE = "None of these can run here: add a provider's key, or start its server."


def where(local: bool) -> dict[str, str]:
    return LOCAL if local else CLOUD


def address(path: str, mode: str, slot: str | None = None) -> str:
    """The dialog opened on ``mode`` (and a chain's ``slot``)."""
    return f"{path}?{urlencode({'mode': mode, **({'slot': slot} if slot else {})})}"


async def view(
    db: Any,
    path: str,
    *,
    voice: Any | None,
    calling: Any | None,
    mode: str | None = None,
    slot: str | None = None,
    query: str = "",
) -> dict[str, Any]:
    """The dialog's call setup: the mode shown (``mode``, else the kind of
    model calls run on), its parts with the open one's list (``slot``;
    narrowed to ``query``), what speaks her, and the line that sums them
    up. ``calling`` is the model calls run on, ``voice`` the active
    profile. A list opens unasked only where nothing is picked yet."""
    from app.core.config import settings
    from app.services.ai.service import (
        call_setup,
        get_stt_models,
        get_stt_providers,
        get_tts_models,
        get_tts_providers,
        live_engines,
    )

    query = query.strip()
    # A dated snapshot and the id that follows the newest are one model.
    live = one_per_base(
        newest_first(await models.call_models()),
        keep=calling.model_id if calling else None,
    )
    on = next((m for m in live if calling and m["model_id"] == calling.model_id), None)
    mode = mode if mode in MODES else (CHAIN if on and on["kind"] == "cascade" else ONE)
    kind = "realtime" if mode == ONE else "cascade"
    shown = on if on and on["kind"] == kind else None
    wait = await live_engines.first_word_ms(db, shown["model_id"]) if shown else None
    # The one in use leads: the list is long, and it is what you check.
    live.sort(key=lambda m: m is not on)
    listed = [m for m in live if m["kind"] == kind]
    modes = [
        {"label": label, "url": address(path, key), "active": key == mode}
        for key, label in MODES.items()
    ]
    if mode == ONE:
        listing = slot == ONE or not shown or bool(query)
        one = {
            "label": "Hears, thinks and speaks",
            "name": shown["title"] if shown else PICK,
            "badges": [CLOUD] if shown else [],
            "note": "",
        }
        return {
            "mode": mode,
            "modes": modes,
            "parts": [{**one, **_opens(path, ONE, ONE, listing)}],
            "listing": listing,
            "speaking": _speaking(
                voice,
                shown["title"],
                f"{shown['vendor']}:{shown['model_id']}",
            )
            if voice and shown
            else None,
            "summary": await call_setup.one_summary(
                shown["model_id"], shown["vendor"], wait_ms=wait
            )
            if shown
            else None,
            **_listed(await _call_rows(listed) if listing else [], query, NO_LIVE),
            "search": {"mode": mode, "slot": ONE},
            "post": f"{path}/calls",
            "current": shown["model_id"] if shown else None,
            "mark": "data-call-model",
        }
    listing = slot in SLOTS or not shown or bool(query)
    slot = slot if slot in SLOTS else THINKS
    heard = call_setup.hears(settings)
    spoken = call_setup.speaks(voice, settings)
    parts = {
        HEARS: {"name": heard.name, "badges": [where(heard.local)], "note": ""},
        THINKS: {
            "name": shown["title"] if shown else PICK,
            "badges": [where(is_local_model(shown))] if shown else [],
            "note": "",
        },
        SPEAKS: {
            "name": spoken.name,
            "badges": [where(spoken.local)],
            "note": spoken.note,
        },
    }
    # The open part's list alone, and only while open: a server of its is
    # asked whether it answers.
    if slot == THINKS:
        listed = await _call_rows(listed) if listing else []
        current, empty = shown["model_id"] if shown else None, NO_THINKER
    else:
        catalog = (
            (get_stt_models, get_stt_providers)
            if slot == HEARS
            else (get_tts_models, get_tts_providers)
        )
        listed = await _rows(*catalog) if listing else []
        current = (heard if slot == HEARS else spoken).model
        empty = NO_RUNNABLE
    verb = VERBS[slot]
    return {
        "mode": mode,
        "modes": modes,
        "parts": [
            {
                **parts[key],
                "label": label,
                **_opens(path, CHAIN, key, listing and key == slot),
            }
            for key, label in SLOTS.items()
        ],
        "listing": listing,
        "speaking": _speaking(voice, _speaker(settings)) if voice else None,
        "summary": await call_setup.chain_summary(
            voice, settings, thinks_local=is_local_model(shown), wait_ms=wait
        )
        if shown
        else None,
        **_listed(listed, query, empty),
        "search": {"mode": mode, "slot": slot},
        "post": f"{path}/{verb}s",
        "mark": f"data-{verb}-model",
        "current": current,
    }


async def _call_rows(live: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The models calls can run on, as rows (only for a list shown: their
    icons are a read)."""
    icons = await models.vendor_icons(live)
    return [
        models.picker_row(
            m,
            under_vendor=None,
            icons=icons,
            badges=[where(is_local_model(m))],
            priced=m["kind"] == "realtime",
        )
        for m in live
    ]


def _opens(path: str, mode: str, key: str, open_: bool) -> dict[str, Any]:
    """A part's card: it opens its list, or, open, closes it."""
    return {
        "key": key,
        "open": open_,
        "url": address(path, mode) if open_ else address(path, mode, key),
    }


def _speaker(settings: Any) -> str:
    """The setup's speaking provider, by name."""
    from app.services.ai.service import get_tts_providers

    provider = settings.TTS_PROVIDER
    return next((p.name for p in get_tts_providers() if p.id == provider), provider)


def _speaking(voice: Any, engine: str, model: str | None = None) -> dict[str, Any]:
    """The Speaks-as line: ``engine`` named, then what of her it takes
    (``call_setup.speaking``)."""
    from app.core.config import settings
    from app.services.ai.service import call_setup

    return {"engine": engine, **call_setup.speaking(voice, settings, model)}


def _listed(rows: list[dict[str, Any]], query: str, empty: str) -> dict[str, Any]:
    """A list's rows narrowed to ``query``, and what it says when none are
    left: why there are none, or that none match."""
    return {
        "rows": filter_models(rows, query),
        "query": query,
        "empty": NO_MATCH if query and rows else empty,
    }


async def _rows(
    models: Callable[[], list[Any]], providers: Callable[[], list[Any]]
) -> list[dict[str, Any]]:
    """A part's models a call can use now (``can_run_now``), as rows, each
    naming what runs it: Kokoro-FastAPI's model is "Kokoro"."""
    from app.services.ai.service import can_run_now

    listed = providers()
    ok = await can_run_now(listed)
    local = {p.id for p in listed if p.is_local}
    names = {p.id: p.name for p in listed}
    return [
        {
            "model_id": m.id,
            "title": m.name,
            "facts": names[m.provider_id],
            "icon_name": None,
            "icon_url": None,
            "badges": [where(m.provider_id in local)],
        }
        for m in models()
        if m.provider_id in ok
    ]
