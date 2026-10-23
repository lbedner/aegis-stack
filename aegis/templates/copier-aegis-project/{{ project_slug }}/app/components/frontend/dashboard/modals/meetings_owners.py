"""Who owns what nobody pressed send for, in the Flet Overseer: a meeting
nobody owns given to someone (``GiveBox``, in the meeting's pane), and who
an agent's calendar meetings go to when nobody on the invite has an
account here (the Agents tab's picker). The same as the htmx Overseer's,
over the admin API (``api/meetings/admin.py``). Shown only with someone to
pick: nobody without auth.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import flet as ft

from app.components.frontend.controls import NativeDropdown

from .meetings_follow import api

API = "/api/v1/meetings/admin"
OWNERS = f"{API}/owners"


async def owners_of(page: ft.Page) -> list[dict[str, Any]]:
    """Everyone a meeting can be given to (the admin API's), by email."""
    found = await api(page).get(OWNERS)
    return found if isinstance(found, list) else []


class OwnerPicker(NativeDropdown):
    """One of ``owners`` (the admin API's), or nobody; ``on_pick`` gets the
    user's id (None: nobody). Hidden while there is nobody to pick."""

    def __init__(
        self,
        label: str,
        owners: list[dict[str, Any]],
        value: int | None,
        on_pick: Callable[[int | None], Any],
    ) -> None:
        super().__init__(
            label=label,
            value="" if value is None else str(value),
            options=[
                ft.dropdown.Option(key="", text="Nobody"),
                *[
                    ft.dropdown.Option(key=str(o["id"]), text=str(o["email"]))
                    for o in owners
                ],
            ],
            width=260,
            enable_filter=False,
            enable_search=False,
            visible=bool(owners),
            on_change=lambda e: on_pick(
                int(e.control.value) if e.control.value else None
            ),
        )


def give_box(
    page: ft.Page, record: dict[str, Any], given: Callable[[Any], None]
) -> list[ft.Control]:
    """The pane's give box, while nobody owns its meeting (``MeetingRecord``)."""
    meeting = record["meeting"]
    if meeting.get("owner_user_id") is not None:
        return []
    return [GiveBox(page, int(meeting["id"]), given)]


class GiveBox(ft.Container):
    """Whom a meeting nobody owns is given to; ``given`` gets the meeting
    read again (``MeetingRecord``) once it is theirs."""

    def __init__(
        self, page: ft.Page, meeting_id: int, given: Callable[[Any], None]
    ) -> None:
        super().__init__(visible=False)
        self.page = page
        self._meeting_id = meeting_id
        self._given = given
        page.run_task(self._load)

    async def _load(self) -> None:
        owners = await owners_of(self.page)
        self.content = OwnerPicker(
            "Nobody owns it. Give it to", owners, None, self._pick
        )
        self.visible = bool(owners)
        # ``_load`` starts before the box is mounted: update only once it is.
        if self.page and self.visible:
            self.update()

    def _pick(self, user_id: int | None) -> None:
        if user_id is not None:
            self.page.run_task(self._give, user_id)

    async def _give(self, user_id: int) -> None:
        record = await api(self.page).post(
            f"{API}/{self._meeting_id}/owner", json={"user_id": user_id}
        )
        self._given(record)
