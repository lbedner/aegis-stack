"""The chat's model picker: the composer's chip names the model answering,
and opens one list of the models this install can call, grouped by vendor,
the recently used leading, searched in one box.

Switching is the install-wide active model (the AI routes re-read it per
request), not a per-conversation setting, and it goes through the same
``set_active_model`` the CLI and the API use, so a provider without a key
is refused here as it is there. Honest caps: a group shows this many rows
and a search this many, with a "more - search to narrow" line rather than
silent truncation. Needs the catalog, so offered with a persistence
backend only.
"""

from typing import Any

from app.core.model_picker import (
    display_title,
    filter_models,
    format_context_window,
    format_price,
    group_models,
    is_local_model,
    lab_for_model,
    model_label,
    newest_first,
)

from .overseer_ai_chat import PATH

MODELS = f"{PATH}/models"
# How many recently used models lead the list; read from a few more, as
# some may not be callable now.
RECENT = 3
RECENT_LOOKBACK = 12
SECTION_ROW_CAP = 30
FLAT_ROW_CAP = 60
CATALOG_LIMIT = 200


async def catalog() -> list[dict[str, Any]]:
    """Every model this install can call right now."""
    from app.components.backend.api.llm.routes import get_models

    # Every argument spelled out: called in-process, the handler's Query
    # defaults are not values.
    models = await get_models(
        pattern=None,
        vendor=None,
        modality=None,
        limit=CATALOG_LIMIT,
        include_disabled=False,
        usable=True,
    )
    return [m.model_dump() for m in models]


async def vendor_icons(vendors: list[str]) -> dict[str, str]:
    """``{vendor: icon URL}`` for the vendors the catalog holds a mark for,
    served by the AI page's icon route like every other Overseer logo."""
    from app.core.db import get_async_session

    from .overseer_ai_common import mark_urls

    async with get_async_session() as db:
        return await mark_urls(db, {v: (v,) for v in vendors})


async def running_model() -> str:
    from .overseer_ai_common import get_current_config

    return (await get_current_config()).model


async def recent_ids() -> list[str]:
    from app.core.db import get_async_session
    from app.services.ai.domains.llm.queries import recent_model_ids

    async with get_async_session() as db:
        return await recent_model_ids(db, RECENT_LOOKBACK)


async def switch(model_id: str) -> str | None:
    """Make ``model_id`` the active model; why not, when it was refused."""
    from app.services.ai.domains.llm.llm_service import set_active_model

    result = await set_active_model(model_id)
    return None if result.success else result.message


def chip(model: str) -> dict[str, Any]:
    """What the composer's chip says: the model's id, clipped."""
    return {"label": model_label({"model": model}), "model": model}


def _row(
    model: dict[str, Any], *, under_vendor: str | None, icons: dict[str, str]
) -> dict[str, Any]:
    """One picker row. An icon only where it adds information: the lab
    behind a hosted model when it differs from the group's vendor, and the
    vendor in flat views that have no group around them."""
    lab = lab_for_model(model)
    vendor = str(model.get("vendor") or "")
    if under_vendor:
        icon_for = lab if lab and lab.casefold() != under_vendor.casefold() else None
    else:
        icon_for = lab or vendor
    facts = " · ".join(
        part
        for part in (
            format_context_window(model.get("context_window")),
            format_price(
                model.get("input_price"),
                model.get("output_price"),
                local=is_local_model(model),
            ),
        )
        if part
    )
    return {
        "model_id": model["model_id"],
        "title": display_title(model, under_vendor=under_vendor),
        "facts": facts,
        "icon_name": icon_for,
        "icon_url": icons.get(icon_for or ""),
    }


def _flat(
    models: list[dict[str, Any]], query: str, icons: dict[str, str]
) -> list[dict[str, Any]]:
    rows = newest_first(filter_models(models, query))
    shown = rows[:FLAT_ROW_CAP]
    return [
        {
            "name": None,
            "rows": [_row(m, under_vendor=None, icons=icons) for m in shown],
            "hidden": len(rows) - len(shown),
        }
    ]


def _grouped(
    models: list[dict[str, Any]], icons: dict[str, str]
) -> list[dict[str, Any]]:
    """A group per vendor, each starting closed: the models in use lead the
    list among the recently used, so an opened group only pushes them down."""
    sections = []
    for vendor, rows in group_models(models, by="vendor"):
        shown = rows[:SECTION_ROW_CAP]
        sections.append(
            {
                "name": vendor,
                "icon_url": icons.get(vendor),
                "count": len(rows),
                "rows": [_row(m, under_vendor=vendor, icons=icons) for m in shown],
                "hidden": len(rows) - len(shown),
            }
        )
    return sections


def _recent(
    models: list[dict[str, Any]], ids: list[str], icons: dict[str, str]
) -> list[dict[str, Any]]:
    """The model in use, then the last few used, leading the list with no
    heading: the ones you switch between, one click away."""
    by_id = {model["model_id"]: model for model in models}
    recent = [by_id[i] for i in dict.fromkeys(ids) if i in by_id][:RECENT]
    if not recent:
        return []
    return [
        {
            "name": None,
            "recent": True,
            "rows": [_row(m, under_vendor=None, icons=icons) for m in recent],
            "hidden": 0,
        }
    ]


async def picker(query: str, current: str) -> dict[str, Any]:
    """The dialog's contents: grouped by vendor, or flat when searching,
    with the recently used leading and the active model marked."""
    models = await catalog()
    icons = await vendor_icons(sorted({str(m.get("vendor") or "") for m in models}))
    query = query.strip()
    if query:
        sections = _flat(models, query, icons)
    else:
        # A pick leads at once: it has no usage until it answers.
        leading = [current, *await recent_ids()]
        sections = _recent(models, leading, icons) + _grouped(models, icons)
    return {
        "query": query,
        "active": {current},
        "sections": sections,
        "empty": not any(section["rows"] for section in sections),
        "path": MODELS,
    }
