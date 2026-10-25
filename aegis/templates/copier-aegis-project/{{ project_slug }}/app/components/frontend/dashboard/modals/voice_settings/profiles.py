"""The voice tab's Profiles view, as the htmx Overseer's Voice > Profiles:
every voice profile at a glance (``/api/v1/voice/design/profiles``), each
to hear, edit or put in use, and a new one made from the active one; Edit
opens the profile's editor (``designer``)."""

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    DataTable,
    DataTableColumn,
    SecondaryText,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.theme import AegisTheme as Theme

from .designer import API, VoiceEditor, api, play

COLUMNS = [
    DataTableColumn("Profile", width=180, style="primary"),
    DataTableColumn("Voice", width=140),
    DataTableColumn("Style", width=200, style="secondary"),
    DataTableColumn("Speed", width=80, style="secondary"),
    DataTableColumn("", sortable=False),
]


class VoiceProfiles(ft.Column):
    """Every profile at a glance, or the one being edited."""

    def __init__(self) -> None:
        super().__init__(spacing=Theme.Spacing.MD, scroll=ft.ScrollMode.AUTO)
        self._held: list[ft.Audio] = []
        self._name = ft.TextField(hint_text="New profile's name", dense=True, width=240)

    def did_mount(self) -> None:
        self.page.run_task(self._list)

    async def _list(self) -> None:
        found = await api(self.page).get(f"{API}/design/profiles")
        rows = found if isinstance(found, list) else []
        self.controls = [
            DataTable(
                columns=COLUMNS, rows=[self._cells(p) for p in rows], row_padding=6
            ),
            ft.Row(
                [
                    self._name,
                    PulseButton(on_click_callable=self._make, text="New profile"),
                    SecondaryText("starts from the one in use"),
                ],
                spacing=Theme.Spacing.MD,
            ),
        ]
        if self.page:
            self.update()

    def _cells(self, p: dict[str, Any]) -> list[Any]:
        """A profile's row: its name, voice, style and speed, then whether
        it is in use (else Use this one), Listen and Edit."""
        actions = ft.Row(
            [
                SecondaryText(
                    "In use", color=Theme.Colors.SUCCESS, visible=p["active"]
                ),
                ft.TextButton(
                    "Use this one",
                    visible=not p["active"],
                    on_click=lambda _: self.page.run_task(self._activate, p["id"]),
                ),
                ft.IconButton(
                    ft.Icons.VOLUME_UP,
                    icon_size=16,
                    tooltip="Listen",
                    on_click=lambda _: play(
                        self.page,
                        self._held,
                        f"{API}/design/profiles/{p['id']}/preview",
                    ),
                ),
                ft.TextButton("Edit", on_click=lambda _: self._edit(p["id"])),
            ],
            spacing=0,
        )
        return [p["name"], p["voice"], p["style"], str(p["speed"]), actions]

    def _edit(self, profile_id: int) -> None:
        editor = VoiceEditor(profile_id, back=lambda: self.page.run_task(self._list))
        self.controls = [editor]
        self.update()
        self.page.run_task(editor.load, {})

    async def _activate(self, profile_id: int) -> None:
        await api(self.page).post(f"{API}/profiles/{profile_id}/active")
        await self._list()

    async def _make(self) -> None:
        made = await api(self.page).post(
            f"{API}/design/profiles", json={"name": self._name.value or ""}
        )
        if isinstance(made, dict):
            self._edit(made["id"])
