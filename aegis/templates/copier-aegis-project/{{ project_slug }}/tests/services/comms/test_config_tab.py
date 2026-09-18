"""Both configuration tabs edit the same way, so they share one base.

``EmailTab`` and ``TwilioTab`` each carried a byte-identical
``_build_content`` / ``_toggle_edit_mode`` / ``_cancel_edit`` and the
same six lines of constructor before them. Two copies of a contract is
two places for it to drift: a fix to how cancel behaves would land on
one tab and not the other.

What the base owns is the edit-mode contract itself - which mode the
tab is in, and that changing it rebuilds. What goes in each mode stays
with the tab that knows its own fields.
"""

from __future__ import annotations

import pytest

from app.components.frontend.dashboard.modals.comms_modal import EmailTab, TwilioTab
from app.components.frontend.dashboard.modals.comms_modal.config_tab import (
    EditableConfigTab,
)

METADATA = {
    "resend_from_email": "noreply@example.com",
    "twilio_phone_number": "+15551234567",
}

TABS = [EmailTab, TwilioTab]


@pytest.mark.parametrize("tab_class", TABS)
class TestTheEditModeContract:
    def test_a_tab_starts_in_view_mode(self, tab_class: type) -> None:
        assert tab_class(METADATA)._edit_mode is False

    def test_toggling_enters_edit_mode(self, tab_class: type) -> None:
        tab = tab_class(METADATA)

        tab._toggle_edit_mode()

        assert tab._edit_mode is True

    def test_toggling_again_leaves_it(self, tab_class: type) -> None:
        tab = tab_class(METADATA)
        tab._toggle_edit_mode()

        tab._toggle_edit_mode()

        assert tab._edit_mode is False

    @pytest.mark.asyncio
    async def test_cancelling_returns_to_view_mode(self, tab_class: type) -> None:
        """Cancel is not a toggle: from edit mode it must land in view
        mode, and from view mode it must stay there."""
        tab = tab_class(METADATA)
        tab._toggle_edit_mode()

        await tab._cancel_edit()

        assert tab._edit_mode is False

    def test_changing_mode_rebuilds_the_content(self, tab_class: type) -> None:
        """The reason the contract exists. A tab that flips the flag and
        does not rebuild shows the old mode's controls."""
        tab = tab_class(METADATA)
        before = tab.content

        tab._toggle_edit_mode()

        assert tab.content is not before

    def test_it_is_one_contract_and_not_two(self, tab_class: type) -> None:
        assert issubclass(tab_class, EditableConfigTab)
