"""The approvals queue and its Overview pointer.

The full queue lives on Review > Approvals (cards flow as a wrapping
grid and the tab scrolls); Overview carries only a one-line banner so
proposals are never invisible but never bury the summary page either.
"""

import flet as ft

from app.components.frontend.dashboard.modals.finance_modal.pending_changes import (
    PendingChangesBanner,
    PendingChangesSection,
    pending_banner_label,
)
from tests.components.frontend._tree import rendered


class TestSectionLayout:
    def test_cards_flow_as_a_wrapping_grid(self) -> None:
        """A queue tab has vertical room: cards wrap into rows instead
        of hiding in a sideways scroll."""
        section = PendingChangesSection(page=None)

        rail = section._cards
        assert isinstance(rail, ft.Row)
        assert rail.wrap is True

    def test_a_queue_home_stays_visible_when_empty(self) -> None:
        """On Review, an empty queue says so (like every other queue
        there) instead of vanishing."""
        section = PendingChangesSection(
            page=None, empty_message="Nothing awaiting your approval."
        )
        section._render_items([])

        assert section.visible is True
        assert "Nothing awaiting your approval." in rendered(section)

    def test_the_overview_style_section_hides_when_empty(self) -> None:
        section = PendingChangesSection(page=None)
        section._render_items([])

        assert section.visible is False


class TestBanner:
    def test_the_label_counts_and_pluralizes(self) -> None:
        assert pending_banner_label(1) == (
            "1 pending change awaiting your approval"
        )
        assert pending_banner_label(3) == (
            "3 pending changes awaiting your approval"
        )

    def test_the_banner_shows_a_count_and_hides_at_zero(self) -> None:
        banner = PendingChangesBanner(page=None)

        banner.show_count(3)
        assert banner.visible is True
        assert "3 pending changes awaiting your approval" in rendered(banner)

        banner.show_count(0)
        assert banner.visible is False

    def test_the_banner_is_clickable_when_it_can_jump(self) -> None:
        jumped: list[bool] = []
        banner = PendingChangesBanner(
            page=None, on_open_review=lambda: jumped.append(True)
        )
        banner.show_count(2)

        assert banner.on_click is not None
        banner.on_click(None)
        assert jumped == [True]

    def test_without_a_jump_target_it_is_informational(self) -> None:
        banner = PendingChangesBanner(page=None)
        banner.show_count(2)

        assert banner.on_click is None
