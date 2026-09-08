"""Reads for the LLM domain: the catalog, its prices, the active
selection, and the usage ledger.

Sync and async both live here because the callers do: the CLI, the
usage rollups and the catalog context run on a plain ``Session``;
request paths on an ``AsyncSession``. The annotation on each function
says which. Statement builders only - no business logic, no writes.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Integer, func
from sqlalchemy.orm import selectinload
from sqlmodel import Session, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.ai.models.llm import (
    LargeLanguageModel,
    LLMActiveSelection,
    LLMModality,
    LLMOrg,
    LLMPrice,
    LLMUsage,
)
from app.services.shared.queries import owner_clause

# --- Catalog -----------------------------------------------------------


async def llm_by_model_id(
    session: AsyncSession, model_id: str
) -> LargeLanguageModel | None:
    return (
        await session.exec(
            select(LargeLanguageModel).where(LargeLanguageModel.model_id == model_id)
        )
    ).first()


async def llm_with_vendor(
    session: AsyncSession, model_id: str
) -> LargeLanguageModel | None:
    """The catalog row with its SERVING org loaded."""
    stmt = (
        select(LargeLanguageModel)
        .join(LLMOrg, LargeLanguageModel.served_by_org_id == LLMOrg.id)
        .options(selectinload(LargeLanguageModel.served_by))
        .where(LargeLanguageModel.model_id == model_id)
    )
    return (await session.exec(stmt)).first()


async def latest_price_for(session: AsyncSession, llm_id: int) -> LLMPrice | None:
    return (
        await session.exec(
            select(LLMPrice)
            .where(LLMPrice.llm_id == llm_id)
            .order_by(LLMPrice.effective_date.desc())
            .limit(1)
        )
    ).first()


def latest_price_for_model(session: Session, model_name: str) -> LLMPrice | None:
    """Current price row for a bare model name, or None if uncataloged."""
    llm = session.exec(
        select(LargeLanguageModel).where(LargeLanguageModel.model_id == model_name)
    ).first()
    if llm is None:
        return None
    return session.exec(
        select(LLMPrice)
        .where(LLMPrice.llm_id == llm.id)
        .order_by(LLMPrice.effective_date.desc())
    ).first()


async def modalities_for(session: AsyncSession, llm_id: int) -> list[str]:
    rows = (
        await session.exec(select(LLMModality).where(LLMModality.llm_id == llm_id))
    ).all()
    return sorted({str(row.modality) for row in rows})


async def catalog_models(
    session: AsyncSession,
    *,
    pattern: str | None = None,
    vendor: str | None = None,
    vendors: Sequence[str] | None = None,
    modality: str | None = None,
    include_disabled: bool = False,
    limit: int | None = None,
) -> list[LargeLanguageModel]:
    """Catalog rows newest-first with both orgs loaded.

    ``vendor`` is a substring match, ``vendors`` an exact whitelist.
    ``limit`` caps the SQL result; a caller capping per vendor leaves it
    unset, since a global cap under newest-first ordering would let one
    vendor's fresh catalog starve the others.
    """
    stmt = (
        select(LargeLanguageModel)
        .join(LLMOrg, LargeLanguageModel.served_by_org_id == LLMOrg.id)
        .options(
            selectinload(LargeLanguageModel.served_by),
            selectinload(LargeLanguageModel.made_by),
        )
    )
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
        stmt = stmt.where(LLMOrg.name.in_(vendors))
    if modality:
        stmt = stmt.join(
            LLMModality, LargeLanguageModel.id == LLMModality.llm_id
        ).where(LLMModality.modality == modality)
    if not include_disabled:
        stmt = stmt.where(LargeLanguageModel.enabled == True)  # noqa: E712
    stmt = stmt.order_by(
        LargeLanguageModel.released_on.desc().nulls_last(),
        LargeLanguageModel.model_id,
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list((await session.exec(stmt)).all())


async def latest_prices_by_llm_ids(
    session: AsyncSession, llm_ids: Iterable[int]
) -> dict[int, LLMPrice]:
    """Newest price per model, one query."""
    wanted = list(llm_ids)
    if not wanted:
        return {}
    rows = (
        await session.exec(
            select(LLMPrice)
            .where(LLMPrice.llm_id.in_(wanted))
            .order_by(LLMPrice.llm_id, LLMPrice.effective_date.desc())
        )
    ).all()
    latest: dict[int, LLMPrice] = {}
    for price in rows:
        latest.setdefault(price.llm_id, price)
    return latest


def vendor_model_counts(session: Session) -> Sequence[tuple[str, int]]:
    """(org name, models served) for every org, name-sorted.

    Two keys point at ``llm_org`` (who made a model, who serves it); this
    is the SERVING surface, so the join says so.
    """
    return session.exec(
        select(LLMOrg.name, func.count(LargeLanguageModel.id))
        .join(
            LargeLanguageModel,
            LargeLanguageModel.served_by_org_id == LLMOrg.id,
            isouter=True,
        )
        .group_by(LLMOrg.id)
        .order_by(LLMOrg.name)
    ).all()


def modality_model_counts(session: Session) -> Sequence[tuple[str, int]]:
    """(modality, distinct models) for every modality, name-sorted."""
    return session.exec(
        select(LLMModality.modality, func.count(func.distinct(LLMModality.llm_id)))
        .group_by(LLMModality.modality)
        .order_by(LLMModality.modality)
    ).all()


def orgs_named(session: Session, names: Iterable[str]) -> Sequence[LLMOrg]:
    return session.exec(select(LLMOrg).where(LLMOrg.name.in_(list(names)))).all()


def models_served_by(
    session: Session, org_ids: Iterable[int]
) -> Sequence[LargeLanguageModel]:
    """Every model the given orgs serve, with prices, deployments and
    modalities loaded - the catalog context's one fetch."""
    return session.exec(
        select(LargeLanguageModel)
        .where(LargeLanguageModel.served_by_org_id.in_(list(org_ids)))
        .options(
            selectinload(LargeLanguageModel.llm_prices),
            selectinload(LargeLanguageModel.deployments),
            selectinload(LargeLanguageModel.modalities),
        )
    ).all()


