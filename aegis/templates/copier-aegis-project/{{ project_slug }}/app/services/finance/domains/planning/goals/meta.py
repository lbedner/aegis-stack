"""What a goal IS: the metadata blob on the account, validated.

A goal is an account with a target rather than a table of its own,
so this is the whole contract - read it, write it, clear it.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

GOAL_ACCOUNT_TYPE = "goal"
GOAL_STATUSES = ("active", "paused", "reached")
_TARGET_KEY = "goal_target_amount"
_DATE_KEY = "goal_target_date"
_MONTHLY_KEY = "goal_monthly_contribution"
_STATUS_KEY = "goal_status"
_KIND_KEY = "goal_contribution_kind"
_BPS_KEY = "goal_contribution_bps"
_PRIORITY_KEY = "goal_priority"
_RULE_KEY = "goal_target_rule"
_FACTOR_KEY = "goal_target_factor"
_SCOPE_KEY = "goal_target_scope"
_GOAL_KEYS = (
    _TARGET_KEY,
    _DATE_KEY,
    _MONTHLY_KEY,
    _STATUS_KEY,
    _KIND_KEY,
    _BPS_KEY,
    _PRIORITY_KEY,
    _RULE_KEY,
    _FACTOR_KEY,
    _SCOPE_KEY,
)
CONTRIBUTION_KINDS = ("fixed", "percent_income", "surplus")
TARGET_RULES = ("fixed", "months_of_expenses")
MAX_TARGET_FACTOR = 120
DEFAULT_PRIORITY = 100
_AUTO_KEY = "goal_auto_contribute"


class GoalMeta(BaseModel):
    """An account's goal facts, parsed and validated.

    Each field's alias IS its stored ``metadata_`` key, so the model both
    parses a stored blob and serializes back to one.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    target_amount: int = Field(alias=_TARGET_KEY)  # cents, > 0
    status: str = Field(default="active", alias=_STATUS_KEY)  # one of GOAL_STATUSES
    target_date: date | None = Field(default=None, alias=_DATE_KEY)
    # cents, >= 0; fixed kind only
    monthly_contribution: int | None = Field(default=None, alias=_MONTHLY_KEY)
    # How the goal funds itself each month. ``fixed`` keeps the original
    # behaviour (declared cents, or derived from the target date);
    # ``percent_income`` re-evaluates against the month's confirmed
    # income; ``surplus`` sweeps whatever the month has left. Modes
    # (baby-steps, FIRE, 50/30/20) are just prioritized sets of these.
    contribution_kind: str = Field(default="fixed", alias=_KIND_KEY)
    # basis points, percent kind only
    contribution_bps: int | None = Field(default=None, alias=_BPS_KEY)
    priority: int = Field(default=DEFAULT_PRIORITY, alias=_PRIORITY_KEY)  # lower first
    # How ``target_amount`` was arrived at. Under a relative rule the
    # stored cents are the last resolved value, kept as the fallback for
    # a book with no figures yet; the rule plus factor are the truth.
    target_rule: str = Field(default="fixed", alias=_RULE_KEY)
    target_factor: int | None = Field(default=None, alias=_FACTOR_KEY)  # months
    # Which cash accounts the run rate is measured on. Empty means all
    # of them - a book with one checking account never has to care.
    target_scope: list[int] = Field(default_factory=list, alias=_SCOPE_KEY)


def _validated(meta: GoalMeta) -> GoalMeta:
    if meta.target_amount <= 0:
        raise ValueError(
            f"Goal target must be positive cents, got {meta.target_amount}."
        )
    if meta.status not in GOAL_STATUSES:
        raise ValueError(
            f"Unknown goal status {meta.status!r}. Known: {', '.join(GOAL_STATUSES)}."
        )
    if meta.monthly_contribution is not None and meta.monthly_contribution < 0:
        raise ValueError(
            f"Monthly contribution cannot be negative, got {meta.monthly_contribution}."
        )
    if meta.contribution_kind not in CONTRIBUTION_KINDS:
        raise ValueError(
            f"Unknown contribution kind {meta.contribution_kind!r}. "
            f"Known: {', '.join(CONTRIBUTION_KINDS)}."
        )
    if meta.target_rule not in TARGET_RULES:
        raise ValueError(
            f"Unknown target rule {meta.target_rule!r}. Known: {', '.join(TARGET_RULES)}."
        )
    if meta.target_rule == "months_of_expenses" and not (
        meta.target_factor is not None and 0 < meta.target_factor <= MAX_TARGET_FACTOR
    ):
        raise ValueError(
            "months_of_expenses needs a factor in "
            f"(0, {MAX_TARGET_FACTOR}] months; got {meta.target_factor!r}."
        )
    if meta.target_rule == "fixed" and (
        meta.target_factor is not None or meta.target_scope
    ):
        raise ValueError(
            "A fixed target takes no factor or scope; set target_rule to express one."
        )
    if meta.contribution_kind == "percent_income" and not (
        meta.contribution_bps is not None and 0 < meta.contribution_bps <= 10_000
    ):
        raise ValueError(
            "percent_income needs basis points in (0, 10000]; "
            f"got {meta.contribution_bps!r}."
        )
    return meta


def goal_metadata(metadata: dict[str, Any] | None) -> GoalMeta | None:
    """The account's ``GoalMeta``, or ``None`` when it wears no goal
    metadata (the target key is the presence marker).

    Raises ``ValueError`` on corrupt stored values - a goal with an
    unreadable target or an unknown status must fail loudly, not read as
    almost-a-goal.
    """
    if not metadata or _TARGET_KEY not in metadata:
        return None
    stored = {key: metadata[key] for key in _GOAL_KEYS if key in metadata}
    return _validated(GoalMeta.model_validate(stored))


def set_goal_metadata(
    metadata: dict[str, Any] | None,
    *,
    target_amount: int,
    target_date: date | None = None,
    monthly_contribution: int | None = None,
    status: str = "active",
    contribution_kind: str = "fixed",
    contribution_bps: int | None = None,
    priority: int = DEFAULT_PRIORITY,
    target_rule: str = "fixed",
    target_factor: int | None = None,
    target_scope: list[int] | None = None,
) -> dict[str, Any]:
    """A new metadata dict with the goal keys written (neighbours kept)."""
    meta = _validated(
        GoalMeta(
            target_amount=target_amount,
            status=status,
            target_date=target_date,
            monthly_contribution=monthly_contribution,
            contribution_kind=contribution_kind,
            contribution_bps=contribution_bps,
            priority=priority,
            target_rule=target_rule,
            target_factor=target_factor,
            target_scope=list(target_scope or []),
        )
    )
    return {**(metadata or {}), **meta.model_dump(mode="json", by_alias=True)}


def clear_goal_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """A new metadata dict with the goal keys stripped (the unflag path -
    a linked goal's account survives, wearing everything else it wore)."""
    return {k: v for k, v in (metadata or {}).items() if k not in _GOAL_KEYS}


def goal_auto_contribute(metadata: dict[str, Any] | None) -> bool:
    """Whether 's monthly job books this goal's declared amount.
    Off by default - automation is opted into, never assumed."""
    return bool((metadata or {}).get(_AUTO_KEY))


def set_auto_contribute(
    metadata: dict[str, Any] | None, enabled: bool
) -> dict[str, Any]:
    return {**(metadata or {}), _AUTO_KEY: bool(enabled)}
