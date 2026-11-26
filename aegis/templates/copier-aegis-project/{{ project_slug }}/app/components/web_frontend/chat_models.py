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

It holds the chat models only. What a live call runs on is picked with
the voice it speaks in (``chat_voices``, laid out by ``chat_calls``): the
models a call can reach (``call_models``), a pick making one the active
voice profile's engine (``use_for_calls``, made on the spot when it has
none).
"""

from typing import TYPE_CHECKING, Any

from app.core.model_picker import (
    NO_MATCH,
    display_title,
    filter_models,
    format_context_window,
    group_models,
    lab_for_model,
    model_label,
    model_price,
    newest_first,
)

if TYPE_CHECKING:  # a session only where the stack has a database
    from sqlmodel.ext.asyncio.session import AsyncSession

# How many recently used models lead the list; read from a few more, as
# some may not be callable now.
RECENT = 3
RECENT_LOOKBACK = 12
SECTION_ROW_CAP = 30
FLAT_ROW_CAP = 60
CATALOG_LIMIT = 200


async def catalog(mode: str | None = "chat") -> list[dict[str, Any]]:
    """Every model of this kind (every kind, with None) this install can
    call right now."""
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
        mode=mode,
    )
    return [m.model_dump() for m in models]


async def model_choices(
    db: "AsyncSession", current: str | None
) -> list[dict[str, Any]]:
    """The chat models as a grouped select's options (an agent's model, an
    eval run's), by vendor as the picker groups them; ``current`` kept,
    first, when the catalog no longer lists it, so saving does not drop it.
    The catalog reads on its own connection, so ``db``'s lock goes first."""
    # Imported here: the module loads on every AI stack, the database only
    # comes with a persistence backend, the only one with models to pick.
    from app.core.db import release_lock

    await release_lock(db)
    models = await catalog("chat")
    groups = [
        {
            "label": vendor,
            "options": [
                {"id": m["model_id"], "name": display_title(m, under_vendor=vendor)}
                for m in rows
            ],
        }
        for vendor, rows in group_models(models, keep=current)
    ]
    if current and all(m["model_id"] != current for m in models):
        unlisted = {"id": current, "name": f"{current} (not in the catalog)"}
        groups.insert(0, {"label": "Chosen", "options": [unlisted]})
    return groups


async def call_models() -> list[dict[str, Any]]:
    """What a live call can run on (``live_engines.reachable``), each with
    its ``kind``: a realtime model, or a chat model that calls tools (local
    or cloud), which a call runs as a cascade. One read of every kind: the
    rule picks."""
    from app.services.ai.service import live_engines

    return [
        {**m, "kind": "realtime" if m["mode"] == "realtime" else "cascade"}
        for m in await catalog(None)
        if live_engines.reachable(
            str(m.get("vendor") or ""),
            m["mode"],
            m["model_id"],
            m.get("supports_tools"),
        )
    ]


async def calling_model(db: "AsyncSession") -> Any | None:
    """The catalog model a live call runs on now (the call setup's
    engine: its ``model_id`` and ``title``), or None; read on the request's
    session (``db``)."""
    from app.core.config import settings
    from app.services.ai.service import live_engines

    engine = await live_engines.resolve(db, settings.VOICE_LIVE_ENGINE)
    return engine.llm if engine else None


async def use_for_calls(model_id: str) -> str | None:
    """Make ``model_id`` what a live call runs on: its engine (made when it
    has none) on the call setup, the voice untouched; why not, when it
    cannot be."""
    from app.components.backend.api.ai.service import ai_service
    from app.core.config import settings
    from app.core.db import get_async_session
    from app.services.ai.service import live_engines, profiles

    async with get_async_session() as db:
        engine = await live_engines.choose(db, model_id)
        if engine is None:
            return f"A live call cannot run on {model_id}."
        setup = await profiles.set_up(db, settings, live_engine=engine.key)
    profiles.apply(None, settings, ai_service, setup)
    return None


async def vendor_icons(models: list[dict[str, Any]]) -> dict[str, str]:
    """``{vendor: icon URL}`` for the vendors of ``models`` the catalog
    holds a mark for (served by the Overseer's icon route; none without
    the Overseer)."""
    from .chat_surface import marks

    vendors = sorted({str(m.get("vendor") or "") for m in models})
    return await marks({v: (v,) for v in vendors})


