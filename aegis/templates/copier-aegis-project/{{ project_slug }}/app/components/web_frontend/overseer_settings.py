"""Context for the Overseer Settings page: every ``Configurable`` setting
(``app.core.saved_settings``), grouped by the code that reads it, with its
value, where it comes from and its default.

The Secrets page's machinery carries it: the same store and rules, the same
row actions, and the same dialog (``routes/partials/overseer_secrets.py``)
to save a value. A saved value applies when the app restarts, since code
reads these through ``settings``; one set in ``.env`` wins and is changed
there."""

from typing import Any

from app.core import saved_settings, secrets
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_title

from .overseer_nav import NavItem, SectionRequest
from .overseer_secrets import base_row, page_context, shown
from .rendering import status_cell

# The section a component's or service's page gets when it has settings
# (``Configurable`` owner: its registry key); this page has every group.
SECTION = {"settings": "Settings"}
# This page is that one section, with every group (no sub-menu).
SECTIONS = ((None, SECTION),)

ITEM = NavItem(
    group="settings",
    name="settings",
    title="Settings",
    url="/overseer/settings",
    status="",
    component=ComponentStatus(name="settings", message=""),
)


def _row(row: secrets.SecretStatus, writable: bool) -> dict[str, Any]:
    source = status_cell(row.state, "ok" if row.is_set else "muted")
    value = shown(row, row.in_effect or "", False, source)
    return base_row(row) | {
        # Its default beside where it comes from, once something else is set.
        "shown": value | {"default": (row.default or "") if row.is_set else ""},
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


def owns(key: str) -> bool:
    """Whether this stack has settings owned by ``key`` (a registry key)."""
    return key in saved_settings.owners()


async def owned_context(key: str) -> dict[str, Any]:
    """A component's or service's own Settings section: its group alone."""
    title = get_component_title(key)
    rows = [row for row in await secrets.status(setting=True) if row.owner == title]
    return page_context(rows, _row) | {
        "section_subtitle": "Overseer > Settings lists every group.",
    }
