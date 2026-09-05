"""Reading the state of the LLM catalog, as opposed to changing it.

The sync service writes the catalog; these answer what is in it - the
counts ``llm status`` prints, and the two yes/no questions the startup
hook asks before deciding whether to sync at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session, func, select

from app.services.ai.models.llm import (
    LargeLanguageModel,
    LLMDeployment,
    LLMOrg,
    LLMPrice,
)


@dataclass
class CatalogStats:
    """Statistics for the LLM catalog."""

    vendor_count: int
    model_count: int
    deployment_count: int
    price_count: int
    top_vendors: list[tuple[str, int]]


def catalog_is_populated(session: Session) -> bool:
    """Whether any model is already in the catalog.

    The webserver startup hook syncs only into an EMPTY catalog; once
    populated, the scheduler's periodic job owns freshness. Before this
    guard every startup (and every dev hot-reload) re-ran a full sync -
    tens of thousands of queries against a catalog that was already
    current.
    """
    first = session.exec(select(LargeLanguageModel.id).limit(1)).first()
    return first is not None


def ollama_models_present(session: Session) -> bool:
    """Whether any locally served Ollama tag is in the catalog.

    The remote catalog never carries a local tag, and the picker's
    ``usable`` filter shows only vendors the install can call - with no
    API keys, Ollama alone. A fresh Ollama stack therefore opened an
    empty picker until someone knew to run ``llm sync --source ollama``.
    The startup hook syncs local tags when this says none are there.
    """
    first = session.exec(
        select(LargeLanguageModel.id)
        .join(LLMOrg, LargeLanguageModel.served_by_org_id == LLMOrg.id)
        .where(LLMOrg.name == "ollama")
        .limit(1)
    ).first()
    return first is not None


def get_catalog_stats(session: Session) -> CatalogStats:
    """Get LLM catalog statistics.

    Args:
        session: Database session.

    Returns:
        CatalogStats with counts and top vendors.
    """
    vendor_count = session.exec(select(func.count()).select_from(LLMOrg)).one()
    model_count = session.exec(
        select(func.count()).select_from(LargeLanguageModel)
    ).one()
    deployment_count = session.exec(
        select(func.count()).select_from(LLMDeployment)
    ).one()
    price_count = session.exec(select(func.count()).select_from(LLMPrice)).one()

    # Get top vendors by model count
    top_vendors_result = session.exec(
        select(
            LLMOrg.name,
            func.count(LargeLanguageModel.id).label("model_count"),
        )
        # Two keys point at llm_org - who made a model and who serves it -
        # so the join has to say which. "Top vendors" means who SERVES.
        .join(
            LargeLanguageModel,
            LargeLanguageModel.served_by_org_id == LLMOrg.id,
            isouter=True,
        )
        .group_by(LLMOrg.id)
        .order_by(func.count(LargeLanguageModel.id).desc())
        .limit(10)
    ).all()

    return CatalogStats(
        vendor_count=vendor_count,
        model_count=model_count,
        deployment_count=deployment_count,
        price_count=price_count,
        top_vendors=list(top_vendors_result),
    )
