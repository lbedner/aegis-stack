"""Logs in Flet, as in htmx (``ui_logs``): the Logs section every component
modal with a container behind it gets (``BaseDetailPopup`` adds it after
Container), and, with no page, Overseer > Logs over every service
(``LogsPopup``), each line naming its service. Newest first unless the order
says otherwise, filtered by window, level and text (and service), then new
lines added at the newest end as the containers write them while open,
unless paused."""

from concurrent.futures import Future
from typing import Any

import flet as ft

from app.components.frontend.controls import (
    BodyText,
    H3Text,
    NumericText,
    SecondaryText,
)
from app.components.frontend.controls.buttons import IconCopyButton
from app.components.frontend.dashboard.modals.modal_sections import DateRangeChips
from app.components.frontend.dashboard.modals.modal_sections.chart_primitives import (
    ChartColors,
)
from app.components.frontend.theme import TONE_COLORS
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import split_matches
from app.services.system import ui_logs

# A level's color, from its tone (``ui_logs.TONES``); info and an
# unlevelled line stay plain. A warning or worse also marks its line's left
# edge, and a debug line steps back.
LEVEL_COLORS = {level: TONE_COLORS[tone] for level, tone in ui_logs.TONES.items()}
EDGED = tuple(
    level for level, tone in ui_logs.TONES.items() if tone in ("warn", "error")
)
MUTED = ft.TextStyle(color=ft.Colors.ON_SURFACE_VARIANT)
MARKED = ft.TextStyle(
    color=Theme.Colors.PRIMARY,
    bgcolor=ft.Colors.with_opacity(0.25, Theme.Colors.PRIMARY),
)


class LogsSection(ft.Column):
    """The log lines behind one Overseer page (``page``: ``redis``, ...), or
    behind every page with none."""

    def __init__(self, page: str | None = None) -> None:
        super().__init__(spacing=Theme.Spacing.SM)
        self._page_key = page
        self._query: dict[str, str] = {}
        self._services: set[str] = set()  # ticked; none is every service
        # Every service's title by page, read on load (Overseer > Logs only).
        self._titles: dict[str, str] | None = None
        self._reading: list[str] = [page] if page else []
        self.paused = False
        self._following: Future[None] | None = None
        self._note = SecondaryText("", visible=False)
        self._lines = ft.ListView(spacing=2, height=420)
        self._services_menu = ft.PopupMenuButton(
            content=SecondaryText("Services"), visible=page is None
        )
        self._pause = ft.IconButton(
            ft.Icons.PAUSE, tooltip="Pause", on_click=lambda _: self._toggle_pause()
        )
        filters = ft.Row(
            [
                DateRangeChips(
                    options=[(label, seconds) for seconds, label in ui_logs.WINDOWS],
                    selected_days=ui_logs.DEFAULT_WINDOW,
                    on_change=lambda seconds: self._pick({"window": str(seconds)}),
                ),
                ft.Dropdown(
                    options=[
                        ft.dropdown.Option("", "All levels"),
                        *(
                            ft.dropdown.Option(level, label)
                            for level, label in ui_logs.LEVEL_CHOICES
                        ),
                    ],
                    value="",
                    dense=True,
                    width=150,
                    on_change=lambda e: self._pick({"level": e.control.value or ""}),
                ),
                ft.Dropdown(
                    options=[
                        ft.dropdown.Option(order, name)
                        for order, name in ui_logs.ORDERS
                    ],
                    value=ui_logs.DEFAULT_ORDER,
                    dense=True,
                    width=160,
                    on_change=lambda e: self._pick({"order": e.control.value or ""}),
                ),
                self._services_menu,
                ft.TextField(
                    hint_text="Search lines",
                    dense=True,
                    width=220,
                    on_submit=lambda e: self._pick({"q": e.control.value or ""}),
                ),
                self._pause,
                ft.IconButton(
                    ft.Icons.VERTICAL_ALIGN_TOP,
                    tooltip="Top",
                    on_click=lambda _: self._lines.scroll_to(offset=0, duration=200),
                ),
                ft.IconButton(
                    ft.Icons.VERTICAL_ALIGN_BOTTOM,
                    tooltip="Bottom",
                    on_click=lambda _: self._lines.scroll_to(offset=-1, duration=200),
                ),
            ],
            wrap=True,
            spacing=Theme.Spacing.MD,
        )
        self.controls = [H3Text("Logs"), filters, self._note, self._lines]

    def did_mount(self) -> None:
        self.page.run_task(self.show, {})

    def will_unmount(self) -> None:
        self._stop()

    def _pick(self, changes: dict[str, str]) -> None:
        self.page.run_task(self.show, changes)

    async def show(self, changes: dict[str, str]) -> None:
        """Read the lines again with ``changes`` to the filters, and follow
        from there."""
        self._query |= changes
        await self.load()
        self._stop()
        if self.page is not None:
            self._following = self.page.run_task(self.follow)

    async def pick_services(self, pages: set[str]) -> None:
        """Show only these services' lines (every one's, when empty)."""
        self._services = pages
        await self.show({})

    def _toggle_service(self, page: str) -> None:
        self.page.run_task(self.pick_services, self._services ^ {page})

    def _toggle_pause(self) -> None:
        self.paused = not self.paused
        self._pause.icon = ft.Icons.PLAY_ARROW if self.paused else ft.Icons.PAUSE
        self._pause.tooltip = "Resume" if self.paused else "Pause"
        self._pause.update()

    async def _read_services(self) -> None:
        """Every service's title, the menu to tick them, and which to read."""
        sources = await ui_logs.sources()
        self._titles = {s["page"]: s["title"] for s in sources}
        self._services_menu.items = [
            ft.PopupMenuItem(
                text=s["title"],
                checked=s["page"] in self._services,
                on_click=lambda _, page=s["page"]: self._toggle_service(page),
            )
            for s in sources
        ]
        ticked = [page for page in self._titles if page in self._services]
        self._reading = ticked or list(self._titles)

    async def load(self) -> None:
        if self._page_key is None:
            await self._read_services()
        view = await ui_logs.recent(self._reading, self._query)
        self._note.value = view["note"] or ""
        self._note.visible = bool(view["note"])
        self._lines.controls = [
            _line(row, self._titles, self._query.get("q", "")) for row in view["lines"]
        ]
        # Oldest first, the newest end is the bottom: stay there as lines come.
        self._lines.auto_scroll = ui_logs.order_of(self._query) == "asc"
        if self.page is not None:
            self.update()

    async def follow(self) -> None:
        """Add new lines at the newest end until the modal closes or a
        filter changes; paused, a new line is dropped."""
        newest_first = ui_logs.order_of(self._query) == "desc"
        async for batch in ui_logs.follow(self._reading, self._query):
            if self.paused:
                continue
            lines = [
                _line(row, self._titles, self._query.get("q", "")) for row in batch
            ]
            if newest_first:
                self._lines.controls[:0] = lines
            else:
                self._lines.controls.extend(lines)
            if self.page is not None:
                self.update()

    def _stop(self) -> None:
        if self._following is not None:
            self._following.cancel()
            self._following = None


