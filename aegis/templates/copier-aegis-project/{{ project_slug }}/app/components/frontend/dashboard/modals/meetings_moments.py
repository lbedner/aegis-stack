"""What a call threw up, in the Flet Overseer's meeting pane: a section per
kind of moment (``MomentRecord``), each with who said it and when, a
button per action it offers (a browser action copies its prompt; the
others are asked through ``ask``), and what was asked of it."""

from collections.abc import Awaitable, Callable
from operator import itemgetter
from typing import Any

import flet as ft

from app.components.frontend.controls import PrimaryText, SecondaryText, status_dot
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.snack_bar import SuccessSnackBar
from app.components.frontend.theme import TONE_COLORS
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_clock
from app.services.meetings.service import by_kind

from .meetings_follow import api
from .modal_sections import SectionHeader

# Ask the action named of the moment (its id); copy a prompt.
Ask = Callable[[int, str], Awaitable[None]]
Copy = Callable[[str], Awaitable[None]]
# What the pane does with a meeting's moments: ask, copy, and each card's
# fold as the reader left it (its moment id -> open).
Acts = tuple[Ask, Copy, dict[int, bool]]


def moment_actions(
    page: ft.Page, base: str, refresh: Callable[[], Awaitable[None]]
) -> Acts:
    """The pane's two callbacks for one meeting (``base``, its API path):
    ask an action of a moment, then ``refresh``; copy a prompt. And the
    folds the reader left, kept in the session for the meeting, so the
    pane redrawing itself while it follows a run keeps them."""

    async def ask(moment_id: int, action: str) -> None:
        await api(page).post(
            f"{base}/moments/{moment_id}/runs", json={"action": action}
        )
        await refresh()

    async def copy(prompt: str) -> None:
        page.set_clipboard(prompt)
        SuccessSnackBar("Copied").launch(page)

    key = f"meetings:folds:{base}"
    if not page.session.contains_key(key):
        page.session.set(key, {})
    return ask, copy, page.session.get(key)


def moments_controls(
    record: dict[str, Any],
    ask: Ask,
    copy: Copy,
    folds: dict[int, bool] | None = None,
) -> list[ft.Control]:
    """A section per kind of moment the record holds, in the order first
    heard; nothing when nothing was."""
    folds = {} if folds is None else folds
    controls: list[ft.Control] = []
    for listed in by_kind(record.get("moments") or [], itemgetter("kind")):
        controls.append(SectionHeader(listed[0]["title"]))
        controls.extend(_moment(m, ask, copy, folds) for m in listed)
    return controls


def _moment(
    moment: dict[str, Any], ask: Ask, copy: Copy, folds: dict[int, bool]
) -> ft.Control:
    """A card folded to what was asked (its topic, else its question), a
    dot per answer: open while one is going, else as the reader left it.
    Inside, a burst: its first moment, the ones said right after it, then
    what can be done with them all and what has been."""
    moment_id, runs = int(moment["id"]), moment.get("runs") or []
    also = moment.get("also") or []

    def folded(e: ft.ControlEvent) -> None:
        folds[moment_id] = e.data == "true"

    title = PrimaryText(moment.get("topic") or moment["text"], max_lines=2)
    tile = ft.ExpansionTile(
        title=ft.Row([ft.Container(title, expand=True), *map(_dot, runs)], spacing=6),
        subtitle=SecondaryText(f"{len(also) + 1} asked") if also else None,
        initially_expanded=folds.get(moment_id, any(r.get("going") for r in runs)),
        on_change=folded,
        dense=True,
        shape=ft.RoundedRectangleBorder(radius=Theme.Components.CARD_RADIUS),
        collapsed_shape=ft.RoundedRectangleBorder(radius=Theme.Components.CARD_RADIUS),
        controls=[_inside(moment, ask, copy)],
    )
    return ft.Container(
        tile,
        border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=Theme.Components.CARD_RADIUS,
    )


def _dot(run: dict[str, Any]) -> ft.Control:
    """Where one answer stands, in its tone (ok while it is going)."""
    dot = status_dot(TONE_COLORS["ok" if run.get("going") else run["tone"]], size=8)
    dot.tooltip = f"{run['label']} · {run['state']}"
    return dot


def _inside(moment: dict[str, Any], ask: Ask, copy: Copy) -> ft.Control:
    return ft.Container(
        ft.Column(
            [
                *_said(moment),
                *(
                    ft.Container(
                        ft.Column(_said(more), spacing=2),
                        padding=ft.padding.only(left=Theme.Spacing.SM),
                    )
                    for more in moment.get("also") or []
                ),
                ft.Row(
                    [_button(moment["id"], a, ask, copy) for a in moment["actions"]],
                    spacing=8,
                    wrap=True,
                ),
                *(_run(r) for r in moment.get("runs") or []),
            ],
            spacing=Theme.Spacing.XS,
        ),
        padding=ft.padding.all(Theme.Spacing.SM),
    )


def _said(moment: dict[str, Any]) -> list[ft.Control]:
    return [
        SecondaryText(f"{moment['speaker']} · {format_clock(moment['at'])}"),
        PrimaryText(moment["text"], size=Theme.Typography.BODY),
    ]


def _button(moment_id: int, choice: dict[str, Any], ask: Ask, copy: Copy) -> ft.Control:
    """A browser action copies its prompt; any other is asked."""
    name, prompt = choice["name"], choice.get("prompt") or ""

    async def clicked() -> None:
        await (copy(prompt) if choice["where"] == "browser" else ask(moment_id, name))

    return PulseButton(
        on_click_callable=clicked,
        text=choice["label"],
        variant="muted",
        compact=True,
        # Asked already and not yet back: not asked twice.
        disabled=bool(choice.get("busy")),
    )


def _run(run: dict[str, Any]) -> ft.Control:
    lines: list[ft.Control] = [SecondaryText(f"{run['label']} · {run['state']}")]
    if run.get("result"):
        lines.append(ft.Markdown(run["result"], selectable=True))
    return ft.Container(
        ft.Column(lines, spacing=2),
        padding=ft.padding.only(left=Theme.Spacing.SM),
        border=ft.border.only(left=ft.BorderSide(2, TONE_COLORS[run["tone"]])),
    )
