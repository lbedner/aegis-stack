"""Choosing tags, and choosing where a post is syndicated."""

from collections.abc import Callable
from typing import Any

import flet as ft
from app.components.frontend.controls import (
    LabelText,
    SecondaryText,
)
from app.components.frontend.theme import AegisTheme as Theme

_SYNDICATE_PLATFORMS: list[tuple[str, str]] = [
    ("devto", "Dev.to"),
    ("hashnode", "Hashnode"),
    ("medium", "Medium"),
]


class TagPicker(ft.Container):
    """Multi-select picker for blog tags from a known list.

    Mirrors the form-field shape used elsewhere in the editor: a label
    above a control area. The control shows currently selected tags as
    removable chips and a small dropdown to add tags from the available
    set. Free-form entry is intentionally not supported — tags must be
    created in the Tags tab first.
    """

    def __init__(
        self,
        page: ft.Page,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.page = page
        self._on_change_cb = on_change
        self._available: list[dict[str, Any]] = []
        self._selected_slugs: list[str] = []
        self._chip_row = ft.Row(wrap=True, spacing=Theme.Spacing.SM)
        self._dropdown = ft.Dropdown(
            value=None,
            options=[],
            on_change=self._on_dropdown_change,
            border_radius=Theme.Components.INPUT_RADIUS,
            bgcolor=ft.Colors.SURFACE,
            border_color=ft.Colors.OUTLINE,
            focused_border_color=ft.Colors.PRIMARY,
            text_size=13,
            content_padding=ft.padding.symmetric(horizontal=12, vertical=10),
            hint_text="Add tag",
            width=180,
        )
        self._empty_hint = SecondaryText(
            "No tags yet — create one in the Tags tab.",
            size=Theme.Typography.BODY_SMALL,
        )
        self.content = ft.Column(
            [
                LabelText("Tags"),
                ft.Container(height=4),
                ft.Row(
                    [self._dropdown, self._empty_hint],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=Theme.Spacing.SM,
                ),
                ft.Container(height=Theme.Spacing.SM),
                self._chip_row,
            ],
            spacing=0,
            tight=True,
        )
        page.run_task(self._load)

    async def _load(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        try:
            data = await api.get("/api/v1/blog/tags")
        except Exception:  # noqa: BLE001
            return
        if isinstance(data, dict):
            tags = data.get("tags") or []
            if isinstance(tags, list):
                self._available = [t for t in tags if isinstance(t, dict)]
        self._refresh()

    async def reload(self) -> None:
        """Public re-fetch hook so callers can refresh after tag CRUD elsewhere."""
        await self._load()

    def _refresh(self) -> None:
        unselected = [
            t for t in self._available if t.get("slug") not in self._selected_slugs
        ]
        self._dropdown.options = [
            ft.dropdown.Option(
                key=str(t.get("slug")),
                text=str(t.get("name") or t.get("slug")),
            )
            for t in unselected
        ]
        self._dropdown.value = None
        self._dropdown.disabled = not self._available
        self._empty_hint.visible = not self._available
        self._chip_row.controls = [self._chip(slug) for slug in self._selected_slugs]
        if self.page:
            self.update()

    def _chip(self, slug: str) -> ft.Control:
        name = next(
            (
                str(t.get("name") or slug)
                for t in self._available
                if t.get("slug") == slug
            ),
            slug,
        )
        return ft.Container(
            content=ft.Row(
                [
                    ft.Text(name, size=12, color=ft.Colors.ON_SURFACE),
                    ft.GestureDetector(
                        content=ft.Icon(
                            ft.Icons.CLOSE,
                            size=12,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                        ),
                        on_tap=lambda _, s=slug: self._remove(s),
                        mouse_cursor=ft.MouseCursor.CLICK,
                    ),
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            padding=ft.padding.symmetric(horizontal=8, vertical=2),
            bgcolor=ft.Colors.with_opacity(0.10, ft.Colors.PRIMARY),
            border=ft.border.all(1, ft.Colors.PRIMARY),
            border_radius=10,
            height=22,
        )

    def _on_dropdown_change(self, e: ft.ControlEvent) -> None:
        slug = e.control.value
        if slug and slug not in self._selected_slugs:
            self._selected_slugs.append(slug)
            self._refresh()
            if self._on_change_cb is not None:
                self._on_change_cb()

    def _remove(self, slug: str) -> None:
        self._selected_slugs = [s for s in self._selected_slugs if s != slug]
        self._refresh()
        if self._on_change_cb is not None:
            self._on_change_cb()

    @property
    def tag_slugs(self) -> list[str]:
        return list(self._selected_slugs)

    def set_tag_slugs(self, slugs: list[str]) -> None:
        self._selected_slugs = list(slugs)
        self._refresh()

    def clear_tags(self) -> None:
        self.set_tag_slugs([])


class SyndicatePicker(ft.Container):
    """Toggle-chip picker for syndication targets.

    Mirrors the form-field shape used elsewhere in the editor: a label
    above a control area. Unlike TagPicker the platform set is fixed, so
    each platform renders as a single toggleable chip instead of a
    dropdown-plus-chips arrangement. The export pipeline injects the
    canonical URL regardless; these targets are routing metadata so
    platform tooling knows where each post goes.
    """

    def __init__(self, on_change: Callable[[], None] | None = None) -> None:
        super().__init__()
        self._on_change_cb = on_change
        self._selected: list[str] = []
        self._chip_row = ft.Row(wrap=True, spacing=Theme.Spacing.SM)
        self.content = ft.Column(
            [
                LabelText("Syndicate to"),
                ft.Container(height=4),
                self._chip_row,
                ft.Container(height=4),
                SecondaryText(
                    "Exports include a canonical link back to the original post.",
                    size=Theme.Typography.BODY_SMALL,
                ),
            ],
            spacing=0,
            tight=True,
        )
        self._refresh()

    def _refresh(self) -> None:
        self._chip_row.controls = [
            self._chip(slug, label) for slug, label in _SYNDICATE_PLATFORMS
        ]
        if self.page:
            self.update()

    def _chip(self, slug: str, label: str) -> ft.Control:
        selected = slug in self._selected
        return ft.GestureDetector(
            content=ft.Container(
                content=ft.Text(
                    label,
                    size=12,
                    color=(
                        ft.Colors.ON_SURFACE
                        if selected
                        else ft.Colors.ON_SURFACE_VARIANT
                    ),
                ),
                padding=ft.padding.symmetric(horizontal=10, vertical=2),
                bgcolor=(
                    ft.Colors.with_opacity(0.10, ft.Colors.PRIMARY)
                    if selected
                    else ft.Colors.TRANSPARENT
                ),
                border=ft.border.all(
                    1, ft.Colors.PRIMARY if selected else ft.Colors.OUTLINE
                ),
                border_radius=10,
                height=22,
            ),
            on_tap=lambda _, s=slug: self._toggle(s),
            mouse_cursor=ft.MouseCursor.CLICK,
        )

    def _toggle(self, slug: str) -> None:
        if slug in self._selected:
            self._selected = [s for s in self._selected if s != slug]
        else:
            self._selected.append(slug)
        # Keep storage order stable (platform order, not click order) so
        # repeated saves don't churn the JSON column.
        self._selected = [s for s, _ in _SYNDICATE_PLATFORMS if s in self._selected]
        self._refresh()
        if self._on_change_cb is not None:
            self._on_change_cb()

    @property
    def targets(self) -> list[str]:
        return list(self._selected)

    def set_targets(self, targets: list[str]) -> None:
        # Unknown slugs are dropped defensively; the picker can only
        # represent the platforms it knows how to render.
        wanted = set(targets)
        self._selected = [s for s, _ in _SYNDICATE_PLATFORMS if s in wanted]
        self._refresh()
