"""The Editor tab: writing a post and its metadata."""

from collections.abc import Awaitable, Callable
from typing import Any

import flet as ft
from app.components.frontend.controls import (
    ConfirmDialog,
    FormDropdown,
    FormTextField,
    LabelText,
    SecondaryText,
    SectionCard,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.snack_bar import (
    ErrorSnackBar,
    SuccessSnackBar,
    WarningSnackBar,
)
from app.components.frontend.dashboard.modals.blog_modal.formatting import (
    _post_tag_slugs,
)
from app.components.frontend.dashboard.modals.blog_modal.pickers import (
    SyndicatePicker,
    TagPicker,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import slugify


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
                    f"{p.get('title') or '(untitled)'} [{p.get('status', 'draft')}]",
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
        return slugify(value)
