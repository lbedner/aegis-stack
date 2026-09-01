"""Read-only catalog listing: the picker's query surface.

Extracted from ``llm_service`` (which keeps config and active-model
management) so each module stays inside the size budget. The service
module re-exports these names; existing import paths keep working.
"""

from pydantic import BaseModel
from sqlalchemy.orm import selectinload
from sqlmodel import or_, select

from app.core.db import get_async_session
from app.services.ai.models.llm import (
    LargeLanguageModel,
    LLMModality,
    LLMOrg,
    LLMPrice,
)


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
    async with get_async_session() as session:
        # Build base query with eager loading for vendor
        stmt = (
            select(LargeLanguageModel)
            .join(LLMOrg, LargeLanguageModel.served_by_org_id == LLMOrg.id)
            .options(
                selectinload(LargeLanguageModel.served_by),
                selectinload(LargeLanguageModel.made_by),
            )
        )

        # Apply filters
        if pattern:
            stmt = stmt.where(
                or_(
                    LargeLanguageModel.model_id.ilike(f"%{pattern}%"),
                    LargeLanguageModel.title.ilike(f"%{pattern}%"),
                )
            )

        if vendor:
            stmt = stmt.where(LLMOrg.name.ilike(f"%{vendor}%"))

        if vendors is not None:
            if not vendors:
                return []
            stmt = stmt.where(LLMOrg.name.in_(vendors))

        if modality:
            stmt = stmt.join(
                LLMModality, LargeLanguageModel.id == LLMModality.llm_id
            ).where(LLMModality.modality == modality)

        if not include_disabled:
            stmt = stmt.where(LargeLanguageModel.enabled == True)  # noqa: E712

        # Sort by release date (newest first), nulls last
        stmt = stmt.order_by(
            LargeLanguageModel.released_on.desc().nulls_last(),
            LargeLanguageModel.model_id,
        )
        # With a vendors whitelist the cap is applied per vendor AFTER the
        # fetch: a SQL limit under the global newest-first ordering would
        # let one vendor's fresh catalog starve the others entirely.
        if not vendors:
            stmt = stmt.limit(limit)

        result = await session.exec(stmt)
        models = list(result.all())
        if vendors:
            per_vendor: dict[str, int] = {}
            capped = []
            for m in models:
                name = m.served_by.name if m.served_by else ""
                per_vendor[name] = per_vendor.get(name, 0) + 1
                if per_vendor[name] <= limit:
                    capped.append(m)
            models = capped

        # Batch-fetch prices to avoid N+1 queries
        model_ids = [m.id for m in models]
        price_map: dict[int, LLMPrice] = {}
        if model_ids:
            price_stmt = (
                select(LLMPrice)
                .where(LLMPrice.llm_id.in_(model_ids))
                .order_by(LLMPrice.llm_id, LLMPrice.effective_date.desc())
            )
            price_result = await session.exec(price_stmt)
            prices = price_result.all()
            # Keep only the latest price per model (first due to ordering)
            for price in prices:
                if price.llm_id not in price_map:
                    price_map[price.llm_id] = price

        results: list[LLMListResult] = []
        for model in models:
            price = price_map.get(model.id)
            results.append(
                LLMListResult(
                    model_id=model.model_id,
                    title=model.title,
                    vendor=model.served_by.name if model.served_by else "Unknown",
                    family=model.family,
                    color=model.color,
                    context_window=model.context_window,
                    input_price=price.input_cost_per_token * 1_000_000
                    if price
                    else None,
                    output_price=price.output_cost_per_token * 1_000_000
                    if price
                    else None,
                    lab=model.made_by.name if model.made_by else None,
                    lab_icon_b64=model.made_by.icon_b64 if model.made_by else None,
                    released_on=model.released_on.strftime("%Y-%m-%d")
                    if model.released_on
                    else None,
                )
            )

        return results
