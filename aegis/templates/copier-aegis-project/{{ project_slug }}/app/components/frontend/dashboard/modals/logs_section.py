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
    NumericText,
    SecondaryText,
)
from app.components.frontend.controls.buttons import IconCopyButton
from app.components.frontend.controls.dropdown import (
    NativeDropdown,
    chosen,
    filter_dropdown,
)
from app.components.frontend.controls.inputs import StyledTextField
from app.components.frontend.core.session_health import SessionLoops, page_is_connected
from app.components.frontend.dashboard.modals.modal_sections import DateRangeChips
from app.components.frontend.dashboard.modals.modal_sections.chart_primitives import (
    chart_dot,
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
# The most lines a section holds while following: each is a control Flet
# diffs on the event loop, so a modal left open must not grow without end.
MAX_LINES = 1000
# A line's fixed columns, so every line's message starts at one edge.
TIME_WIDTH = 60
LEVEL_WIDTH = 60
SERVICE_WIDTH = 110
# The copy button's box: a bare icon button is 40 high, taller than a line.
COPY_SIZE = 24
MUTED = ft.TextStyle(color=ft.Colors.ON_SURFACE_VARIANT)
MARKED = ft.TextStyle(
    color=Theme.Colors.PRIMARY,
    bgcolor=ft.Colors.with_opacity(0.25, Theme.Colors.PRIMARY),
)


class LogsSection(ft.Column):
    """The log lines behind one Overseer page (``page``: ``redis``, ...), or
    behind every page with none."""

    def __init__(self, page: str | None = None) -> None:
        # As tall as what holds it; its lines scroll inside it.
        super().__init__(spacing=Theme.Spacing.SM, expand=True)
        self._page_key = page
        self._query: dict[str, str] = {}
        self._services: set[str] = set()  # ticked; none is every service
        # Every service's title by page, read on load (Overseer > Logs only).
        self._titles: dict[str, str] | None = None
        self._reading: list[str] = [page] if page else []
        # The containers the service menu was built from, for the lines too.
        self._found: ui_logs.Containers | None = None
        self.paused = False
        self._following: Future[None] | None = None
        self._note = SecondaryText("", visible=False)
        self._lines = ft.ListView(spacing=2, expand=True)
        self._services_menu = ft.PopupMenuButton(
            content=SecondaryText("Services"), visible=page is None
        )
        self._pause = _tool(ft.Icons.PAUSE, "Pause", lambda _: self._toggle_pause())
        filters = ft.Row(
            [
                DateRangeChips(
                    options=[(label, seconds) for seconds, label in ui_logs.WINDOWS],
                    selected_days=ui_logs.DEFAULT_WINDOW,
                    on_change=lambda seconds: self._pick({"window": str(seconds)}),
                ),
                filter_dropdown(
                    "All levels",
                    list(ui_logs.LEVEL_CHOICES),
                    width=150,
                    on_change=lambda e: self._pick({"level": chosen(e.control.value)}),
                ),
                NativeDropdown(
                    options=[
                        ft.dropdown.Option(order, name)
                        for order, name in ui_logs.ORDERS
                    ],
                    value=ui_logs.DEFAULT_ORDER,
                    width=160,
                    enable_filter=False,
                    enable_search=False,
                    on_change=lambda e: self._pick({"order": e.control.value or ""}),
                ),
                self._services_menu,
                StyledTextField(
                    compact=True,
                    hint_text="Search lines",
                    prefix_icon=ft.Icons.SEARCH,
                    width=240,
                    on_submit=lambda e: self._pick({"q": e.control.value or ""}),
                ),
                self._pause,
                _tool(
                    ft.Icons.VERTICAL_ALIGN_TOP,
                    "Top",
                    lambda _: self._lines.scroll_to(offset=0, duration=200),
                ),
                _tool(
                    ft.Icons.VERTICAL_ALIGN_BOTTOM,
                    "Bottom",
                    lambda _: self._lines.scroll_to(offset=-1, duration=200),
                ),
            ],
            wrap=True,
            spacing=Theme.Spacing.SM,
            run_spacing=Theme.Spacing.SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.controls = [filters, self._note, self._lines]

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
        self._found = await ui_logs.containers()
        sources = ui_logs.sources(self._found)
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
        else:
            self._found = await ui_logs.containers([self._page_key])
        view = await ui_logs.recent(self._reading, self._query, found=self._found)
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
        """Add new lines at the newest end until the modal closes, a filter
        changes or the tab goes (``SessionLoops``: Flet keeps a closed tab's
        session for an hour); paused, a new line is dropped. The oldest
        lines past ``MAX_LINES`` go."""
        newest_first = ui_logs.order_of(self._query) == "desc"
        loops = SessionLoops(self.page, lambda: page_is_connected(self.page))
        async for batch in ui_logs.follow(
            self._reading, self._query, found=self._found
        ):
            if not loops.alive():
                return
            if self.paused:
                continue
            lines = [
                _line(row, self._titles, self._query.get("q", "")) for row in batch
            ]
            if newest_first:
                self._lines.controls[:0] = lines
                del self._lines.controls[MAX_LINES:]
            else:
                self._lines.controls.extend(lines)
                del self._lines.controls[:-MAX_LINES]
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
    which of its containers when it has several (``source``), level, each
    in its own fixed column, then the message (the lead the time repeats
    left out, the search marked), its logger and its fields, as one text
    wrapping in what is left; a traceback folds under it. Hovering it
    shows a copy of the whole line."""
    fields = " ".join(f"{key}={value}" for key, value in row["fields"])
    logger = f"[{row['logger']}]" if row["logger"] else ""
    service = titles.get(row["page"], row["page"]) if titles else ""
    level = row["level"] or ""
    said = BodyText(
        "",
        size=12,
        selectable=True,
        expand=True,
        spans=[
            *_marked(row["message"], query),
            *([ft.TextSpan(f" {logger}", MUTED)] if logger else []),
            *(
                span
                for key, value in row["fields"]
                for span in (ft.TextSpan(f"  {key}=", MUTED), *_marked(value, query))
            ),
        ],
    )
    whole = " ".join(
        part
        for part in (
            row["at"],
            service,
            row["instance"],
            level,
            row["prefix"] + row["message"],
            logger,
            fields,
        )
        if part
    )
    copy = IconCopyButton(
        lambda: "\n".join(part for part in (whole, row["trace"]) if part),
        icon_size=14,
        width=COPY_SIZE,
        height=COPY_SIZE,
        padding=0,
        opacity=0,  # shown on hover; hidden, it still holds its place
    )
    head = ft.Row(
        [
            NumericText(
                row["at"], size=11, color=ft.Colors.ON_SURFACE_VARIANT, width=TIME_WIDTH
            ),
            ft.Container(
                ft.Row(
                    [
                        chart_dot(row["color"] + 1, data="service-dot"),
                        BodyText(
                            service,
                            size=11,
                            no_wrap=True,
                            overflow=ft.TextOverflow.ELLIPSIS,
                            expand=True,
                        ),
                    ],
                    spacing=6,
                ),
                width=SERVICE_WIDTH,
                tooltip=service or None,
                visible=bool(service),
            ),
            ft.Container(
                SecondaryText(row["source"], size=11),
                tooltip=row["instance"],
                visible=bool(row["source"]),
            ),
            ft.Text(level, size=11, color=LEVEL_COLORS.get(level), width=LEVEL_WIDTH),
            said,
            copy,
        ],
        spacing=Theme.Spacing.SM,
        vertical_alignment=ft.CrossAxisAlignment.START,
    )
    body: ft.Control = head
    if row["trace"]:
        # Folded under the message, past the time, service and level.
        indent = TIME_WIDTH + LEVEL_WIDTH + 2 * Theme.Spacing.SM
        if service:
            indent += SERVICE_WIDTH + Theme.Spacing.SM
        trace = ft.ExpansionTile(
            title=SecondaryText("Traceback", size=11),
            controls=[SecondaryText(row["trace"], size=11, selectable=True)],
            dense=True,
            tile_padding=ft.padding.only(left=indent),
            controls_padding=ft.padding.only(left=indent),
        )
        body = ft.Column([head, trace], spacing=0)
    edge = LEVEL_COLORS[level] if level in EDGED else ft.Colors.TRANSPARENT
    return ft.Container(
        body,
        border=ft.border.only(left=ft.BorderSide(2, edge)),
        padding=ft.padding.only(left=6, top=2, bottom=2),
        opacity=0.6 if level == "debug" else None,
        on_hover=lambda e: _reveal(copy, e.data == "true"),
    )


def _tool(icon: str, tooltip: str, on_click: Any) -> ft.IconButton:
    """A toolbar icon: small and quiet, as the house icon buttons are."""
    return ft.IconButton(
        icon,
        tooltip=tooltip,
        icon_size=18,
        icon_color=ft.Colors.ON_SURFACE_VARIANT,
        on_click=on_click,
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
