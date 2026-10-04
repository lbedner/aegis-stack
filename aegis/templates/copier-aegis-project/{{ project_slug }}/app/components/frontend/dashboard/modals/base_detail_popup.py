"""
Base Detail Popup for Component Modals

Extends BasePopup with consistent modal structure for component details,
including title, status badge, scrollable sections, and close button.
"""

import flet as ft

from app.components.frontend.controls import H2Text, SecondaryText, StatusTag
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system import ui_runtime
from app.services.system.models import ComponentStatus, ComponentStatusType

from .base_popup import BasePopup
from .container_section import ContainerSection
from .logs_section import LogsSection
from .modal_constants import ModalLayout

# What every component with a container behind it shows, in order.
RUNTIME_SECTIONS = (("Container", ContainerSection), ("Logs", LogsSection))


class BaseDetailPopup(BasePopup):
    """
    Base class for all component detail popups.

    Provides consistent title formatting, status badges, layout structure,
    and close behavior. Child classes need only provide sections and
    customization parameters.

    Usage:
        class MyDetailPopup(BaseDetailPopup):
            def __init__(self, component_data: ComponentStatus, page: ft.Page):
                sections = [
                    MyOverviewSection(component_data.metadata),
                    ft.Divider(height=20, color=ft.Colors.OUTLINE_VARIANT),
                    MyStatsSection(component_data),
                ]

                super().__init__(
                    page=page,
                    component_data=component_data,
                    title_text="My Component Details",
                    sections=sections,
                )
    """

    def __init__(
        self,
        page: ft.Page,
        component_data: ComponentStatus,
        title_text: str,
        sections: list[ft.Control],
        subtitle_text: str | None = None,
        status_detail: str | None = None,
        width: int = ModalLayout.DEFAULT_WIDTH,
        height: int = ModalLayout.DEFAULT_HEIGHT,
        scrollable: bool = True,
    ) -> None:
        """
        Initialize the base detail popup.

        Args:
            component_data: ComponentStatus containing component health and metrics
            title_text: Title text (e.g., "Scheduler Details")
            sections: List of section controls to display in modal body
            subtitle_text: Optional subtitle text (e.g., "Web Framework")
            status_detail: Optional detail text for status badge (e.g., "2/3 online")
            width: Modal width in pixels (default: 900)
            height: Modal height in pixels (default: 700)
            scrollable: Whether to wrap sections in scrollable container
                        (default: True). Set to False for tabs with own scrolling.
        """
        self.component_data = component_data
        self.title_text = title_text
        self.subtitle_text = subtitle_text
        self.status_detail = status_detail
        self._status_tag: StatusTag | None = None
        self._title_row: ft.Row | None = None

        # Every component with a container behind it shows that container and
        # its logs: as tabs where the body is a tab bar, below the sections
        # otherwise.
        if (key := ui_runtime.page_of(component_data.name)) is not None:
            tabbed = not scrollable and sections and isinstance(sections[0], ft.Tabs)
            for title, section in RUNTIME_SECTIONS:
                if tabbed:
                    tab = ft.Column([section(key)], scroll=ft.ScrollMode.AUTO)
                    sections[0].tabs.append(ft.Tab(text=title, content=tab))
                else:
                    divider = ft.Divider(height=20, color=ft.Colors.OUTLINE_VARIANT)
                    sections = [*sections, divider, section(key)]

        # Build sections container - scrollable or direct based on parameter
        if scrollable:
            sections_container = ft.Container(
                content=ft.Column(
                    sections,
                    spacing=0,
                    scroll=ft.ScrollMode.AUTO,
                ),
                expand=True,
            )
        else:
            # For tabs or content that manages its own scrolling
            sections_container = ft.Container(
                content=sections[0]
                if len(sections) == 1
                else ft.Column(sections, spacing=0),
                expand=True,
            )

        # Build modal content with title, sections, and close button
        modal_content = ft.Column(
            controls=[
                # Title with status badge
                self._create_title(),
                # Sections (scrollable or not based on parameter)
                sections_container,
                # Actions
                ft.Container(
                    content=ft.Row(
                        [
                            PulseButton(
                                on_click_callable=self._handle_close,
                                text="Close",
                                variant="muted",
                                compact=True,
                            )
                        ],
                        alignment=ft.MainAxisAlignment.END,
                    ),
                    padding=ft.padding.only(top=10),
                ),
            ],
            spacing=10,
            expand=True,
        )

        # Wrap in container with padding
        content_container = ft.Container(
            content=modal_content,
            padding=ModalLayout.CONTENT_PADDING,
            width=width,
            height=height,
        )

        # Initialize BasePopup with styled container
        super().__init__(
            page=page,
            content=content_container,
            width=width,
            height=height,
            border=ft.border.all(1, ft.Colors.OUTLINE),
            border_radius=Theme.Components.CARD_RADIUS,
            bgcolor=ft.Colors.SURFACE,
            shadow=ft.BoxShadow(
                spread_radius=0,
                blur_radius=20,
                color=ft.Colors.with_opacity(0.3, ft.Colors.BLACK),
                offset=ft.Offset(0, 4),
            ),
        )

    def _create_title(self) -> ft.Control:
        """
        Create the modal title with optional subtitle and status badge.

        Returns a Row containing the title text (with optional subtitle)
        and a status badge using theme-aware colors.
        """
        # Build title column with optional subtitle
        title_controls: list[ft.Control] = [H2Text(self.title_text)]
        if self.subtitle_text:
            title_controls.append(SecondaryText(self.subtitle_text))

        title_column = ft.Column(
            title_controls,
            spacing=2,
        )

        # Create and store status tag reference for later updates
        self._status_tag = StatusTag(
            status=self.component_data.status, detail=self.status_detail
        )

        self._title_row = ft.Row(
            [
                title_column,
                self._status_tag,
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        return self._title_row

    def update_status(
        self, status: ComponentStatusType, detail: str | None = None
    ) -> None:
        """
        Update the status tag in the modal header.

        Args:
            status: New component status
            detail: Optional detail text for the status badge
        """
        if self._title_row and self._status_tag:
            # Create new status tag with updated values
            new_tag = StatusTag(status=status, detail=detail)

            # Replace the old tag in the title row
            self._title_row.controls[-1] = new_tag
            self._status_tag = new_tag

            # Update the component data for consistency
            self.component_data.status = status
            self.status_detail = detail

    def _handle_close_click(self, e: ft.ControlEvent) -> None:
        """Handle close button click."""
        self.hide()
        if e.page:
            e.page.update()

    async def _handle_close(self) -> None:
        """Close the popup (PulseButton's async no-arg contract)."""
        self.hide()
        if self.page:
            self.page.update()


class PagePopup(BaseDetailPopup):
    """An Overseer page outside the health tree (Logs, Deployments) as a
    popup the header opens (``open_on``): a subclass names it (``TITLE``,
    ``SUBTITLE``) and builds its one section; no status badge, since no
    health check stands behind it."""

    TITLE: str
    SUBTITLE: str

    def __init__(self, page: ft.Page) -> None:
        super().__init__(
            page=page,
            component_data=ComponentStatus(
                name=self.TITLE.lower(), status=ComponentStatusType.INFO, message=""
            ),
            title_text=self.TITLE,
            subtitle_text=self.SUBTITLE,
            sections=[self.section()],
        )
        if self._status_tag is not None:
            self._status_tag.visible = False

    def section(self) -> ft.Control:
        raise NotImplementedError

    @classmethod
    def open_on(cls, page: ft.Page) -> None:
        """Show the page's one popup of this kind, adding it the first time."""
        popup = next((c for c in page.overlay if isinstance(c, cls)), None)
        if popup is None:
            popup = cls(page)
            page.overlay.append(popup)
        popup.show()
        page.update()
