"""What a live call runs on, laid out as the parts it is made of, for the
voice dialog (``chat_voices``).

Two ways a call can run, picked first: one model that hears and speaks by
itself (a realtime model), or a chain, hear then think then speak (a local
chat model between the active voice's STT and TTS: ``cascade``). A chain
shows its three parts, each opening its own list below: Hears is the
voice's hearing model, Thinks the model calls run on, Speaks the voice.
A line under them says where the call runs, what it costs and how long a
caller waits (``call_setup``). The mode is the model's, not stored: picking
one of the other kind switches it.
"""

from typing import Any
from urllib.parse import urlencode

from app.components.web_frontend import chat_models as models
from app.core.model_picker import newest_first

ONE, CHAIN = "one", "chain"
MODES = {ONE: "One model hears and speaks", CHAIN: "Hear → think → speak"}
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
    model calls run on), its parts with the open one's list, and the line
    that sums them up. ``calling`` is the model calls run on, ``voice`` the
    active profile."""
    from app.core.config import settings
    from app.services.ai.service import call_setup, live_engines, realtime_calls

    live = newest_first(await models.call_models())
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
        voice_id = getattr(voice, "tts_voice", None)
        said = (
            realtime_calls.call_voice(
                f"{shown['vendor']}:{shown['model_id']}", voice_id
            )
            if shown
            else None
        )
        one = {
            "label": "Hears, thinks and speaks",
            "name": shown["title"] if shown else PICK,
            "badges": [CLOUD] if shown else [],
            "note": (f"speaks as {said}" if said else "speaks in its own voice")
            if shown
            else "",
        }
        return {
            "mode": mode,
            "modes": modes,
            "parts": [{**one, "key": ONE, "url": address(path, ONE), "open": True}],
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
            "list": None,
        }
    slot = slot if slot in SLOTS else THINKS
    heard = call_setup.hears(voice, settings)
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
    lists: dict[str, Any] = {
        HEARS: _hearing_rows(),
        THINKS: rows,
        SPEAKS: None,  # the voice list
    }
    return {
        "mode": mode,
        "modes": modes,
        "parts": [
            {
                **parts[key],
                "key": key,
                "label": label,
                "url": address(path, CHAIN, key),
                "open": key == slot,
            }
            for key, label in SLOTS.items()
        ],
        "summary": await call_setup.chain_summary(
            voice, settings, thinks_local=True, wait_ms=wait
        )
        if shown
        else None,
        "rows": lists[slot],
        "post": f"{path}/hears" if slot == HEARS else f"{path}/calls",
        "mark": "data-hear-model" if slot == HEARS else "data-call-model",
        "empty": NO_LOCAL,
        "current": heard.model
        if slot == HEARS
        else (shown["model_id"] if shown else None),
        "list": slot,
    }


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
