"""Trimming a budget back to fit: what to cut, and by how much."""

from __future__ import annotations

from app.services.finance.schemas import (
    BudgetLineResponse,
    BudgetTrimPlan,
    BudgetTrimResponse,
    GoalAsk,
)


def plan_budget_trims(
    lines: list[BudgetLineResponse],
    *,
    deficit: int,
    goals: list[GoalAsk] | None = None,
) -> BudgetTrimPlan:
    """Deterministic cuts that close a negative month.

    The rules, stated once so the UI and any later decision layer share
    them. TIER 1: pause a goal before cutting a budget - a dream
    deferred beats groceries squeezed. Goals pause largest-need-first
    (fewest dreams disturbed), each recovering its whole monthly need
    (a pause is all-or-nothing), until the gap is covered or goals run
    out. TIER 2: a line's FLOOR is what it has already spent this period
    (a budget below money already gone is a lie, not a plan); cuts
    distribute proportionally to each line's slack above its floor,
    largest-remainder rounded so they sum exactly. Whatever neither tier
    covers is returned as ``residual`` - the part of the gap that
    belongs to bills or income. Every row carries ``kind``
    (``pause_goal`` | ``cut_budget``).
    """
    if deficit <= 0:
        return BudgetTrimPlan()
    pauses: list[BudgetTrimResponse] = []
    for goal in sorted(
        goals or [],
        key=lambda g: (-g.monthly_need, g.label.casefold()),
    ):
        if deficit <= 0:
            break
        need = goal.monthly_need
        if need <= 0:
            continue
        pauses.append(
            BudgetTrimResponse(
                kind="pause_goal",
                account_id=goal.account_id,
                label=goal.label or "Goal",
                recovered=need,
            )
        )
        deficit -= need
    if deficit <= 0:
        return BudgetTrimPlan(cuts=pauses)
    slack = [
        (line, max(0, line.allocated_amount - max(line.spent_amount, 0)))
        for line in lines
    ]
    slack = [(line, room) for line, room in slack if room > 0]
    total_slack = sum(room for _line, room in slack)
    if total_slack == 0:
        return BudgetTrimPlan(cuts=pauses, residual=deficit)
    take = min(deficit, total_slack)
    raw = [(line, room, take * room / total_slack) for line, room in slack]
    cuts = [(line, room, int(share)) for line, room, share in raw]
    remainder = take - sum(cut for _l, _r, cut in cuts)
    # Largest fractional parts absorb the leftover cents, never past slack.
    by_fraction = sorted(
        range(len(cuts)), key=lambda i: raw[i][2] - cuts[i][2], reverse=True
    )
    for i in by_fraction:
        if remainder <= 0:
            break
        line, room, cut = cuts[i]
        if cut < room:
            cuts[i] = (line, room, cut + 1)
            remainder -= 1
    return BudgetTrimPlan(
        cuts=pauses
        + [
            BudgetTrimResponse(
                kind="cut_budget",
                id=line.id,
                label=line.category_name or line.payee_label or "Overall",
                category_id=line.category_id,
                payee_key=line.payee_key,
                allocated_amount=line.allocated_amount,
                spent_amount=line.spent_amount,
                cut=cut,
                suggested_amount=line.allocated_amount - cut,
            )
            for line, _room, cut in cuts
            if cut > 0
        ],
        residual=deficit - take,
    )