# --- Active selection --------------------------------------------------


async def active_selection(
    session: AsyncSession, *, owner_user_id: int | None = None
) -> LLMActiveSelection | None:
    return (
        await session.exec(
            select(LLMActiveSelection).where(
                owner_clause(LLMActiveSelection.owner_user_id, owner_user_id)
            )
        )
    ).first()


async def active_selections(session: AsyncSession) -> list[LLMActiveSelection]:
    return list((await session.exec(select(LLMActiveSelection))).all())


# --- Usage ledger ------------------------------------------------------


def _usage_window(
    stmt: Any,
    *,
    user_id: str | None,
    start_time: datetime | None,
    end_time: datetime | None,
) -> Any:
    if user_id:
        stmt = stmt.where(LLMUsage.user_id == user_id)
    if start_time:
        stmt = stmt.where(LLMUsage.timestamp >= start_time)
    if end_time:
        stmt = stmt.where(LLMUsage.timestamp <= end_time)
    return stmt


def usage_totals(
    session: Session,
    *,
    user_id: str | None,
    start_time: datetime | None,
    end_time: datetime | None,
) -> Any:
    """One row: input_tokens, output_tokens, total_cost, total_requests,
    success_count - or None when the window is empty."""
    stmt = select(
        func.coalesce(func.sum(LLMUsage.input_tokens), 0).label("input_tokens"),
        func.coalesce(func.sum(LLMUsage.output_tokens), 0).label("output_tokens"),
        func.coalesce(func.sum(LLMUsage.total_cost), 0.0).label("total_cost"),
        func.count(LLMUsage.id).label("total_requests"),
        func.sum(func.cast(LLMUsage.success, Integer)).label("success_count"),
    )
    return session.exec(
        _usage_window(stmt, user_id=user_id, start_time=start_time, end_time=end_time)
    ).first()


def usage_by_model(
    session: Session,
    *,
    user_id: str | None,
    start_time: datetime | None,
    end_time: datetime | None,
) -> Sequence[Any]:
    """Per-model rows (model_id, title, vendor, vendor_color, requests,
    tokens, cost), busiest first. LEFT-joined so ledger rows for models
    no longer in the catalog still count."""
    stmt = (
        select(
            LLMUsage.model_id,
            func.coalesce(LargeLanguageModel.title, LLMUsage.model_id).label("title"),
            func.coalesce(LLMOrg.name, "unknown").label("vendor"),
            func.coalesce(LLMOrg.color, "#808080").label("vendor_color"),
            func.count(LLMUsage.id).label("requests"),
            func.coalesce(
                func.sum(LLMUsage.input_tokens + LLMUsage.output_tokens), 0
            ).label("tokens"),
            func.coalesce(func.sum(LLMUsage.total_cost), 0.0).label("cost"),
        )
        .outerjoin(LargeLanguageModel, LLMUsage.model_id == LargeLanguageModel.model_id)
        .outerjoin(LLMOrg, LargeLanguageModel.served_by_org_id == LLMOrg.id)
        .group_by(
            LLMUsage.model_id,
            LargeLanguageModel.title,
            LLMOrg.name,
            LLMOrg.color,
        )
        .order_by(func.count(LLMUsage.id).desc())
    )
    return session.exec(
        _usage_window(stmt, user_id=user_id, start_time=start_time, end_time=end_time)
    ).all()


def recent_usage(
    session: Session,
    *,
    user_id: str | None,
    start_time: datetime | None,
    end_time: datetime | None,
    limit: int,
) -> Sequence[Any]:
    """The newest ledger rows (timestamp, model_id, input_tokens,
    output_tokens, total_cost, success, action)."""
    stmt = (
        select(
            LLMUsage.timestamp,
            LLMUsage.model_id,
            LLMUsage.input_tokens,
            LLMUsage.output_tokens,
            LLMUsage.total_cost,
            LLMUsage.success,
            LLMUsage.action,
        )
        .order_by(LLMUsage.timestamp.desc())
        .limit(limit)
    )
    return session.exec(
        _usage_window(stmt, user_id=user_id, start_time=start_time, end_time=end_time)
    ).all()


async def spend_since(
    session: AsyncSession, *, user_id: str, action_prefix: str, since: datetime
) -> float:
    """Ledgered cost for one user's action family since ``since``."""
    row = await session.exec(
        select(func.coalesce(func.sum(LLMUsage.total_cost), 0.0))
        .where(LLMUsage.user_id == user_id)
        .where(LLMUsage.action.like(f"{action_prefix}%"))  # type: ignore[attr-defined]
        .where(LLMUsage.timestamp >= since)
    )
    return float(row.one())
