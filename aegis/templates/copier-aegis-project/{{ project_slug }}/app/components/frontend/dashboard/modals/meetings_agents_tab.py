"""Meetings > Agents in the Flet Overseer: each Google account the bot joins
calls as, who it is, whether its sign-in still works and which meeting it
is in now; and the picker the Meetings tab sends the bot with. The same as
the htmx Overseer's Agents page, over the admin API
(``api/meetings/admin.py``). An agent is made by signing it in:
``meetings login --agent``.
"""

from __future__ import annotations

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    DataTable,
    DataTableColumn,
    NativeDropdown,
    SecondaryText,
)
from app.components.frontend.state.session_state import get_session_state
from app.components.frontend.theme import AegisTheme as Theme

from .modal_sections import EmptyStatePlaceholder

AGENTS = "/api/v1/meetings/admin/agents"


def agent_cells(row: dict[str, Any]) -> list[str]:
    """One agent's row: its name, the name it joins as, its Google account,
    its sign-in and the meetings it is in now."""
    account = row["account"]
    in_now = ", ".join(f"Meeting {m}" for m in row.get("in_now") or [])
    return [
        str(account.get("name") or ""),
        str(account.get("display_name") or ""),
        str(account.get("email") or "-"),
        str(row.get("sign_in") or ""),
        in_now or "-",
    ]


class AgentPicker(NativeDropdown):
    """Which agent the bot is sent as, shown only while there is a choice."""

    def __init__(self) -> None:
        super().__init__(
            label="Agent",
            width=200,
            enable_filter=False,
            enable_search=False,
            visible=False,
        )

    def fill(self, rows: list[dict[str, Any]]) -> None:
        """The agents to pick from (the admin API's), the default first and
        picked until another is."""
        names = [str(r["account"]["name"]) for r in rows]
        self.options = [ft.dropdown.Option(key=name) for name in names]
        self.visible = len(names) > 1
        if self.value not in names:
            self.value = names[0] if names else None
        if self.page:
            self.update()

    def chosen(self) -> dict[str, str]:
        """The send request's part: the agent picked, while there is a choice."""
        return {"agent": str(self.value)} if self.visible and self.value else {}


class AgentsTab(ft.Container):
    """Every agent, the default first."""

    def __init__(self, page: ft.Page) -> None:
        super().__init__()
        self.page = page
        self._table = ft.Container(
            content=EmptyStatePlaceholder("Loading agents..."), expand=True
        )
        self.content = ft.Column(
            [
                self._table,
                SecondaryText(
                    "Sign one in, or add another: meetings login --agent <name>",
                    size=Theme.Typography.BODY_SMALL,
                ),
            ],
            spacing=Theme.Spacing.MD,
            expand=True,
        )
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True
        page.run_task(self._load)

    async def _load(self) -> None:
        data = await get_session_state(self.page).api_client.get(AGENTS)
        rows = data if isinstance(data, list) else []
        self._table.content = DataTable(
            columns=[
                DataTableColumn("Agent", width=140, style="primary"),
                DataTableColumn("Joins as", width=180),
                DataTableColumn("Google account", width=240, style="secondary"),
                DataTableColumn("Sign-in", width=120),
                DataTableColumn("In now", width=220, style="secondary"),
            ],
            rows=[agent_cells(r) for r in rows],
            scroll_height=600,
            empty_message="No agents yet",
        )
        # ``_load`` starts before the tab is mounted: update only once it is.
        if self._table.page:
            self._table.update()
