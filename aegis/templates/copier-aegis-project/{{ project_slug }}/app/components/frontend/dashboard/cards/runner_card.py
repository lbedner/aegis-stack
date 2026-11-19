"""Runner component card: how many runs wait, how many a runner has, and
whether a runner is listening."""

from typing import Any

import flet as ft

from app.components.runner.health import RunnerFact
from app.components.runner.models import ASKED, CLAIMED, LABELS
from app.core.constants import ComponentName
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_title

from .counts_card import counts_card


def counts(metadata: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        (LABELS[ASKED], str(metadata.get(RunnerFact.WAITING, 0))),
        (LABELS[CLAIMED], str(metadata.get(RunnerFact.RUNNING, 0))),
        ("Listening", "Yes" if metadata.get(RunnerFact.LISTENING) else "No"),
    ]


class RunnerCard:
    """The queue's counts and whether a runner answers it, side by side."""

    def __init__(self, component_data: ComponentStatus) -> None:
        self.component_data = component_data

    def build(self) -> ft.Container:
        """Build the runner card."""
        return counts_card(
            self.component_data,
            ComponentName.RUNNER,
            get_component_title(ComponentName.RUNNER),
            counts(self.component_data.metadata or {}),
        )
