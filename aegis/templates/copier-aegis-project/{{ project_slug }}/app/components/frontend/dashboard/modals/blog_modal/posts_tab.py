"""The Posts tab: the list, and importing into it."""

from collections.abc import Callable
from typing import Any

import flet as ft
from app.components.frontend.controls import (
    ActionMenu,
    ActionMenuItem,
    ConfirmDialog,
    DataTable,
    DataTableColumn,
    FormDropdown,
    Tag,
)
from app.components.frontend.controls.snack_bar import (
    ErrorSnackBar,
    SuccessSnackBar,
)
from app.components.frontend.dashboard.modals.blog_modal.formatting import (
    _format_date,
    _post_tag_slugs,
    _status_color,
)
from app.components.frontend.theme import AegisTheme as Theme

from ..modal_sections import EmptyStatePlaceholder


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
                                    on_click=lambda _: self.page.run_task(self._load),
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
            ErrorSnackBar("Cannot read picked file (no local path).").launch(self.page)
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
            ErrorSnackBar("Unsupported file type. Use .md, .zip, or .json.").launch(
                self.page
            )
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
                    lambda _: self.page.run_task(self._post_action, post_id, "publish"),
                )
            )
        if status != "archived":
            items.append(
                ActionMenuItem(
                    "Archive",
                    ft.Icons.ARCHIVE,
                    lambda _: self.page.run_task(self._post_action, post_id, "archive"),
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
