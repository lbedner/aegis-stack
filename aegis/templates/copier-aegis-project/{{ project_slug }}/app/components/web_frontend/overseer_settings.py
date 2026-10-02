"""Context for the Overseer Settings page: every ``Configurable`` setting
(``app.core.saved_settings``), grouped by the code that reads it, with its
value, where it comes from and its default.

The Secrets page's machinery carries it: the same store and rules, the same
row actions, and the same dialog (``routes/partials/overseer_secrets.py``)
to save a value. A saved value applies when the app restarts, since code
reads these through ``settings``; one set in ``.env`` wins and is changed
there."""

from typing import Any

from app.core import secrets
from app.services.system.models import ComponentStatus

from .overseer_nav import NavItem, SectionRequest
from .overseer_secrets import base_row, page_context
from .rendering import status_cell

SECTIONS = ((None, {"overview": "Overview"}),)

ITEM = NavItem(
    group="settings",
    name="settings",
    title="Settings",
    url="/overseer/settings",
    status="",
    component=ComponentStatus(name="settings", message=""),
)


def _row(row: secrets.SecretStatus, writable: bool) -> dict[str, Any]:
    state = status_cell(row.state, "ok" if row.is_set else "muted")
    return base_row(row) | {
        "state": state,
        "shown": {"text": row.in_effect or "", "missing": False},
        "default": row.default or "",
        "editable": writable and row.source != secrets.ENV,
        "set_label": "Change",
    }


async def section_context(
    section: str, component: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    """The settings by owner, and whether they can be saved here."""
    return page_context(await secrets.status(setting=True), _row) | {
        "section_subtitle": "What the app is configured with, apart from its credentials.",
    }
