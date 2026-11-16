"""The shapes the spend reads hand back."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, computed_field


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


class KindModelSpend(BaseModel):
    """One model under one kind of use (a model call, a live call, a
    transcription, speech) in a window: how often, how long, how many
    tokens, what it cost."""

    model_config = ConfigDict(frozen=True)

    kind: str
    model_id: str
    uses: int
    seconds: float
    tokens: int
    cost: float


class CallSpend(BaseModel):
    """One live call: itself (its voice, by the second or by its tokens)
    and the answers its agent gave during it."""

    model_config = ConfigDict(frozen=True)

    started: datetime
    model_id: str
    seconds: float
    call_cost: float
    answers_cost: float
    success: bool

    @computed_field
    @property
    def total(self) -> float:
        """The call and its answers: a field of the call's, so every
        reader (``ai costs --json``, the Costs section) gets it."""
        return self.call_cost + self.answers_cost
