"""The runner card and modal in Flet: how many runs wait, how many a
runner has, and whether one is listening."""

from unittest.mock import MagicMock

from app.components.frontend.dashboard.cards.runner_card import RunnerCard, counts
from app.components.frontend.dashboard.modals.runner_modal import RunnerDetailDialog
from app.components.runner.health import RunnerFact
from app.core.constants import ComponentName
from app.services.system.models import ComponentStatus, ComponentStatusType
from tests.components.frontend._tree import rendered

RUNNER = ComponentStatus(
    name=ComponentName.RUNNER,
    status=ComponentStatusType.WARNING,
    message="Runs wait on no runner.",
    metadata={
        RunnerFact.WAITING: 3,
        RunnerFact.RUNNING: 0,
        RunnerFact.LISTENING: False,
    },
)


def test_each_figure_is_under_its_own_name() -> None:
    assert counts(RUNNER.metadata) == [
        ("Waiting", "3"),
        ("Running", "0"),
        ("Listening", "No"),
    ]


def test_the_card_counts_the_queue() -> None:
    shown = rendered(RunnerCard(RUNNER).build())

    assert "Runner" in shown
    assert "Waiting" in shown and "Listening" in shown


def test_the_dialog_shows_the_queue_and_why_it_warns() -> None:
    shown = rendered(RunnerDetailDialog(RUNNER, MagicMock()))

    assert "Waiting" in shown
    assert RUNNER.message in shown
