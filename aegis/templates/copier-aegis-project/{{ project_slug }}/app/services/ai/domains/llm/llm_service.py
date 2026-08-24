"""LLM model management service.

Provides business logic for listing, viewing, and switching LLM models.
"""

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy.orm import selectinload
from sqlmodel import Session, or_, select

from app.core.config import settings
from app.core.db import engine, get_async_session
from app.core.log import logger
from app.services.ai.domains.llm import active_model
from app.services.ai.models import AIProvider
from app.services.ai.models.llm import (
    LargeLanguageModel,
    LLMModality,
    LLMPrice,
    LLMVendor,
)
from app.services.ai.domains.llm.provider_management import update_env_file


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


class VendorListResult(BaseModel):
    """Result for a single vendor in list output."""

    name: str
    model_count: int


class ModalityListResult(BaseModel):
    """Result for a single modality in list output."""

    modality: str
    model_count: int


class CurrentLLMConfig(BaseModel):
    """Current LLM configuration from environment."""

    provider: str
    model: str
    temperature: float
    max_tokens: int
    # Whether the model has a catalog row at all. Distinct from the enrichment
    # fields below: an Ollama model is in the catalog but reports no context
    # window, and inferring "not synced" from a missing window tells the user
    # to re-run a sync that already worked.
    in_catalog: bool = False
    # Provenance: where the active value comes from. "override" means a
    # stored dashboard/CLI selection is shadowing .env; "env" means .env is
    # in charge. ``env_model`` is what .env would give, so a UI can say
    # exactly what a reset returns to.
    source: str = "env"
    override_updated_at: datetime | None = None
    env_model: str | None = None
    # Optional enrichment from catalog
    context_window: int | None = None
    input_price: float | None = None
    output_price: float | None = None
    modalities: list[str] | None = None


class SetModelResult(BaseModel):
    """Result of setting a new active model."""

    success: bool
    model_id: str
    vendor: str | None
    provider_updated: bool
    message: str


class LLMDetails(BaseModel):
    """Full details for a single LLM model."""

    model_id: str
    title: str
    description: str
    vendor: str
    context_window: int
    streamable: bool
    enabled: bool
    released_on: str | None
    input_price: float | None
    output_price: float | None
    modalities: list[str]


