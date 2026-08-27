"""API payloads for the Flet component suite, built from the REAL schemas.

Hand-typed dicts made the two suites strangers: the backend could rename
a key, both suites stay green, and the live UI breaks. Every builder
here constructs the actual response model and ships ``model_dump()``
output, so schema drift snaps a frontend test instead of the app.

Keyword overrides go through the model, so a typo'd field name is a
validation error, not a silently ignored dict key.
"""

from typing import Any


def budget_line(**overrides: Any) -> dict[str, Any]:
    from app.services.finance.schemas import BudgetLineResponse

    defaults: dict[str, Any] = {
        "id": 1,
        "category_id": 10,
        "category_name": "Food & Dining:Groceries",
        "payee_key": None,
        "payee_label": None,
        "allocated_amount": 100_000,
        "spent_amount": 40_000,
        "status": "good",
    }
    return BudgetLineResponse(**{**defaults, **overrides}).model_dump(mode="json")


def bucket(
    name: str, lines: list[dict[str, Any]] | None = None, **overrides: Any
) -> dict[str, Any]:
    from app.services.finance.schemas import BudgetBucketResponse

    rows = lines or []
    defaults: dict[str, Any] = {
        "name": name,
        "total_allocated": sum(r["allocated_amount"] for r in rows),
        "total_spent": sum(r["spent_amount"] for r in rows),
        "lines": rows,
    }
    return BudgetBucketResponse(**{**defaults, **overrides}).model_dump(mode="json")


def budget_stats(**overrides: Any) -> dict[str, Any]:
    from app.services.finance.schemas import BudgetStatsResponse

    defaults: dict[str, Any] = {
        "flexible_spent": 40_000,
        "flexible_allocated": 100_000,
        "days_left_in_period": 7,
        "flexible_count": 1,
        "on_track_count": 1,
        "over_budget_count": 0,
        "over_budget_labels": [],
        "fixed_total": 0,
        "fixed_count": 0,
    }
    return BudgetStatsResponse(**{**defaults, **overrides}).model_dump(mode="json")


def budget_summary(
    *,
    buckets: list[dict[str, Any]] | None = None,
    stats: dict[str, Any] | None = None,
    trims: list[dict[str, Any]] | None = None,
    period_month: int = 202608,
) -> dict[str, Any]:
    from app.services.finance.schemas import BudgetSummaryResponse

    return BudgetSummaryResponse(
        period_month=period_month,
        buckets=buckets
        if buckets is not None
        else [bucket("flexible", [budget_line()])],
        stats=stats or budget_stats(),
        trims=trims or [],
    ).model_dump(mode="json")
