"""Overseer > Deployments in Flet, opened from the dashboard header: the
same provider (``hosting``: where it runs, where it can), live build, host,
history and database backups as the htmx page (``ui_deployments``), read
when the popup opens."""

import asyncio
from typing import Any

import flet as ft

from app.components.frontend.controls import BodyText, H3Text, SecondaryText
from app.components.frontend.dashboard.modals.modal_sections import StatRowsSection
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system import hosting, ui_deployments

from .base_detail_popup import PagePopup
from .table_tab import TableTab, columns_of


class DeploymentsSection(ft.Column):
    """What is live, the host it runs on, and the backups beside it."""

    def __init__(self) -> None:
        super().__init__(spacing=Theme.Spacing.SM)
        self.controls = [SecondaryText("Reading the deployment.")]

    def did_mount(self) -> None:
        self.page.run_task(self.load)

    async def load(self) -> None:
        running, now, host, history = await asyncio.gather(
            hosting.running_on(),
            ui_deployments.now(),
            ui_deployments.host(),
            ui_deployments.history(),
        )
        target = hosting.deploys_to()
        current = running["key"] or (target or {}).get("key")
        self.controls = [
            _where("Running on", running),
            *([_where("Deploys to", target)] if target else []),
            H3Text("Where it can run"),
            ProviderCards(hosting.providers(current)),
            StatRowsSection("Now", dict(now)),
            SecondaryText(host["note"])
            if host["note"]
            else StatRowsSection("Host", dict(host["facts"])),
            *_table("History", history, ui_deployments.HISTORY_COLUMNS),
            *_table("Backups", ui_deployments.backups(), ui_deployments.BACKUP_COLUMNS),
        ]
        if self.page is not None:
            self.update()


def _where(title: str, place: dict[str, Any]) -> ft.Control:
    """A provider and its facts (``hosting``)."""
    return StatRowsSection(title, {"Provider": place["name"], **dict(place["facts"])})


class ProviderCards(ft.Column):
    """Every provider aegis knows as a card, the one in use marked; picking
    one shows its command and the token it reads."""

    def __init__(self, cards: list[dict[str, Any]]) -> None:
        super().__init__(spacing=Theme.Spacing.SM)
        self._cards = {c["key"]: c for c in cards}
        self._detail = SecondaryText("", selectable=True)
        picked = next((c for c in cards if c["current"]), cards[0])
        self.controls = [
            ft.Row([self._card(c) for c in cards], wrap=True, spacing=Theme.Spacing.SM),
            self._detail,
        ]
        self._show(picked["key"])

    def _card(self, card: dict[str, Any]) -> ft.Control:
        mark: ft.Control = (
            ft.Image(src=card["logo"], width=20, height=20)
            if card["logo"]
            else BodyText(card["name"][0])
        )
        lines: list[ft.Control] = [
            ft.Row([mark, BodyText(card["name"])], spacing=Theme.Spacing.SM)
        ]
        if card["current"]:
            lines.append(SecondaryText("You're here", color=Theme.Colors.PRIMARY))
        lines.append(SecondaryText(" · ".join(card["can"]), size=11))
        return ft.Container(
            ft.Column(lines, spacing=4),
            width=170,
            padding=Theme.Spacing.SM,
            border_radius=8,
            border=ft.border.all(
                1,
                Theme.Colors.PRIMARY if card["current"] else ft.Colors.OUTLINE_VARIANT,
            ),
            on_click=lambda _, key=card["key"]: self._pick(key),
        )

    def _show(self, key: str) -> None:
        card = self._cards[key]
        token = (
            f"  (reads {card['token']} from your environment)" if card["token"] else ""
        )
        self._detail.value = f"{card['command']}{token}"

    def _pick(self, key: str) -> None:
        self._show(key)
        self._detail.update()


def _table(
    title: str, view: dict[str, Any], columns: tuple[tuple[str, str], ...]
) -> list[ft.Control]:
    """A titled table of ``view``'s rows, or why it has none."""
    body: ft.Control = (
        SecondaryText(view["note"])
        if view["note"]
        else TableTab(view["rows"], columns_of(columns), "Nothing yet")
    )
    return [H3Text(title), body]


class DeploymentsPopup(PagePopup):
    TITLE = "Deployments"
    SUBTITLE = "What is live, and where it runs."

    def section(self) -> ft.Control:
        return DeploymentsSection()