async def list_models(
    pattern: str | None = None,
    vendor: str | None = None,
    modality: str | None = None,
    limit: int = 50,
    include_disabled: bool = False,
) -> list[LLMListResult]:
    """List LLM models from catalog with optional filtering.

    Args:
        pattern: Search pattern for model_id or title (case-insensitive)
        vendor: Filter by vendor name
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
            .join(LLMVendor, LargeLanguageModel.llm_vendor_id == LLMVendor.id)
            .options(selectinload(LargeLanguageModel.llm_vendor))
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
            stmt = stmt.where(LLMVendor.name.ilike(f"%{vendor}%"))

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
        stmt = stmt.limit(limit)

        result = await session.exec(stmt)
        models = result.all()

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
                    vendor=model.llm_vendor.name if model.llm_vendor else "Unknown",
                    family=model.family,
                    color=model.color,
                    context_window=model.context_window,
                    input_price=price.input_cost_per_token * 1_000_000
                    if price
                    else None,
                    output_price=price.output_cost_per_token * 1_000_000
                    if price
                    else None,
                    released_on=model.released_on.strftime("%Y-%m-%d")
                    if model.released_on
                    else None,
                )
            )

        return results


async def get_current_config() -> CurrentLLMConfig:
    """Get the LLM configuration that is actually in effect.

    ``.env`` is only the bootstrap default: a selection made with ``llm use``
    or from the dashboard is stored in the database and replayed into settings
    as each process boots. A fresh CLI process has not booted through that
    hook, so reading settings alone would report the .env value and call a
    model live that is not - which is exactly how "I already switched it" turns
    into an hour of confusion. Resolve the override first, then enrich from the
    catalog.

    Returns:
        CurrentLLMConfig with the effective settings and optional catalog
        enrichment
    """
    provider = settings.AI_PROVIDER
    model = settings.AI_MODEL

    source = "env"
    override_updated_at = None
    async with get_async_session() as session:
        override = await active_model.resolve_override(session)
        if override is not None:
            model = override.model_id
            provider = override.provider or provider
            source = "override"
            override_updated_at = override.updated_at

    # In a booted process settings.AI_MODEL already carries the override, so
    # the .env value has to come from the pre-override capture.
    env_model = active_model.env_default_model() or settings.AI_MODEL

    config = CurrentLLMConfig(
        provider=provider,
        model=model,
        temperature=settings.AI_TEMPERATURE,
        max_tokens=settings.AI_MAX_TOKENS,
        source=source,
        override_updated_at=override_updated_at,
        env_model=env_model,
    )

    # Try to enrich from catalog
    async with get_async_session() as session:
        stmt = select(LargeLanguageModel).where(
            LargeLanguageModel.model_id == config.model
        )
        result = await session.exec(stmt)
        model = result.first()

        if model:
            config.in_catalog = True
            config.context_window = model.context_window

            # Get latest price
            price_stmt = (
                select(LLMPrice)
                .where(LLMPrice.llm_id == model.id)
                .order_by(LLMPrice.effective_date.desc())
                .limit(1)
            )
            price_result = await session.exec(price_stmt)
            price = price_result.first()
            if price:
                config.input_price = price.input_cost_per_token * 1_000_000
                config.output_price = price.output_cost_per_token * 1_000_000

            # Get modalities
            modality_stmt = select(LLMModality).where(LLMModality.llm_id == model.id)
            modality_result = await session.exec(modality_stmt)
            modalities = modality_result.all()
            config.modalities = list({str(m.modality) for m in modalities})

    return config


async def _store_active_selection(
    *, model_id: str, provider: str | None, owner_user_id: int | None = None
) -> bool:
    """Write the selection to the catalog database. False if there isn't one.

    Returns False rather than raising when the table is absent (a stack whose
    AI backend is in-memory, or one whose migrations have not run), so the
    caller can fall back to the ``.env`` write.
    """
    try:
        async with get_async_session() as session:
            await active_model.set_active_override(
                session,
                model_id=model_id,
                provider=provider,
                owner_user_id=owner_user_id,
            )
            await session.commit()
    except Exception:
        logger.warning(
            "No catalog database for the active-model selection; falling back to .env",
            exc_info=True,
        )
        return False
    return True


async def clear_active_model() -> bool:
    """Remove the stored selection; the app answers from .env again.

    Applies live in this process (settings are restored from the values .env
    provided at boot); other processes pick it up at their next start, same
    as a switch. True when there was a row to remove.
    """
    try:
        async with get_async_session() as session:
            cleared = await active_model.clear_active_override(session, settings)
            await session.commit()
    except Exception:
        logger.warning("Could not clear the active-model selection", exc_info=True)
        return False
    return cleared


async def set_active_model(model_id: str, force: bool = False) -> SetModelResult:
    """Set the active LLM model.

    Updates AI_MODEL in .env, and optionally AI_PROVIDER if the model
    belongs to a different vendor and current provider is not 'public'.

    Args:
        model_id: The model ID to set as active
        force: Skip catalog validation and allow any model string

    Returns:
        SetModelResult indicating success/failure and what was changed
    """
    vendor_name: str | None = None
    provider_updated = False

    if not force:
        # Lookup model in catalog
        async with get_async_session() as session:
            stmt = (
                select(LargeLanguageModel)
                .join(LLMVendor, LargeLanguageModel.llm_vendor_id == LLMVendor.id)
                .options(selectinload(LargeLanguageModel.llm_vendor))
                .where(LargeLanguageModel.model_id == model_id)
            )
            result = await session.exec(stmt)
            model = result.first()

            if model:
                vendor_name = model.llm_vendor.name if model.llm_vendor else None
            else:
                # Model not in catalog - check if it's an Ollama model
                try:
                    from app.services.ai.domains.llm.ollama import OllamaClient

                    client = OllamaClient()
                    if await client.is_available():
                        ollama_models = await client.fetch_models()
                        if any(m.model_id == model_id for m in ollama_models):
                            vendor_name = "Ollama"
                except Exception:
                    pass  # Ollama not available, fall through to error

                # If still not found anywhere, suggest --force
                if not vendor_name:
                    return SetModelResult(
                        success=False,
                        model_id=model_id,
                        vendor=None,
                        provider_updated=False,
                        message=f"Model '{model_id}' not found in catalog. "
                        "Use --force to set anyway.",
                    )

    # Prepare updates
    updates: dict[str, str] = {"AI_MODEL": model_id}

    # Auto-detect provider from the model's vendor, but only persist a value
    # that resolves to a real AIProvider. A vendor display name like "LLM7.io"
    # must become "public", never a bogus AI_PROVIDER that would crash config
    # loading on the next boot.
    provider_value: str | None = None
    if vendor_name:
        resolved_provider = AIProvider.from_name(vendor_name)
        if resolved_provider is not None:
            provider_value = resolved_provider.value
            updates["AI_PROVIDER"] = provider_value
            provider_updated = True

    # Persist. With a catalog database the selection is a row, which every
    # process picks up at startup and this process picks up immediately -
    # no restart, no rewriting the operator's .env. Stacks without one
    # (ai_backend=memory) have nowhere to put it, so they keep writing .env
    # and take effect on the next boot.
    stored_in_db = await _store_active_selection(
        model_id=model_id, provider=provider_value
    )
    if stored_in_db:
        active_model.apply_to_settings(
            settings, model_id=model_id, provider=provider_value
        )
    else:
        update_env_file(updates)

    message = f"Switched to model '{model_id}'"
    if provider_updated:
        message += f" (provider changed to '{vendor_name}')"

    return SetModelResult(
        success=True,
        model_id=model_id,
        vendor=vendor_name,
        provider_updated=provider_updated,
        message=message,
    )


async def get_model_info(model_id: str) -> LLMDetails | None:
    """Get full details for a specific LLM model.

    Args:
        model_id: The model ID to look up

    Returns:
        LLMDetails with full model information, or None if not found
    """
    async with get_async_session() as session:
        stmt = (
            select(LargeLanguageModel)
            .join(LLMVendor, LargeLanguageModel.llm_vendor_id == LLMVendor.id)
            .options(selectinload(LargeLanguageModel.llm_vendor))
            .where(LargeLanguageModel.model_id == model_id)
        )
        result = await session.exec(stmt)
        model = result.first()

        if not model:
            return None

        # Get latest price
        price_stmt = (
            select(LLMPrice)
            .where(LLMPrice.llm_id == model.id)
            .order_by(LLMPrice.effective_date.desc())
            .limit(1)
        )
        price_result = await session.exec(price_stmt)
        price = price_result.first()

        # Get modalities
        modality_stmt = select(LLMModality).where(LLMModality.llm_id == model.id)
        modality_result = await session.exec(modality_stmt)
        modalities = modality_result.all()

        return LLMDetails(
            model_id=model.model_id,
            title=model.title,
            description=model.description,
            vendor=model.llm_vendor.name if model.llm_vendor else "Unknown",
            context_window=model.context_window,
            streamable=model.streamable,
            enabled=model.enabled,
            released_on=model.released_on.isoformat() if model.released_on else None,
            input_price=price.input_cost_per_token * 1_000_000 if price else None,
            output_price=price.output_cost_per_token * 1_000_000 if price else None,
            modalities=list({str(m.modality) for m in modalities}),
        )


def list_vendors() -> list[VendorListResult]:
    """List all LLM vendors with their model counts.

    Returns:
        List of VendorListResult sorted alphabetically by name.
    """
    from sqlmodel import func

    with Session(engine) as session:
        results = session.exec(
            select(
                LLMVendor.name,
                func.count(LargeLanguageModel.id).label("model_count"),
            )
            .join(LargeLanguageModel, isouter=True)
            .group_by(LLMVendor.id)
            .order_by(LLMVendor.name)
        ).all()

        return [
            VendorListResult(name=name, model_count=count) for name, count in results
        ]


def list_modalities() -> list[ModalityListResult]:
    """List all modalities with their model counts.

    Returns:
        List of ModalityListResult sorted alphabetically.
    """
    from sqlmodel import func

    with Session(engine) as session:
        results = session.exec(
            select(
                LLMModality.modality,
                func.count(func.distinct(LLMModality.llm_id)).label("model_count"),
            )
            .group_by(LLMModality.modality)
            .order_by(LLMModality.modality)
        ).all()

        return [
            ModalityListResult(modality=str(mod), model_count=count)
            for mod, count in results
        ]
