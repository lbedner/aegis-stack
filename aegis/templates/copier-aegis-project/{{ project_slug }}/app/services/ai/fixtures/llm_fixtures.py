"""Writing the LLM catalog seed into the database.

One loader per table, each skipping rows that are already there, so a
re-run is a no-op rather than a conflict. The data itself is in
``llm_catalog``, which is also where the four tables are explained.
"""

from datetime import UTC, datetime

from app.core.log import logger
from app.services.ai.models.llm import (
    LargeLanguageModel,
    LLMDeployment,
    LLMOrg,
    LLMPrice,
)
from sqlmodel import Session, select

from .llm_catalog import DEPLOYMENTS, MODELS, PRICES, VENDORS

# =============================================================================
# Loading Functions
# =============================================================================


def _load_vendors(session: Session) -> int:
    """Load vendor fixtures, skipping existing."""
    count = 0
    for vendor_data in VENDORS:
        existing = session.exec(
            select(LLMOrg).where(LLMOrg.name == vendor_data["name"])
        ).first()
        if not existing:
            # The vendor key IS the slug for a catalog-sourced org.
            vendor = LLMOrg(slug=vendor_data["name"], **vendor_data)
            session.add(vendor)
            count += 1
            logger.debug(f"Added vendor: {vendor_data['name']}")
    session.commit()
    return count


def _load_models(session: Session) -> int:
    """Load model fixtures, skipping existing."""
    count = 0

    # Get vendor ID mapping
    vendors = session.exec(select(LLMOrg)).all()
    vendor_map = {v.name: v.id for v in vendors}

    for vendor_name, models in MODELS.items():
        vendor_id = vendor_map.get(vendor_name)
        if not vendor_id:
            logger.warning(f"Vendor not found for models: {vendor_name}")
            continue

        for model_data in models:
            existing = session.exec(
                select(LargeLanguageModel).where(
                    LargeLanguageModel.model_id == model_data["model_id"]
                )
            ).first()

            if not existing:
                model = LargeLanguageModel(
                    served_by_org_id=vendor_id,
                    **model_data,
                )
                session.add(model)
                count += 1
                logger.debug(f"Added model: {model_data['model_id']}")

    session.commit()
    return count


def _load_deployments(session: Session) -> int:
    """Load deployment fixtures, skipping existing."""
    count = 0

    # Get vendor and model mappings
    vendors = session.exec(select(LLMOrg)).all()
    vendor_map = {v.name: v.id for v in vendors}

    models = session.exec(select(LargeLanguageModel)).all()
    model_map = {m.model_id: m.id for m in models}

    for vendor_name, deployments in DEPLOYMENTS.items():
        vendor_id = vendor_map.get(vendor_name)
        if not vendor_id:
            logger.warning(f"Vendor not found for deployments: {vendor_name}")
            continue

        for deployment_data in deployments:
            model_id = model_map.get(deployment_data["model_id"])
            if not model_id:
                logger.warning(
                    f"Model not found for deployment: {deployment_data['model_id']}"
                )
                continue

            # Check if deployment already exists
            existing = session.exec(
                select(LLMDeployment).where(
                    LLMDeployment.org_id == vendor_id,
                    LLMDeployment.llm_id == model_id,
                )
            ).first()

            if not existing:
                deployment = LLMDeployment(
                    org_id=vendor_id,
                    llm_id=model_id,
                    speed=deployment_data.get("speed", 50),
                    intelligence=deployment_data.get("intelligence", 50),
                    reasoning=deployment_data.get("reasoning", 50),
                )
                session.add(deployment)
                count += 1
                logger.debug(
                    f"Added deployment: {vendor_name} -> {deployment_data['model_id']}"
                )

    session.commit()
    return count


def _load_prices(session: Session) -> int:
    """Load price fixtures, skipping existing."""
    count = 0
    effective_date = datetime.now(UTC)

    # Get vendor and model mappings
    vendors = session.exec(select(LLMOrg)).all()
    vendor_map = {v.name: v.id for v in vendors}

    models = session.exec(select(LargeLanguageModel)).all()
    model_map = {m.model_id: m.id for m in models}

    for (vendor_name, model_id), price_data in PRICES.items():
        vendor_id = vendor_map.get(vendor_name)
        llm_id = model_map.get(model_id)

        if not vendor_id:
            logger.warning(f"Vendor not found for price: {vendor_name}")
            continue
        if not llm_id:
            logger.warning(f"Model not found for price: {model_id}")
            continue

        # Check if price already exists for this vendor-model pair
        existing = session.exec(
            select(LLMPrice).where(
                LLMPrice.org_id == vendor_id,
                LLMPrice.llm_id == llm_id,
            )
        ).first()

        if not existing:
            # Convert from per-1M-tokens to per-token
            price = LLMPrice(
                org_id=vendor_id,
                llm_id=llm_id,
                input_cost_per_token=price_data["input"] / 1_000_000,
                output_cost_per_token=price_data["output"] / 1_000_000,
                effective_date=effective_date,
            )
            session.add(price)
            count += 1
            logger.debug(f"Added price: {vendor_name} + {model_id}")

    session.commit()
    return count


def load_all_llm_fixtures(session: Session) -> dict[str, int]:
    """Load all LLM fixtures in correct order.

    Loading order matters due to foreign key dependencies:
    1. Vendors (no dependencies)
    2. Models (depends on vendors for ownership)
    3. Deployments (depends on vendors and models)
    4. Prices (depends on vendors and models)

    Skips any records that already exist (duplicate detection).

    Args:
        session: Database session

    Returns:
        dict with counts: {"vendors": N, "models": N, "deployments": N, "prices": N}
    """
    logger.info("Loading LLM fixtures...")

    vendors_added = _load_vendors(session)
    models_added = _load_models(session)
    deployments_added = _load_deployments(session)
    prices_added = _load_prices(session)

    result = {
        "vendors": vendors_added,
        "models": models_added,
        "deployments": deployments_added,
        "prices": prices_added,
    }

    logger.info(
        f"LLM fixtures loaded: {vendors_added} vendors, {models_added} models, "
        f"{deployments_added} deployments, {prices_added} prices"
    )

    return result
