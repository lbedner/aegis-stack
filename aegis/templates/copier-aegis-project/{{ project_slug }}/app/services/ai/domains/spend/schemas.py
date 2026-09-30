"""The shapes the spend reads hand back."""

from datetime import date

from pydantic import BaseModel, ConfigDict


class ActionSpend(BaseModel):
    """What one ledger action cost in a window."""

    model_config = ConfigDict(frozen=True)

    calls: int
    cost: float


class ModelSpend(BaseModel):
    """What one model cost in a window (``title`` when the catalog has it)."""

    model_config = ConfigDict(frozen=True)

    model_id: str
    title: str | None
    cost: float


class SpendLedger(BaseModel):
    """Every figure a cost report is built from, for one window: a month
    (Overview, Breakdown) or the last 90 days (Projections)."""

    model_config = ConfigDict(frozen=True)

    daily: dict[date, float]
    actions: dict[str, ActionSpend]
    users: int
    models: list[ModelSpend]
    voice: dict[str, float]
