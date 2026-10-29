"""The voice tab, as the htmx Overseer's Voice section: Profiles (each
voice profile, and its editor: ``designer``) where profiles are kept, then
Models, the voice
overview's rows (``/api/v1/voice/overview``, what the active profile uses,
then every model and voice) in one tight table, narrowed by kind,
provider and text, each playing its own voice on its own model; Use
puts a row on the active profile and Profile switches it, both over the
API. Below, the recorder, which transcribes what the microphone hears."""

import asyncio
from typing import Any

import flet as ft

from app.components.frontend.controls import (
    BodyText,
    DataTable,
    DataTableColumn,
    NativeDropdown,
)
from app.components.frontend.controls.dropdown import chosen, filter_dropdown
from app.components.frontend.controls.tabs import PulseTabs
from app.components.frontend.dashboard.modals.modal_sections.chart_primitives import (
    chart_dot,
)
from app.components.frontend.dashboard.modals.voice_settings.designer import (
    API,
    api,
    play,
    preview,
)
from app.components.frontend.dashboard.modals.voice_settings.profiles import (
    VoiceProfiles,
)
from app.components.frontend.dashboard.modals.voice_settings.recorder import (
    STTRecorderSection,
)
from app.components.frontend.theme import AegisTheme as Theme

# The htmx page's columns, the same order.
# The fixed widths leave Details (the one that stretches) room in the
# modal: summed past its width, Details shrank to a few letters.
COLUMNS = [
    DataTableColumn("Kind", width=80, style="secondary"),
    DataTableColumn("Provider", width=120),
    DataTableColumn("Name", width=180, style="primary"),
    DataTableColumn("Details", style="secondary"),
    DataTableColumn("Plays on", width=150, style="secondary"),
    DataTableColumn("Price / 1M", width=90, alignment="right", style="secondary"),
    DataTableColumn("", width=150, sortable=False),
]


def _designs() -> bool:
    """Whether the stack keeps voice profiles to design (a database)."""
    import app.services.ai.service as ai

    return getattr(ai, "design", None) is not None


def kept(row: dict[str, Any], *, kind: str, provider: str, query: str) -> bool:
    """Whether the filters keep ``row``: its kind and provider when picked,
    ``query`` anywhere in its name, details or the model it plays on."""
    text = " ".join([row["name"], row["detail"], row["plays_on"] or ""]).lower()
    return (
        kind in ("", row["kind"])
        and provider in ("", row["provider"])
        and query.lower() in text
    )


def preview_url(row: dict[str, Any]) -> str | None:
    """Where the row's voice says its preview line on its model."""
    return preview(*row["sample"]) if row["sample"] else None


