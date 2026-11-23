"""What a live call runs on, laid out as the parts it is made of, for the
voice dialog (``chat_voices``).

Two ways a call can run, picked first: one model that hears and speaks by
itself (a realtime model), or a chain, hear then think then speak (a local
chat model between the call setup's STT and TTS: ``cascade``). A chain
shows its three parts, each opening its own list below: Hears is the
setup's hearing model, Thinks the model calls run on, Speaks its speaking
model, in the active voice. Picking any of them changes the setup, never
the voice.
A line under them says where the call runs, what it costs and how long a
caller waits (``call_setup``). The mode is the model's, not stored: picking
one of the other kind switches it.
"""

from typing import Any
from urllib.parse import urlencode

from app.components.web_frontend import chat_models as models
from app.core.model_picker import newest_first, one_per_base

ONE, CHAIN = "one", "chain"
MODES = {ONE: "One model", CHAIN: "Hear → think → speak"}
HEARS, THINKS, SPEAKS = "hears", "thinks", "speaks"
SLOTS = {HEARS: "Hears", THINKS: "Thinks", SPEAKS: "Speaks"}
# What a row or a part shows of where it runs and what it can do.
LOCAL = {"label": "Local", "tone": "ok"}
CLOUD = {"label": "Cloud", "tone": "warn"}
TOOLS = {"label": "Tools", "tone": "ok"}
PICK = "Pick a model below"  # a part with no model yet
NO_LIVE = (
    "No live model can be reached: a call needs an OpenAI or Google key "
    "with a realtime model in the catalog."
)
NO_LOCAL = (
    "No local model here can call tools. Load one in the inference engine, "
    "then sync the catalog (llm sync --source local)."
)


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
) -> dict[str, Any]:
    """The dialog's call setup: the mode shown (``mode``, else the kind of
    model calls run on), its parts with the open one's list (``slot``),
    what speaks her, and the line that sums them up. ``calling`` is the
    model calls run on, ``voice`` the active profile. A list opens unasked
    only where nothing is picked yet; Speaks is the voice, so its card
    opens every voice."""
    from app.core.config import settings
    from app.services.ai.service import call_setup, live_engines

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
    icons = await models.vendor_icons(live)
    rows = [
        models.picker_row(
            m,
            under_vendor=None,
            icons=icons,
            badges=_badges(m),
            priced=m["kind"] == "realtime",
        )
        for m in live
        if m["kind"] == kind
    ]
    modes = [
        {"label": label, "url": address(path, key), "active": key == mode}
        for key, label in MODES.items()
    ]
    if mode == ONE:
        listing = slot == ONE or not shown
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
            "rows": rows,
            "post": f"{path}/calls",
            "current": shown["model_id"] if shown else None,
            "mark": "data-call-model",
            "empty": NO_LIVE,
        }
    listing = slot in (HEARS, THINKS) or not shown
    slot = slot if slot in (HEARS, THINKS) else THINKS
    heard = call_setup.hears(settings)
    spoken = call_setup.speaks(voice, settings)
    thinks = {
        "name": shown["title"] if shown else PICK,
        "badges": _badges(shown) if shown else [],
        "note": "",
    }
    parts = {
        HEARS: {"name": heard.name, "badges": [where(heard.local)], "note": ""},
        THINKS: thinks,
        SPEAKS: {
            "name": spoken.name,
            "badges": [where(spoken.local)],
            "note": spoken.note,
        },
    }
    lists: dict[str, Any] = {HEARS: _hearing_rows, THINKS: lambda: rows}
    cards = [
        {
            **parts[key],
            "label": label,
            **_opens(path, CHAIN, key, listing and key == slot),
        }
        for key, label in SLOTS.items()
    ]
    # Speaks is the voice: its card opens every voice.
    cards[-1]["url"] = f"{path}/manage"
    return {
        "mode": mode,
        "modes": modes,
        "parts": cards,
        "listing": listing,
        "speaking": _speaking(voice, _speaker(settings)) if voice else None,
        "summary": await call_setup.chain_summary(
            voice, settings, thinks_local=True, wait_ms=wait
        )
        if shown
        else None,
        "rows": lists[slot]() if listing else [],
        "post": f"{path}/hears" if slot == HEARS else f"{path}/calls",
        "mark": "data-hear-model" if slot == HEARS else "data-call-model",
        "empty": NO_LOCAL,
        "current": heard.model
        if slot == HEARS
        else (shown["model_id"] if shown else None),
    }


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


def _badges(model: dict[str, Any]) -> list[dict[str, str]]:
    """A call model's: where it runs, and Tools where its engine says it
    can call them (a chain's model answers with the agent's tools)."""
    local = model["kind"] == "cascade"
    return [where(local), *([TOOLS] if model.get("supports_tools") else [])]


def _hearing_rows() -> list[dict[str, Any]]:
    """Every hearing model, as rows."""
    from app.services.ai.service import get_stt_models, get_stt_providers

    local = {p.id for p in get_stt_providers() if p.is_local}
    return [
        {
            "model_id": m.id,
            "title": m.name,
            "facts": "",
            "icon_name": None,
            "icon_url": None,
            "badges": [where(m.provider_id in local)],
        }
        for m in get_stt_models()
    ]
