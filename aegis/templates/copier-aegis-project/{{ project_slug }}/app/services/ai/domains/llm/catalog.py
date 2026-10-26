"""Catalog lookups: the picker's listing and the hot path's one question.

The full catalog service (``llm_service``) is a management surface;
this module is what the picker and a chat turn ask of the catalog.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

from app.core.db import get_async_session
from app.core.figures import FIGURES
from app.core.time import utcnow
from app.core.tools import register_tool
from app.services.ai.domains.llm import queries
from app.services.ai.models.llm import LargeLanguageModel, LLMPrice


async def context_window_for(model_id: str) -> int | None:
    """The catalog's context window for one model id, or None when the
    model is not in the catalog (unknown local tags, fresh installs)."""
    async with get_async_session() as session:
        row = await queries.llm_by_model_id(session, model_id)
    return row.context_window if row else None


class CatalogModel(BaseModel):
    """A model as the ``catalog`` tool gives it: what an agent weighs one by.
    The picker's ``LLMListResult`` is this and what it draws besides."""

    model_config = FIGURES

    model_id: str
    title: str
    vendor: str
    context_window: int
    input_price: float | None  # USD per million tokens
    output_price: float | None
    released_on: str | None
    # WHO MADE IT: the publishing org, resolved at sync time. None for a
    # model the registry does not know - unmarked beats mislabelled.
    lab: str | None = None
    # What kind of model: "chat", or a voice kind (LargeLanguageModel.mode).
    mode: str = "chat"


class LLMListResult(CatalogModel):
    """Result for a single model in list output: the catalog's row, and the
    family, colour and logo a picker draws."""

    family: str | None
    color: str
    lab_icon_b64: str | None = None

    @property
    def display_id(self) -> str:
        """The id as a table shows it, beside a vendor column that repeats it.

        The catalog stores what the provider calls the model, which for
        several of them repeats the vendor: ``gemini/gemini-3``,
        ``openai/gpt-4o``. Next to a Vendor column that already says
        "gemini", the prefix is noise. Lookups accept either form, so what
        is printed is still what ``llm use`` takes.
        """
        prefix = f"{self.vendor.lower()}/"
        if self.vendor and self.model_id.lower().startswith(prefix):
            return self.model_id[len(prefix) :]
        return self.model_id


async def list_models(
    pattern: str | None = None,
    vendor: str | None = None,
    vendors: list[str] | None = None,
    modality: str | None = None,
    limit: int = 50,
    include_disabled: bool = False,
    released_after: date | None = None,
    mode: str | None = "chat",
) -> list[LLMListResult]:
    """List LLM models from catalog with optional filtering.

    Args:
        pattern: Search pattern for model_id or title (case-insensitive)
        vendor: Filter by vendor name (substring match)
        vendors: Whitelist of EXACT vendor names; ``limit`` then applies
            per vendor in one query, so one large catalog cannot crowd
            the others out (the picker's usable path - looping a
            session per vendor is what made it slow)
        modality: Filter by modality (text, vision, audio, etc.)
        limit: Maximum number of results to return
        include_disabled: Include disabled models in results
        released_after: Only models released on or after this day
        mode: The kind of model ("chat", a voice kind), or None for every
            kind; a chat listing is the default, so no caller picking a
            model to talk to is offered a voice one

    Returns:
        List of LLMListResult with model summary data
    """
    if vendors is not None and not vendors:
        return []
    async with get_async_session() as session:
        models = await queries.catalog_models(
            session,
            pattern=pattern,
            vendor=vendor,
            vendors=vendors,
            modality=modality,
            include_disabled=include_disabled,
            limit=None if vendors else limit,
            released_after=released_after,
            mode=mode,
        )
        if vendors:
            models = _capped_per_vendor(models, limit)
        prices = await queries.latest_prices_by_llm_ids(
            session, [m.id for m in models if m.id is not None]
        )
    return [_list_result(model, prices.get(model.id or -1)) for model in models]


def _capped_per_vendor(
    models: list[LargeLanguageModel], limit: int
) -> list[LargeLanguageModel]:
    """``limit`` newest per vendor, applied AFTER the fetch: a SQL limit
    under the global newest-first ordering would let one vendor's fresh
    catalog starve the others entirely."""
    per_vendor: dict[str, int] = {}
    capped = []
    for model in models:
        name = model.served_by.name if model.served_by else ""
        per_vendor[name] = per_vendor.get(name, 0) + 1
        if per_vendor[name] <= limit:
            capped.append(model)
    return capped


def _list_result(model: LargeLanguageModel, price: LLMPrice | None) -> LLMListResult:
    return LLMListResult(
        model_id=model.model_id,
        title=model.title,
        vendor=model.served_by.name if model.served_by else "Unknown",
        family=model.family,
        color=model.color,
        context_window=model.context_window,
        input_price=price.input_cost_per_token * 1_000_000 if price else None,
        output_price=price.output_cost_per_token * 1_000_000 if price else None,
        lab=model.made_by.name if model.made_by else None,
        lab_icon_b64=model.made_by.icon_b64 if model.made_by else None,
        released_on=model.released_on.strftime("%Y-%m-%d")
        if model.released_on
        else None,
        mode=model.mode,
    )


class CatalogAnswer(BaseModel):
    """The ``catalog`` tool's answer, and when it was read."""

    model_config = FIGURES

    models: tuple[CatalogModel, ...]
    read_at: datetime


async def catalog(
    text: str | None = None,
    vendor: str | None = None,
    modality: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """The model catalog: models this install could run, newest first, each
    with its vendor, the lab that made it, its context window and its price
    in USD per million input and output tokens. ``text`` matches the id or
    title, ``vendor`` the provider (openai, anthropic, ...), ``modality``
    what it takes in (vision, audio, ...). ``limit`` caps the rows (at most
    50). The active model is in your session section; this is what else
    there is."""
    rows = await list_models(
        pattern=text, vendor=vendor, modality=modality, limit=min(limit, 50)
    )
    fields = set(CatalogModel.model_fields)
    return CatalogAnswer(
        models=tuple(CatalogModel(**row.model_dump(include=fields)) for row in rows),
        read_at=utcnow(),
    ).model_dump(mode="json")


register_tool(
    "catalog",
    catalog,
    description="Look up the models this install could use, with prices",
    replace=True,
    effect="read",
)
