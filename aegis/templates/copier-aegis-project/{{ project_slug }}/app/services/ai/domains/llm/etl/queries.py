"""Reads for the catalog ETL, as opposed to the writes that change it.

The sync service writes the catalog; these answer what is in it - the
counts ``llm status`` prints, the two yes/no questions the startup hook
asks before deciding whether to sync at all, and the lookups the sync
and the lab resolver make. Sync sessions throughout: the ETL runs on
one.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TypeVar

from sqlmodel import Session, SQLModel, col, func, or_, select

from app.services.ai.models.llm import (
    LargeLanguageModel,
    LLMDeployment,
    LLMOrg,
    LLMPrice,
)

RowT = TypeVar("RowT", bound=SQLModel)


def all_rows(session: Session, table: type[RowT]) -> Sequence[RowT]:
    """Every row of one table - the sync loads whole tables into caches."""
    return session.exec(select(table)).all()


def llms_by_model_ids(
    session: Session, model_ids: Sequence[str]
) -> dict[str, LargeLanguageModel]:
    """The catalog rows for these ids, in one read - keyed by model_id."""
    rows = session.exec(
        select(LargeLanguageModel).where(
            col(LargeLanguageModel.model_id).in_(model_ids)
        )
    ).all()
    return {row.model_id: row for row in rows}


def orgs_to_mark(
    session: Session, fetched: Iterable[str], shipped: Iterable[str]
) -> Sequence[LLMOrg]:
    """The provider orgs whose logo the marks step may write: a fetched
    one's while it has none, a shipped one's always (it costs no fetch)."""
    return session.exec(
        select(LLMOrg).where(
            or_(
                col(LLMOrg.slug).in_(set(fetched)) & col(LLMOrg.icon_b64).is_(None),
                col(LLMOrg.slug).in_(set(shipped)),
            )
        )
    ).all()


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


def local_models_present(session: Session, engine: str) -> bool:
    """Whether a model ``engine`` serves is in the catalog.

    The remote catalog never carries a local tag, and the picker's
    ``usable`` filter shows only vendors the install can call - with no
    API keys, the local engine alone. A fresh local stack therefore opened
    an empty picker until someone knew to run ``llm sync --source local``.
    The startup hook syncs local tags when this says none are there, asked
    for the engine it runs: an install switched engines still holds the
    old one's tags, and none of the new one's.
    """
    first = session.exec(
        select(LargeLanguageModel.id)
        .join(LLMOrg, LargeLanguageModel.served_by_org_id == LLMOrg.id)
        .where(LLMOrg.name == engine)
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
