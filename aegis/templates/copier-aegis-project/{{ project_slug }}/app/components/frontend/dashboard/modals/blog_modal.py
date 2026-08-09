"""Blog service detail modal."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import flet as ft
from app.components.frontend.controls import (
    ActionMenu,
    ActionMenuItem,
    ConfirmDialog,
    DataTable,
    DataTableColumn,
    FormDropdown,
    FormTextField,
    H1Text,
    LabelText,
    SecondaryText,
    SectionCard,
    Tag,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.snack_bar import (
    ErrorSnackBar,
    SuccessSnackBar,
    WarningSnackBar,
)
from app.components.frontend.controls.tabs import PulseTabs
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle, get_component_title

from ..cards.card_utils import get_status_detail
from .base_detail_popup import BaseDetailPopup
from .modal_sections import EmptyStatePlaceholder


def _status_color(status: str) -> str:
    colors = {
        "draft": Theme.Colors.WARNING,
        "published": Theme.Colors.SUCCESS,
        "archived": ft.Colors.ON_SURFACE_VARIANT,
    }
    return colors.get(status, ft.Colors.ON_SURFACE_VARIANT)


def _format_date(value: str | None) -> str:
    """Render an ISO timestamp as a human-readable relative or absolute date.

    Recent timestamps render as "just now" / "5m ago" / "3h ago" / "2d ago";
    anything older than a week falls back to "Mon D, YYYY" (e.g. "May 7, 2026").
    """
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value.split("T", 1)[0]
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    seconds = int((datetime.now(UTC) - dt).total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    if seconds < 7 * 86400:
        return f"{seconds // 86400}d ago"
    return dt.strftime("%b %d, %Y").replace(" 0", " ")


def _post_tag_slugs(post: dict[str, Any]) -> list[str]:
    tags = post.get("tags", [])
    if not isinstance(tags, list):
        return []
    return [
        str(tag.get("slug"))
        for tag in tags
        if isinstance(tag, dict) and tag.get("slug")
    ]


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
            border=ft.border.only(
                left=ft.border.BorderSide(1, ft.Colors.OUTLINE)
            ),
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
            self._main_area.content = EmptyStatePlaceholder(
                "No published posts yet."
            )
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
                    [
                        Tag(slug, color=Theme.Colors.PRIMARY)
                        for slug in tag_slugs
                    ],
                    spacing=6,
                    alignment=ft.MainAxisAlignment.START,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    tight=True,
                )
            )

        body_control = ft.Markdown(
            value=body,
            selectable=True,
            extension_set=ft.MarkdownExtensionSet.GITHUB_FLAVORED,
            auto_follow_links=True,
        )

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
        self._sidebar_list.controls = [
            self._sidebar_item(post) for post in self._posts
        ]
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


class PostsTab(ft.Container):
    """Post listing and workflow actions."""

    def __init__(
        self,
        page: ft.Page,
        on_edit: Callable[[dict[str, Any]], None],
    ) -> None:
        super().__init__()
        self.page = page
        self._on_edit = on_edit
        self._status_filter = FormDropdown(
            label="Status",
            value="all",
            width=180,
            options=[
                ("all", "All"),
                ("draft", "Draft"),
                ("published", "Published"),
                ("archived", "Archived"),
            ],
            on_change=lambda _: self.page.run_task(self._load),
        )
        self._table_container = ft.Container(
            content=EmptyStatePlaceholder("Loading posts..."),
            expand=True,
        )
        # Hidden file picker for the Import flow. Lives in page.overlay so
        # the modal containing this tab can reach it.
        self._file_picker = ft.FilePicker(on_result=self._on_import_picked)
        if self._file_picker not in page.overlay:
            page.overlay.append(self._file_picker)
        self.content = ft.Column(
            [
                ft.Row(
                    [
                        self._status_filter,
                        ft.Row(
                            [
                                ft.PopupMenuButton(
                                    icon=ft.Icons.DOWNLOAD,
                                    icon_color=ft.Colors.ON_SURFACE_VARIANT,
                                    tooltip="Export posts",
                                    items=[
                                        ft.PopupMenuItem(
                                            text="Markdown (.zip)",
                                            on_click=lambda _: self.page.launch_url(
                                                "/api/v1/blog/export?format=markdown"
                                            ),
                                        ),
                                        ft.PopupMenuItem(
                                            text="JSON",
                                            on_click=lambda _: self.page.launch_url(
                                                "/api/v1/blog/export?format=json"
                                            ),
                                        ),
                                    ],
                                ),
                                ft.TextButton(
                                    "Import",
                                    icon=ft.Icons.UPLOAD,
                                    on_click=lambda _: self._file_picker.pick_files(
                                        allow_multiple=False,
                                        allowed_extensions=[
                                            "md",
                                            "markdown",
                                            "zip",
                                            "json",
                                        ],
                                    ),
                                    style=ft.ButtonStyle(
                                        color=ft.Colors.ON_SURFACE_VARIANT
                                    ),
                                ),
                                ft.TextButton(
                                    "Refresh",
                                    icon=ft.Icons.REFRESH,
                                    on_click=lambda _: self.page.run_task(
                                        self._load
                                    ),
                                    style=ft.ButtonStyle(
                                        color=ft.Colors.ON_SURFACE_VARIANT
                                    ),
                                ),
                            ],
                            spacing=4,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                self._table_container,
            ],
            spacing=Theme.Spacing.MD,
            expand=True,
        )
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True
        page.run_task(self._load)

    async def _load(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        params: dict[str, Any] = {"page_size": 50}
        status = self._status_filter.value
        if status and status != "all":
            params["status"] = status
        data = await api.get("/api/v1/blog/admin/posts", params=params)
        posts = []
        if isinstance(data, dict) and isinstance(data.get("posts"), list):
            posts = data["posts"]
        self._render_posts(posts)

    def _on_import_picked(self, e: ft.FilePickerResultEvent) -> None:
        """Forward the picker callback into an async import task."""
        if not e.files:
            return
        self.page.run_task(self._do_import, e.files[0])

    async def _do_import(self, file: Any) -> None:
        """Read the picked file and POST it to /blog/import."""
        from app.components.frontend.state.session_state import get_session_state

        if not file.path:
            ErrorSnackBar(
                "Cannot read picked file (no local path)."
            ).launch(self.page)
            return
        try:
            with open(file.path, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            ErrorSnackBar(f"Read failed: {exc}").launch(self.page)
            return

        name = file.name.lower()
        if name.endswith(".zip"):
            mime = "application/zip"
        elif name.endswith(".json"):
            mime = "application/json"
        elif name.endswith((".md", ".markdown")):
            mime = "text/markdown"
        else:
            ErrorSnackBar(
                "Unsupported file type. Use .md, .zip, or .json."
            ).launch(self.page)
            return

        api = get_session_state(self.page).api_client
        result = await api.post_multipart(
            "/api/v1/blog/import",
            files={"file": (file.name, data, mime)},
            params={"on_conflict": "skip"},
        )
        if not isinstance(result, dict):
            ErrorSnackBar("Import failed.").launch(self.page)
            return

        SuccessSnackBar(

                f"Imported: {result.get('created', 0)} created, "
                f"{result.get('updated', 0)} updated, "
                f"{result.get('skipped', 0)} skipped, "
                f"{result.get('failed', 0)} failed."

        ).launch(self.page)
        await self._load()

    def _render_posts(self, posts: list[dict[str, Any]]) -> None:
        columns = [
            DataTableColumn("Title", width=260, style="primary"),
            DataTableColumn("Status", width=120),
            DataTableColumn("Created", width=110, style="secondary"),
            DataTableColumn("Updated", width=110, style="secondary"),
            DataTableColumn("Tags", width=170, style="secondary"),
            DataTableColumn("Actions", width=80),
        ]
        rows = []
        for post in posts:
            status = str(post.get("status", "draft"))
            rows.append(
                [
                    str(post.get("title", "-")),
                    # Wrap in a tight Row so the Tag chip only consumes the
                    # width of its text instead of stretching to fill the
                    # 120px column cell.
                    ft.Row(
                        [Tag(status.title(), color=_status_color(status))],
                        tight=True,
                        alignment=ft.MainAxisAlignment.START,
                    ),
                    _format_date(post.get("created_at")),
                    _format_date(post.get("updated_at")),
                    ", ".join(_post_tag_slugs(post)) or "-",
                    self._action_buttons(post),
                ]
            )
        self._table_container.content = DataTable(
            columns=columns,
            rows=rows,
            scroll_height=520,
            empty_message="No posts yet",
        )
        if self.page:
            self._table_container.update()

    def _action_buttons(self, post: dict[str, Any]) -> ft.Control:
        post_id = int(post["id"])
        status = str(post.get("status", "draft"))

        items: list[ft.PopupMenuItem] = [
            ActionMenuItem("Edit", ft.Icons.EDIT, lambda _: self._on_edit(post)),
        ]
        if status != "published":
            items.append(
                ActionMenuItem(
                    "Publish",
                    ft.Icons.UPLOAD,
                    lambda _: self.page.run_task(
                        self._post_action, post_id, "publish"
                    ),
                )
            )
        if status != "archived":
            items.append(
                ActionMenuItem(
                    "Archive",
                    ft.Icons.ARCHIVE,
                    lambda _: self.page.run_task(
                        self._post_action, post_id, "archive"
                    ),
                )
            )
        items.append(ft.PopupMenuItem())
        items.append(
            ActionMenuItem(
                "Delete",
                ft.Icons.DELETE_OUTLINE,
                lambda _: self._confirm_delete(post),
                destructive=True,
            )
        )
        return ActionMenu(items)

    async def _post_action(self, post_id: int, action: str) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        await api.post(f"/api/v1/blog/posts/{post_id}/{action}")
        await self._load()

    def _confirm_delete(self, post: dict[str, Any]) -> None:
        post_id = int(post["id"])
        title = str(post.get("title") or "this post").strip() or "this post"

        async def _do_delete() -> None:
            await self._delete_post(post_id)

        ConfirmDialog(
            page=self.page,
            title="Delete post?",
            message=f'"{title}" will be permanently removed. This cannot be undone.',
            confirm_text="Delete",
            destructive=True,
            on_confirm=_do_delete,
        ).show()

    async def _delete_post(self, post_id: int) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        await api.delete(f"/api/v1/blog/posts/{post_id}")
        await self._load()


class TagsTab(ft.Container):
    """Tag management tab."""

    def __init__(self, page: ft.Page) -> None:
        super().__init__()
        self.page = page
        self._name = FormTextField(label="Name", width=280)
        self._slug = FormTextField(label="Slug", width=240)
        self._table_container = ft.Container(
            content=EmptyStatePlaceholder("Loading tags..."),
            expand=True,
        )
        self.content = ft.Column(
            [
                ft.Row(
                    [
                        self._name,
                        self._slug,
                        PulseButton(
                            on_click_callable=self._create_tag,
                            text="Add Tag",
                            variant="teal",
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.END,
                ),
                self._table_container,
            ],
            spacing=Theme.Spacing.MD,
            expand=True,
        )
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True
        page.run_task(self._load)

    async def _load(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        data = await api.get("/api/v1/blog/tags")
        tags = []
        if isinstance(data, dict) and isinstance(data.get("tags"), list):
            tags = data["tags"]
        self._render_tags(tags)

    def _render_tags(self, tags: list[dict[str, Any]]) -> None:
        columns = [
            DataTableColumn("Name", width=260, style="primary"),
            DataTableColumn("Slug", width=260, style="secondary"),
            DataTableColumn("Created", width=140, style="secondary"),
            DataTableColumn("Actions", width=80),
        ]
        rows = [
            [
                tag.get("name", "-"),
                tag.get("slug", "-"),
                _format_date(tag.get("created_at")),
                self._tag_action_menu(tag),
            ]
            for tag in tags
        ]
        self._table_container.content = DataTable(
            columns=columns,
            rows=rows,
            scroll_height=560,
            empty_message="No tags yet",
        )
        if self.page:
            self._table_container.update()

    async def _create_tag(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        name = self._name.value or ""
        if not name.strip():
            return
        api = get_session_state(self.page).api_client
        payload = {
            "name": name.strip(),
            "slug": (self._slug.value or "").strip() or None,
        }
        await api.post("/api/v1/blog/tags", json=payload)
        self._name.value = ""
        self._slug.value = ""
        await self._load()

    def _tag_action_menu(self, tag: dict[str, Any]) -> ft.Control:
        return ActionMenu(
            [
                ActionMenuItem(
                    "Delete",
                    ft.Icons.DELETE_OUTLINE,
                    lambda _: self._confirm_delete_tag(tag),
                    destructive=True,
                ),
            ]
        )

    def _confirm_delete_tag(self, tag: dict[str, Any]) -> None:
        tag_id = int(tag["id"])
        name = str(tag.get("name") or tag.get("slug") or "this tag").strip() or "this tag"

        async def _do_delete() -> None:
            await self._delete_tag(tag_id)

        ConfirmDialog(
            page=self.page,
            title="Delete tag?",
            message=f'"{name}" will be removed from all posts. This cannot be undone.',
            confirm_text="Delete",
            destructive=True,
            on_confirm=_do_delete,
        ).show()

    async def _delete_tag(self, tag_id: int) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        await api.delete(f"/api/v1/blog/tags/{tag_id}")
        await self._load()


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


# Platforms the export frontmatter understands (see
# app/services/blog/models.py ``syndicate_targets``): slug -> display label.
_SYNDICATE_PLATFORMS: list[tuple[str, str]] = [
    ("devto", "Dev.to"),
    ("hashnode", "Hashnode"),
    ("medium", "Medium"),
]


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


class EditorTab(ft.Container):
    """Create and edit blog posts."""

    def __init__(
        self,
        page: ft.Page,
        on_change: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        super().__init__()
        self.page = page
        self._on_change_callback = on_change
        self._post_id: int | None = None
        self._slug_manual = False
        self._advanced_visible = False
        self._dirty = False
        self._posts_cache: list[dict[str, Any]] = []
        self._post_picker = FormDropdown(
            label="Switch post",
            options=[],
            on_change=self._on_pick_post,
            width=320,
        )
        self._title = FormTextField(
            label="Title",
            width=360,
            on_change=self._title_changed,
        )
        self._slug = FormTextField(
            label="Slug",
            width=260,
            on_change=self._slug_changed,
        )
        self._excerpt = FormTextField(
            label="Excerpt",
            multiline=True,
            min_lines=2,
            max_lines=2,
            on_change=lambda _: self._mark_dirty(),
        )
        self._content = ft.TextField(
            multiline=True,
            min_lines=14,
            border=ft.InputBorder.NONE,
            bgcolor=ft.Colors.TRANSPARENT,
            filled=False,
            text_size=13,
            content_padding=ft.padding.symmetric(horizontal=12, vertical=10),
            expand=True,
            on_change=lambda _: self._mark_dirty(),
        )
        self._tags = TagPicker(page, on_change=self._mark_dirty)
        self._seo_title = FormTextField(
            label="SEO Title",
            on_change=lambda _: self._mark_dirty(),
        )
        self._seo_description = FormTextField(
            label="SEO Description",
            on_change=lambda _: self._mark_dirty(),
        )
        self._hero = FormTextField(
            label="Hero Image URL",
            on_change=lambda _: self._mark_dirty(),
        )
        self._syndicate = SyndicatePicker(on_change=self._mark_dirty)
        self._preview = ft.Container(
            content=SecondaryText("Markdown preview"),
            padding=ft.padding.all(Theme.Spacing.MD),
            expand=True,
        )
        self._preview_mode = False
        self._editor_container = ft.Container(self._content, expand=True)
        self._preview_container = ft.Container(
            content=self._preview,
            expand=True,
            visible=False,
        )
        self._mode_toggle = PulseButton(
            on_click_callable=self._toggle_preview,
            text="Preview",
            variant="muted",
            compact=True,
        )
        self._body_label = LabelText("Body")
        self._advanced_button = PulseButton(
            on_click_callable=self._toggle_advanced,
            text="Advanced",
            variant="muted",
            compact=True,
        )
        self._save_button = PulseButton(
            on_click_callable=self._save,
            text="Save Draft",
            variant="muted",
        )
        self._save_button.disabled = True
        self._advanced_section = ft.Container(
            content=ft.Column(
                [
                    self._excerpt,
                    ft.Row(
                        [
                            ft.Container(self._hero, expand=1),
                            ft.Container(self._seo_title, expand=1),
                            ft.Container(self._seo_description, expand=2),
                        ],
                        spacing=Theme.Spacing.MD,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                    self._syndicate,
                ],
                spacing=Theme.Spacing.SM,
            ),
            visible=False,
        )
        self.content = ft.Column(
            [
                ft.Row(
                    [self._post_picker],
                    alignment=ft.MainAxisAlignment.START,
                ),
                ft.Container(height=Theme.Spacing.SM),
                ft.Row(
                    [
                        PulseButton(
                            on_click_callable=self._on_new,
                            text="New",
                            variant="muted",
                            compact=True,
                        ),
                        PulseButton(
                            on_click_callable=self._delete,
                            text="Delete",
                            variant="muted",
                            compact=True,
                        ),
                        self._advanced_button,
                    ],
                    alignment=ft.MainAxisAlignment.START,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    spacing=6,
                ),
                ft.Container(height=Theme.Spacing.MD),
                ft.Row(
                    [
                        self._title,
                        self._slug,
                        ft.Container(self._tags, expand=True),
                    ],
                    spacing=Theme.Spacing.MD,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                self._advanced_section,
                ft.Container(height=Theme.Spacing.MD),
                SectionCard(
                    title=self._body_label,
                    body=ft.Container(
                        content=ft.Column(
                            [self._editor_container, self._preview_container],
                            spacing=0,
                        ),
                        height=360,
                    ),
                    actions=[self._mode_toggle],
                ),
                ft.Container(height=Theme.Spacing.MD),
                ft.Row(
                    [self._save_button],
                    alignment=ft.MainAxisAlignment.END,
                ),
            ],
            spacing=Theme.Spacing.SM,
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = ft.padding.symmetric(
            horizontal=Theme.Spacing.MD, vertical=Theme.Spacing.LG
        )
        self.expand = True

    async def refresh_post_list(self) -> None:
        """Refresh the post-picker dropdown and the tag picker.

        Called when the Editor tab is selected and after every save so the
        picker stays in sync with what's in the DB. Also re-pulls tags so
        any new tags added in the Tags section show up in the tag picker.
        """
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        data = await api.get(
            "/api/v1/blog/admin/posts",
            params={"page": 1, "page_size": 200},
        )
        posts: list[dict[str, Any]] = []
        if isinstance(data, dict) and isinstance(data.get("posts"), list):
            posts = data["posts"]
        self._posts_cache = posts
        self._post_picker.set_options(
            [
                (
                    str(p.get("id")),
                    f"{p.get('title') or '(untitled)'} "
                    f"[{p.get('status', 'draft')}]",
                )
                for p in posts
            ]
        )
        if self._post_id is not None:
            self._post_picker.value = str(self._post_id)
        await self._tags.reload()
        if self.page:
            self.update()

    def _on_pick_post(self, e: ft.ControlEvent) -> None:
        """Handle a selection in the post-picker dropdown."""
        raw = (e.control.value or "").strip()
        if not raw:
            return
        try:
            target_id = int(raw)
        except ValueError:
            return
        if target_id == self._post_id:
            return
        target = next(
            (p for p in self._posts_cache if int(p.get("id", -1)) == target_id),
            None,
        )
        if target is None:
            return

        if not self._dirty:
            self.load_post(target)
            return

        async def _save_and_swap() -> None:
            post_id = await self._save()
            if post_id is not None:
                self.load_post(target)

        async def _discard() -> None:
            self.load_post(target)

        # Snap the picker back to the current post until the user resolves
        # the dialog, so the visible selection matches what's in the editor.
        self._post_picker.value = (
            str(self._post_id) if self._post_id is not None else ""
        )
        if self.page:
            self.update()

        ConfirmDialog(
            page=self.page,
            title="Unsaved changes",
            message="Save your draft before switching posts?",
            confirm_text="Save Draft",
            secondary_text="Discard",
            secondary_destructive=True,
            cancel_text="Cancel",
            on_confirm=_save_and_swap,
            on_secondary=_discard,
        ).show()

    def load_post(self, post: dict[str, Any]) -> None:
        """Load a post into the editor."""
        self._post_id = int(post["id"])
        # Drafts keep auto-syncing slug from title; once published or
        # archived, the slug is part of a public URL and must be edited
        # explicitly to change.
        self._slug_manual = str(post.get("status") or "draft") != "draft"
        self._title.value = str(post.get("title") or "")
        self._slug.value = str(post.get("slug") or "")
        self._excerpt.value = str(post.get("excerpt") or "")
        self._content.value = str(post.get("content") or "")
        self._tags.set_tag_slugs(_post_tag_slugs(post))
        self._seo_title.value = str(post.get("seo_title") or "")
        self._seo_description.value = str(post.get("seo_description") or "")
        self._hero.value = str(post.get("hero_image_url") or "")
        targets = post.get("syndicate_targets")
        self._syndicate.set_targets(targets if isinstance(targets, list) else [])
        # Advanced stays collapsed on load; the user opens it explicitly
        # via the Advanced toggle if they want to edit those fields.
        self._set_advanced_visible(False)
        self._update_preview()
        self._dirty = False
        self._refresh_save_state()
        # Reflect the loaded post in the picker if it's a known option.
        # A freshly-saved post not yet in the cache will simply leave the
        # picker blank until the next refresh.
        if self._posts_cache and any(
            int(p.get("id", -1)) == self._post_id for p in self._posts_cache
        ):
            self._post_picker.value = str(self._post_id)
        if self.page:
            self.update()

    async def _on_new(self) -> None:
        if not self._dirty:
            self.clear()
            return

        async def _save_and_clear() -> None:
            post_id = await self._save()
            if post_id is not None:
                self.clear()

        async def _discard() -> None:
            self.clear()

        ConfirmDialog(
            page=self.page,
            title="Unsaved changes",
            message="You have unsaved edits. Save them as a draft, or discard?",
            confirm_text="Save Draft",
            secondary_text="Discard",
            secondary_destructive=True,
            cancel_text="Cancel",
            on_confirm=_save_and_clear,
            on_secondary=_discard,
        ).show()

    def _mark_dirty(self) -> None:
        self._dirty = True

    def _refresh_save_state(self) -> None:
        valid = bool((self._title.value or "").strip())
        self._save_button.disabled = not valid
        self._save_button.set_variant("teal" if valid else "muted")

    def clear(self, _: ft.ControlEvent | None = None) -> None:
        """Reset the editor for a new draft."""
        self._post_id = None
        self._slug_manual = False
        for field in (
            self._title,
            self._slug,
            self._excerpt,
            self._content,
            self._seo_title,
            self._seo_description,
            self._hero,
        ):
            field.value = ""
        self._tags.clear_tags()
        self._syndicate.set_targets([])
        self._set_advanced_visible(False)
        self._update_preview()
        self._dirty = False
        self._refresh_save_state()
        if self.page:
            self.update()

    async def _toggle_advanced(self) -> None:
        self._set_advanced_visible(not self._advanced_visible)

    async def _toggle_preview(self) -> None:
        self._preview_mode = not self._preview_mode
        self._editor_container.visible = not self._preview_mode
        self._preview_container.visible = self._preview_mode
        self._mode_toggle.set_variant("teal" if self._preview_mode else "muted")
        self._body_label.value = "Preview" if self._preview_mode else "Body"
        if self._preview_mode:
            self._update_preview()
        if self._editor_container.page:
            self._editor_container.update()
        if self._preview_container.page:
            self._preview_container.update()
        if self._body_label.page:
            self._body_label.update()

    def _set_advanced_visible(self, visible: bool) -> None:
        self._advanced_visible = visible
        self._advanced_section.visible = visible
        self._advanced_button.set_variant("teal" if visible else "muted")
        if self._advanced_section.page:
            self._advanced_section.update()

    def _title_changed(self, _: ft.ControlEvent) -> None:
        self._mark_dirty()
        if not self._slug_manual:
            self._slug.value = self._slugify(self._title.value or "")
            if self._slug.page:
                self._slug.update()
        self._refresh_save_state()

    def _slug_changed(self, _: ft.ControlEvent) -> None:
        self._slug_manual = True
        self._mark_dirty()

    def _update_preview(self) -> None:
        content = self._content.value or ""
        self._preview.content = ft.Markdown(
            content or "_Nothing to preview yet._",
            selectable=True,
            extension_set=ft.MarkdownExtensionSet.GITHUB_FLAVORED,
        )
        if self._preview.page:
            self._preview.update()

    async def _save(self) -> int | None:
        from app.components.frontend.state.session_state import get_session_state

        title = self._title.value or ""
        if not title.strip():
            WarningSnackBar("Title is required to save.").launch(self.page)
            return None
        api = get_session_state(self.page).api_client
        payload = self._payload()
        try:
            if self._post_id is None:
                data = await api.post("/api/v1/blog/posts", json=payload)
            else:
                data = await api.put(
                    f"/api/v1/blog/posts/{self._post_id}", json=payload
                )
        except Exception as e:  # noqa: BLE001
            ErrorSnackBar(f"Save failed: {e}").launch(self.page)
            return None
        if isinstance(data, dict) and data.get("id"):
            self.load_post(data)
            SuccessSnackBar("Draft saved.").launch(self.page)
            await self._notify_change()
            return int(data["id"])
        return self._post_id

    async def _delete(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        if self._post_id is None:
            self.clear()
            return
        api = get_session_state(self.page).api_client
        try:
            await api.delete(f"/api/v1/blog/posts/{self._post_id}")
        except Exception as e:  # noqa: BLE001
            ErrorSnackBar(f"Delete failed: {e}").launch(self.page)
            return
        self.clear()
        SuccessSnackBar("Post deleted.").launch(self.page)
        await self._notify_change()

    async def _notify_change(self) -> None:
        if self._on_change_callback is not None:
            await self._on_change_callback()
        # Keep the post picker in sync with the latest DB state after a save.
        await self.refresh_post_list()

    def _payload(self) -> dict[str, Any]:
        tag_slugs = self._tags.tag_slugs
        return {
            "title": (self._title.value or "").strip(),
            "slug": (self._slug.value or "").strip() or None,
            "excerpt": (self._excerpt.value or "").strip() or None,
            "content": self._content.value or "",
            "tag_slugs": tag_slugs,
            "seo_title": (self._seo_title.value or "").strip() or None,
            "seo_description": (self._seo_description.value or "").strip() or None,
            "hero_image_url": (self._hero.value or "").strip() or None,
            # Always send the full list: ``[]`` clears targets on update
            # (the service collapses it to NULL); ``None`` would mean
            # "leave untouched", which an editor sending full state never
            # wants.
            "syndicate_targets": self._syndicate.targets,
        }

    @staticmethod
    def _slugify(value: str) -> str:
        import re

        return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


class BlogDetailDialog(BaseDetailPopup):
    """Detail modal for the blog service."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        posts_tab: PostsTab  # forward declaration
        overview_tab = OverviewTab(page, component_data)

        async def _on_editor_change() -> None:
            await posts_tab._load()
            await overview_tab._load()

        editor_tab = EditorTab(page, on_change=_on_editor_change)
        tabs: ft.Tabs

        def edit_post(post: dict[str, Any]) -> None:
            editor_tab.load_post(post)
            tabs.selected_index = 3
            if tabs.page:
                tabs.update()
            # Programmatic tab switches don't always fire `on_change`, so
            # refresh the picker directly here as well.
            page.run_task(editor_tab.refresh_post_list)

        posts_tab = PostsTab(page, edit_post)

        def _on_tab_change(e: ft.ControlEvent) -> None:
            # Refresh the editor's post picker when the Editor tab is shown
            # so the dropdown reflects whatever's currently in the DB.
            if e.control.selected_index == 3:
                page.run_task(editor_tab.refresh_post_list)

        tabs = PulseTabs(
            selected_index=0,
            tabs=[
                ft.Tab(text="Overview", content=overview_tab),
                ft.Tab(text="Posts", content=posts_tab),
                ft.Tab(text="Tags", content=TagsTab(page)),
                ft.Tab(text="Editor", content=editor_tab),
            ],
            expand=True,
            on_change=_on_tab_change,
        )

        super().__init__(
            page=page,
            component_data=component_data,
            title_text=get_component_title("service_blog"),
            subtitle_text=get_component_subtitle(
                "service_blog", component_data.metadata
            ),
            sections=[tabs],
            scrollable=False,
            width=1280,
            height=840,
            status_detail=get_status_detail(component_data),
        )
