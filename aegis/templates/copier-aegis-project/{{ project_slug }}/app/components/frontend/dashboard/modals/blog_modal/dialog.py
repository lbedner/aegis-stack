"""The blog modal itself: the tab bar and what it holds."""

from typing import Any

import flet as ft
from app.components.frontend.controls.tabs import PulseTabs
from app.components.frontend.dashboard.modals.blog_modal.editor_tab import (
    EditorTab,
)
from app.components.frontend.dashboard.modals.blog_modal.overview_tab import (
    OverviewTab,
)
from app.components.frontend.dashboard.modals.blog_modal.posts_tab import (
    PostsTab,
)
from app.components.frontend.dashboard.modals.blog_modal.tags_tab import (
    TagsTab,
)
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle, get_component_title

from ...cards.card_utils import get_status_detail
from ..base_detail_popup import BaseDetailPopup


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
