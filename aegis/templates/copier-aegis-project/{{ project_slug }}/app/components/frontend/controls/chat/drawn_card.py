"""Cards the assistant draws in a reply (``draw_card``), in the Flet chat.

A drawn card rides the answer's trace as a ``chat_card`` marker carrying
its id only; the card fetches its kind and kept payload over the API
(``/api/v1/ai/cards``) and draws it with the dashboard's own chart cards,
the kinds the htmx thread draws as charts. A click opens it larger, as the
htmx frame does. A kind with no drawing here yet (table, compare, path),
or a card that is gone, is absent.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import flet as ft

from app.components.frontend.controls.dialog import DialogHandle, StyledAlertDialog
from app.components.frontend.controls.text import LabelText, SecondaryText
from app.components.frontend.dashboard.modals.modal_sections.chart_bar import (
    RankedBarCard,
)
from app.components.frontend.dashboard.modals.modal_sections.chart_line import (
    LineChartCard,
)
from app.components.frontend.dashboard.modals.modal_sections.chart_pie import (
    PieChartCard,
)
from app.components.frontend.dashboard.modals.modal_sections.chart_primitives import (
    RankedBar,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_value
from app.core.money import dollars
from app.core.time import short_date

# card_id -> {"kind", "card"} (the API's body), or None when it is gone.
FetchCard = Callable[[str], Awaitable[dict[str, Any] | None]]

WIDTH = 520
LARGE_WIDTH = 820


def _values(card: dict[str, Any]) -> tuple[list[float], str | None]:
    """The rows' values as drawn (money arrives in cents) and the format
    they read in."""
    unit = card.get("unit")
    values = [
        dollars(r["value"]) if unit == "money" else r["value"] for r in card["rows"]
    ]
    return values, unit if unit in ("money", "percent") else None


def _trend(card: dict[str, Any], large: bool) -> ft.Container:
    values, fmt = _values(card)
    return LineChartCard.from_chart(
        card["title"],
        {
            "labels": [short_date(r["date"]) for r in card["rows"]],
            "series": [{"label": card["measure"], "values": values}],
            "format": fmt,
        },
        subtitle=card["measure"],
        height=420 if large else 214,
    )


def _bar(card: dict[str, Any], large: bool) -> ft.Container:
    values, fmt = _values(card)
    return RankedBarCard(
        title="",
        rows=[
            RankedBar(r["label"], v, format_value(v, fmt))
            for r, v in zip(card["rows"], values, strict=True)
        ],
    )


def _pie(card: dict[str, Any], large: bool) -> ft.Container:
    values, fmt = _values(card)
    return PieChartCard(
        "",
        [
            {"value": v, "label": r["label"]}
            for r, v in zip(card["rows"], values, strict=True)
        ],
        value_formatter=lambda v: format_value(v, fmt),
        chart_size=300 if large else 170,
    )


# The frame (the box, its title and the measure under it) is the card's,
# as the htmx ``card_frame`` is: each drawing is the chart alone.
Drawing = Callable[[dict[str, Any], bool], ft.Container]


def _unboxed(chart: ft.Container) -> ft.Container:
    """A chart card without its own box, to sit in the frame's (or the
    dialog's) rather than draw a box inside a box. Its padding stays: the
    axis labels draw into it."""
    chart.bgcolor, chart.border = None, None
    return chart


DRAWINGS: dict[str, Drawing] = {
    "trend": _trend,
    "bar": _bar,
    "pie": _pie,
}


class DrawnCard(ft.Container):
    """One drawn card: hidden until its payload arrives, then the kind's
    chart, opening larger on a click."""

    def __init__(
        self,
        card_id: str,
        fetch: FetchCard,
        on_drawn: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(
            width=WIDTH,
            visible=False,
            padding=Theme.Spacing.SM,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            border=ft.border.all(0.5, ft.Colors.OUTLINE),
            border_radius=Theme.Components.CARD_RADIUS,
        )
        self.card_id = card_id
        self._fetch = fetch
        # The thread scrolled to its end before the card had a height: it
        # follows again once the card is drawn.
        self._on_drawn = on_drawn
        self._card: dict[str, Any] = {}
        self._draw: Drawing | None = None

    def did_mount(self) -> None:
        self.page.run_task(self.load)

    async def load(self) -> None:
        body = await self._fetch(self.card_id)
        draw = DRAWINGS.get(str((body or {}).get("kind")))
        if body is None or draw is None:
            return
        self._card, self._draw = body["card"], draw
        self.content = ft.Column(
            [
                ft.Column(
                    [
                        LabelText(self._card["title"]),
                        SecondaryText(self._card.get("measure", "")),
                    ],
                    spacing=0,
                    tight=True,
                ),
                _unboxed(draw(self._card, False)),
            ],
            spacing=Theme.Spacing.SM,
            tight=True,
        )
        self.on_click = lambda _e: self.open_large()
        self.visible = True
        if self.page:
            self.update()
        if self._on_drawn is not None:
            self._on_drawn()

    def open_large(self) -> None:
        if self._draw is None or not self.page:
            return
        handle = DialogHandle()

        async def _close() -> None:
            handle.close(self.page)

        self.page.open(
            StyledAlertDialog(
                handle=handle,
                title=self._card["title"],
                body=_unboxed(self._draw(self._card, True)),
                width=LARGE_WIDTH,
                on_close=_close,
            )
        )
