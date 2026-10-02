"""The Overseer AI page's Catalog section: every model in the catalog,
searched, windowed by release, narrowed to picked vendors and to what this
install can call, and one model in the drawer with "Use this model". Split
from ``overseer_ai`` (imported when the section is asked for); needs a
persistence backend, which is the only place the catalog lives.
"""

from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlencode

from app.core.config import settings
from app.services.ai.domains.llm.provider_management import usable_providers

from .overseer_ai_common import (
    PARTIALS,
    dollars,
    get_current_config,
    icon_url,
    label,
    per_million,
    section_url,
)
from .rendering import drawer_state

CATALOG_LIMIT = 100
# The catalog's release window: a label, and how far back (None: all time,
# which is also the only window that shows undated models).
RELEASED = {
    "3m": ("3 months", timedelta(days=91)),
    "6m": ("6 months", timedelta(days=182)),
    "1y": ("1 year", timedelta(days=365)),
    "all": ("All time", None),
}
MODEL_PARAM = "model"
# A model's kind (LargeLanguageModel.mode) as the page says it.
KINDS = {
    "chat": "Chat",
    "realtime": "Realtime",
    "audio_transcription": "Transcription",
    "audio_speech": "Speech",
}


async def list_models(**filters: Any) -> list[Any]:
    """The catalog's models (a persistence backend's module)."""
    from app.services.ai.domains.llm.catalog import list_models as catalog

    return await catalog(**filters)


async def get_model_info(model_id: str) -> Any:
    """One catalog model's details (a persistence backend's module)."""
    from app.services.ai.domains.llm.llm_service import get_model_info as info

    return await info(model_id)


async def catalog_vendors(db: Any) -> list[Any]:
    """Every vendor in the catalog with its model count, on the request's
    session (a persistence backend's module)."""
    from app.services.ai.domains.llm.llm_service import list_vendors

    return await list_vendors(session=db)


async def _vendor_filter(chosen: list[str], usable: bool) -> list[str] | None:
    """The vendors to list: the ones picked, the callable ones, both (where
    they meet), or None for every vendor."""
    if not usable:
        return chosen or None
    callable_now = await usable_providers(settings)
    return [v for v in chosen if v in callable_now] if chosen else callable_now


def _vendor_options(chosen: list[str], vendors: list[Any]) -> list[dict[str, Any]]:
    """The vendor picker: every catalog vendor, most models first, and a
    picked vendor the catalog no longer lists (still ticked, so it can be
    unticked)."""
    listed = sorted(vendors, key=lambda v: -v.model_count)
    names = {v.name for v in listed}
    listed += [SimpleNamespace(name=n, model_count=0) for n in chosen if n not in names]
    return [
        {
            "name": v.name,
            "label": label(v.name),
            "count": v.model_count,
            "checked": v.name in chosen,
        }
        for v in listed
    ]


def model_url(model_id: str, **filters: str | None) -> str:
    return section_url("catalog", **filters, **{MODEL_PARAM: model_id})


async def section_context(db: Any, query: Any) -> dict[str, Any]:
    q = (query.get("q") or "").strip() or None
    usable = query.get("usable") == "1"
    chosen = sorted(set(query.getlist("vendor"))) if hasattr(query, "getlist") else []
    released = query.get("released") if query.get("released") in RELEASED else "all"
    reach = RELEASED[released][1]
    models = await list_models(
        pattern=q,
        vendors=await _vendor_filter(chosen, usable),
        limit=CATALOG_LIMIT,
        released_after=date.today() - reach if reach else None,
        mode=None,  # a place to look: every kind, each saying which
    )
    from app.services.ai.domains.llm.queries import org_icons

    marked = await org_icons(db, {m.vendor for m in models})
    filters: dict[str, Any] = {
        "q": q,
        "vendor": chosen,
        "usable": "1" if usable else None,
        "released": None if released == "all" else released,
    }
    wanted = query.get(MODEL_PARAM) or ""

    def icon(model: Any) -> str | None:
        key = (
            model.lab
            if model.lab_icon_b64
            else model.vendor
            if model.vendor in marked
            else None
        )
        return icon_url(key) if key else None

    return drawer_state(
        MODEL_PARAM,
        f"{PARTIALS}/models/drawer?{urlencode({'model': wanted})}" if wanted else None,
    ) | {
        "q": q or "",
        "usable": usable,
        "catalog_url": section_url("catalog"),
        "chips": [
            {
                "label": label,
                "url": section_url("catalog", **(filters | {"usable": flag})),
                "active": (flag == "1") == usable,
            }
            for flag, label in ((None, "All models"), ("1", "Usable now"))
        ],
        "released_chips": [
            {
                "label": label,
                "url": section_url(
                    "catalog",
                    **(filters | {"released": None if key == "all" else key}),
                ),
                "active": key == released,
            }
            for key, (label, _) in RELEASED.items()
        ],
        "released": filters["released"],
        "vendor_options": _vendor_options(chosen, await catalog_vendors(db)),
        "vendor_count": len(chosen),
        "rows": [
            {
                "model": {
                    "label": m.title or m.display_id,
                    "url": model_url(m.model_id, **filters),
                },
                "icon_url": icon(m),
                "id": m.display_id,
                "kind": KINDS.get(m.mode, m.mode),
                "vendor": label(m.vendor),
                "context": m.context_window or None,
                "input": dollars(m.input_price),
                "output": dollars(m.output_price),
                "released": m.released_on,
            }
            for m in models
        ],
        "limit": CATALOG_LIMIT,
    }


async def model_context(model_id: str) -> dict[str, Any] | None:
    """One catalog model for the drawer, or None when it is not there."""
    info = await get_model_info(model_id)
    if info is None:
        return None
    current = await get_current_config()
    return {
        "info": info,
        "current": current.model == info.model_id,
        # Only a chat model can be the model the app answers with.
        "use_url": f"{PARTIALS}/models/use" if info.mode == "chat" else None,
        "facts": [
            ("Description", info.description or None),
            ("Vendor", label(info.vendor)),
            ("Kind", KINDS.get(info.mode, info.mode)),
            ("Model ID", info.model_id),
            (
                "Context window",
                f"{info.context_window:,} tokens" if info.context_window else None,
            ),
            ("Input price", per_million(info.input_price)),
            ("Output price", per_million(info.output_price)),
            ("Modalities", ", ".join(info.modalities) or None),
            ("Streaming", "Yes" if info.streamable else "No"),
            ("Released", info.released_on),
            ("Enabled", None if info.enabled else "No"),
        ],
    }