def _line(
    row: dict[str, Any], titles: dict[str, str] | None = None, query: str = ""
) -> ft.Control:
    """One line: time, its service in its own color (with ``titles``) and
    which of its containers when it has several (``source``), level, then
    the message (the lead the time repeats left out, the search marked) and
    its fields; a traceback folds under it. Hovering it shows a
    copy of the whole line."""
    fields = " ".join(f"{key}={value}" for key, value in row["fields"])
    service = titles.get(row["page"], row["page"]) if titles else ""
    level = row["level"] or ""
    head = ft.Row(
        [
            NumericText(row["at"], size=11, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Row(
                [
                    ft.Container(
                        width=8,
                        height=8,
                        border_radius=4,
                        bgcolor=ChartColors.RAMP[row["color"] % len(ChartColors.RAMP)],
                        data="service-dot",
                    ),
                    BodyText(service, size=11),
                ],
                spacing=6,
                visible=bool(service),
            ),
            ft.Container(
                SecondaryText(row["source"], size=11),
                tooltip=row["instance"],
                visible=bool(row["source"]),
            ),
            ft.Text(level, size=11, color=LEVEL_COLORS.get(level), width=60),
            BodyText(
                "",
                size=12,
                selectable=True,
                spans=_marked(row["message"], query),
            ),
            BodyText(
                "",
                size=11,
                selectable=True,
                visible=bool(fields),
                spans=[
                    span
                    for key, value in row["fields"]
                    for span in (
                        ft.TextSpan(f" {key}=", MUTED),
                        *_marked(value, query),
                    )
                ],
            ),
        ],
        spacing=Theme.Spacing.SM,
        vertical_alignment=ft.CrossAxisAlignment.START,
        wrap=True,
    )
    whole = " ".join(
        part
        for part in (
            row["at"],
            service,
            row["instance"],
            level,
            row["prefix"] + row["message"],
            fields,
        )
        if part
    )
    copy = IconCopyButton(
        lambda: "\n".join(part for part in (whole, row["trace"]) if part),
        icon_size=14,
        opacity=0,  # shown on hover; hidden, it still holds its place
    )
    head.controls.append(copy)
    body: ft.Control = head
    if row["trace"]:
        trace = ft.ExpansionTile(
            title=SecondaryText("Traceback", size=11),
            controls=[SecondaryText(row["trace"], size=11, selectable=True)],
            dense=True,
        )
        body = ft.Column([head, trace], spacing=0)
    edge = LEVEL_COLORS[level] if level in EDGED else None
    return ft.Container(
        body,
        border=ft.border.only(left=ft.BorderSide(2, edge)) if edge else None,
        padding=ft.padding.only(left=6) if edge else None,
        opacity=0.6 if level == "debug" else None,
        on_hover=lambda e: _reveal(copy, e.data == "true"),
    )


def _marked(text: str, query: str) -> list[ft.TextSpan]:
    """``text`` as spans, each match of ``query`` marked (``split_matches``)."""
    return [
        ft.TextSpan(run, MARKED if hit else None)
        for run, hit in split_matches(text, query)
    ]


def _reveal(control: ft.Control, shown: bool) -> None:
    control.opacity = 1 if shown else 0
    control.update()
