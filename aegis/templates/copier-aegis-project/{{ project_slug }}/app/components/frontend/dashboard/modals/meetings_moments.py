"""What a call threw up, in the Flet Overseer's meeting pane: a section per
kind of moment (``MomentRecord``), each with who said it and when, a
button per action it offers (a browser action copies its prompt; the
others are asked through ``ask``), and what was asked of it."""

from collections.abc import Awaitable, Callable
from operator import itemgetter
from typing import Any

import flet as ft

from app.components.frontend.controls import PrimaryText, SecondaryText
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.snack_bar import SuccessSnackBar
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_clock
from app.services.meetings.service import by_kind

from .meetings_follow import api
from .modal_sections import SectionHeader

# Ask the action named of the moment (its id); copy a prompt.
Ask = Callable[[int, str], Awaitable[None]]
Copy = Callable[[str], Awaitable[None]]


def moment_actions(
    page: ft.Page, base: str, refresh: Callable[[], Awaitable[None]]
) -> tuple[Ask, Copy]:
    """The pane's two callbacks for one meeting (``base``, its API path):
    ask an action of a moment, then ``refresh``; copy a prompt."""

    async def ask(moment_id: int, action: str) -> None:
        await api(page).post(
            f"{base}/moments/{moment_id}/runs", json={"action": action}
        )
        await refresh()

    async def copy(prompt: str) -> None:
        page.set_clipboard(prompt)
        SuccessSnackBar("Copied").launch(page)

    return ask, copy


def moments_controls(record: dict[str, Any], ask: Ask, copy: Copy) -> list[ft.Control]:
    """A section per kind of moment the record holds, in the order first
    heard; nothing when nothing was."""
    controls: list[ft.Control] = []
    for listed in by_kind(record.get("moments") or [], itemgetter("kind")):
        controls.append(SectionHeader(listed[0]["title"]))
        controls.extend(_moment(m, ask, copy) for m in listed)
    return controls


def _moment(moment: dict[str, Any], ask: Ask, copy: Copy) -> ft.Control:
    return ft.Container(
        ft.Column(
            [
                SecondaryText(f"{moment['speaker']} · {format_clock(moment['at'])}"),
                PrimaryText(moment["text"], size=Theme.Typography.BODY),
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
        border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=Theme.Components.CARD_RADIUS,
    )


def _button(moment_id: int, choice: dict[str, Any], ask: Ask, copy: Copy) -> ft.Control:
    """A browser action copies its prompt; any other is asked."""
    name, prompt = choice["name"], choice.get("prompt") or ""

    async def clicked() -> None:
        await (copy(prompt) if choice["where"] == "browser" else ask(moment_id, name))

    return PulseButton(
        on_click_callable=clicked, text=choice["label"], variant="muted", compact=True
    )


def _run(run: dict[str, Any]) -> ft.Control:
    lines: list[ft.Control] = [SecondaryText(f"{run['label']} · {run['state']}")]
    if run.get("result"):
        lines.append(ft.Markdown(run["result"], selectable=True))
    return ft.Container(
        ft.Column(lines, spacing=2),
        padding=ft.padding.only(left=Theme.Spacing.SM),
        border=ft.border.only(left=ft.BorderSide(2, ft.Colors.OUTLINE_VARIANT)),
    )
