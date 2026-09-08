"""Catalog lookups: the picker's listing and the hot path's one question.

The full catalog service (``llm_service``) is a management surface;
this module is what the picker and a chat turn ask of the catalog.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.core.db import get_async_session
from app.services.ai.domains.llm import queries
from app.services.ai.models.llm import LargeLanguageModel, LLMPrice


async def context_window_for(model_id: str) -> int | None:
    """The catalog's context window for one model id, or None when the
    model is not in the catalog (unknown local tags, fresh installs)."""
    async with get_async_session() as session:
        row = await queries.llm_by_model_id(session, model_id)
    return row.context_window if row else None


class LLMListResult(BaseModel):
    """Result for a single model in list output."""

    model_id: str
    title: str
    vendor: str
    family: str | None
    color: str
    context_window: int
    input_price: float | None
    output_price: float | None
    released_on: str | None
    # WHO MADE IT: the publishing org, resolved at sync time. None for a
    # model the registry does not know - unmarked beats mislabelled.
    lab: str | None = None
    lab_icon_b64: str | None = None


async def list_models(
    pattern: str | None = None,
    vendor: str | None = None,
    vendors: list[str] | None = None,
    modality: str | None = None,
    limit: int = 50,
    include_disabled: bool = False,
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
    )
