"""The browser card and modal in Flet: where the server is and which
Playwright client talks to it."""

from unittest.mock import MagicMock

from app.components.browser.health import BrowserFact
from app.components.frontend.dashboard.cards.browser_card import BrowserCard
from app.components.frontend.dashboard.modals.browser_modal import BrowserDetailDialog
from app.core.constants import ComponentName
from app.services.system.models import ComponentStatus, ComponentStatusType
from tests.components.frontend._tree import rendered

BROWSER = ComponentStatus(
    name=ComponentName.BROWSER,
    status=ComponentStatusType.HEALTHY,
    message="Browser server reachable",
    metadata={BrowserFact.ENDPOINT: "ws://browser:3000/", BrowserFact.CLIENT: "1.63.0"},
)


def test_the_card_names_the_server_and_the_client() -> None:
    shown = rendered(BrowserCard(BROWSER).build())

    assert "Browser" in shown
    assert "ws://browser:3000/" in shown
    assert "1.63.0" in shown


def test_the_dialog_shows_the_connection() -> None:
    shown = rendered(BrowserDetailDialog(BROWSER, MagicMock()))

    assert "ws://browser:3000/" in shown
    assert "1.63.0" in shown
    assert "Browser server reachable" in shown
