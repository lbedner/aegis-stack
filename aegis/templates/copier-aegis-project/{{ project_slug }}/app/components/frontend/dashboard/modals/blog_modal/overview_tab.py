"""The Overview tab: what has been published lately."""

from typing import Any

import flet as ft
from app.components.frontend.controls import (
    H1Text,
    LabelText,
    SecondaryText,
    Tag,
)
from app.components.frontend.controls.markdown import copyable_markdown
from app.components.frontend.dashboard.modals.blog_modal.formatting import (
    _format_date,
    _post_tag_slugs,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatus

from ..modal_sections import EmptyStatePlaceholder


class OverviewTab(ft.Container):
    """Reader-style blog overview: latest post body in the main area, recent
    posts as a clickable list in a sidebar.

    Content-first instead of metric-first. Counts already show up in the
    Posts tab table and the CLI ``status`` command, so we don't repeat them
    here.
    """

    _SIDEBAR_WIDTH = 280
    _SIDEBAR_LIMIT = 10

    def __init__(self, page: ft.Page, component_data: ComponentStatus) -> None:
        super().__init__()
        self.page = page
        self._posts: list[dict[str, Any]] = []
        self._current_id: int | None = None

        self._main_area = ft.Container(
            content=EmptyStatePlaceholder("Loading..."),
            expand=True,
            padding=ft.padding.all(Theme.Spacing.LG),
        )
        self._sidebar_list = ft.Column(
            spacing=2,
            scroll=ft.ScrollMode.AUTO,
            tight=True,
        )
        self._sidebar = ft.Container(
            content=ft.Column(
                [
                    LabelText("Recent posts"),
                    ft.Container(height=Theme.Spacing.SM),
                    self._sidebar_list,
                ],
                spacing=0,
                expand=True,
            ),
            width=self._SIDEBAR_WIDTH,
            padding=ft.padding.all(Theme.Spacing.MD),
            border=ft.border.only(left=ft.border.BorderSide(1, ft.Colors.OUTLINE)),
        )
        self.content = ft.Row(
            [self._main_area, self._sidebar],
            expand=True,
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        self.padding = ft.padding.all(0)
        self.expand = True
        page.run_task(self._load)

    async def _load(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        # Public endpoint (only published) — Overview is the reader view.
        data = await api.get(
            "/api/v1/blog/posts",
            params={"page_size": self._SIDEBAR_LIMIT},
        )
        posts: list[dict[str, Any]] = []
        if isinstance(data, dict) and isinstance(data.get("posts"), list):
            posts = data["posts"]
        self._posts = posts

        if not posts:
            self._main_area.content = EmptyStatePlaceholder("No published posts yet.")
            self._sidebar_list.controls = []
        else:
            self._show_post(posts[0])
            self._render_sidebar()
        if self.page:
            self.update()

    def _show_post(self, post: dict[str, Any]) -> None:
        title = str(post.get("title") or "")
        body = str(post.get("content") or "")
        published = _format_date(post.get("published_at"))
        author = str(post.get("author_name") or "").strip()

        meta_bits: list[str] = []
        if published and published != "-":
            meta_bits.append(published)
        if author:
            meta_bits.append(author)
        meta_text = "  ·  ".join(meta_bits)

        header_children: list[ft.Control] = [H1Text(title)]
        if meta_text:
            header_children.append(ft.Container(height=4))
            header_children.append(SecondaryText(meta_text))

        tag_slugs = _post_tag_slugs(post)
        if tag_slugs:
            header_children.append(ft.Container(height=Theme.Spacing.SM))
            header_children.append(
                ft.Row(
                    [Tag(slug, color=Theme.Colors.PRIMARY) for slug in tag_slugs],
                    spacing=6,
                    alignment=ft.MainAxisAlignment.START,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    tight=True,
                )
            )

        body_control = copyable_markdown(body)

        self._main_area.content = ft.Column(
            [
                *header_children,
                ft.Container(height=Theme.Spacing.LG),
                body_control,
            ],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            spacing=0,
        )
        try:
            self._current_id = int(post.get("id"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            self._current_id = None

        if self._main_area.page:
            self._main_area.update()
        # Re-render sidebar so the highlight follows the selection.
        if self._sidebar_list.controls:
            self._render_sidebar()

    def _render_sidebar(self) -> None:
        self._sidebar_list.controls = [self._sidebar_item(post) for post in self._posts]
        if self._sidebar_list.page:
            self._sidebar_list.update()

    def _sidebar_item(self, post: dict[str, Any]) -> ft.Control:
        title = str(post.get("title") or "(untitled)")
        date = _format_date(post.get("published_at"))
        try:
            post_id = int(post.get("id"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            post_id = -1
        is_current = post_id == self._current_id

        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        title,
                        size=13,
                        color=ft.Colors.ON_SURFACE,
                        weight=(
                            ft.FontWeight.W_600 if is_current else ft.FontWeight.W_400
                        ),
                        no_wrap=False,
                        max_lines=2,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    ft.Text(
                        date if date and date != "-" else "",
                        size=11,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                ],
                spacing=2,
                tight=True,
            ),
            padding=ft.padding.symmetric(
                horizontal=Theme.Spacing.SM,
                vertical=Theme.Spacing.XS,
            ),
            border_radius=Theme.Components.INPUT_RADIUS,
            bgcolor=(
                ft.Colors.with_opacity(0.08, Theme.Colors.PRIMARY)
                if is_current
                else None
            ),
            on_click=lambda _, p=post: self._show_post(p),
            ink=True,
        )