class VoiceSettingsTab(ft.Container):
    """The voice overview, filtered, played and changed from here."""

    def __init__(self) -> None:
        super().__init__()
        self._found: dict[str, Any] = {
            "rows": [],
            "profiles": [],
            "active": None,
            "kinds": {},
        }
        self._kind, self._provider, self._query = "", "", ""
        self._held: list[ft.Audio] = []
        self._recorder: STTRecorderSection | None = None
        self._table = ft.Container()
        self._toolbar = ft.Row(wrap=True, spacing=Theme.Spacing.MD)
        self._models = ft.Column(
            [self._toolbar, self._table],
            spacing=Theme.Spacing.SM,
            scroll=ft.ScrollMode.AUTO,
        )
        tabs = [ft.Tab(text="Models", content=self._models)]
        if _designs():
            tabs.insert(0, ft.Tab(text="Profiles", content=VoiceProfiles()))
        self.content = PulseTabs(tabs=tabs)

    def did_mount(self) -> None:
        self.page.run_task(self._load)

    def _api(self) -> Any:
        return api(self.page)

    async def _load(self) -> None:
        api = self._api()
        found, current = await asyncio.gather(
            api.get(f"{API}/overview"), api.get(f"{API}/settings")
        )
        if self._recorder is None and isinstance(current, dict):
            self._recorder = STTRecorderSection(current_settings=current)
            self._models.controls.append(self._recorder)
        if isinstance(found, dict):
            self._show(found)

    def _show(self, found: dict[str, Any]) -> None:
        self._found = found
        self._toolbar.controls = self._filters()
        self._draw()

    def _filters(self) -> list[ft.Control]:
        found = self._found
        providers = {r["provider"]: r["provider_name"] for r in found["rows"]}
        controls: list[ft.Control] = [
            self._pick("Kinds", found["kinds"], self._kind, "_kind"),
            self._pick("Providers", providers, self._provider, "_provider"),
            ft.TextField(
                hint_text="Search voices and models",
                dense=True,
                width=240,
                on_change=lambda e: self._set("_query", e.control.value or ""),
            ),
        ]
        if found["active"] is not None:
            controls.insert(
                0,
                NativeDropdown(
                    options=[
                        ft.dropdown.Option(str(p["id"]), p["name"])
                        for p in found["profiles"]
                    ],
                    value=str(found["active"]),
                    width=180,
                    on_change=lambda e: self.page.run_task(
                        self._switch, int(e.control.value)
                    ),
                ),
            )
        return controls

    def _pick(
        self, label: str, choices: dict[str, str], value: str, field: str
    ) -> ft.Control:
        return filter_dropdown(
            f"All {label.lower()}",
            list(choices.items()),
            value=value,
            width=170,
            on_change=lambda e: self._set(field, chosen(e.control.value)),
        )

    def _set(self, field: str, value: str) -> None:
        setattr(self, field, value)
        self._draw()

    def _draw(self) -> None:
        rows = self._found["rows"]
        colors = {
            p: i for i, p in enumerate(dict.fromkeys(r["provider"] for r in rows))
        }
        kept_rows = [
            r
            for r in rows
            if kept(r, kind=self._kind, provider=self._provider, query=self._query)
        ]
        self._table.content = DataTable(
            columns=COLUMNS,
            rows=[self._cells(r, colors[r["provider"]]) for r in kept_rows],
            row_padding=4,
            scroll_height=460,
            empty_message="Nothing matches",
            row_bgcolors=[
                Theme.Colors.SURFACE_2 if r["used"] else None for r in kept_rows
            ],
        )
        if self.page:
            self.update()

    def _cells(self, row: dict[str, Any], color: int) -> list[Any]:
        """One row in the table's columns: its kind, its provider in its own
        color, its name, what it is, the model it plays on, its price, then
        play and Use."""
        url = preview_url(row)
        provider = ft.Row(
            [
                chart_dot(color + 1),
                BodyText(row["provider_name"], size=11),
            ],
            spacing=6,
        )
        actions = ft.Row(
            [
                ft.Text(
                    row["blocked"] or "",
                    size=11,
                    color=Theme.Colors.WARNING,
                    visible=bool(row["blocked"]),
                ),
                ft.IconButton(
                    ft.Icons.VOLUME_UP,
                    icon_size=16,
                    tooltip="Listen",
                    visible=bool(url),
                    on_click=lambda _: play(self.page, self._held, url),
                ),
                ft.TextButton(
                    "Use",
                    visible=bool(row["use"]),
                    on_click=lambda _: self.page.run_task(self._use, row),
                ),
            ],
            spacing=0,
        )
        return [
            row["label"],
            provider,
            row["name"],
            row["detail"],
            row["plays_on"] or "",
            row["price"] or "",
            actions,
        ]

    async def _use(self, row: dict[str, Any]) -> None:
        found = await self._api().post(f"{API}/use", json=row["use"])
        if isinstance(found, dict):
            self._show(found)

    async def _switch(self, profile_id: int) -> None:
        found = await self._api().post(f"{API}/profiles/{profile_id}/active")
        if isinstance(found, dict):
            self._show(found)
