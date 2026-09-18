"""The Tags tab."""

from typing import Any

import flet as ft
from app.components.frontend.controls import (
    ActionMenu,
    ActionMenuItem,
    ConfirmDialog,
    DataTable,
    DataTableColumn,
    FormTextField,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.dashboard.modals.blog_modal.formatting import (
    _format_date,
)
from app.components.frontend.theme import AegisTheme as Theme

from ..modal_sections import EmptyStatePlaceholder


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
        name = (
            str(tag.get("name") or tag.get("slug") or "this tag").strip() or "this tag"
        )

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
