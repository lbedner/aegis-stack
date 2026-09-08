"""Reads for sources, metric types, metric rows and records."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.insights.models import (
    InsightMetric,
    InsightMetricType,
    InsightRecord,
    InsightSource,
)

MetricOrder = Literal["date_asc", "date_desc", "value_desc"]


def _scoped(stmt: Any, project_id: int | None) -> Any:
    """``WHERE project_id = ...`` when scoped; the column only exists on
    per-user builds, and only a scoped call ever names it."""
    if project_id is None:
        return stmt
    return stmt.where(InsightMetric.project_id == project_id)  # type: ignore[attr-defined]


# --- Sources and types -------------------------------------------------


async def sources(
    db: AsyncSession, *, enabled_only: bool = False
) -> list[InsightSource]:
    stmt = select(InsightSource).order_by(InsightSource.id)
    if enabled_only:
        stmt = stmt.where(InsightSource.enabled == True)  # noqa: E712
    return list((await db.exec(stmt)).all())


async def source_by_key(db: AsyncSession, key: str) -> InsightSource | None:
    return (
        await db.exec(select(InsightSource).where(InsightSource.key == key))
    ).first()


async def metric_type_by_key(
    db: AsyncSession, key: str, *, source_id: int | None = None
) -> InsightMetricType | None:
    stmt = select(InsightMetricType).where(InsightMetricType.key == key)
    if source_id is not None:
        stmt = stmt.where(InsightMetricType.source_id == source_id)
    return (await db.exec(stmt)).first()


async def metric_types(
    db: AsyncSession, *, source_id: int | None = None
) -> list[InsightMetricType]:
    stmt = select(InsightMetricType)
    if source_id is not None:
        stmt = stmt.where(InsightMetricType.source_id == source_id)
    return list((await db.exec(stmt.order_by(InsightMetricType.id))).all())


async def metric_types_by_keys(
    db: AsyncSession, keys: Iterable[str]
) -> dict[str, InsightMetricType]:
    rows = (
        await db.exec(
            select(InsightMetricType).where(InsightMetricType.key.in_(list(keys)))  # type: ignore[union-attr]
        )
    ).all()
    return {row.key: row for row in rows}


# --- Metric rows -------------------------------------------------------


async def metrics_where(
    db: AsyncSession,
    type_ids: Iterable[int | None],
    *,
    period: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    before: datetime | None = None,
    order: MetricOrder | None = "date_asc",
    limit: int | None = None,
    offset: int | None = None,
    project_id: int | None = None,
) -> list[InsightMetric]:
    """Metric rows for the given types. ``since``/``until`` are inclusive,
    ``before`` is exclusive. One statement serves every per-key read."""
    ids = [type_id for type_id in type_ids if type_id is not None]
    if not ids:
        return []
    stmt = select(InsightMetric).where(InsightMetric.metric_type_id.in_(ids))  # type: ignore[union-attr]
    if period is not None:
        stmt = stmt.where(InsightMetric.period == period)
    if since is not None:
        stmt = stmt.where(InsightMetric.date >= since)
    if until is not None:
        stmt = stmt.where(InsightMetric.date <= until)
    if before is not None:
        stmt = stmt.where(InsightMetric.date < before)
    if order == "date_asc":
        stmt = stmt.order_by(InsightMetric.date.asc())  # type: ignore[union-attr]
    elif order == "date_desc":
        stmt = stmt.order_by(InsightMetric.date.desc())  # type: ignore[union-attr]
    elif order == "value_desc":
        stmt = stmt.order_by(InsightMetric.value.desc())  # type: ignore[union-attr]
    if offset is not None:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list((await db.exec(_scoped(stmt, project_id))).all())


async def metric_on(
    db: AsyncSession,
    type_id: int,
    *,
    date: datetime,
    period: str,
    project_id: int | None = None,
) -> InsightMetric | None:
    """The one row a non-event period dedups on: (type, date, period),
    per project when scoped."""
    stmt = select(InsightMetric).where(
        InsightMetric.metric_type_id == type_id,
        InsightMetric.date == date,
        InsightMetric.period == period,
    )
    return (await db.exec(_scoped(stmt, project_id))).first()


async def metrics_joined(
    db: AsyncSession,
    *,
    source_key: str | None = None,
    metric_keys: Iterable[str] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[InsightMetric]:
    """Metric rows filtered by source key and metric-type keys, newest
    first - the CLI's ad-hoc query surface."""
    stmt = select(InsightMetric).join(InsightMetricType)
    if source_key is not None:
        stmt = stmt.join(InsightSource).where(InsightSource.key == source_key)
    if metric_keys is not None:
        stmt = stmt.where(InsightMetricType.key.in_(list(metric_keys)))  # type: ignore[union-attr]
    if since is not None:
        stmt = stmt.where(InsightMetric.date >= since)
    if until is not None:
        stmt = stmt.where(InsightMetric.date <= until)
    stmt = stmt.order_by(InsightMetric.date.desc())  # type: ignore[union-attr]
    return list((await db.exec(stmt)).all())


async def sum_metric_values(
    db: AsyncSession, type_id: int, *, period: str, since: datetime
) -> float:
    stmt = select(func.coalesce(func.sum(InsightMetric.value), 0.0)).where(
        InsightMetric.metric_type_id == type_id,
        InsightMetric.date >= since,
        InsightMetric.period == period,
    )
    return float((await db.exec(stmt)).one())


async def latest_created_at(
    db: AsyncSession, type_ids: Iterable[int | None]
) -> datetime | None:
    ids = [type_id for type_id in type_ids if type_id is not None]
    if not ids:
        return None
    stmt = select(func.max(InsightMetric.created_at)).where(
        InsightMetric.metric_type_id.in_(ids)  # type: ignore[union-attr]
    )
    return (await db.exec(stmt)).first()


async def metric_count(db: AsyncSession) -> int:
    return (await db.exec(select(func.count()).select_from(InsightMetric))).one()


# --- Records -----------------------------------------------------------


async def records(db: AsyncSession) -> list[InsightRecord]:
    stmt = select(InsightRecord).order_by(InsightRecord.date_achieved.desc())  # type: ignore[union-attr]
    return list((await db.exec(stmt)).all())


async def record_for_type(db: AsyncSession, type_id: int) -> InsightRecord | None:
    return (
        await db.exec(
            select(InsightRecord).where(InsightRecord.metric_type_id == type_id)
        )
    ).first()