async def current_config() -> Any:
    """The model in effect. With a persistence backend that is the catalog
    service's answer (a stored choice can shadow ``.env``); on the memory
    backend there is no catalog and ``.env`` is the whole story."""
    from .chat_surface import PERSISTED

    if PERSISTED:
        from app.services.ai.service import (
            get_current_config as current,
        )

        return await current()
    from types import SimpleNamespace

    from app.core.config import settings

    return SimpleNamespace(
        provider=settings.AI_PROVIDER,
        model=settings.AI_MODEL,
        temperature=settings.AI_TEMPERATURE,
        max_tokens=settings.AI_MAX_TOKENS,
        in_catalog=False,
        source="env",
        env_model=settings.AI_MODEL,
        context_window=None,
        input_price=None,
        output_price=None,
    )


async def running_model() -> str:
    return (await current_config()).model


async def recent_ids() -> list[str]:
    from app.core.db import get_async_session
    from app.services.ai.service import recent_model_ids

    async with get_async_session(read_only=True) as db:
        return await recent_model_ids(db, RECENT_LOOKBACK)


async def switch(model_id: str) -> str | None:
    """Make ``model_id`` the active model; why not, when it was refused."""
    from app.services.ai.service import set_active_model

    result = await set_active_model(model_id)
    return None if result.success else result.message


def chip(model: str) -> dict[str, Any]:
    """What the composer's chip says: the model's id, clipped."""
    return {"label": model_label({"model": model}), "model": model}


def picker_row(
    model: dict[str, Any],
    *,
    under_vendor: str | None,
    icons: dict[str, str],
    badges: list[dict[str, str]] | None = None,
    priced: bool = True,
) -> dict[str, Any]:
    """One picker row. An icon only where it adds information: the lab
    behind a hosted model when it differs from the group's vendor, and the
    vendor in flat views that have no group around them; ``badges`` (each
    a ``label`` and ``tone``) where the row has more to say than facts;
    not ``priced`` where its own price is not what it costs (a chain call's
    model, whose speech is paid for around it)."""
    lab = lab_for_model(model)
    vendor = str(model.get("vendor") or "")
    voice = model.get("kind") == "realtime"
    if under_vendor:
        icon_for = lab if lab and lab.casefold() != under_vendor.casefold() else None
    else:
        icon_for = lab or vendor
    versions = model.get("versions", 1)
    facts = " · ".join(
        part
        for part in (
            # A voice model's window is not what picks it; its price is.
            None if voice else format_context_window(model.get("context_window")),
            f"{versions} versions" if versions > 1 else None,
            model_price(model) if priced else None,
        )
        if part
    )
    return {
        "model_id": model["model_id"],
        "title": display_title(model, under_vendor=under_vendor),
        "facts": facts,
        "icon_name": icon_for,
        "icon_url": icons.get(icon_for or ""),
        "badges": badges or [],
    }


def _flat(
    models: list[dict[str, Any]], query: str, icons: dict[str, str]
) -> list[dict[str, Any]]:
    rows = newest_first(filter_models(models, query))
    shown = rows[:FLAT_ROW_CAP]
    return [
        {
            "name": None,
            "rows": [picker_row(m, under_vendor=None, icons=icons) for m in shown],
            "hidden": len(rows) - len(shown),
        }
    ]


def _grouped(
    models: list[dict[str, Any]], icons: dict[str, str], current: str
) -> list[dict[str, Any]]:
    """A group per vendor, each starting closed: the models in use lead the
    list among the recently used, so an opened group only pushes them down."""
    sections = []
    for vendor, rows in group_models(models, by="vendor", keep=current):
        shown = rows[:SECTION_ROW_CAP]
        sections.append(
            {
                "name": vendor,
                "icon_url": icons.get(vendor),
                "count": len(rows),
                "rows": [
                    picker_row(m, under_vendor=vendor, icons=icons) for m in shown
                ],
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
            "rows": [picker_row(m, under_vendor=None, icons=icons) for m in recent],
            "hidden": 0,
        }
    ]


async def picker(query: str, current: str, path: str) -> dict[str, Any]:
    """The dialog's contents: grouped by vendor, or flat when searching,
    with the recently used leading and the active model marked. ``path``
    is the picker's own URL on the chat mount it opened from."""
    models = await catalog()
    icons = await vendor_icons(models)
    query = query.strip()
    if query:
        sections = _flat(models, query, icons)
    else:
        # A pick leads at once: it has no usage until it answers.
        leading = [current, *await recent_ids()]
        sections = _recent(models, leading, icons) + _grouped(models, icons, current)
    return {
        "query": query,
        "current": current,
        "sections": sections,
        # What the list says when the search leaves none.
        "empty": None if any(section["rows"] for section in sections) else NO_MATCH,
        "path": path,
    }
